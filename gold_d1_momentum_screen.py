"""gold_d1_momentum_screen.py -- neighbourhood (1) of the 2026-09-06 outside read: gold DAILY-horizon momentum,
the "other side of the asymmetry" (gold reverts intraday, trends daily). Pre-committed gates BEFORE reading:
  G1 net Sharpe > 0.5 in BOTH halves (2016-21 / 2021-26) after real CFD cost (spread+commission+swap)
  G2 recent-3y net positive
  G3 sizing wall: at the 0.01-lot floor on the live $2,390 balance the strategy's worst equity DD <= 20% of balance
Data: 11y XM GOLD M30 (analysis_data/xm_gold_m30_export.csv) resampled to D1 (server-day close). One instrument, so
this cannot contradict the 20-market futures verdicts (ib_trend_phase1 / edge_trend_st) -- it answers the
narrower question the read actually asks: does GOLD alone carry daily momentum worth a CFD's carry?
Cost model: spread+commission $0.18/oz round trip (PEP XAUUSD median spread 11pt + $7/lot RT commission);
swap = per-night charge on the held side, swept {0, -2, -4, -6} %/yr of notional (PEP gold long swap is negative;
sweep because the exact figure is not on file -- the sensitivity is the point)."""
import numpy as np, pandas as pd, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
m30 = pd.read_csv("analysis_data/xm_gold_m30_export.csv", parse_dates=["time"]).set_index("time")
d1 = m30["close"].resample("1D").last().dropna()
d1 = d1[d1.index.dayofweek < 5]
ret = np.log(d1).diff().dropna()
px = d1.reindex(ret.index)
print(f"gold D1 bars {len(d1):,}  {d1.index[0].date()} -> {d1.index[-1].date()}")
RT_COST_OZ = 0.18
def run(pos, swap_pct):
    """pos = target position in units of +/-1 oz-equivalent (already vol-scaled), decided on close t, held t->t+1."""
    pos = pos.shift(1).fillna(0)                      # act next bar
    pnl_oz = pos * (px.diff())                        # $/oz
    turn = pos.diff().abs().fillna(pos.abs())
    cost = turn * RT_COST_OZ / 2                      # half RT per side crossed
    carry = abs(pos) * px * (swap_pct / 100.0) / 365.0    # swap_pct<0 = pay on any held side
    net = pnl_oz - cost + carry
    return net
def stats(net, label):
    n = net.dropna()
    h1 = n[: "2021-06-30"]; h2 = n["2021-07-01":]; r3 = n[n.index[-1] - pd.Timedelta(days=3 * 365):]
    sh = lambda x: (x.mean() / x.std() * np.sqrt(252)) if x.std() > 0 else np.nan
    eq = n.cumsum(); dd = (eq - eq.cummax()).min()
    return dict(label=label, sharpe=sh(n), h1=sh(h1), h2=sh(h2), r3=sh(r3), net_oz=n.sum(), maxdd_oz=dd,
                r3_net=r3.sum(), flips_yr=float((net.index.size and 0) or 0))
vol = ret.rolling(60).std() * np.sqrt(252)
rows = []
for swap in (0, -2, -4, -6):
    for L in (20, 60, 120, 250):
        sig = np.sign(np.log(px / px.shift(L)))                 # TSMOM sign
        pos = (sig * (0.10 / vol)).clip(-3, 3)                  # 10% vol target, in oz-units per $1 of... relative
        rows.append(dict(swap=swap, family="TSMOM", param=L, longonly=False, **stats(run(pos, swap), f"tsmom{L}")))
        rows.append(dict(swap=swap, family="TSMOM", param=L, longonly=True, **stats(run(pos.clip(lower=0), swap), f"tsmom{L}L")))
    for N in (20, 55, 100):
        hi = px.rolling(N).max().shift(1); lo = px.rolling(N).min().shift(1)
        pos = pd.Series(np.nan, index=px.index)
        pos[px > hi] = 1; pos[px < lo] = -1
        pos = pos.ffill().fillna(0) * (0.10 / vol)
        rows.append(dict(swap=swap, family="DONCH", param=N, longonly=False, **stats(run(pos.clip(-3, 3), swap), f"donch{N}")))
df = pd.DataFrame(rows)
pd.set_option("display.width", 200)
for swap in (0, -2, -4, -6):
    d = df[df.swap == swap].copy()
    print(f"\n=== swap {swap}%/yr on held notional  (Sharpe: full / h1 2016-21 / h2 2021-26 / recent 3y; net $/oz) ===")
    print(d[["label", "sharpe", "h1", "h2", "r3", "net_oz", "maxdd_oz", "r3_net"]].round(2).to_string(index=False))
# sizing wall at the 0.01-lot floor
atr = (m30["high"].resample("1D").max() - m30["low"].resample("1D").min()).dropna()
atr14 = atr.rolling(14).mean()
print(f"\nSIZING WALL: gold ATR(D1,14) now ${atr14.iloc[-1]:.0f}/oz; 0.01 lot = $1/point -> 2xATR stop = ${2*atr14.iloc[-1]:.0f} "
      f"= {200*atr14.iloc[-1]/2390:.1f}% of the $2,390 balance per trade; daily 1-sigma at 0.01 lot = "
      f"${px.iloc[-1]*ret.tail(60).std():.0f} = {100*px.iloc[-1]*ret.tail(60).std()/2390:.1f}%/day of balance")
print("\nG3 SIZING WALL at a FIXED 0.01 lot (1 oz, sign-only, swap -4%/yr) on $2,390:")
for L in (60,120):
    sig=np.sign(np.log(px/px.shift(L))); n=run(sig,-4).dropna(); eq=n.cumsum(); dd=(eq-eq.cummax())
    nL=run(sig.clip(lower=0),-4).dropna(); eqL=nL.cumsum(); ddL=(eqL-eqL.cummax())
    worst_yr=n.groupby(n.index.year).sum().min()
    print(f"  tsmom{L} long/short: net ${n.sum():,.0f} over {len(n)/252:.1f}y = ${n.sum()/(len(n)/252):,.0f}/yr, maxDD ${dd.min():,.0f} = {-100*dd.min()/2390:.0f}% of balance, worst calendar year ${worst_yr:,.0f}; DD>=20%bal? {'FAIL' if -dd.min()>478 else 'PASS'}")
    print(f"  tsmom{L} long-only : net ${nL.sum():,.0f}, maxDD ${ddL.min():,.0f} = {-100*ddL.min()/2390:.0f}% of balance; DD>=20%bal? {'FAIL' if -ddL.min()>478 else 'PASS'}")
best = df[(df.swap == -4)].sort_values("sharpe", ascending=False).iloc[0]
print(f"\nGATES at swap -4%/yr, best cell {best.label}: G1 both halves >0.5 -> {'PASS' if best.h1 > 0.5 and best.h2 > 0.5 else 'FAIL'} "
      f"(h1 {best.h1:.2f}, h2 {best.h2:.2f}); G2 recent-3y net>0 -> {'PASS' if best.r3_net > 0 else 'FAIL'} ({best.r3_net:+.0f} $/oz)")
