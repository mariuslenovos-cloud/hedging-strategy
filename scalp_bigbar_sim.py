"""OUTSIZED-BAR FADE scalper, priced first-order on the M1 mid export (2026-09-05).
Idea: gold's M1 reversion is ~3-9% of a bar (inside the spread on average) but it is a FRACTION,
so only bars >= k sigma carry an expected snap-back bigger than cost. Fade only those.
Entry next bar OPEN (taker) or a LIMIT one half-spread better (maker; fills only on penetration).
TP = f x bar range, SL = 1 x bar range, time-out N bars at close. Cost C round turn. Pessimistic:
stop-first when both levels sit in one bar. Pre-committed bar: avg net > 0 with t > 2 on >= 300 trades,
surviving cost x1.5. Prints a per-server-hour table for the best cell."""
import pandas as pd, numpy as np, itertools, sys
sym = sys.argv[1] if len(sys.argv) > 1 else "xauusd"
C = 0.25 if sym == "xauusd" else 0.05
d = pd.read_csv(f"analysis_data/{sym}_m1_export.csv", parse_dates=["time"]).reset_index(drop=True)
d["ret"] = d.mid.diff(); d["sig"] = d.ret.rolling(100).std(); d["rng"] = d.high - d.low
d["hr"] = d.time.dt.hour
O, H, L, Cl, R = d.open.values, d.high.values, d.low.values, d.close.values, d.rng.values
z = (d.ret / d.sig).values
def run(k, f, N, maker):
    out = []
    idx = np.where(np.abs(z) >= k)[0]
    last = -1
    for i in idx:
        if i <= last or i + 2 >= len(d): continue
        side = -1 if z[i] > 0 else 1            # fade: up-bar -> sell
        e = i + 1
        if maker:                                # limit half-spread better than next open; fill only if next bar penetrates
            px = O[e] - side * 0.06
            filled = (L[e] <= px) if side == 1 else (H[e] >= px)
            if not filled: continue
        else:
            px = O[e]
        tp = px + side * f * R[i]; sl = px - side * R[i]
        res = None
        for k2 in range(e, min(e + N, len(d))):
            if side == 1:
                if L[k2] <= sl: res = sl; break
                if H[k2] >= tp: res = tp; break
            else:
                if H[k2] >= sl: res = sl; break
                if L[k2] <= tp: res = tp; break
        if res is None: res = Cl[min(e + N - 1, len(d) - 1)]
        out.append(((res - px) * side, d.hr[e]))
        last = e + N
    return out
rows = []
for k, f, N, maker in itertools.product((2, 3, 4), (0.3, 0.5), (3, 5, 10), (False, True)):
    t = run(k, f, N, maker)
    if len(t) < 30: continue
    g = np.array([x[0] for x in t]); n = len(g)
    net = g - C; net15 = g - 1.5 * C
    rows.append(dict(k=k, f=f, N=N, maker=maker, n=n, gross=g.mean(), net=net.mean(), t=net.mean() / net.std() * np.sqrt(n), net_c15=net15.mean(), win=(net > 0).mean()))
res = pd.DataFrame(rows).sort_values("t", ascending=False)
pd.set_option("display.width", 200)
print(f"{sym}  span {d.time.iloc[0]:%Y-%m-%d} -> {d.time.iloc[-1]:%Y-%m-%d}  bars {len(d):,}  C={C}")
print(res.round(3).to_string(index=False))
b = res.iloc[0]
t = run(b.k, b.f, b.N, b.maker); tt = pd.DataFrame(t, columns=["gross", "hr"]); tt["net"] = tt.gross - C
print(f"\nbest cell k={b.k} f={b.f} N={b.N} maker={b.maker}: n={len(tt)} net {tt.net.mean():+.3f} t={tt.net.mean()/tt.net.std()*np.sqrt(len(tt)):.2f}  total {tt.net.sum():+.1f}/oz")
print(tt.groupby("hr").agg(n=("net", "size"), net=("net", "mean"), tot=("net", "sum")).round(2).to_string())
passing = res[(res.t > 2) & (res.n >= 300) & (res.net_c15 > 0)]
print("\nPRE-COMMITTED GATE (t>2, n>=300, net at cost x1.5 > 0):", "PASS\n" + passing.round(3).to_string(index=False) if len(passing) else "FAIL - no cell")
