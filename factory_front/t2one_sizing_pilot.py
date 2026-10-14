"""t2one_sizing_pilot.py -- t2one research regime, hypothesis H1 (2026-10-14): SIZE, DON'T GATE.
Every gate tried on t2one (ADX, spread, trend M5..D1, regime, range position, cooldown) removed ladders at an UNCHANGED win
rate. The house law that has paid on the gold grid is the opposite: trade every fire, size the better-measured ones up.

First-order replay (the project's rule: levers get a Python pilot before an EA build). Source = the 10-month backtest fire log
(analysis_data/mm_fires_t2one_bt10m_20261008.csv), the live config's population: SELL, tier>=2, 3 x risk <= $40, taken ONE AT
A TIME (no new ladder until the previous resolved = maxPos 3 / no-reverse), ladder $ = r_tp1_0.5R x risk x 3 at 0.01x3.
A sizing rule multiplies a ladder's $ by its size multiple (1x or 2x = 0.02x3; the ladder's $ risk doubles with it).

PRE-REGISTERED BAR (before the run): a rule passes only if, vs the flat 1x control, it raises net AND RF (net / realized maxDD)
in BOTH halves, and the worst ladder stays <= $80 (= the cap at 2x). The size rules are fixed a priori from the record:
  S1 adx >= 34.4          (the 10-08 fire-level survivor: +0.10R, 74% both halves -- killed as a GATE, never tried as SIZE)
  S2 D1 regime DOWN       (88% of the backtest net is in gold-DOWN months; up-regime ladders still positive -> size, don't gate)
  S3 hour in the best block 04-11 server (H2 positive in every 4-h block; 04-07 and 08-11 the two largest)
  S4 S1 OR S2
"""
import os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
f = pd.read_csv(os.path.join(HERE, "analysis_data", "mm_fires_t2one_bt10m_20261008.csv"))
f["t"] = pd.to_datetime(f.signal_time, format="mixed"); f["ct"] = pd.to_datetime(f.close_time, format="mixed", errors="coerce")
f = f.drop_duplicates("t").sort_values("t")
f = f[(f.dir == "SELL") & (f.tier >= 2) & (3 * f.risk_price <= 40) & f["r_tp1_0.5R"].notna()].reset_index(drop=True)

# one at a time
keep, busy = [], pd.Timestamp.min
for r in f.itertuples():
    if r.t <= busy: continue
    keep.append(r.Index); busy = r.ct if pd.notna(r.ct) else r.t
L = f.loc[keep].copy()
L["usd"] = L["r_tp1_0.5R"] * L.risk_price * 3

# D1 regime from gold's own daily closes (prior day close vs prior-day EMA50) -- no look-ahead
d1 = pd.read_csv(os.path.join(HERE, "analysis_data", "xauusd_m1_15mo.csv"), parse_dates=["time"]).set_index("time").close.resample("1D").last().dropna()
ema = d1.ewm(span=50, adjust=False).mean()
down = ((d1.shift(1) < ema.shift(1))).reindex(L.t.dt.floor("1D")).values
L["down"] = pd.Series(down, index=L.index).fillna(False).astype(bool)

half = L.t.median()
rules = {"S0 flat 1x (control)": np.zeros(len(L), bool),
         "S1 adx>=34.4 -> 2x": (L.adx >= 34.4).values,
         "S2 D1 down -> 2x": L.down.values,
         "S3 hours 04-11 -> 2x": L.t.dt.hour.between(4, 11).values,
         "S4 S1 or S2 -> 2x": ((L.adx >= 34.4) | L.down).values}


def stats(x):
    eq = x.cumsum(); dd = (eq - eq.cummax()).min()
    return x.sum(), dd, (x.sum() / -dd if dd < 0 else np.inf)


print(f"t2one live-config population, one at a time: {len(L)} ladders {L.t.min().date()} -> {L.t.max().date()}, "
      f"win {(L['r_tp1_0.5R'] > 0).mean()*100:.1f}%, net ${L.usd.sum():,.0f}  (split {half.date()})")
print(f"{'rule':<24}{'2x share':>9}{'win@2x':>8}{'net':>9}{'maxDD':>8}{'RF':>6}{'worst':>8} |{'H1 net':>8}{'H1 RF':>7}{'H2 net':>8}{'H2 RF':>7}  verdict")
base = {}
for name, m in rules.items():
    x = L.usd * np.where(m, 2.0, 1.0); n_, dd, rf = stats(x)
    h1 = x[L.t <= half]; h2 = x[L.t > half]; s1 = stats(h1); s2 = stats(h2)
    if name.startswith("S0"): base = dict(n1=s1[0], r1=s1[2], n2=s2[0], r2=s2[2])
    ok = (not name.startswith("S0")) and s1[0] > base["n1"] and s1[2] > base["r1"] and s2[0] > base["n2"] and s2[2] > base["r2"] and x.min() >= -80
    win2 = (L["r_tp1_0.5R"][m] > 0).mean() * 100 if m.any() else float("nan")
    print(f"{name:<24}{m.mean()*100:>8.0f}%{win2:>7.1f}%{n_:>9,.0f}{dd:>8,.0f}{rf:>6.1f}{x.min():>8,.0f} |{s1[0]:>8,.0f}{s1[2]:>7.1f}{s2[0]:>8,.0f}{s2[2]:>7.1f}  "
          + ("-" if name.startswith("S0") else ("PASS" if ok else "fail")))
