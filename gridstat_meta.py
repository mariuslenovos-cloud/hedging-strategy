"""
gridstat_meta.py -- AFML meta-labeling experiment (Ch.3.6 + 4 + 7 + 8 + 14).

THE QUESTION
------------
Does an ML META-MODEL (a uniqueness-weighted Random Forest that predicts
P(this Goldminer signal wins) from the rich feature columns) beat the incumbent
DIR|SESSION|ATR fingerprint gate -- HONESTLY measured out-of-sample?

This is proper meta-labeling: the PRIMARY model (Goldminer) already chose the
SIDE; the SECONDARY model only decides WHETHER to take the trade (and how big).
We pool gold+silver+oil shadow data so the ML has enough samples (the exact
reason single-symbol feature-cuts overfit -- see CLAUDE.md session 17).

HONESTY MACHINERY
-----------------
* Purged K-Fold (AFML Ch.7): time-contiguous folds; each signal tested exactly
  once on a model that never saw it. PURGE+EMBARGO are SYMBOL-AWARE (a gold label
  cannot leak into an oil label -- different instruments).
* Uniqueness weighting (Ch.4) computed PER SYMBOL feeds the RF sample_weight.
* Three selection methods scored on the SAME OOS folds, apples-to-apples:
    TRADE-ALL      -- take every signal (the no-selection floor)
    FINGERPRINT    -- the live EA gate: symbol|DIR|SESSION|ATR, n>=10 & wr>=0.55
    ML-GATE        -- RF p(win) >= 0.55
    ML-SIZED       -- RF, bet size from probability (Ch.10), skip if p<=0.5
* Deflated / Probabilistic Sharpe Ratio (Ch.14) on the ML OOS trade series.

Reads ONLY the read-only analysis_data/ snapshots (separation policy).

Usage:
    python gridstat_meta.py                 # N=6 folds, trials=50, print only
    python gridstat_meta.py 8 100           # N folds, N_trials for DSR
    python gridstat_meta.py --write         # ALSO save dated report + per-symbol
                                            #   EA-readable sizing tables to analysis_data/
"""
import csv
import math
import os
import sys
from collections import defaultdict
from datetime import datetime

import numpy as np
from scipy.stats import norm, skew, kurtosis
from sklearn.ensemble import RandomForestClassifier

HERE = os.path.dirname(os.path.abspath(__file__))
AD = os.path.join(HERE, "analysis_data")
SOURCES = {
    "gold":   "gridstat_setups_gold_20260609.csv",
    "silver": "gridstat_setups_silver_research_20260609.csv",
    "oil":    "gridstat_setups_oil_g4_20260610.csv",
}
EMBARGO_PCT = 0.02
GATE_WR = 0.55
GATE_N = 10
DATE = datetime.now().strftime("%Y%m%d")

FEATURES = ["dir_buy", "hour", "session", "atr_at_entry", "wpr", "adx",
            "ma_angle", "runup", "period_used", "bars_in_band", "big_move",
            "symbol_code"]
SESS = {"HR_ASIA": 0, "HR_LDN": 1, "HR_OVL": 2, "HR_NY": 3}
SYMS = {"gold": 0, "silver": 1, "oil": 2}


def _parse(ts):
    return datetime.strptime(ts, "%Y.%m.%d %H:%M")


def session_tag(h):
    return "HR_ASIA" if h < 9 else "HR_LDN" if h < 14 else "HR_OVL" if h < 18 else "HR_NY"


def load_pool():
    rows = []
    for sym, fn in SOURCES.items():
        with open(os.path.join(AD, fn), newline="") as f:
            for r in csv.DictReader(f):
                if not r.get("setup_key"):
                    continue
                t0 = _parse(r["entry_time"])
                t1 = _parse(r["outcome_time"])
                if t1 < t0:
                    t1 = t0
                rr = float(r["r_multiple"])
                rows.append({
                    "symbol": sym, "t0": t0, "t1": t1,
                    "setup_key": r["setup_key"],
                    "r": rr, "y": 1 if rr > 0 else 0,
                    "dir_buy": 1.0 if r["direction"] == "BUY" else 0.0,
                    "hour": float(t0.hour),
                    "session": float(SESS[session_tag(t0.hour)]),
                    "atr_at_entry": float(r["atr_at_entry"]),
                    "wpr": float(r["wpr"]), "adx": float(r["adx"]),
                    "ma_angle": float(r["ma_angle"]), "runup": float(r["runup"]),
                    "period_used": float(r["period_used"]),
                    "bars_in_band": float(r["bars_in_band"]),
                    "big_move": float(r["big_move"]),
                    "symbol_code": float(SYMS[sym]),
                })
    rows.sort(key=lambda r: r["t0"])
    return rows


