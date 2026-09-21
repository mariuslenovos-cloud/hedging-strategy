#!/usr/bin/env python3
"""
gridstat_ml_screen.py -- ML PROGRAM item (1): the FINGERPRINT-DISCOVERY SCREEN (2026-08-29).

ML PROPOSES, THE PIPELINE DISPOSES. This script does NOT pick trades. It asks one question of the
S28 all-fires shadow DB (every Goldminer fire incl. gate-blocked, triple-barrier labelled):
   "Is there a cut / interaction the coarse DIR|session|ATR fingerprint misses that predicts R
    OUT OF SAMPLE, and does it survive the same within-cell control that killed 6 of 7 hand
    features?"

Method (AFML): purged K-fold over time blocks (purge = the 24h barrier horizon, embargo 2%) ->
  A. interpretable depth-3 tree (the FXFade / hand-codable form) -> leaves = candidate cuts
  B. HistGradientBoosting -> OOS ranking power + permutation importance (which features carry it)
  C. THE HONEST BASELINE: the production fingerprint gate rebuilt from train folds only
     (cell win-rate >= 0.55, n >= 10) -> OOS avgR / totalR of its pass-set
  D. Head-to-head at EQUAL TRADE COUNT (ML top-k vs gate pass-set) and as a SIZING OVERLAY inside
     the gate's pass-set (does ML P(win) tercile separate R within already-passing fires?)
  E. WITHIN-CELL CONTROL on every candidate cut: sign-consistent inside the DIR|session|ATR cells,
     and stable across first/second half. Mixed signs = noise (the S30 signature).

Known-answer anchor: day-rank must re-emerge as a top feature (it is the one dimension that
survived by hand). If the screen cannot find day-rank, reject the screen.

Datasets: s30long (2024-01 -> 2026-08, 8.7k fires = discovery) and research (Dec-25 -> Aug-26,
2.4k fires = the recent-window check). Gold only (grisk 4, bands 71/29).
Run: python gridstat_ml_screen.py [long|recent]
"""
import io, sys, csv, math, warnings
import numpy as np, pandas as pd
from collections import defaultdict
warnings.filterwarnings("ignore")
from sklearn.tree import DecisionTreeRegressor, DecisionTreeClassifier, export_text
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance

COMMON = r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\Common\Files"
FILES = {"long": COMMON + r"\gridstat_setups_gold_s30long_allfires.csv",
         "recent": COMMON + r"\gridstat_setups_gold_research_allfires.csv"}
UPPER, LOWER = 71.0, 29.0          # grisk-4 gold bands
GATE_WR, GATE_N = 0.55, 10
N_FOLDS = 6
PURGE_H = 24                       # triple-barrier horizon
EMBARGO = 0.02

# ----------------------------------------------------------------------------- load + features
def read_allfires(path):
    """The EA writes skip_reason unquoted, and 'trendWeak(adx,ang)' carries a comma -> re-join."""
    rows = list(csv.reader(io.open(path, encoding="utf-8", errors="replace")))
    hdr = rows[0]; n = len(hdr); out = []
    for rw in rows[1:]:
        if not rw: continue
        while len(rw) > n:                       # merge the overflow back into skip_reason (idx 19)
            rw[19] = rw[19] + "," + rw[20]; del rw[20]
        if len(rw) == n: out.append(rw)
    return pd.DataFrame(out, columns=hdr)

