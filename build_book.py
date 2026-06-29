#!/usr/bin/env python3
"""
BUILD THE BOOK  --  turn the screened edges into a portfolio blueprint.

The software-company product is a BOOK of uncorrelated streams, not one engine. This measures the key
claim empirically -- are the new sleeves actually uncorrelated? -- then prints the composition + the
combined-portfolio math + the venue/capital/deploy plan.

Streams:
  CORE (proven, live/locked, on MT5): GridStat gold/silver/oil + fib C gold = the MAGNITUDE base.
       intraday gold/commodity reversion -> ~uncorrelated to everything daily below (different timeframe+mechanism).
  NEW sleeves (screened this hunt):
       RV energy spreads (WTI-Brent + crack-spread pairs) -- market-neutral, OOS Sharpe ~0.6-1.4   [IB]
       crypto-trend (12-coin Donchian)                    -- ~0.4 Sharpe, decaying                  [exchange]
       crypto funding-carry                               -- ~2.5-5% market-neutral, leverageable   [exchange]

This script measures RV-basket vs crypto-trend-basket correlation + combined Sharpe from real data.
Run:  python build_book.py
"""
import json, time, ssl, urllib.request
from datetime import datetime
import numpy as np, pandas as pd

RV_PAIRS = [("CVX","VLO"),("PSX","VLO"),("COP","OXY")]   # the OOS survivors that trade on cheap stock legs
RV_FUT   = [("CL=F","BZ=F")]                              # WTI-Brent (futures; roll-caveat) - shown separately
CRYPTO   = ["BTC-USD","ETH-USD","SOL-USD","BNB-USD","XRP-USD","DOGE-USD","ADA-USD",
            "AVAX-USD","LINK-USD","LTC-USD","NEAR-USD","TRX-USD"]
RANGE="10y"; TVOL=0.10; _ctx=ssl.create_default_context(); _ctx.check_hostname=False; _ctx.verify_mode=ssl.CERT_NONE

def fetch(t):
    url=f"https://query1.finance.yahoo.com/v8/finance/chart/{t}?range={RANGE}&interval=1d"
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"})
    for a in range(3):
        try:
            with urllib.request.urlopen(req,timeout=20,context=_ctx) as r: j=json.load(r)
            res=j["chart"]["result"][0]; q=res["indicators"]["quote"][0]
            idx=pd.to_datetime(res["timestamp"],unit="s").normalize()   # align stocks(open) vs crypto(00:00) by DATE
            df=pd.DataFrame({"h":q["high"],"l":q["low"],"c":q["close"]},index=idx).dropna()
            return df[~df.index.duplicated(keep="last")]
        except Exception:
            if a==2: return None
            time.sleep(1.0)

def voltarget(sr):
    dv=sr.rolling(30).std(); lev=(TVOL/np.sqrt(252)/dv).clip(upper=3).replace([np.inf,-np.inf],0).fillna(0)
    return sr*lev

def trend_ret(df):
    c=df["c"]; r=c.pct_change()
    dh=df["h"].rolling(40).max().shift(1).values; dl=df["l"].rolling(40).min().shift(1).values
    pc=c.shift(1); tr=pd.concat([df["h"]-df["l"],(df["h"]-pc).abs(),(df["l"]-pc).abs()],axis=1).max(axis=1)
    av=tr.rolling(20).mean().values; h=df["h"].values; l=df["l"].values; cc=c.values
    pos=np.zeros(len(cc)); st=0; ext=0.0
    for t in range(len(cc)):
        if not(np.isnan(dh[t]) or np.isnan(av[t])):
            if st==0:
                if cc[t]>dh[t]: st=1; ext=h[t]
                elif cc[t]<dl[t]: st=-1; ext=l[t]
            elif st==1:
                ext=max(ext,h[t]);
                if cc[t]<ext-3*av[t]: st=0
            else:
                ext=min(ext,l[t]);
                if cc[t]>ext+3*av[t]: st=0
        pos[t]=st
    lev=(TVOL/np.sqrt(252)/r.rolling(30).std()).clip(upper=3).replace([np.inf,-np.inf],0).fillna(0)
    p=pd.Series(pos,index=df.index)*lev
    return (p.shift(1)*r - 0.0008*p.diff().abs().fillna(0)).dropna()

def rv_ret(a,b,cost):
    la,lb=np.log(a["c"]),np.log(b["c"]); df=pd.concat([la,lb],axis=1,keys=["a","b"]).dropna()
    beta=np.polyfit(df["b"].values,df["a"].values,1)[0]
    s=df["a"]-beta*df["b"]; z=(s-s.rolling(60).mean())/s.rolling(60).std(); zv=z.values
    pos=np.zeros(len(zv)); st=0
    for t in range(len(zv)):
        zt=zv[t]
        if np.isnan(zt): pos[t]=st; continue
        if st==0:
            if zt>2: st=-1
            elif zt<-2: st=1
        elif st==1:
            if zt>=-0.5 or zt<=-4: st=0
        elif st==-1:
            if zt<=0.5 or zt>=4: st=0
        pos[t]=st
    p=pd.Series(pos,index=df.index)
    raw=p.shift(1)*s.diff() - (cost/1e4)*(1+abs(beta))*p.diff().abs().fillna(0)
    return voltarget(raw.dropna())   # vol-target so it's equal-risk with the others

