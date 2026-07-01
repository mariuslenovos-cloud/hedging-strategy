#!/usr/bin/env python3
"""
RV -- final check with a KALMAN-FILTER hedge ratio (the standard pairs-trading estimator, smoother/less noisy
than rolling-OLS). If RV still dies here, it's definitively dead. Chan-style dynamic linear regression:
state = [slope, intercept] as a random walk; the innovation e_t (forecast error) is the mean-reverting signal,
traded vs its Kalman std sqrt(Q_t). No look-ahead (beta_t uses data up to t). Real 2-leg cost. Robustness over delta.

Run:  python rv_kalman.py
"""
import json, ssl, time, urllib.request
from datetime import datetime
import numpy as np, pandas as pd

PAIRS=[("CL=F","BZ=F","WTI-Brent",3.5),("PSX","VLO","crack",2.0),("COP","OXY","producers",2.0),
       ("VLO","MPC","refiners",2.0),("XOM","CVX","integrateds",2.0),("JPM","BAC","BANK CTRL",2.0)]
RANGE="14y"; _ctx=ssl.create_default_context(); _ctx.check_hostname=False; _ctx.verify_mode=ssl.CERT_NONE

def fetch(t):
    url=f"https://query1.finance.yahoo.com/v8/finance/chart/{t}?range={RANGE}&interval=1d"
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"})
    for a in range(3):
        try:
            with urllib.request.urlopen(req,timeout=20,context=_ctx) as r: j=json.load(r)
            res=j["chart"]["result"][0]
            s=pd.Series(res["indicators"]["quote"][0]["close"],
                        index=pd.to_datetime(res["timestamp"],unit="s").normalize()).dropna()
            return np.log(s[~s.index.duplicated(keep="last")])
        except Exception:
            if a==2: return None
            time.sleep(1.0)

def kalman_pairs(la, lb, delta, cost_bps, Ve=1e-3, E=1.5, X=0.5, S=5.0):
    df=pd.concat([la,lb],axis=1,keys=["y","x"]).dropna()
    y=df["y"].values; xb=df["x"].values; n=len(y)
    Xm=np.column_stack([xb,np.ones(n)])                 # state = [slope, intercept]
    Vw=delta/(1-delta)*np.eye(2)
    beta=np.zeros(2); P=np.zeros((2,2)); e=np.zeros(n); Q=np.zeros(n); slope=np.zeros(n)
    for t in range(n):
        Pp = P+Vw if t>0 else P
        xt=Xm[t]; et=y[t]-xt.dot(beta); qt=xt.dot(Pp).dot(xt)+Ve
        K=Pp.dot(xt)/qt; beta=beta+K*et; P=Pp-np.outer(K,xt.dot(Pp))
        e[t]=et; Q[t]=qt; slope[t]=beta[0]
    z=pd.Series(e/np.sqrt(Q),index=df.index); z.iloc[:60]=np.nan
    slope=pd.Series(slope,index=df.index); zv=z.values; pos=np.zeros(n); st=0
    for t in range(n):
        zt=zv[t]
        if np.isnan(zt): pos[t]=st; continue
        if st==0:
            if zt>E: st=-1
            elif zt<-E: st=1
        elif st==1:
            if zt>=-X or zt<=-S: st=0
        elif st==-1:
            if zt<=X or zt>=S: st=0
        pos[t]=st
    pos=pd.Series(pos,index=df.index)
    pnl=pos.shift(1)*(df["y"].diff()-slope.shift(1)*df["x"].diff())
    cost=(cost_bps/1e4)*(1+slope.abs())*pos.diff().abs().fillna(pos.abs())
    net=(pnl-cost).dropna()
    return net, int((pos.diff().abs()>0).sum())

def sh(x):
    x=x.dropna()
    if len(x)<100 or x.std()==0: return 0.0
    return x.mean()/x.std()*np.sqrt(252)
def dd(x):
    eq=(1+x.dropna()).cumprod(); return (eq/eq.cummax()-1).min()

def main():
    print(f"RV -- KALMAN hedge-ratio final check  |  {datetime.now():%Y-%m-%d %H:%M}  |  NET of 2-leg cost\n")
    print(f"{'pair':14} {'Sharpe':>7} {'maxDD':>7} {'trades':>6}  {'delta-robustness (Sh @ 1e-5/1e-4/1e-3)'}")
    logs={}
    def g(t):
        if t not in logs: logs[t]=fetch(t); time.sleep(0.3)
        return logs[t]
    for ta,tb,lbl,cost in PAIRS:
        la,lb=g(ta),g(tb)
        if la is None or lb is None: print(f"{lbl:14} fetch failed"); continue
        base,tr=kalman_pairs(la,lb,1e-4,cost)
        robust=[sh(kalman_pairs(la,lb,d,cost)[0]) for d in (1e-5,1e-4,1e-3)]
        print(f"{lbl:14} {sh(base):>7.2f} {dd(base)*100:>6.0f}% {tr:>6}   {robust[0]:+.2f} / {robust[1]:+.2f} / {robust[2]:+.2f}")
    print("\nVERDICT: if the structural pairs are still ~0 across delta (and the bank control stays ~0/neg),")
    print("RV cointegration is DEFINITIVELY not tradeable on retail daily data net of cost -> close it, move to equity-reversion.")

if __name__=="__main__":
    main()