def load(which):
    df = read_allfires(FILES[which])
    for c in ["entry_price", "atr_at_entry", "r_multiple", "mfe_r", "big_move", "wpr", "adx", "ma_angle",
              "runup", "period_used", "bars_in_band"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["t"] = pd.to_datetime(df["entry_time"], format="%Y.%m.%d %H:%M")
    df = df.sort_values("t").reset_index(drop=True)
    df["r"] = df["r_multiple"].astype(float)
    df["win"] = (df["r"] > 0).astype(int)
    parts = df["setup_key"].str.split("|", expand=True)
    df["dir"] = (parts[0] == "BUY").astype(int)
    df["sess"] = parts[1]
    df["atrreg"] = parts[2]
    df["cell"] = df["setup_key"]
    df["hour"] = df["t"].dt.hour
    df["dow"] = df["t"].dt.dayofweek
    # signal strength = penetration past the band in the trade's direction (the A-LIVE 07-23 form)
    df["pen"] = np.where(df["dir"] == 1, df["wpr"] - UPPER, LOWER - df["wpr"])
    df["atr_pct"] = 100.0 * df["atr_at_entry"] / df["entry_price"]
    df["ma_al"] = df["ma_angle"].astype(float)      # already signed with the trade in the EA log
    # normalise skip_reason to its class ('trendWeak(adx=10.1,ang=82.7)' -> 'trendWeak'), else the
    # one-hot explodes to ~700 unique columns
    df["skip_reason"] = df["skip_reason"].astype(str).str.replace(r"\(.*", "", regex=True).str.strip()
    df["gate_quality"] = df["skip_reason"].isin(["PASS", "maxBaskets"]).astype(int)
    # day-rank: rank of a GATE-QUALITY fire within its server day (S29 definition), K1/K2/K3+
    df["day"] = df["t"].dt.date
    df["day_rank"] = 0
    gq = df[df["gate_quality"] == 1]
    df.loc[gq.index, "day_rank"] = gq.groupby("day").cumcount() + 1
    df["k3"] = (df["day_rank"] >= 3).astype(int)
    if "mkt_state" not in df.columns: df["mkt_state"] = "NA"
    df["mkt_up"] = (df["mkt_state"] == "UP").astype(int)
    for c in ["sess", "atrreg", "skip_reason"]:
        for v in sorted(df[c].dropna().unique()):
            df[f"{c}_{v}"] = (df[c] == v).astype(int)
    return df

FEATS_BASE = ["dir", "hour", "dow", "pen", "adx", "ma_al", "runup", "bars_in_band", "atr_pct", "mkt_up",
              "day_rank", "gate_quality"]

def feature_cols(df):
    return FEATS_BASE + [c for c in df.columns if c.startswith(("sess_", "atrreg_", "skip_reason_"))]

# ----------------------------------------------------------------------------- purged folds
def purged_folds(df, k=N_FOLDS):
    n = len(df); edges = np.linspace(0, n, k + 1).astype(int)
    t = df["t"].values
    for i in range(k):
        te = np.arange(edges[i], edges[i + 1])
        t0, t1 = t[te[0]], t[te[-1]]
        purge = np.timedelta64(PURGE_H, "h")
        emb = np.timedelta64(int(EMBARGO * (t[-1] - t[0]) / np.timedelta64(1, "h")), "h")
        tr = np.array([j for j in range(n) if (t[j] < t0 - purge - emb) or (t[j] > t1 + purge + emb)])
        yield tr, te

# ----------------------------------------------------------------------------- baseline gate
def gate_from_train(df, tr):
    g = df.iloc[tr].groupby("cell")["win"].agg(["mean", "size"])
    return set(g[(g["mean"] >= GATE_WR) & (g["size"] >= GATE_N)].index)

# ----------------------------------------------------------------------------- main
def run(which):
    df = load(which); F = feature_cols(df)
    X = df[F].fillna(0).values; y = df["win"].values; r = df["r"].values
    print(f"=== {which}: {len(df)} fires {df['t'].min():%Y-%m-%d} -> {df['t'].max():%Y-%m-%d} | "
          f"raw win {y.mean():.3f} avgR {r.mean():+.3f} | gate-quality {df['gate_quality'].sum()} | {len(F)} features")

    oos_p = np.full(len(df), np.nan); oos_gate = np.zeros(len(df), bool)
    imp = defaultdict(list); fold_rows = []
    for fi, (tr, te) in enumerate(purged_folds(df)):
        gbm = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_depth=3,
                                             min_samples_leaf=40, l2_regularization=1.0, random_state=0)
        gbm.fit(X[tr], y[tr]); p = gbm.predict_proba(X[te])[:, 1]; oos_p[te] = p
        # THE HONEST BASELINE = the production decision as it was actually made: a fire the EA
        # would have TRADED (passed D1 + trend + the win-rate gate; blocked only by the slot).
        # (Rebuilding the gate from train folds over ALL fires would credit the gate with
        #  D1-blocked / trendWeak fires it never saw -- an unfair baseline.)
        gm = df.iloc[te]["gate_quality"].values.astype(bool); oos_gate[te] = gm
        # head-to-head at equal count
        k = int(gm.sum()); ml_top = np.zeros(len(te), bool)
        if k > 0: ml_top[np.argsort(-p)[:k]] = True
        rr = r[te]
        fold_rows.append((fi, len(te), k, rr[gm].mean() if k else np.nan, rr[gm].sum() if k else 0,
                          rr[ml_top].mean() if k else np.nan, rr[ml_top].sum() if k else 0))
        pi = permutation_importance(gbm, X[te], y[te], n_repeats=5, random_state=0, scoring="roc_auc")
        for f, v in zip(F, pi.importances_mean): imp[f].append(v)

    print("\n--- HEAD-TO-HEAD OOS at EQUAL trade count (gate pass-set vs ML top-k), per purged fold ---")
    print(f"{'fold':>4s}{'n':>6s}{'k':>5s}{'gate avgR':>11s}{'gate totR':>11s}{'ML avgR':>10s}{'ML totR':>10s}")
    for fr in fold_rows: print(f"{fr[0]:4d}{fr[1]:6d}{fr[2]:5d}{fr[3]:11.3f}{fr[4]:11.1f}{fr[5]:10.3f}{fr[6]:10.1f}")
    ga = np.nanmean([f[3] for f in fold_rows]); ma = np.nanmean([f[5] for f in fold_rows])
    gt = sum(f[4] for f in fold_rows); mt = sum(f[6] for f in fold_rows)
    print(f"{'ALL':>4s}{len(df):6d}{int(oos_gate.sum()):5d}{ga:11.3f}{gt:11.1f}{ma:10.3f}{mt:10.1f}"
          f"   folds ML>gate on avgR: {sum(1 for f in fold_rows if f[5] > f[3])}/{len(fold_rows)}")

    print("\n--- SIZING-OVERLAY test: inside the gate's OOS pass-set, does ML P(win) tercile separate R? ---")
    m = oos_gate & ~np.isnan(oos_p)
    if m.sum() > 30:
        q = pd.qcut(oos_p[m], 3, labels=["low", "mid", "high"], duplicates="drop")
        t = pd.DataFrame({"q": q, "r": r[m], "win": y[m]}).groupby("q", observed=True).agg(n=("r", "size"), win=("win", "mean"), avgR=("r", "mean"), totR=("r", "sum"))
        print(t.round(3).to_string())
        # halves stability of the overlay
        idx = np.where(m)[0]; half = len(idx) // 2
        for lbl, sl in (("1st half", idx[:half]), ("2nd half", idx[half:])):
            qq = pd.qcut(oos_p[sl], 3, labels=["low", "mid", "high"], duplicates="drop")
            tt = pd.DataFrame({"q": qq, "r": r[sl]}).groupby("q", observed=True)["r"].mean()
            print(f"   {lbl}: " + "  ".join(f"{k}={v:+.3f}" for k, v in tt.items()))

    print("\n--- PERMUTATION IMPORTANCE (OOS AUC drop, mean over folds; known answer: day_rank must appear) ---")
    for f, v in sorted(imp.items(), key=lambda kv: -np.mean(kv[1]))[:14]:
        print(f"   {f:22s} {np.mean(v):+.4f}  (std {np.std(v):.4f})")

    # ---------------- interpretable tree on ALL data -> candidate cuts (then within-cell control)
    print("\n--- DEPTH-3 TREE (regression on R, min leaf 60) = candidate cuts ---")
    tree = DecisionTreeRegressor(max_depth=3, min_samples_leaf=60, random_state=0).fit(X, r)
    print(export_text(tree, feature_names=F, decimals=2, show_weights=True))
    leaf = tree.apply(X); df["leaf"] = leaf
    lt = df.groupby("leaf").agg(n=("r", "size"), win=("win", "mean"), avgR=("r", "mean"), totR=("r", "sum")).sort_values("avgR")
    print(lt.round(3).to_string())

    print("\n--- WITHIN-CELL CONTROL on the tree's best and worst leaves (sign must hold inside DIR|session|ATR cells + across halves) ---")
    best, worst = lt.index[-1], lt.index[0]
    half_t = df["t"].iloc[len(df) // 2]
    for lbl, L in (("BEST leaf", best), ("WORST leaf", worst)):
        inl = df["leaf"] == L
        print(f"  {lbl} {L}: n={int(inl.sum())} avgR {df.loc[inl,'r'].mean():+.3f} vs rest {df.loc[~inl,'r'].mean():+.3f}")
        cells = df[inl].groupby("cell").size().sort_values(ascending=False).head(6).index
        for c in cells:
            a = df[(df["cell"] == c) & inl]["r"]; b = df[(df["cell"] == c) & ~inl]["r"]
            if len(a) >= 15 and len(b) >= 15:
                print(f"     {c:24s} in-leaf {a.mean():+.3f} (n{len(a)})  vs  rest-of-cell {b.mean():+.3f} (n{len(b)})  -> {'SAME sign' if np.sign(a.mean()-b.mean())==np.sign(df.loc[inl,'r'].mean()-df.loc[~inl,'r'].mean()) else 'FLIPS'}")
        for hl, hm in (("1st half", df["t"] < half_t), ("2nd half", df["t"] >= half_t)):
            a = df[inl & hm]["r"]; b = df[~inl & hm]["r"]
            print(f"     {hl}: in-leaf {a.mean():+.3f} (n{len(a)}) vs rest {b.mean():+.3f}")

    # ---------------- gate-quality-only tree (the flow the engine can actually trade)
    gq = df["gate_quality"] == 1
    if gq.sum() > 300:
        print(f"\n--- DEPTH-3 TREE on GATE-QUALITY fires only (n={int(gq.sum())}) — the tradeable flow ---")
        Fq = [f for f in F if not f.startswith("skip_reason_") and f != "gate_quality"]
        Xq = df.loc[gq, Fq].fillna(0).values; rq = df.loc[gq, "r"].values
        tq = DecisionTreeRegressor(max_depth=3, min_samples_leaf=40, random_state=0).fit(Xq, rq)
        print(export_text(tq, feature_names=Fq, decimals=2, show_weights=True))

if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "long")
