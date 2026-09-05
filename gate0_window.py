"""Gate 0, the user's exact form: lag-1 autocorrelation of M1 returns inside the Engine-A window
(00:00-13:30 SAST), on MID (bounce-free) vs BID close (bounce-contaminated). t = ac*sqrt(n).
Pairs are consecutive bars only (no cross-gap, no cross-window pairs). Pre-committed: pass = mid t < -2."""
import numpy as np, pandas as pd, sys
TZ = -1  # server -> SAST
def load(sym):
    d = pd.read_csv(f"analysis_data/{sym}_m1_export.csv"); d["ts"] = pd.to_datetime(d.time) + pd.Timedelta(hours=TZ)
    return d
def pairs(d, col, mask):
    lp = np.log(d[col].to_numpy()); r = np.diff(lp)
    dt = d.ts.diff().dt.total_seconds().to_numpy()[1:]; ok = dt <= 5*np.nanmedian(dt)
    m = mask.to_numpy()[1:]                       # return i belongs to bar i+1's timestamp
    a, b = r[:-1], r[1:]; keep = ok[:-1] & ok[1:] & m[:-1] & m[1:]
    a, b = a[keep], b[keep]; ac = np.corrcoef(a, b)[0, 1]; n = len(a)
    return ac, ac*np.sqrt(n), n, r[ok & m].std()
for sym, cost in (("xauusd", 0.25), ("spotcrude", 0.05)):
    d = load(sym); h = d.ts.dt.hour; mi = d.ts.dt.minute
    win = (h < 13) | ((h == 13) & (mi < 30)); rest = ~win
    print(f"=== {sym}  {d.ts.iloc[0]} -> {d.ts.iloc[-1]} (SAST)")
    for name, mask in (("00:00-13:30 (Engine A window)", win), ("13:30-24:00 (complement)", rest), ("all hours", win | rest)):
        for col in ("mid", "close"):
            ac, t, n, sd = pairs(d, col, mask)
            px = d[col].iloc[-1]; move = abs(ac) * sd * px
            print(f"  {name:32s} {col:5s} lag1={ac:+.4f} t={t:+6.2f} n={n:6d} | 1-sigma bar ${sd*px:.3f}, predictable ${move:.3f} vs cost ${cost}")
    # per-hour on mid, window hours only, so the bucket verdict can't hide a single hour
    print("  per-hour (mid): hr lag1 t")
    for hr in range(0, 14):
        mk = (h == hr) if hr < 13 else ((h == 13) & (mi < 30))
        ac, t, n, sd = pairs(d, "mid", mk); print(f"    {hr:02d} {ac:+.4f} {t:+6.2f} n={n}")