def sharpe(x):
    x=x.dropna(); return x.mean()/x.std()*np.sqrt(252) if len(x)>60 and x.std()>0 else 0.0
def mdd(x):
    eq=(1+x.dropna()).cumprod(); return (eq/eq.cummax()-1).min()

def main():
    print(f"BUILD THE BOOK  |  {datetime.now():%Y-%m-%d %H:%M}\n")
    print("Measuring the NEW sleeves from real data (vol-targeted to 10% each = equal-risk)...")
    cache={}
    def g(t):
        if t not in cache: cache[t]=fetch(t); time.sleep(0.3)
        return cache[t]
    # RV basket (stock crack-spread survivors)
    rv=[]
    for a,b in RV_PAIRS:
        da,db=g(a),g(b)
        if da is not None and db is not None: rv.append(rv_ret(da,db,2.0).rename(f"{a}/{b}"))
    # WTI-Brent (futures) separately (roll caveat)
    wb=None
    da,db=g("CL=F"),g("BZ=F")
    if da is not None and db is not None: wb=rv_ret(da,db,3.5).rename("WTI/Brent")
    rv_basket=pd.concat(rv,axis=1).mean(axis=1).rename("RV") if rv else None
    # crypto-trend basket
    ct=[]
    for t in CRYPTO:
        d=g(t)
        if d is not None: ct.append(trend_ret(d).rename(t.replace("-USD","")))
    ct_basket=pd.concat(ct,axis=1).mean(axis=1).rename("CTrend") if ct else None

    sleeves={}
    if rv_basket is not None: sleeves["RV-stocks"]=rv_basket
    if wb is not None: sleeves["WTI-Brent"]=wb
    if ct_basket is not None: sleeves["CryptoTrend"]=ct_basket
    P=pd.concat(sleeves.values(),axis=1,keys=sleeves.keys()).dropna()
    print(f"\naligned {len(P)} common days\n")
    print(f"{'sleeve':14} {'Sharpe':>7} {'maxDD':>7}")
    for k in P.columns: print(f"{k:14} {sharpe(P[k]):>7.2f} {mdd(P[k])*100:>6.0f}%")
    print("\nCROSS-CORRELATION (the diversification proof):")
    print(P.corr().round(2).to_string())
    comb=P.mean(axis=1)
    print(f"\nEQUAL-RISK COMBINED (new sleeves only): Sharpe {sharpe(comb):.2f} | maxDD {mdd(comb)*100:.0f}%")
    iu=np.triu_indices(len(P.columns),1); ac=np.nanmean(P.corr().values[iu])
    print(f"avg pairwise correlation {ac:+.2f}")
    print("\n" + "="*70)
    print("THE BOOK  (composition -> the multi-strat product)")
    print("="*70)
    print("""  CORE (MAGNITUDE, live/locked, MT5)
     - GridStat gold/silver/oil   momentum grid, PF 2.3-3.9, ~uncorrelated metals/commodity
     - fib C gold                 recovery grid, 14.5% DD, ~$11k/2.5yr
       => intraday gold reversion: ~ZERO correlation to every daily sleeve below (diff timeframe+mechanism)

  NEW SLEEVES (screened; build in this order)
     1. RV energy spreads   market-neutral, OOS Sharpe ~0.6-1.4   venue: Interactive Brokers (futures+stocks)
                            = BEST new edge; leverageable; structural (persists OOS)
     2. crypto funding-carry market-neutral, ~2.5-5% (lever 3-4x -> ~10-20%)  venue: ccxt exchange
     3. crypto-trend        ~0.4 Sharpe, decaying (small)          venue: ccxt exchange (banked)

  WHY A BOOK: uncorrelated streams add in QUADRATURE -> combined Sharpe ~ sqrt(sum of squares).
  Each sleeve is modest alone; together + the magnitude core they raise the book's Sharpe AND the
  total deployable capital (each stream gets its own risk budget; DDs don't peak together).

  DEPLOY SEQUENCE (highest ROI first):
     A. Core is live  -> keep running gold/silver/oil + fib C on MT5.
     B. Build the RV energy sleeve on IB (best new edge, market-neutral) -> the platform leap off MT5.
     C. Add the crypto sleeves (carry + trend) on a ccxt exchange.
     D. Risk-budget capital across streams (inverse-vol / HRP); lever the market-neutral sleeves.

  HONEST: the new sleeves are SCREENED edges, not built EAs yet. RV (1.39 WTI-Brent) needs a clean
  per-contract futures backtest; all need a live demo (fills are the truth). This is the blueprint.""")

if __name__=="__main__":
    main()
