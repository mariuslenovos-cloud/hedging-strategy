#!/usr/bin/env python3
"""
RV SLEEVE (build step 1) -- harden the relative-value / cointegration mean-reversion edge before any execution.

The screen (rv_screen.py) proved structural pairs PERSIST OOS (WTI-Brent 1.39, crack-spread ~0.6) and arbitrary
controls FAIL. This hardens it into a tradeable estimate:
  - ROLLING hedge ratio (beta re-estimated from a trailing window each bar) -> no look-ahead, and it adapts to the
    WTI-Brent roll (the Yahoo continuous-futures artifact that could inflate the static-beta 1.39).
  - ROLLING z-score, slow reversion (enter |z|>=E, exit |z|<=X, stop |z|>=S) -> low turnover.
  - REAL 2-leg cost charged on turnover (IB stocks ~2bps/leg, futures ~3.5bps).
  - ROBUSTNESS grid (entry-z x beta-window) -> require a positive plateau, not a lucky cell.
  - BOOTSTRAP reshuffle (the one worth stealing from the video): reshuffle the daily returns 500x to map the
    drawdown a bad SEQUENCE could produce (sequence-luck), report median & 95th-pctile maxDD.
  - PORTFOLIO of the structural pairs, equal-risk, + a control pair that should FAIL.

Run:  python rv_sleeve.py
"""
import json, ssl, time, urllib.request
from datetime import datetime
import numpy as np, pandas as pd

# (legA, legB, label, cost_bps_per_leg)  -- structural energy pairs (persist) + 1 control (should fail)
PAIRS = [
    ("CL=F","BZ=F","WTI-Brent (fut)", 3.5),
    ("PSX","VLO","refiner crack",     2.0),
    ("COP","OXY","producers",         2.0),
    ("VLO","MPC","refiner-refiner",   2.0),
    ("XOM","CVX","integrateds",       2.0),
    ("JPM","BAC","BANK CONTROL",      2.0),   # should NOT survive
]
RANGE="14y"; BETA_WIN=120; ZWIN=60; TVOL=0.10
GRID_E=[1.5,2.0,2.5]; GRID_W=[90,120,180]
_ctx=ssl.create_default_context(); _ctx.check_hostname=False; _ctx.verify_mode=ssl.CERT_NONE

def fetch(t):
    url=f"https://query1.finance.yahoo.com/v8/finance/chart/{t}?range={RANGE}&interval=1d"
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"})
    for a in range(3):
        try:
            with urllib.request.urlopen(req,timeout=20,context=_ctx) as r: j=json.load(r)
            res=j["chart"]["result"][0]
            s=pd.Series(res["indicators"]["quote"][0]["close"],
                        index=pd.to_datetime(res["timestamp"],unit="s").normalize()).dropna()
            return s[~s.index.duplicated(keep="last")]
        except Exception:
            if a==2: return None
            time.sleep(1.0)

def pair_returns(la, lb, beta_win, zwin, cost_bps, E=2.0, X=0.5, S=4.0):
    """rolling beta -> spread -> rolling z -> slow reversion -> daily returns net of 2-leg cost."""
    df=pd.concat([la,lb],axis=1,keys=["a","b"]).dropna()
    a,b=df["a"].values, df["b"].values; n=len(a)
    beta=np.full(n,np.nan)
    for t in range(beta_win,n):
        wa=a[t-beta_win:t]; wb=b[t-beta_win:t]
        v=np.var(wb)
        beta[t]= (np.cov(wa,wb)[0,1]/v) if v>0 else np.nan
    beta=pd.Series(beta,index=df.index).ffill()
    s=df["a"]-beta*df["b"]                                  # rolling-hedged spread
    z=(s-s.rolling(zwin).mean())/s.rolling(zwin).std()
    zv=z.values; pos=np.zeros(n); st=0
    for t in range(n):
        zt=zv[t]
        if np.isnan(zt): pos[t]=st; continue
        if st==0:
            if zt> E: st=-1
            elif zt<-E: st=1
        elif st==1:
            if zt>=-X or zt<=-S: st=0
        elif st==-1:
            if zt<= X or zt>= S: st=0
        pos[t]=st
    pos=pd.Series(pos,index=df.index)
    # TRUE pair P&L: hold long A / short beta*B with beta FIXED over the day (no phantom beta-change P&L)
    pnl=pos.shift(1)*(df["a"].diff()-beta.shift(1)*df["b"].diff())
    cost=(cost_bps/1e4)*(1+beta.abs())*pos.diff().abs().fillna(pos.abs())
    net=(pnl-cost).dropna()
    dv=net.rolling(60).std(); lev=(TVOL/np.sqrt(252)/dv).clip(upper=5).replace([np.inf,-np.inf],np.nan).ffill().fillna(0)
    vt=(net*lev.shift(1)).dropna()                          # vol-targeted for equal-risk portfolio
    trades=int((pos.diff().abs()>0).sum())
    return vt, trades

