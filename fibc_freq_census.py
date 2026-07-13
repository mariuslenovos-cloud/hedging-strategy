#!/usr/bin/env python3
"""
FIB C TRADE-FREQUENCY CENSUS (2026-07-13, user directive: make fib C trade more
often by adapting its entry signal).

fib C entry stack (live): Goldminer(grisk=7) -> session 9-23 -> trend gate
(ADX>25 AND |EMA20 5-bar angle|>20). June 2026 = ZERO fib C MT5 trades.
Question: WHICH gate starves it, and what does each candidate adaptation buy?

Census on GOLD M5 (last ~9 months): per month, Goldminer fires at grisk {7,5,4}
and survival through each gate (session -> ADX -> angle), using the
signalscan-validated reproductions (WPR/angle exact-ish; ADX approximate,
parity gap flagged -> also report ADX>15 sensitivity).
"""
import numpy as np, pandas as pd, MetaTrader5 as mt5
from gridstat_signalscan import gm_val_series, gm_signals, wilder_adx, ema

BARS = 55_000   # ~9 months of M5

def main():
    if not mt5.initialize(path=r"C:\Program Files\XM Global MT5\terminal64.exe"):
        raise SystemExit(mt5.last_error())
    r = mt5.copy_rates_from_pos("GOLD", mt5.TIMEFRAME_M5, 0, BARS)
    mt5.shutdown()
    o,h,l,c = r['open'],r['high'],r['low'],r['close']
    t = pd.to_datetime(r['time'], unit='s')
    hours = ((r['time']//3600)%24).astype(int)
    adx = np.array([x if x is not None else 0.0 for x in wilder_adx(h,l,c,14)])
    e20 = np.array([x if x is not None else np.nan for x in ema(list(c),20)])
    point = 0.01  # GOLD point (validated in signalscan parity: med angle err 0.22 deg)
    ang = np.zeros(len(c))
    ang[5:] = np.degrees(np.arctan((e20[5:]-e20[:-5])/(5*point)))
    rows=[]
    for grisk in (7,5,4):
        val = gm_val_series(o,h,l,c,grisk)
        dirs = gm_signals(val,grisk)          # per-bar 'BUY'/'SELL'/None
        sigs = [(i,d) for i,d in enumerate(dirs) if d]
        for i,d in sigs:
            rows.append(dict(month=str(t[i])[:7], grisk=grisk,
                             insess=(9<=hours[i]<23),
                             adx25=adx[i]>25, adx15=adx[i]>15,
                             ang20=abs(ang[i])>20))
    df = pd.DataFrame(rows)
    for grisk in (7,5,4):
        g = df[df.grisk==grisk]
        agg = g.groupby('month').agg(fires=('insess','size'),
                                     in_session=('insess','sum'))
        both25 = g[g.insess & g.adx25 & g.ang20].groupby('month').size()
        both15 = g[g.insess & g.adx15 & g.ang20].groupby('month').size()
        agg['pass_adx25+ang'] = both25; agg['pass_adx15+ang'] = both15
        agg = agg.fillna(0).astype(int)
        print(f"\n===== grisk {grisk} =====")
        print(agg.to_string())
        tot = g[g.insess]
        print(f"gate kill rates (in-session sigs={len(tot)}): "
              f"ADX25 blocks {(~tot.adx25).mean()*100:.0f}%  "
              f"ang20 blocks {(~tot.ang20).mean()*100:.0f}%  "
              f"both pass {(tot.adx25&tot.ang20).mean()*100:.0f}% "
              f"(ADX15 variant: {(tot.adx15&tot.ang20).mean()*100:.0f}%)")

if __name__ == "__main__":
    main()