# ---- uniqueness weighting (AFML Ch.4), computed PER SYMBOL ----
def uniqueness_per_symbol(rows):
    w = [1.0] * len(rows)
    by_sym = defaultdict(list)
    for i, r in enumerate(rows):
        by_sym[r["symbol"]].append(i)
    for sym, idxs in by_sym.items():
        spans = [(rows[i]["t0"], rows[i]["t1"], i) for i in idxs]
        bks = sorted({t for s in spans for t in (s[0], s[1])})
        own = defaultdict(float); life = defaultdict(float)
        for k in range(len(bks) - 1):
            a, b = bks[k], bks[k + 1]
            dur = (b - a).total_seconds()
            if dur <= 0:
                continue
            active = [i for (t0, t1, i) in spans if t0 <= a and t1 > a]
            if not active:
                continue
            contrib = dur / len(active)
            for i in active:
                own[i] += contrib; life[i] += dur
        for i in idxs:
            w[i] = (own[i] / life[i]) if life[i] > 0 else 1.0
    return w


# ---- symbol-aware purge + embargo ----
def purge(train_idx, test_idx, rows, embargo_secs):
    spans = [(rows[j]["t0"], rows[j]["t1"], rows[j]["symbol"]) for j in test_idx]
    kept = []
    for i in train_idx:
        t0, t1, sym = rows[i]["t0"], rows[i]["t1"], rows[i]["symbol"]
        leak = False
        for (s0, s1, ssym) in spans:
            if ssym != sym:                      # different instrument != leakage
                continue
            if not (t1 < s0 or s1 < t0):         # overlapping label windows
                leak = True; break
            if 0 <= (t0 - s1).total_seconds() <= embargo_secs:
                leak = True; break
        if not leak:
            kept.append(i)
    return kept


def X(rows, idx):
    return np.array([[rows[i][f] for f in FEATURES] for i in idx], dtype=float)


def new_rf():
    return RandomForestClassifier(n_estimators=400, max_depth=4,
                                  min_samples_leaf=20, class_weight="balanced",
                                  random_state=7, n_jobs=-1)


def bet_size(p):
    """AFML Ch.10 bet size from probability (binary), long-the-chosen-side only."""
    if p <= 0.5:
        return 0.0
    p = min(p, 0.999999)
    z = (p - 0.5) / math.sqrt(p * (1 - p))
    return 2 * norm.cdf(z) - 1            # in (0,1]


def fingerprint_table(train_rows):
    by = defaultdict(list)
    for r in train_rows:
        by[(r["symbol"], r["setup_key"])].append(r["r"])
    keep = set()
    for k, rs in by.items():
        wr = sum(1 for x in rs if x > 0) / len(rs)
        if len(rs) >= GATE_N and wr >= GATE_WR:
            keep.add(k)
    return keep


def psr(sr, n, g3, g4, sr_star=0.0):
    denom = math.sqrt(max(1e-12, 1 - g3 * sr + (g4 - 1) / 4.0 * sr * sr))
    return norm.cdf((sr - sr_star) * math.sqrt(n - 1) / denom)


def deflated_sr(sr, n, g3, g4, fold_sharpes, n_trials):
    """DSR (Ch.14): PSR against the expected MAX Sharpe of n_trials noise strats."""
    var_trials = np.var(fold_sharpes, ddof=1) if len(fold_sharpes) > 1 else 0.0
    if var_trials <= 0 or n_trials < 2:
        return psr(sr, n, g3, g4, 0.0), 0.0
    eul = 0.5772156649
    z1 = norm.ppf(1 - 1.0 / n_trials)
    z2 = norm.ppf(1 - 1.0 / (n_trials * math.e))
    sr_star = math.sqrt(var_trials) * ((1 - eul) * z1 + eul * z2)
    return psr(sr, n, g3, g4, sr_star), sr_star


