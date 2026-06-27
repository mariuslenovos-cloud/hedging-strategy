"""
gridstat_meta_xs.py -- CROSS-SECTIONAL meta-labeling (Stage 1 of the "ideal EA").

THE GATE QUESTION
-----------------
The 3-symbol meta-test (gridstat_meta.py, 746 events) FAILED: ML didn't beat the
fingerprint -- diagnosed as sample-starved. The thesis (AFML): pool MANY
instruments -> thousands of events -> the shared meta-model finally separates
winners and BEATS the per-symbol fingerprint out-of-sample. THIS tests that
thesis on the scanner's 19-symbol dataset BEFORE we build the heavy
dollar-bars/microstructure/ONNX/EA pipeline (Stages 2-4).

DATA: analysis_data/gridstat_scan_mom_<date>.csv (Goldminer momentum scan, 19
symbols x grisk, exit-AGNOSTIC horizon). We fix ONE grisk (default 4) for a clean
single-sensitivity signal set, label = horizon_r>0, R = horizon_r (held-to-288-bar
outcome). NOTE: horizon-exit is a SIGNAL-SELECTION proxy, NOT the grid P&L -- this
measures whether ML SELECTS better signals cross-sectionally (the gate), not live $.

METHOD (identical honesty machinery to gridstat_meta.py):
 purged K-fold (symbol-aware purge+embargo) | uniqueness-weighted RF |
 head-to-head: trade-all / per-symbol fingerprint gate / ML-gate / ML-sized |
 Deflated + Probabilistic Sharpe on the ML OOS trade series.

Usage:
    python gridstat_meta_xs.py                # grisk=4, N=6 folds, trials=100
    python gridstat_meta_xs.py 4 6 100        # grisk, folds, DSR-trials
"""
import csv, math, os, sys
from collections import defaultdict
from datetime import datetime
import numpy as np
from scipy.stats import norm, skew, kurtosis
from sklearn.ensemble import RandomForestClassifier

HERE = os.path.dirname(os.path.abspath(__file__))
SCAN = os.path.join(HERE, "analysis_data", "gridstat_scan_mom_20260609.csv")
EMBARGO_PCT = 0.02
GATE_WR, GATE_N = 0.55, 10
FEATURES = ["dir_buy", "hour", "session", "atr_at_entry", "wpr", "adx",
            "ma_angle", "runup", "period_used", "bars_in_band", "symbol_code"]
SESS = {"HR_ASIA": 0, "HR_LDN": 1, "HR_OVL": 2, "HR_NY": 3}


def _parse(ts):
    for fmt in ("%Y.%m.%d %H:%M:%S", "%Y.%m.%d %H:%M"):
        try: return datetime.strptime(ts, fmt)
        except ValueError: pass
    return None


def sess_tag(h):
    return "HR_ASIA" if h < 9 else "HR_LDN" if h < 14 else "HR_OVL" if h < 18 else "HR_NY"


def load():
    """grisk is SYMBOL-SPECIFIC ([[grisk-per-symbol]]): pick EACH symbol's best grisk
    by TOTAL horizon_r (the locked scan metric, [[validate-pipeline-against-known-anchor]]),
    then pool those signal sets. Gold MUST come out grisk=4 (the trust anchor)."""
    groups = defaultdict(list)            # (sym,grisk) -> [row dicts]
    with open(SCAN, newline="") as f:
        for r in csv.DictReader(f):
            try: g = int(float(r["grisk"]))
            except (ValueError, KeyError): continue
            t0 = _parse(r["entry_time"]); t1 = _parse(r["outcome_time"])
            if t0 is None or t1 is None: continue
            if t1 < t0: t1 = t0
            try: hr = float(r["horizon_r"])
            except (ValueError, KeyError): continue
            def fl(k):
                try: return float(r[k])
                except (ValueError, KeyError): return 0.0
            groups[(r["symbol"], g)].append({
                "symbol": r["symbol"], "t0": t0, "t1": t1, "setup_key": r["setup_key"],
                "r": hr, "y": 1 if hr > 0 else 0,
                "dir_buy": 1.0 if r["direction"] == "BUY" else 0.0,
                "hour": float(t0.hour), "session": float(SESS[sess_tag(t0.hour)]),
                "atr_at_entry": fl("atr_at_entry"), "wpr": fl("wpr"), "adx": fl("adx"),
                "ma_angle": fl("ma_angle"), "runup": fl("runup"),
                "period_used": fl("period_used"), "bars_in_band": fl("bars_in_band")})
    totals = defaultdict(dict)             # sym -> {grisk: total horizon_r}
    for (sym, g), ds in groups.items():
        totals[sym][g] = sum(d["r"] for d in ds)
    best = {sym: max(totals[sym], key=lambda g: totals[sym][g]) for sym in totals}
    rows = []
    for sym, g in best.items():
        rows += groups[(sym, g)]
    syms = {s: i for i, s in enumerate(sorted(best))}
    for d in rows: d["symbol_code"] = float(syms[d["symbol"]])
    rows.sort(key=lambda d: d["t0"])
    return rows, syms, best, totals


