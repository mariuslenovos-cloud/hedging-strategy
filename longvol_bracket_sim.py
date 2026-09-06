"""longvol_bracket_sim.py -- REBUILD of the 2026-08-24 long-volatility bracket sim (the original lived in a scratchpad
and was never saved; the recorded survivors were arm 13:00 k=0.7 w6/w9 and arm 15:00 k=0.5 w6, positive in the
pain windows under pessimistic fills). Mechanism: at server hour H arm an OCO stop-pair at ref +/- k*ATR(D1,14);
a breach enters WITH the move, the opposite level is the stop, exit at arm+w hours. No direction opinion.
PESSIMISTIC FILLS (pass-2 of 08-24): entry AND stop filled at the NEXT M5 bar's open; both levels breached in one
bar = full bracket loss. Cost = actual bar spread at entry + exit (points*0.01 $/oz) + $0.07/oz commission.
PRE-COMMITTED GATES (before reading): the three recorded survivors must (a) be net-positive, (b) positive in both
halves, (c) positive summed over the pain windows; k=0.3 cells should fail (recorded as killed). G3 sizing: at the
0.01-lot floor on $2,390, max equity DD <= 20% ($478). Data: analysis_data/xauusd_m5_export.csv (PEP, server time)."""
import numpy as np, pandas as pd, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
m5 = pd.read_csv("analysis_data/xauusd_m5_export.csv", parse_dates=["time"])
m5["date"] = m5.time.dt.date
day = m5.groupby("date").agg(hi=("high", "max"), lo=("low", "min"))
atr14 = (day.hi - day.lo).rolling(14).mean().shift(1)          # prior 14 days only
COMM = 0.07
WINDOWS = [("Jan parabola+crash", "2026-01-20", "2026-02-07"), ("Mar slide", "2026-03-01", "2026-04-01"),
           ("Apr whipsaw", "2026-04-13", "2026-04-18"), ("May event", "2026-05-10", "2026-05-15"),
           ("Jun oil crash", "2026-06-01", "2026-07-01"), ("Jul oil slide", "2026-07-24", "2026-07-30"),
           ("Aug meltup+whip", "2026-08-03", "2026-08-08"), ("Aug-19 whipsaw", "2026-08-18", "2026-08-21")]
def run(H, k, w):
    out = []
    for d, g in m5.groupby("date"):
        a = atr14.get(d, np.nan)
        if not np.isfinite(a): continue
        g = g.reset_index(drop=True)
        arm_idx = g.index[(g.time.dt.hour == H)]
        if len(arm_idx) == 0: continue
        i0 = arm_idx[0]; t0 = g.time[i0]; ref = g.open[i0]
        up, dn = ref + k * a, ref - k * a
        tend = t0 + pd.Timedelta(hours=w)
        win = g[(g.index >= i0) & (g.time < tend)]
        if len(win) < 3: continue
        side = 0; entry = None; pnl = None
        for j in win.index:
            r = g.loc[j]
            if side == 0:
                both = r.high >= up and r.low <= dn
                if both:
                    pnl = -(2 * k * a) - r.spread * 0.01 * 2 - COMM; break
                if r.high >= up or r.low <= dn:
                    side = 1 if r.high >= up else -1
                    if j + 1 >= len(g): side = 0; break          # breach on the day's last bar: no fill possible
                    entry = g.open[j + 1]; ecost = r.spread * 0.01
                    stop = dn if side == 1 else up
                    continue
            else:
                hit = (r.low <= stop) if side == 1 else (r.high >= stop)
                if hit:
                    ex = g.open[j + 1] if j + 1 < len(g) else g.close[j]; pnl = side * (ex - entry) - ecost - r.spread * 0.01 - COMM; break
        if side != 0 and pnl is None:                     # window ended: exit at open of next bar after window
            j = win.index[-1]
            ex = g.open[j + 1] if j + 1 < len(g) else g.close[j]      # day's last bar: fill at its close
            pnl = side * (ex - entry) - ecost - g.spread[j] * 0.01 - COMM
        if pnl is not None: out.append((t0, pnl))
    return pd.Series(dict(out)).sort_index()
def report(H, k, w):
    s = run(H, k, w); mid = s.index[len(s) // 2]
    h1, h2 = s[:mid].sum(), s[mid:].sum()
    pain = sum(s[(s.index >= pd.Timestamp(a)) & (s.index < pd.Timestamp(b))].sum() for _, a, b in WINDOWS)
    eq = s.cumsum(); dd = (eq - eq.cummax()).min()
    win = (s > 0).mean() * 100
    return dict(cell=f"H{H} k{k} w{w}", n=len(s), net=s.sum(), h1=h1, h2=h2, pain=pain, win=win, maxdd=dd,
                avg=s.mean(), worst=s.min())
rows = [report(H, k, w) for H in (13, 15) for k in (0.3, 0.5, 0.7) for w in (6, 9)]
df = pd.DataFrame(rows); pd.set_option("display.width", 200)
print(f"gold M5 {m5.time.iloc[0]} -> {m5.time.iloc[-1]}; $ per oz = $ at 0.01 lot; pessimistic next-bar fills, real bar spread + $0.07 comm")
print(df.round(2).to_string(index=False))
print("\nGATES (recorded 08-24 survivors = H13 k0.7 w6/w9, H15 k0.5 w6): net>0 & both halves>0 & pain>0")
for c in ("H13 k0.7 w6", "H13 k0.7 w9", "H15 k0.5 w6"):
    r = df[df.cell == c].iloc[0]
    ok = r.net > 0 and r.h1 > 0 and r.h2 > 0 and r.pain > 0
    print(f"  {c}: {'PASS' if ok else 'FAIL'}  net ${r.net:.0f}  h1 ${r.h1:.0f} h2 ${r.h2:.0f}  pain ${r.pain:.0f}  maxDD ${r.maxdd:.0f} = {-100*r.maxdd/2390:.1f}% of $2,390 -> G3 {'PASS' if -r.maxdd <= 478 else 'FAIL'}  worst trade ${r.worst:.0f} = {-100*r.worst/2390:.1f}%")
print("\nPER-WINDOW (H13 k0.7 w9 vs the grid's documented losses):")
s = run(13, 0.7, 9)
for lab, a, b in WINDOWS:
    x = s[(s.index >= pd.Timestamp(a)) & (s.index < pd.Timestamp(b))]
    print(f"  {lab:20s} {len(x):3d} trades  ${x.sum():+7.0f}")