# ---- EA-readable sizing table (the "use it" artifact) ----
def write_sizing_tables(rows, rf, emit):
    """Pooled full-data RF -> per-SYMBOL fingerprint sizing table in the EXACT
    format the EA's LookupSizing() reads (setup_key,size_mult,... ; size_mult is
    col idx 1). Written to analysis_data/ (research). PROMOTE to Common\\Files
    ONLY after A/B in the tester -- separation policy [[separate-research-from-production-csv]].

    Sizing rule (respects [[rigor-drives-sizing-not-gating]]): NEGATIVE-R fingerprint
    -> 0 (skip). POSITIVE but thin (<8) -> 0.75x probationary. Otherwise size by
    RELATIVE ML confidence: rank the fingerprint's mean P(win) against the pool of
    eligible fingerprints and map percentile 0..1 -> 0.75x..2.0x. (Relative, because
    the RF's absolute probabilities are compressed by class-balancing -- the usable
    signal is the RANK, i.e. which setups the model prefers.)"""
    P = rf.predict_proba(X(rows, range(len(rows))))[:, 1]
    by = defaultdict(lambda: defaultdict(list))    # symbol -> setup_key -> [(p,r)]
    for i, r in enumerate(rows):
        by[r["symbol"]][r["setup_key"]].append((P[i], r["r"]))

    # aggregate + collect eligible mean-p for cross-pool relative ranking
    agg = {}                                       # (sym,setup) -> (mean_p, avg_r, n)
    for sym in by:
        for k in by[sym]:
            ps = [x[0] for x in by[sym][k]]
            rs = [x[1] for x in by[sym][k]]
            agg[(sym, k)] = (float(np.mean(ps)), float(np.mean(rs)), len(rs))
    eligible = sorted(mp for (mp, ar, nn) in agg.values() if ar > 0 and nn >= 8)

    def mult(mp, ar, nn):
        if ar <= 0:
            return 0.0, "NEGATIVE-skip"
        if nn < 8:
            return 0.75, f"thin n={nn}"
        if len(eligible) < 2:
            return 1.0, "base"
        pct = sum(1 for x in eligible if x < mp) / (len(eligible) - 1)
        pct = min(1.0, pct)
        return round(0.75 + 1.25 * pct, 2), f"ml p={mp:.2f} rank={pct:.2f}"

    emit("\nEA-readable ML sizing tables written (per symbol, analysis_data/; "
         "size = relative-ML-confidence rank):")
    for sym in sorted(by):
        path = os.path.join(AD, f"gridstat_sizing_meta_{sym}_{DATE}.csv")
        n_pos = 0
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["setup_key", "size_mult", "eff_n", "avg_r", "t_stat", "tier"])
            for k in sorted(by[sym]):
                mp, ar, nn = agg[(sym, k)]
                m, tier = mult(mp, ar, nn)
                if m > 0:
                    n_pos += 1
                w.writerow([k, f"{m:.2f}", nn, f"{ar:.3f}", "", tier])
        emit(f"   {os.path.basename(path)}  ({len(by[sym])} setups, {n_pos} trade)")
    emit("\n   TO A/B (NOT auto-promoted): copy a table -> Common\\Files\\gridstat_sizing_<sym>.csv,")
    emit("   set UseSizingTable=true / StatsFilterEnabled=false / SizingCSVFile=that name,")
    emit("   MaxSizeMult=2.0, then run EVERY-TICK and compare to the live (filter-gated) config.")
    emit("   WARNING: OOS test below showed standalone ML selection does NOT beat the live")
    emit("   fingerprint config -- treat these as RESEARCH artifacts, validate before any live use.")