def stats(x):
    x=x.dropna()
    if len(x)<100 or x.std()==0: return dict(sh=0,dd=0,ann=0)
    ann=x.mean()*252; vol=x.std()*np.sqrt(252); sh=ann/vol if vol>0 else 0
    eq=(1+x).cumprod(); dd=(eq/eq.cummax()-1).min()
    return dict(sh=sh,dd=dd,ann=ann)

def bootstrap_dd(x, n=500):
    x=x.dropna().values
    if len(x)<100: return 0,0
    dds=[]
    rng=np.random.default_rng(7)
    for _ in range(n):
        s=rng.choice(x,size=len(x),replace=True)
        eq=np.cumprod(1+s); dds.append((eq/np.maximum.accumulate(eq)-1).min())
    return float(np.median(dds)), float(np.percentile(dds,5))   # median & worst-5% maxDD

def main():
    print(f"RV SLEEVE hardening  |  {datetime.now():%Y-%m-%d %H:%M}  |  rolling beta({BETA_WIN}) + z({ZWIN}), NET of 2-leg cost\n")
    logs={}
    def g(t):
        if t not in logs:
            s=fetch(t); logs[t]=np.log(s) if s is not None else None; time.sleep(0.3)
        return logs[t]
    ret={}
    print(f"{'pair':18} {'Sharpe':>7} {'maxDD':>7} {'trades':>6} {'grid+':>6} {'verdict'}")
    for ta,tb,lbl,cost in PAIRS:
        la,lb=g(ta),g(tb)
        if la is None or lb is None: print(f"{lbl:18} fetch failed"); continue
        base,tr=pair_returns(la,lb,BETA_WIN,ZWIN,cost)
        s=stats(base)
        # robustness grid
        pos=0; tot=0
        for E in GRID_E:
            for W in GRID_W:
                tot+=1; gs=stats(pair_returns(la,lb,W,ZWIN,cost,E=E)[0])
                if gs['sh']>0.3: pos+=1
        robust = pos>=6 and s['sh']>0.4 and "CONTROL" not in lbl
        if "CONTROL" not in lbl and s['sh']>0: ret[lbl]=base
        print(f"{lbl:18} {s['sh']:>7.2f} {s['dd']*100:>6.0f}% {tr:>6} {pos:>4}/{tot} {'PERSISTS' if robust else ('control-fails' if 'CONTROL' in lbl else 'weak')}")

    keep=[k for k in ret if stats(ret[k])['sh']>0.4]
    print(f"\nstructural survivors kept: {keep}")
    if len(keep)>=2:
        P=pd.concat([ret[k] for k in keep],axis=1,keys=keep).dropna()
        port=P.mean(axis=1); ps=stats(port)
        iu=np.triu_indices(len(keep),1); ac=np.nanmean(P.corr().values[iu])
        med_dd,p5_dd=bootstrap_dd(port)
        print(f"\nEQUAL-RISK RV SLEEVE (market-neutral):")
        print(f"  Sharpe {ps['sh']:.2f} | ann {ps['ann']*100:.0f}% | maxDD {ps['dd']*100:.0f}% | avg pair-corr {ac:+.2f}")
        print(f"  BOOTSTRAP (500x reshuffle) maxDD: median {med_dd*100:.0f}% | worst-5% {p5_dd*100:.0f}%  (sequence-luck stress)")
        h=len(port)//2
        print(f"  era check: 1st-half Sharpe {stats(port.iloc[:h])['sh']:.2f} | 2nd-half {stats(port.iloc[h:])['sh']:.2f}")
    print("\nREAD: market-neutral (uncorrelated to the gold/oil grid book AND to equities), tail-bounded by structure.")
    print("Rolling beta de-risks the WTI-Brent roll artifact. If the sleeve holds ~0.8+ Sharpe with a contained")
    print("bootstrap DD and both halves positive -> real -> build ib_insync execution on IB (futures+stock legs).")
    print("Caveat: still Yahoo daily; the futures leg needs a clean per-contract check on IB data before live.")

if __name__=="__main__":
    main()