def uniqueness(rows):
    w = [1.0] * len(rows)
    by = defaultdict(list)
    for i, r in enumerate(rows): by[r["symbol"]].append(i)
    for idxs in by.values():
        spans = [(rows[i]["t0"], rows[i]["t1"], i) for i in idxs]
        bks = sorted({t for s in spans for t in (s[0], s[1])})
        own = defaultdict(float); life = defaultdict(float)
        for k in range(len(bks) - 1):
            a, b = bks[k], bks[k + 1]; dur = (b - a).total_seconds()
            if dur <= 0: continue
            act = [i for (x0, x1, i) in spans if x0 <= a and x1 > a]
            if not act: continue
            c = dur / len(act)
            for i in act: own[i] += c; life[i] += dur
        for i in idxs: w[i] = (own[i] / life[i]) if life[i] > 0 else 1.0
    return w


def purge(train, test, rows, emb):
    sp = [(rows[j]["t0"], rows[j]["t1"], rows[j]["symbol"]) for j in test]
    kept = []
    for i in train:
        t0, t1, sym = rows[i]["t0"], rows[i]["t1"], rows[i]["symbol"]
        leak = False
        for (s0, s1, ss) in sp:
            if ss != sym: continue
            if not (t1 < s0 or s1 < t0): leak = True; break
            if 0 <= (t0 - s1).total_seconds() <= emb: leak = True; break
        if not leak: kept.append(i)
    return kept


def X(rows, idx):
    return np.array([[rows[i][f] for f in FEATURES] for i in idx], dtype=float)


def rf():
    return RandomForestClassifier(n_estimators=400, max_depth=5, min_samples_leaf=30,
                                  class_weight="balanced", random_state=7, n_jobs=-1)


def bet_size(p):
    if p <= 0.5: return 0.0
    p = min(p, 0.999999)
    return 2 * norm.cdf((p - 0.5) / math.sqrt(p * (1 - p))) - 1


def fp_keep(train_rows):
    by = defaultdict(list)
    for r in train_rows: by[(r["symbol"], r["setup_key"])].append(r["r"])
    return {k for k, rs in by.items()
            if len(rs) >= GATE_N and sum(1 for x in rs if x > 0) / len(rs) >= GATE_WR}


def psr(sr, n, g3, g4, s0=0.0):
    d = math.sqrt(max(1e-12, 1 - g3 * sr + (g4 - 1) / 4 * sr * sr))
    return norm.cdf((sr - s0) * math.sqrt(n - 1) / d)


