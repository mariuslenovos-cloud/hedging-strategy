#!/usr/bin/env python3
"""
Single-instrument reversion screen: is there a CHEAP instrument that mean-reverts
intraday even HARDER than gold? If yes, the GridStat grid on it could beat gold.
Fair single-leg test (no 2-leg cost). Metrics on M5 returns:
  - Variance Ratio VR(q): Var(q-bar ret)/(q*Var(1-bar ret)). <1 = mean-reverting (lower=harder).
  - lag-1 return autocorrelation (negative = reversion).
  - "pullback rate": after an N-bar directional run, does the next bar retrace?
GridStat works on gold -> gold's numbers are the bar. Anything cheaper-or-equal in
cost that reverts harder = a candidate substrate.
"""
import numpy as np, pandas as pd
import MetaTrader5 as mt5

TF, NBARS = mt5.TIMEFRAME_M5, 40000
CAND = ["GOLD","US100Cash","US500Cash","US30Cash","EURUSD","USDJPY","GBPJPY",
        "AUDJPY","USDCHF","USDCAD","BTCUSD","SILVER","OILCash","BRENTCash","EURGBP"]

def variance_ratio(r, q):
    r = np.asarray(r, float); n = len(r)
    if n < q*3: return np.nan
    mu = r.mean()
    var1 = ((r-mu)**2).sum()/(n-1)
    rq = np.convolve(r, np.ones(q), "valid")          # q-bar sums
    varq = ((rq - q*mu)**2).sum()/(len(rq)-1)
    return varq/(q*var1) if var1>0 else np.nan

def main():
    if not mt5.initialize(): raise SystemExit(f"init {mt5.last_error()}")
    costs = pd.read_csv("_universe_costs.csv").set_index("sym")["spread_bps"].to_dict()
    print(f"{'sym':<12}{'cost_bps':>9}{'VR(6)':>8}{'VR(12)':>8}{'VR(48)':>8}{'autocorr1':>11}{'pullback%':>11}")
    print("-"*67)
    out=[]
    for s in CAND:
        r = mt5.copy_rates_from_pos(s, TF, 0, NBARS)
        if r is None or len(r)<5000:
            print(f"{s:<12}{'(no data)':>9}"); continue
        c = pd.DataFrame(r)["close"].astype(float).values
        ret = np.diff(np.log(c))
        vr6,vr12,vr48 = variance_ratio(ret,6),variance_ratio(ret,12),variance_ratio(ret,48)
        ac1 = np.corrcoef(ret[:-1],ret[1:])[0,1]
        # pullback: after 3 same-sign bars, fraction where next bar reverses
        sign = np.sign(ret); run=0; rev=0; tot=0
        for i in range(3,len(sign)):
            if sign[i-1]==sign[i-2]==sign[i-3]!=0:
                tot+=1
                if sign[i]==-sign[i-1]: rev+=1
        pb = rev/tot if tot else np.nan
        cb = costs.get(s, np.nan)
        out.append((s,cb,vr6,vr12,vr48,ac1,pb))
        print(f"{s:<12}{cb:>9.2f}{vr6:>8.2f}{vr12:>8.2f}{vr48:>8.2f}{ac1:>11.3f}{pb:>10.1%}")
    print("\nVR<1 = mean-reverting (lower=harder revert = better grid substrate).")
    print("Compare each to GOLD (the proven substrate). A cheaper instrument with a")
    print("LOWER VR / more-negative autocorr than gold = a candidate to beat GridStat.")
    mt5.shutdown()

if __name__ == "__main__":
    main()
