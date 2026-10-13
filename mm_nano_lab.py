#!/usr/bin/env python3
"""
mm_nano_lab.py -- score the tick-level capture (mm_nano_capture.py). PLACES NO ORDERS.
Four questions, each with its gate written here BEFORE the data is read:
  Q1 tick-vs-bar: does the tick-exact outcome agree with the EA's bar outcome?  (if < 90%, the bar record is suspect)
  Q2 microstructure meta-labelling: walk-forward AUC on SELL fires from tick features only.   GATE: AUC >= 0.60
  Q3 early-path decision point: P(win | first-30s/60s MAE or MFE bucket). A bucket is usable only if it
     changes expectancy sign with n >= 40 in BOTH halves.
  Q4 tick-timed entry: wait up to W seconds for a pullback of P x R against the fire direction, enter there
     (same stop/target geometry from the fill), else skip. GATE: beats bar entry in BOTH halves on net $ AND worst-28-day.
usage: python mm_nano_lab.py analysis_data\mm_nano_fires_<date>.csv
"""
import sys, os, numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.metrics import roc_auc_score

fn = sys.argv[1]; d = pd.read_csv(fn); d["t"] = pd.to_datetime(d.signal_time, format="mixed"); d = d.sort_values("t").reset_index(drop=True)
tk = np.load(fn.replace("mm_nano_fires_", "mm_nano_ticks_").replace(".csv", ".npz"))
d["usd"] = d.tick_r * d.R * 3 - d.entry_spread * 3          # $ at 0.01x3, tick-exact, spread charged once
s = d[(d.dir == "SELL") & (d.riskUSD <= 40) & d.tick_outcome.notna()].copy(); half = s.t.median()
print(f"{len(d)} fires, {len(s)} cap-eligible SELL with ticks, {s.t.min().date()} -> {s.t.max().date()}")

print("\nQ1 tick-vs-bar outcome agreement:", round((d.tick_outcome == d.bar_outcome).mean() * 100, 1), "%")
print("   SELL tick-exact: win", round((s.tick_outcome == "target").mean() * 100, 1), "% net $", round(s.usd.sum()), " median secs to resolve", s.secs_to_resolve.median())

feats = [c for c in ["tick_rate_600", "tick_rate_60", "tick_rate_10", "imb_600", "imb_60", "spread_mean", "spread_max", "spread_last", "spread_std",
                     "rv_60", "rv_600", "max_run_60", "drift_60", "drift_600", "range_600"] if c in s]
s["y"] = (s.tick_outcome == "target").astype(int); s["blk"] = s.t.dt.to_period("W").astype(str)
oos = []
for b in sorted(s.blk.unique())[3:]:
    tr = s[(s.blk < b)].dropna(subset=feats); te = s[s.blk == b].dropna(subset=feats)
    if len(tr) < 40 or len(te) == 0: continue
    m = make_pipeline(StandardScaler(), LogisticRegression(C=0.3, max_iter=2000)).fit(tr[feats], tr.y); oos.append(te.assign(p=m.predict_proba(te[feats])[:, 1]))
if oos:
    o = pd.concat(oos); print(f"\nQ2 microstructure walk-forward AUC = {roc_auc_score(o.y, o.p):.3f}  (n={len(o)}; GATE 0.60)")
    for c in feats:
        q = pd.qcut(s[c].rank(method="first"), 4, labels=False); print(f"   {c:14s} win% by quartile", [round(v * 100) for v in s.groupby(q).y.mean()])

print("\nQ3 early-path decision points (SELL): P(win) and $/fire by bucket, split by halves")
for col, edges in [("mae_30s", [-9, -0.5, -0.3, -0.15, 0.01]), ("mae_60s", [-9, -0.5, -0.3, -0.15, 0.01]), ("mfe_30s", [-1, 0.05, 0.15, 0.3, 9]), ("mfe_60s", [-1, 0.05, 0.15, 0.3, 9]), ("close_60s", [-9, -0.2, 0, 0.2, 9])]:
    if col not in s: continue
    b = pd.cut(s[col], edges)
    g = s.groupby(b, observed=True).apply(lambda x: pd.Series(dict(n=len(x), win=round(x.y.mean() * 100), usd_per=round(x.usd.mean(), 2),
                                                                 h1_usd=round(x[x.t <= half].usd.sum()), h2_usd=round(x[x.t > half].usd.sum()))))
    print(f"  {col}:"); print(g.to_string())

print("\nQ4 tick-timed entry: wait W s for a pullback of P x R, else skip (same geometry from the fill)")
def sim(P, W):
    res = []
    for i, r in s.iterrows():
        key = f"f{i}"
        if key not in tk: continue
        a = tk[key]; t, bid, ask = a[:, 0], a[:, 1], a[:, 2]; R = r.R
        # SELL: we sell at bid. pullback = ask rises P*R above the fire entry within W s -> we sell at that bid
        if P > 0:
            j = np.where((t <= W) & (bid >= r.entry + P * R))[0]
            if len(j) == 0: res.append(dict(t=r.t, usd=0.0, taken=0)); continue
            j = j[0]
        else: j = 0
        e = bid[j]; sl = e + R; tp = e - 0.5 * R
        hit_t = np.where(ask[j:] <= tp)[0]; hit_s = np.where(ask[j:] >= sl)[0]
        it = hit_t[0] if len(hit_t) else None; ix = hit_s[0] if len(hit_s) else None
        rr = 0.5 if (it is not None and (ix is None or it < ix)) else (-1.0 if ix is not None else (e - ask[-1]) / R)
        res.append(dict(t=r.t, usd=rr * R * 3 - (ask[j] - bid[j]) * 3, taken=1))
    x = pd.DataFrame(res); daily = x.groupby(x.t.dt.date).usd.sum(); w28 = daily.rolling(28, min_periods=1).sum().min()
    return dict(P=P, W=W, taken=int(x.taken.sum()), net=round(x.usd.sum()), h1=round(x[x.t <= half].usd.sum()), h2=round(x[x.t > half].usd.sum()), worst28=round(w28))
rows = [sim(0, 0)] + [sim(P, W) for P in (0.1, 0.2, 0.3) for W in (30, 60, 180, 600)]
print(pd.DataFrame(rows).to_string(index=False))
