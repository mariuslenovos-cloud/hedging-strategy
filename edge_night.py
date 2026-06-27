#!/usr/bin/env python3
"""
NIGHT BATCH 1 (FAST: D1-only, existence-filtered) -- two cost-first screens:
 (A) GRID-SUITABILITY: tonight's corrected criterion = harvest must outrun the tail =
     BIG moves vs cost. score = daily ATR / round-trip-spread ("moves per spread") x
     reversion(VR on D1). Gold = benchmark; find any gold-like grid substrate.
 (B) TREND-FOLLOWING net of real cost: instruments that TREND should WIN trend-following
     (the uncorrelated CTA edge). Donchian(N) entry/exit on D1; charge real spread/trade;
     show daily swap so hold-cost is visible. Judge net/Sharpe/PF, NOT win%.
"""
import sys, numpy as np, pandas as pd
import MetaTrader5 as mt5

WANT = ["EURUSD","GBPUSD","USDJPY","USDCHF","USDCAD","AUDUSD","NZDUSD","EURJPY","GBPJPY",
        "EURGBP","AUDJPY","EURCHF","CADJPY","GBPAUD","EURAUD","NZDUSD",
        "GOLD","SILVER","OILCash","BRENTCash","NGASCash","XPTUSD","XPDUSD",
        "US100Cash","US500Cash","US30Cash","DE40Cash","UK100Cash","JP225Cash","HK50Cash","AUS200Cash","FRA40Cash",
        "BTCUSD","ETHUSD","SOLUSD","XRPUSD"]
NBARS=1500

def vr(r,q):
    r=np.asarray(r,float); n=len(r)
    if n<q*3: return np.nan
    mu=r.mean(); v1=((r-mu)**2).sum()/(n-1)
    rq=np.convolve(r,np.ones(q),"valid"); vq=((rq-q*mu)**2).sum()/(len(rq)-1)
    return vq/(q*v1) if v1>0 else np.nan

def donchian_bt(h,l,c,cost,N=20,Nx=10):
    n=len(c); pos=0; ep=0; pnl=[]; holds=[]; ei=0
    hh=pd.Series(h).rolling(N).max().shift(1).values; ll=pd.Series(l).rolling(N).min().shift(1).values
    xh=pd.Series(h).rolling(Nx).max().shift(1).values; xl=pd.Series(l).rolling(Nx).min().shift(1).values
    for i in range(N,n):
        if pos==0:
            if c[i]>hh[i]: pos=1; ep=c[i]; ei=i
            elif c[i]<ll[i]: pos=-1; ep=c[i]; ei=i
        elif pos==1 and c[i]<xl[i]: pnl.append((c[i]-ep)/ep-cost); holds.append(i-ei); pos=0
        elif pos==-1 and c[i]>xh[i]: pnl.append((ep-c[i])/ep-cost); holds.append(i-ei); pos=0
    if len(pnl)<8: return None
    a=np.array(pnl); eq=np.cumsum(a); dd=eq-np.maximum.accumulate(eq)
    return dict(trades=len(a),win=(a>0).mean(),net=a.sum(),
                pf=(a[a>0].sum()/-a[a<0].sum()) if (a<0).any() else np.inf,
                sharpe=a.mean()/a.std()*np.sqrt(len(a)) if a.std()>0 else 0,
                maxdd=-dd.min(),hold=np.mean(holds))

def main():
    if not mt5.initialize(): raise SystemExit(f"init {mt5.last_error()}")
    have={s.name for s in mt5.symbols_get()}
    costs=pd.read_csv("_universe_costs.csv").set_index("sym")["spread_bps"].to_dict()
    swl=pd.read_csv("_universe_costs.csv").set_index("sym")["swap_long"].to_dict()
    syms=[s for s in dict.fromkeys(WANT) if s in have]
    print(f"{len(syms)}/{len(set(WANT))} symbols exist on broker",flush=True)
    grid=[]; trend=[]
    for s in syms:
        mt5.symbol_select(s,True)
        d=mt5.copy_rates_from_pos(s,mt5.TIMEFRAME_D1,0,NBARS)
        print(f"  {s}: {0 if d is None else len(d)} D1 bars",flush=True)
        if d is None or len(d)<300: continue
        df=pd.DataFrame(d); h,l,c=df["high"].values.astype(float),df["low"].values.astype(float),df["close"].values.astype(float)
        si=mt5.symbol_info(s); cb=costs.get(s)
        if cb is None and si and si.ask>0: cb=(si.ask-si.bid)/((si.ask+si.bid)/2)*1e4
        if cb is None: cb=5.0
        atr=pd.Series(np.maximum(h-l,np.abs(pd.Series(c).diff()))).rolling(20).mean().iloc[-250:].mean()
        atr_bps=atr/c[-1]*1e4
        mps=atr_bps/cb if cb>0 else 0
        ret=np.diff(np.log(c)); v=vr(ret,5)
        grid.append((s,round(cb,2),round(atr_bps,0),round(mps,1),round(v,2)))
        bt=donchian_bt(h,l,c,cb/1e4,20,10)
        if bt: trend.append((s,round(cb,2),swl.get(s,np.nan),bt["trades"],round(bt["win"],2),
                             round(bt["net"]*100,1),round(bt["pf"],2),round(bt["sharpe"],2),
                             round(bt["maxdd"]*100,1),round(bt["hold"],0)))
    print("\n"+"="*78); print("(A) GRID-SUITABILITY  -- dailyATR/cost (moves-per-spread) x reversion; GOLD=benchmark"); print("="*78)
    g=pd.DataFrame(grid,columns=["sym","cost_bps","atr_bps","moves_per_spread","VR5"]).sort_values("moves_per_spread",ascending=False)
    print(g.to_string(index=False))
    print("\n"+"="*78); print("(B) TREND-FOLLOWING net of spread (Donchian 20/10 D1) -- judge net/Sharpe/PF not win%"); print("="*78)
    t=pd.DataFrame(trend,columns=["sym","cost_bps","swap_long","trades","win","net%","PF","Sharpe","maxDD%","hold_d"]).sort_values("Sharpe",ascending=False)
    print(t.to_string(index=False))
    g.to_csv("_grid_suitability.csv",index=False); t.to_csv("_trend_screen.csv",index=False)
    print("\nsaved _grid_suitability.csv + _trend_screen.csv",flush=True)
    mt5.shutdown()

if __name__=="__main__": main()
