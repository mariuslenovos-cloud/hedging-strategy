#!/usr/bin/env python3
"""
gridstat_ml_sizing.py -- ML PROGRAM item (2): the SIZING-OVERLAY holdout test (2026-08-29).

The screen (item 1) showed, on the LONG window, that ML P(win) terciles INSIDE the production
pass-set separate R (bottom tercile ~0R vs +0.11..0.13) -- but the RECENT window did not
reproduce it in-fold. The honest test: TRAIN on the long window BEFORE 2025-12-01 only, apply to
the RECENT window (Dec-25 -> Aug-26) as a TRUE FORWARD HOLDOUT, and look inside the fires the EA
actually traded (gate-quality).  PASS = the bottom P(win) tercile is ~0R or worse while the upper
terciles stay positive, in BOTH halves of the holdout. Then, and only then, a sizing overlay
(0.75x bottom / 1.0x mid / 1.25x top -- never a gate, never below 0.75x) earns a tester A/B.

Deployment note: a per-fire score cannot go through the per-KEY sizing CSV (LookupSizing). The
deployable form is an EA-side depth-3 tree (the FXFade precedent) -> so we also print the
depth-3 tree fitted on the training window for the hand-coded candidate.
"""
import io, sys, numpy as np, pandas as pd, warnings
warnings.filterwarnings("ignore")
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.tree import DecisionTreeClassifier, export_text
from sklearn.metrics import roc_auc_score
sys.path.insert(0, ".")
from gridstat_ml_screen import load, feature_cols

CUT = pd.Timestamp("2025-12-01")

def main():
    lo = load("long"); re_ = load("recent")
    F = [f for f in feature_cols(lo) if f in re_.columns and not f.startswith("skip_reason_")]
    tr = lo[lo["t"] < CUT].copy()
    print(f"train: {len(tr)} fires {tr['t'].min():%Y-%m-%d} -> {tr['t'].max():%Y-%m-%d} (gate-quality {int(tr['gate_quality'].sum())})")
    print(f"holdout: {len(re_)} fires {re_['t'].min():%Y-%m-%d} -> {re_['t'].max():%Y-%m-%d} (gate-quality {int(re_['gate_quality'].sum())})")
    print(f"features ({len(F)}): {F}")

    # model A: trained on ALL train fires; model B: trained on gate-quality train fires only
    for lbl, sub in (("A: trained on all fires", tr), ("B: trained on gate-quality fires only", tr[tr["gate_quality"] == 1])):
        gbm = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_depth=3,
                                             min_samples_leaf=40, l2_regularization=1.0, random_state=0)
        gbm.fit(sub[F].fillna(0).values, sub["win"].values)
        ho = re_[re_["gate_quality"] == 1].copy()
        ho["p"] = gbm.predict_proba(ho[F].fillna(0).values)[:, 1]
        auc = roc_auc_score(ho["win"], ho["p"])
        print(f"\n=== {lbl} -> holdout gate-quality n={len(ho)} | OOS AUC {auc:.3f} | holdout avgR {ho['r'].mean():+.3f}")
        ho["q"] = pd.qcut(ho["p"], 3, labels=["low", "mid", "high"], duplicates="drop")
        t = ho.groupby("q", observed=True).agg(n=("r", "size"), win=("win", "mean"), avgR=("r", "mean"), totR=("r", "sum"))
        print(t.round(3).to_string())
        half = ho["t"].iloc[len(ho) // 2]
        for hl, m in (("1st half", ho["t"] < half), ("2nd half", ho["t"] >= half)):
            s = ho[m]; qq = pd.qcut(s["p"], 3, labels=["low", "mid", "high"], duplicates="drop")
            tt = s.groupby(qq, observed=True)["r"].agg(["mean", "size"])
            print(f"   {hl}: " + "  ".join(f"{k}={v['mean']:+.3f}(n{int(v['size'])})" for k, v in tt.iterrows()))
        # the overlay's first-order economics on the holdout: size 0.75/1.0/1.25 by tercile vs flat
        mult = ho["q"].map({"low": 0.75, "mid": 1.0, "high": 1.25}).astype(float)
        flat = ho["r"].sum(); ov = (ho["r"] * mult).sum()
        print(f"   overlay 0.75/1.0/1.25 first-order: totR {ov:+.1f} vs flat {flat:+.1f} ({100*(ov/flat-1) if flat else 0:+.1f}%) | "
              f"exposure {mult.sum()/len(ho):.3f}x")

    # the hand-codable candidate
    print("\n=== depth-3 tree on train gate-quality fires (P(win)) — the EA-side candidate form ===")
    sub = tr[tr["gate_quality"] == 1]
    Ft = [f for f in F if f != "gate_quality"]
    dt_ = DecisionTreeClassifier(max_depth=3, min_samples_leaf=40, random_state=0).fit(sub[Ft].fillna(0).values, sub["win"].values)
    print(export_text(dt_, feature_names=Ft, decimals=2, show_weights=True))
    ho = re_[re_["gate_quality"] == 1].copy(); ho["leaf"] = dt_.apply(ho[Ft].fillna(0).values)
    ho["ptree"] = dt_.predict_proba(ho[Ft].fillna(0).values)[:, 1]
    print("holdout by tree leaf (train P(win) -> holdout avgR):")
    print(ho.groupby("leaf").agg(train_p=("ptree", "first"), n=("r", "size"), win=("win", "mean"), avgR=("r", "mean")).sort_values("train_p").round(3).to_string())

if __name__ == "__main__":
    main()