def run():
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    N = int(a[0]) if a else 6
    trials = int(a[1]) if len(a) > 1 else 100

    rows, syms, best, totals = load()
    n = len(rows)
    uw = uniqueness(rows)
    span = (rows[-1]["t1"] - rows[0]["t0"]).total_seconds(); emb = span * EMBARGO_PCT
    base = sum(r["y"] for r in rows) / n
    print(f"CROSS-SECTIONAL meta-test | {len(syms)} symbols at EACH symbol's best grisk | {n} signals")
    anchor = "OK" if best.get("GOLD") == 4 else f"!! gold={best.get('GOLD')} (expected 4)"
    print(f"gold-anchor check: GOLD best grisk = {best.get('GOLD')} -> {anchor}")
    print("per-symbol grisk (by total horizon_r):  " +
          "  ".join(f"{s}={best[s]}" for s in sorted(best, key=lambda s: -totals[s][best[s]])))
    print(f"base win rate (horizon_r>0) = {base*100:.1f}%   mean R = {np.mean([r['r'] for r in rows]):+.3f}\n")

    rf_full = rf(); rf_full.fit(X(rows, range(n)), [r["y"] for r in rows], sample_weight=np.array(uw))
    print("Feature importance (MDI, full-data RF, in-sample):")
    for f, v in sorted(zip(FEATURES, rf_full.feature_importances_), key=lambda x: -x[1]):
        print(f"   {f:<14}{v:.3f}  " + "#" * int(round(v * 60)))

    bnd = [round(i * n / N) for i in range(N + 1)]
    blk = [list(range(bnd[b], bnd[b + 1])) for b in range(N)]
    M = ["trade_all", "fingerprint", "ml_gate", "ml_sized"]
    oos = {m: [] for m in M}; fa = {m: [] for m in M}
    for b in range(N):
        te = blk[b]; tr = purge([i for bb in range(N) if bb != b for i in blk[bb]], te, rows, emb)
        if len(tr) < 100: continue
        keep = fp_keep([rows[i] for i in tr])
        m = rf(); m.fit(X(rows, tr), [rows[i]["y"] for i in tr], sample_weight=np.array([uw[i] for i in tr]))
        pr = m.predict_proba(X(rows, te))[:, 1]
        per = {x: [] for x in M}
        for k, i in enumerate(te):
            r = rows[i]; per["trade_all"].append(r["r"])
            if (r["symbol"], r["setup_key"]) in keep: per["fingerprint"].append(r["r"])
            if pr[k] >= GATE_WR: per["ml_gate"].append(r["r"])
            sz = bet_size(pr[k])
            if sz > 0: per["ml_sized"].append(sz * r["r"])
        for x in M:
            oos[x] += per[x]
            if per[x]: fa[x].append(np.mean(per[x]))

    print(f"\nPurged K-Fold OOS head-to-head (N={N}, symbol-aware purge):\n")
    print(f"{'method':<13}{'trades':>8}{'win%':>7}{'totR':>10}{'avgR':>9}{'%posFold':>10}")
    print("-" * 57)
    res = {}
    for x in M:
        arr = np.array(oos[x]) if oos[x] else np.array([0.0])
        t = len(oos[x]); win = sum(1 for v in oos[x] if v > 0) / t * 100 if t else 0
        pf = sum(1 for v in fa[x] if v > 0) / len(fa[x]) * 100 if fa[x] else 0
        res[x] = {"t": t, "tot": arr.sum(), "avg": arr.mean()}
        print(f"{x:<13}{t:>8}{win:>6.0f}%{arr.sum():>+10.2f}{arr.mean():>+9.3f}{pf:>9.0f}%")
    print("-" * 57)

    g = np.array(oos["ml_gate"])
    psr_ml = 0.0
    if len(g) > 5 and g.std() > 0:
        sr = g.mean() / g.std(); g3 = float(skew(g)); g4 = float(kurtosis(g, fisher=False))
        psr_ml = psr(sr, len(g), g3, g4)
        print(f"\nML-GATE OOS series: trades={len(g)} per-trade Sharpe={sr:+.3f}")
        print(f"   PSR(SR>0) = {psr_ml*100:.1f}%   (need >95% to call the edge real)")

    print("\nVERDICT (honest -- requires significance AND magnitude, not just a bigger near-zero):")
    fp, mg = res["fingerprint"], res["ml_gate"]
    print(f"   fingerprint avgR {fp['avg']:+.3f}/{fp['t']}tr  vs  ML avgR {mg['avg']:+.3f}/{mg['t']}tr  "
          f"| ML PSR(SR>0)={psr_ml*100:.0f}%")
    sig = psr_ml >= 0.95
    beats = mg["avg"] > fp["avg"] and mg["tot"] > fp["tot"]
    if sig and beats and mg["avg"] > 0.05:
        print("   -> ML BEATS fingerprint with SIGNIFICANCE -> breadth thesis CONFIRMED; Stages 2-4 justified.")
    elif not sig:
        print("   -> NOT CONFIRMED. PSR<95% = the ML edge is NOT distinguishable from zero, and both")
        print("      methods are ~near-zero on this metric. Pooling 19 symbols did NOT rescue the ML.")
        print("      TWO confounds point the build at FEATURES + the RIGHT LABEL, not more symbols:")
        print("      (1) features (wpr/adx/ma_angle/runup) are weak -> Stage 2 (dollar bars/frac-diff/microstructure).")
        print("      (2) LABEL here = horizon_r (held 288 bars) = a SIGNAL proxy, NOT the grid+harvest P&L")
        print("          that actually makes the money -> re-run the scan logging triple-barrier R per symbol.")
        print("      => do NOT jump to ONNX/EA. Next = upgrade the scanner: richer features + tradeable label,")
        print("         across all symbols, THEN re-run this gate.")
    else:
        print("   -> marginal; treat as inconclusive, prioritize better features/label before deployment.")


if __name__ == "__main__":
    run()