def run():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    N = int(args[0]) if args else 6
    n_trials = int(args[1]) if len(args) > 1 else 50
    do_write = "--write" in sys.argv

    out = []
    def emit(s=""):
        print(s)
        out.append(s)

    rows = load_pool()
    uniq = uniqueness_per_symbol(rows)
    n = len(rows)
    span = (rows[-1]["t1"] - rows[0]["t0"]).total_seconds()
    embargo = span * EMBARGO_PCT

    emit(f"Pooled {n} signals  "
         + "  ".join(f"{s}={sum(1 for r in rows if r['symbol']==s)}" for s in SYMS))
    base_wr = sum(r["y"] for r in rows) / n
    emit(f"Base win rate (trade-all) = {base_wr*100:.1f}%   "
         f"avg R = {np.mean([r['r'] for r in rows]):+.3f}\n")

    # ---- full-data RF: feature importance (in-sample) + the deploy model ----
    rf_full = new_rf()
    rf_full.fit(X(rows, range(n)), [r["y"] for r in rows], sample_weight=np.array(uniq))
    imp = sorted(zip(FEATURES, rf_full.feature_importances_), key=lambda x: -x[1])
    emit("Feature importance (MDI, full-data RF -- IN-SAMPLE read only):")
    for f, v in imp:
        emit(f"   {f:<14} {v:.3f}  " + "#" * int(round(v * 60)))

    # ---- purged K-fold: each signal tested exactly once ----
    bounds = [round(i * n / N) for i in range(N + 1)]
    blocks = [list(range(bounds[b], bounds[b + 1])) for b in range(N)]
    methods = ["trade_all", "fingerprint", "ml_gate", "ml_sized"]
    oos = {m: [] for m in methods}
    fold_avg = {m: [] for m in methods}
    fold_sharpe_ml = []

    for b in range(N):
        test_idx = blocks[b]
        train_idx = [i for bb in range(N) if bb != b for i in blocks[bb]]
        train_idx = purge(train_idx, test_idx, rows, embargo)
        train_rows = [rows[i] for i in train_idx]
        if len(train_rows) < 40:
            continue
        fp_keep = fingerprint_table(train_rows)
        rf = new_rf()
        rf.fit(X(rows, train_idx), [rows[i]["y"] for i in train_idx],
               sample_weight=np.array([uniq[i] for i in train_idx]))
        proba = rf.predict_proba(X(rows, test_idx))[:, 1]
        per = {m: [] for m in methods}
        for k, i in enumerate(test_idx):
            r = rows[i]
            per["trade_all"].append(r["r"])
            if (r["symbol"], r["setup_key"]) in fp_keep:
                per["fingerprint"].append(r["r"])
            p = proba[k]
            if p >= GATE_WR:
                per["ml_gate"].append(r["r"])
            sz = bet_size(p)
            if sz > 0:
                per["ml_sized"].append(sz * r["r"])
        for m in methods:
            oos[m].extend(per[m])
            if per[m]:
                fold_avg[m].append(np.mean(per[m]))
        if per["ml_gate"]:
            a = np.array(per["ml_gate"])
            if a.std() > 0:
                fold_sharpe_ml.append(a.mean() / a.std())

    emit("\nPurged K-Fold OOS head-to-head (each signal tested once, "
         f"N={N} folds, symbol-aware purge):\n")
    emit(f"{'method':<13}{'trades':>7}{'win%':>7}{'totR':>9}{'avgR':>8}"
         f"{'medFoldR':>10}{'%posFold':>10}")
    emit("-" * 64)
    res = {}
    for m in methods:
        a = np.array(oos[m]) if oos[m] else np.array([0.0])
        trades = len(oos[m])
        wins = sum(1 for x in oos[m] if x > 0)
        winr = wins / trades * 100 if trades else 0
        medf = np.median(fold_avg[m]) if fold_avg[m] else 0
        posf = sum(1 for v in fold_avg[m] if v > 0)
        pf = posf / len(fold_avg[m]) * 100 if fold_avg[m] else 0
        res[m] = {"trades": trades, "totR": a.sum(), "avgR": a.mean()}
        emit(f"{m:<13}{trades:>7}{winr:>6.0f}%{a.sum():>+9.2f}{a.mean():>+8.3f}"
             f"{medf:>+10.3f}{pf:>9.0f}%")
    emit("-" * 64)

    g = np.array(oos["ml_gate"])
    if len(g) > 5 and g.std() > 0:
        sr = g.mean() / g.std()
        g3 = float(skew(g)); g4 = float(kurtosis(g, fisher=False))
        psr0 = psr(sr, len(g), g3, g4, 0.0)
        dsr, sr_star = deflated_sr(sr, len(g), g3, g4, fold_sharpe_ml, n_trials)
        emit(f"\nML-GATE out-of-sample trade series (Ch.14):")
        emit(f"   trades={len(g)}  per-trade Sharpe={sr:+.3f}  skew={g3:+.2f}  kurt={g4:.2f}")
        emit(f"   PSR(SR>0)            = {psr0*100:5.1f}%   (prob the true Sharpe is positive)")
        emit(f"   Deflated SR (N={n_trials} trials, SR*={sr_star:.3f}) = "
             f"{dsr*100:5.1f}%   (prob it beats best-of-{n_trials}-noise)")

    emit("\nVERDICT:")
    fp, mg = res["fingerprint"], res["ml_gate"]
    emit(f"   fingerprint avgR {fp['avgR']:+.3f} on {fp['trades']} trades  vs  "
         f"ML-gate avgR {mg['avgR']:+.3f} on {mg['trades']} trades")
    if mg["avgR"] > fp["avgR"] and mg["totR"] > fp["totR"]:
        emit("   -> ML meta-model BEATS the fingerprint OOS (more total edge).")
    elif mg["avgR"] > fp["avgR"]:
        emit("   -> ML higher per-trade edge but lower turnover; net depends on sizing.")
    else:
        emit("   -> Fingerprint holds; ML does NOT beat it OOS on this data "
             "(likely sample-starved -- needs more instruments).")

    if do_write:
        write_sizing_tables(rows, rf_full, emit)
        report = os.path.join(AD, f"meta_report_{DATE}.txt")
        with open(report, "w") as f:
            f.write("\n".join(out) + "\n")
        print(f"\nSaved report -> {report}")


if __name__ == "__main__":
    run()
