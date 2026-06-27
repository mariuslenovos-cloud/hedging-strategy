#!/usr/bin/env python3
"""
NIGHT BATCH 2 -- the OVERNIGHT INDEX EDGE (a documented structural anomaly).
Equity indices have historically earned most of their return OVERNIGHT (close->open
gap up) while the intraday session (open->close) is ~flat/negative. Reason is
structural: overnight risk premium + futures/cash interaction + no intraday supply.
We decompose D1 returns and test "hold overnight only" net of REAL round-trip spread.
If overnight >> intraday AND survives 1 spread/day, it's a cheap structural stream
uncorrelated to the gold grid (different mechanism, different hours).
"""
import numpy as np, pandas as pd
import MetaTrader5 as mt5

IDX = ["US100Cash","US500Cash","US30Cash","DE40Cash","UK100Cash","JP225Cash",
       "HK50Cash","AUS200Cash","FRA40Cash","GOLD","SILVER"]  # gold/silver as non-index controls

def main():
    if not mt5.initialize(): raise SystemExit(f"init {mt5.last_error()}")
    costs=pd.read_csv("_universe_costs.csv").set_index("sym")["spread_bps"].to_dict()
    print(f"{'sym':<11}{'cost':>6}{'days':>6}{'ON_tot%':>9}{'ID_tot%':>9}{'ON_avg_bps':>11}{'ON_win%':>8}{'ON_net%(-cost)':>15}{'ON_Sharpe':>10}")
    print("-"*86)
    rows=[]
    for s in IDX:
        if not mt5.symbol_select(s,True): continue
        d=mt5.copy_rates_from_pos(s,mt5.TIMEFRAME_D1,0,3000)
        if d is None or len(d)<300: continue
        df=pd.DataFrame(d)
        o=df["open"].values.astype(float); c=df["close"].values.astype(float)
        # overnight = today open vs yesterday close ; intraday = today close vs today open
        on=(o[1:]-c[:-1])/c[:-1]
        idr=(c[1:]-o[1:])/o[1:]
        cb=costs.get(s,3.0)/1e4
        on_net=on-cb                       # 1 round-trip spread per overnight hold
        sh=on_net.mean()/on_net.std()*np.sqrt(252) if on_net.std()>0 else 0
        rows.append((s,costs.get(s,3.0)))
        print(f"{s:<11}{costs.get(s,3.0):>6.2f}{len(on):>6}{on.sum()*100:>9.1f}{idr.sum()*100:>9.1f}"
              f"{on.mean()*1e4:>11.2f}{(on>0).mean()*100:>7.0f}%{on_net.sum()*100:>14.1f}%{sh:>10.2f}")
    print("\nON=overnight(close->open hold), ID=intraday(open->close). If ON_tot >> ID_tot AND")
    print("ON_net positive after cost with Sharpe>0.8 = a real structural overnight stream.")
    print("(annualized Sharpe; ~252 trading days/yr. Caveat: cash-CFD open/close = broker session,")
    print(" and the real entry/exit must be near session close/open -- demo confirms fills.)")
    mt5.shutdown()

if __name__=="__main__":
    main()
