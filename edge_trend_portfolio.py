#!/usr/bin/env python3
"""
NIGHT BATCH 3 -- TREND-FOLLOWING PORTFOLIO (the real CTA edge = diversification).
A single trend instrument is noisy (low Sharpe); an equal-risk basket of many
uncorrelated trend bets is the actual managed-futures edge -- the diversification
raises portfolio Sharpe far above any single market. Build a daily equity curve for
an equal-RISK Donchian trend system across a diversified universe, net of real spread,
and report PORTFOLIO Sharpe / maxDD / annual return + the pairwise correlation (should
be ~0 = the diversification that makes it work).
"""
import numpy as np, pandas as pd
import MetaTrader5 as mt5

UNIVERSE = ["EURUSD","GBPUSD","USDJPY","USDCHF","USDCAD","AUDUSD","NZDUSD","EURJPY","GBPJPY",
            "GOLD","SILVER","OILCash","BRENTCash","NGASCash",
            "US100Cash","US500Cash","US30Cash","DE40Cash","UK100Cash","JP225Cash","HK50Cash","BTCUSD","ETHUSD"]
N, NX = 50, 25     # slower Donchian (positional trend, fewer trades, less spread drag)

def daily_returns(sym, cost_frac):
    d=mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_D1, 0, 3000)
    if d is None or len(d)<300: return None
    df=pd.DataFrame(d); df["t"]=pd.to_datetime(df["time"],unit="s")
    h,l,c=df["high"].values,df["low"].values,df["close"].values
    n=len(c)
    hh=pd.Series(h).rolling(N).max().shift(1).values; ll=pd.Series(l).rolling(N).min().shift(1).values
    xh=pd.Series(h).rolling(NX).max().shift(1).values; xl=pd.Series(l).rolling(NX).min().shift(1).values
    atr=pd.Series(np.maximum(h-l, np.abs(pd.Series(c).diff()))).rolling(20).mean().values
    pos=np.zeros(n); p=0
    for i in range(N,n):
        if p==0:
            if c[i]>hh[i]: p=1
            elif c[i]<ll[i]: p=-1
        elif p==1 and c[i]<xl[i]: p=0
        elif p==-1 and c[i]>xh[i]: p=0
        pos[i]=p
    # daily return = position(prev day) * pct change, scaled to ~constant risk (1/ATR%), minus cost on position change
    ret=np.zeros(n); pct=np.zeros(n); pct[1:]=(c[1:]-c[:-1])/c[:-1]
    riskscale=np.where(atr>0, (atr/c), np.nan); riskscale=np.nanmedian(riskscale)/np.where(atr>0,atr/c,np.nan)
    riskscale=np.clip(np.nan_to_num(riskscale,nan=1.0),0.2,5.0)   # target ~constant risk per market
    chg=np.abs(np.diff(np.concatenate([[0],pos])))
    for i in range(1,n):
        ret[i]=pos[i-1]*pct[i]*riskscale[i-1] - chg[i]*cost_frac
    return pd.Series(ret, index=df["t"])

def main():
    if not mt5.initialize(): raise SystemExit(f"init {mt5.last_error()}")
    costs=pd.read_csv("_universe_costs.csv").set_index("sym")["spread_bps"].to_dict()
    series={}
    for s in UNIVERSE:
        if not mt5.symbol_select(s,True): continue
        r=daily_returns(s, costs.get(s,5)/1e4)
        if r is not None and r.abs().sum()>0: series[s]=r
    print(f"loaded {len(series)} trend markets")
    R=pd.DataFrame(series).fillna(0.0)
    # equal-weight portfolio (already risk-scaled per market)
    w=1.0/len(series)
    port=R.sum(axis=1)*w
    ann=port.mean()*252; vol=port.std()*np.sqrt(252); sh=ann/vol if vol>0 else 0
    eq=port.cumsum(); dd=(eq-eq.cummax()); maxdd=-dd.min()
    # avg pairwise correlation of the per-market trend returns
    cc=R.corr().values; iu=np.triu_indices_from(cc,1); avgcorr=np.nanmean(cc[iu])
    print("\n"+"="*60)
    print("TREND PORTFOLIO (equal-risk Donchian 50/25, net of spread)")
    print("="*60)
    print(f"  markets               : {len(series)}")
    print(f"  annual return (1x)    : {ann*100:6.1f}%")
    print(f"  annual vol            : {vol*100:6.1f}%")
    print(f"  PORTFOLIO Sharpe      : {sh:6.2f}")
    print(f"  max drawdown          : {maxdd*100:6.1f}%")
    print(f"  avg pairwise corr     : {avgcorr:+.3f}  (~0 = diversification works)")
    # per-market Sharpe contribution
    print("\n  per-market annual Sharpe:")
    for s in series:
        a=R[s]; ms=a.mean()*252/(a.std()*np.sqrt(252)) if a.std()>0 else 0
        print(f"    {s:<11}{ms:+.2f}")
    print("\nPortfolio Sharpe >1 with ~0 corr = a real, deployable, UNCORRELATED stream")
    print("(vs the gold grid book). The diversification is the edge, not any single market.")
    mt5.shutdown()

if __name__=="__main__":
    main()
