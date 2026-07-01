#!/usr/bin/env python3
"""
EQUITY MEAN-REVERSION screen (the YouTube "9000 backtests" lead), hardened.
Daily RSI(N) snapback on a basket of ~20 liquid stocks/ETFs: go long when RSI(N) < oversold (price stretched
below), exit when RSI(N) > exit. Long-only (the honest form -- reversion buys dips).

THE HONEST TEST THE VIDEO SKIPPED: is this a real TIMING edge, or just "long equities in a 15-yr bull"?
So for every name we compare the strategy Sharpe to BUY-&-HOLD Sharpe, and report % time in market. A real edge
= similar/better return at MUCH lower exposure (higher Sharpe than B&H). If strat Sharpe ~ B&H Sharpe, it's just beta.
Plus: real cost, robustness grid (N x oversold), era half-split, bootstrap DD, equal-risk portfolio.

Run:  python equity_reversion.py
"""
import json, ssl, time, urllib.request
from datetime import datetime
import numpy as np, pandas as pd

UNIV=["SPY","QQQ","IWM","DIA","XLK","XLF","XLE","XLV","XLI","XLY","XLP","XLU","XLB","GLD",
      "AAPL","MSFT","NVDA","JPM","JNJ","XOM"]
RANGE="15y"; COST=2.0; TVOL=0.10
GRID_N=[2,3,4]; GRID_OS=[10,15,20]
BASE_N,BASE_OS,EXIT=2,10,60
_ctx=ssl.create_default_context(); _ctx.check_hostname=False; _ctx.verify_mode=ssl.CERT_NONE

def fetch(t):
    url=f"https://query1.finance.yahoo.com/v8/finance/chart/{t}?range={RANGE}&interval=1d"
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"})
    for a in range(3):
        try:
            with urllib.request.urlopen(req,timeout=20,context=_ctx) as r: j=json.load(r)
            res=j["chart"]["result"][0]
            return pd.Series(res["indicators"]["quote"][0]["close"],
                             index=pd.to_datetime(res["timestamp"],unit="s").normalize()).dropna()
        except Exception:
            if a==2: return None
            time.sleep(1.0)

def rsi(c,n):
    d=c.diff(); up=d.clip(lower=0); dn=-d.clip(upper=0)
    au=up.ewm(alpha=1/n,adjust=False).mean(); ad=dn.ewm(alpha=1/n,adjust=False).mean()
    rs=au/ad.replace(0,np.nan); return (100-100/(1+rs)).fillna(50)

def strat(c, n, os, exit_=EXIT, cost=COST):
    r=c.pct_change(); R=rsi(c,n).values; pos=np.zeros(len(c)); st=0
    for t in range(len(c)):
        if R[t]<os: st=1
        elif R[t]>exit_: st=0
        pos[t]=st
    pos=pd.Series(pos,index=c.index)
    ret=pos.shift(1)*r - (cost/1e4)*pos.diff().abs().fillna(0)
    return ret.dropna(), pos

def stats(x):
    x=x.dropna()
    if len(x)<100 or x.std()==0: return dict(sh=0,dd=0,ann=0)
    ann=x.mean()*252; vol=x.std()*np.sqrt(252)
    eq=(1+x).cumprod()
    return dict(sh=ann/vol if vol else 0, dd=(eq/eq.cummax()-1).min(), ann=ann)

def boot_dd(x,n=500):
    x=x.dropna().values; rng=np.random.default_rng(7); out=[]
    for _ in range(n):
        eq=np.cumprod(1+rng.choice(x,len(x),replace=True)); out.append((eq/np.maximum.accumulate(eq)-1).min())
    return float(np.percentile(out,5))

def main():
    print(f"EQUITY RSI-REVERSION screen  |  {datetime.now():%Y-%m-%d %H:%M}  |  RSI({BASE_N})<{BASE_OS} long, exit>{EXIT}, NET {COST}bps\n")
    data={}
    for t in UNIV:
        c=fetch(t)
        if c is not None and len(c)>800: data[t]=c
        time.sleep(0.25)
    print(f"loaded {len(data)}/{len(UNIV)}\n")
    print(f"{'ticker':7} {'strat Sh':>8} {'B&H Sh':>7} {'edge':>6} {'%inMkt':>7} {'maxDD':>7} {'grid+':>6}")
    rows=[]; port={}
    for t,c in data.items():
        s,pos=strat(c,BASE_N,BASE_OS); ss=stats(s)
        bh=stats(c.pct_change().dropna())              # buy-and-hold
        inmkt=pos.mean()*100
        cells=[stats(strat(c,N,OS)[0])["sh"] for N in GRID_N for OS in GRID_OS]
        gpos=sum(1 for x in cells if x>0.3)
        edge=ss["sh"]-bh["sh"]                          # timing edge over just being long
        rows.append(dict(t=t,strat=ss["sh"],bh=bh["sh"],edge=edge,inmkt=inmkt,dd=ss["dd"],g=gpos))
        # vol-target for portfolio
        dv=s.rolling(30).std(); lev=(TVOL/np.sqrt(252)/dv).clip(upper=3).replace([np.inf,-np.inf],0).fillna(0)
        port[t]=(s*lev.shift(1)).dropna()
    rows.sort(key=lambda x:-x["edge"])
    for x in rows:
        print(f"{x['t']:7} {x['strat']:>8.2f} {x['bh']:>7.2f} {x['edge']:>+6.2f} {x['inmkt']:>6.0f}% {x['dd']*100:>6.0f}% {x['g']:>4}/9")
    # portfolio of the ones with a POSITIVE timing edge over B&H
    keep=[x["t"] for x in rows if x["edge"]>0 and x["strat"]>0.3]
    print(f"\nnames with a real timing edge over buy-&-hold (edge>0, Sharpe>0.3): {len(keep)}/{len(rows)}")
    if len(keep)>=3:
        P=pd.concat([port[t] for t in keep],axis=1,keys=keep).dropna()
        pt=P.mean(axis=1); ps=stats(pt)
        iu=np.triu_indices(len(keep),1); ac=np.nanmean(P.corr().values[iu])
        h=len(pt)//2
        print(f"EQUAL-RISK REVERSION PORTFOLIO: Sharpe {ps['sh']:.2f} | ann {ps['ann']*100:.0f}% | maxDD {ps['dd']*100:.0f}% | avg corr {ac:+.2f}")
        print(f"  era: 1st-half {stats(pt.iloc[:h])['sh']:.2f} | 2nd-half {stats(pt.iloc[h:])['sh']:.2f} | bootstrap worst-5% DD {boot_dd(pt)*100:.0f}%")
        # market-neutral check: strip SPY beta from the portfolio? report portfolio corr to SPY returns
        if "SPY" in data:
            spy=data["SPY"].pct_change().reindex(pt.index)
            beta=np.cov(pt.dropna(),spy.reindex(pt.dropna().index).fillna(0))[0,1]/np.var(spy.dropna())
            print(f"  portfolio beta to SPY: {beta:+.2f}  (near 0 = a real timing edge, not hidden equity beta)")
    print("\nREAD: 'edge' = strategy Sharpe MINUS buy-&-hold Sharpe. If most names have edge<=0, the 'reversion edge'")
    print("is mostly just being long equities in a bull (the video's blind spot). If edge>0 broadly AND portfolio")
    print("beta-to-SPY ~0 with both halves positive -> a real, uncorrelated timing sleeve worth building.")

if __name__=="__main__":
    main()
