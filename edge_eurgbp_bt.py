#!/usr/bin/env python3
"""
Cost-aware SINGLE-INSTRUMENT mean-reversion backtest on the reverting candidates
(EURGBP is the standout: VR 0.67, single-leg 2.78bps). Fade rolling-z extensions,
exit on reversion, charge the REAL round-trip spread. Bar to beat: a positive net
Sharpe/PF that could become a new stream (and ideally beat GridStat's risk-adjusted).
Sweeps a small z-grid + reversion horizon; reports the best NET-of-cost cell per sym.
"""
import numpy as np, pandas as pd
import MetaTrader5 as mt5

TF, NBARS = mt5.TIMEFRAME_M5, 60000
CAND = ["EURGBP","EURUSD","USDJPY","GBPJPY","AUDJPY","USDCAD","USDCHF","GOLD"]
ROLLS  = [50, 100, 200]
Z_INS  = [1.5, 2.0, 2.5]
Z_OUT, Z_STOP = 0.3, 4.0

def bt(close, cost_frac, roll, z_in):
    p = pd.Series(close)
    mu = p.rolling(roll).mean(); sd = p.rolling(roll).std()
    z = ((p - mu) / sd).values
    n = len(close); pos = 0; ep = 0.0; pnl = []
    for i in range(roll, n):
        zi = z[i]
        if np.isnan(zi): continue
        if pos == 0:
            if zi >= z_in:  pos = -1; ep = close[i]
            elif zi <= -z_in: pos = 1; ep = close[i]
        else:
            hit = (pos==1 and (zi>=-Z_OUT or zi<=-Z_STOP)) or \
                  (pos==-1 and (zi<=Z_OUT or zi>=Z_STOP))
            if hit:
                ret = pos*(close[i]-ep)/ep          # fractional move
                pnl.append(ret - cost_frac)         # one round-trip spread
                pos = 0
    if len(pnl) < 20: return None
    a = np.array(pnl)
    return dict(trades=len(a), win=(a>0).mean(),
                pf=(a[a>0].sum()/-a[a<0].sum()) if (a<0).any() else np.inf,
                net_bps=a.sum()*1e4, sharpe=a.mean()/a.std()*np.sqrt(len(a)) if a.std()>0 else 0)

def main():
    if not mt5.initialize(): raise SystemExit(f"init {mt5.last_error()}")
    costs = pd.read_csv("_universe_costs.csv").set_index("sym")["spread_bps"].to_dict()
    print(f"{'sym':<9}{'cost_bps':>9}  best NET-of-cost reversion cell")
    print("-"*78)
    for s in CAND:
        r = mt5.copy_rates_from_pos(s, TF, 0, NBARS)
        if r is None or len(r) < 5000:
            print(f"{s:<9}  (no data)"); continue
        c = pd.DataFrame(r)["close"].astype(float).values
        cost = costs.get(s, 5)/1e4
        best = None
        for roll in ROLLS:
            for zin in Z_INS:
                res = bt(c, cost, roll, zin)
                if res and (best is None or res["sharpe"] > best[0]["sharpe"]):
                    best = (res, roll, zin)
        if best:
            r0, roll, zin = best
            flag = "  <== TRADEABLE" if (r0["sharpe"]>1 and r0["pf"]>1.3) else ""
            print(f"{s:<9}{costs.get(s,0):>9.2f}  roll={roll:<4} z={zin}  "
                  f"trades={r0['trades']:<5} win={r0['win']:.0%} PF={r0['pf']:.2f} "
                  f"net={r0['net_bps']:>7.0f}bps Sharpe={r0['sharpe']:.2f}{flag}")
    print("\n(net_bps = total return over the sample in bps, AFTER real spread. "
          "Sharpe>1 & PF>1.3 net of cost = a candidate to build into a stream.)")
    mt5.shutdown()

if __name__ == "__main__":
    main()
