"""First-order sim of REVSCALP Engine A (GOLD_MR) exactly as specified, on the M1 mid export.
Pessimistic: entry at NEXT bar open, stop-first when TP and SL sit in the same bar, cost C per round turn.
Long side per spec; short side mirrored. Session 00:00-13:30 SAST = 01:00-14:30 server."""
import pandas as pd, numpy as np
d = pd.read_csv("analysis_data/xauusd_m1_export.csv", parse_dates=["time"]).reset_index(drop=True)
C = 0.25
d["tp_"] = (d.high + d.low + d.close) / 3
d["day"] = d.time.dt.date
d["pv"] = (d.tp_ * d.tick_volume).groupby(d.day).cumsum(); d["vv"] = d.tick_volume.groupby(d.day).cumsum()
d["vwap"] = d.pv / d.vv
d["dev"] = d.mid - d.vwap
d["sdev"] = d.dev.rolling(120).std()
d["z"] = d.dev / d.sdev
tr = np.maximum(d.high - d.low, np.maximum((d.high - d.close.shift()).abs(), (d.low - d.close.shift()).abs()))
d["atr1"] = tr.rolling(14).mean()
d["rng"] = d.high - d.low
# M5 context: ER(10), EMA20/50 flatness vs ATR14(M5)
m5 = d.set_index("time").resample("5min").agg(open=("open","first"),high=("high","max"),low=("low","min"),close=("close","last")).dropna()
m5["er"] = (m5.close - m5.close.shift(10)).abs() / (m5.close.diff().abs().rolling(10).sum())
m5["e20"] = m5.close.ewm(span=20, adjust=False).mean(); m5["e50"] = m5.close.ewm(span=50, adjust=False).mean()
tr5 = np.maximum(m5.high - m5.low, np.maximum((m5.high - m5.close.shift()).abs(), (m5.low - m5.close.shift()).abs()))
m5["atr5"] = tr5.rolling(14).mean(); m5["flat"] = (m5.e20 - m5.e50).abs() < 0.25 * m5.atr5
ctx = m5[["er","flat"]].shift(1)  # only completed M5 bars
d = d.join(ctx.reindex(d.time, method="ffill").reset_index(drop=True))
d["hr"] = d.time.dt.hour + d.time.dt.minute/60
insess = (d.hr >= 1.0) & (d.hr <= 14.5)
prev_big = d.rng.shift(1) > 1.5 * d.atr1.shift(1)
rev_up = (d.close > d.open) & (d.close > d.close.shift(1))
rev_dn = (d.close < d.open) & (d.close < d.close.shift(1))
sig_long = insess & (d.z <= -2.0) & (d.er < 0.30) & d.flat & prev_big & rev_up
sig_short = insess & (d.z >= 2.0) & (d.er < 0.30) & d.flat & prev_big & rev_dn
H, L, O, Cl, VW, ER = d.high.values, d.low.values, d.open.values, d.close.values, d.vwap.values, d.er.values
trades = []
def run(idx, side):
    for i in idx:
        e = i + 1
        if e + 1 >= len(d): continue
        px = O[e]; dev = abs(d.dev.values[i]); atr = d.atr1.values[i]
        tgt = max(0.6 * dev, 3.0 * C)
        if side == 1:
            tp = min(px + tgt, VW[i]); sl = px - 1.8 * atr
        else:
            tp = max(px - tgt, VW[i]); sl = px + 1.8 * atr
        if (side == 1 and tp <= px) or (side == -1 and tp >= px): continue  # already past VWAP after the open gap
        out = None
        for k in range(e, min(e + 12, len(d))):
            if side == 1:
                if L[k] <= sl: out = (sl, "SL"); break
                if H[k] >= tp: out = (tp, "TP"); break
            else:
                if H[k] >= sl: out = (sl, "SL"); break
                if L[k] <= tp: out = (tp, "TP"); break
            if ER[k] > 0.45: out = (Cl[k], "REG"); break
        if out is None: out = (Cl[min(e + 11, len(d) - 1)], "TIME")
        gross = (out[0] - px) * side
        trades.append(dict(t=d.time[e], side=side, gross=gross, net=gross - C, why=out[1], hr=int(d.hr[e])))
run(np.where(sig_long)[0], 1); run(np.where(sig_short)[0], -1)
t = pd.DataFrame(trades)
print(f"signals long={sig_long.sum()} short={sig_short.sum()}  trades={len(t)}  span {d.time.iloc[0]:%Y-%m-%d} -> {d.time.iloc[-1]:%Y-%m-%d}")
if len(t):
    print(f"gross avg {t.gross.mean():+.3f}/oz  NET avg {t.net.mean():+.3f}/oz  total net {t.net.sum():+.1f}/oz  win {100*(t.net>0).mean():.0f}%  t-stat {t.net.mean()/t.net.std()*np.sqrt(len(t)):.2f}")
    print(t.groupby("why").agg(n=("net","size"), gross=("gross","mean"), net=("net","mean")).round(3).to_string())
    print(t.groupby("side").agg(n=("net","size"), net=("net","mean"), tot=("net","sum")).round(3).to_string())
    print("by server hour:"); print(t.groupby("hr").agg(n=("net","size"), net=("net","mean"), tot=("net","sum")).round(2).to_string())
    # sensitivity: no cost / half cost / spread x1.5
    for c in (0.0, 0.125, 0.375):
        print(f"  cost {c:.3f}: avg net {(t.gross - c).mean():+.3f}  total {(t.gross - c).sum():+.1f}")
