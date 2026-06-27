#!/usr/bin/env python3
"""
GO BEYOND the recovery grid. PF-5 structure = cut losers TINY (1-2R), let winners RUN.
Donchian breakout entry, initial ATR stop, wide chandelier trail. Ranked by PF, net of
real spread. PF comes from convexity (avgWin >> avgLoss), not win-rate. Not anchored on
GridStat -- this is a different structure with a different (higher) ceiling.
"""
import json, urllib.request, numpy as np, pandas as pd

TK = {"USDJPY=X":("USDJPY",1.55),"EURJPY=X":("EURJPY",1.73),"GBPJPY=X":("GBPJPY",1.82),
      "AUDJPY=X":("AUDJPY",3.27),"GC=F":("GOLD",1.38),"CL=F":("WTI",6.61),
      "^NDX":("NAS100",0.86),"BTC-USD":("BTCUSD",7.70),"^N225":("NIK225",2.0),"SI=F":("SILVER",10.62)}

def yh(tk):
    try:
        req=urllib.request.Request(f"https://query1.finance.yahoo.com/v8/finance/chart/{tk}?range=10y&interval=1d",
                                   headers={"User-Agent":"Mozilla/5.0"})
        q=json.load(urllib.request.urlopen(req,timeout=20))["chart"]["result"][0]["indicators"]["quote"][0]
        return pd.DataFrame({"h":q["high"],"l":q["low"],"c":q["close"]}).dropna().reset_index(drop=True)
    except Exception as e:
        print(tk,"fail",str(e)[:30]); return None

def trend(h,l,c,cost,N,initATR,trailATR):
    n=len(c)
    atr=pd.Series(np.maximum(h-l,np.abs(pd.Series(c).diff()))).rolling(20).mean().values
    hh=pd.Series(h).rolling(N).max().shift(1).values; ll=pd.Series(l).rolling(N).min().shift(1).values
    pos=0;ep=0;stop=0;peak=0;pnl=[]
    for i in range(N,n):
        if np.isnan(atr[i]) or atr[i]<=0: continue
        if pos==0:
            if c[i]>hh[i]: pos=1;ep=c[i];stop=c[i]-initATR*atr[i];peak=c[i]
            elif c[i]<ll[i]: pos=-1;ep=c[i];stop=c[i]+initATR*atr[i];peak=c[i]
        elif pos==1:
            peak=max(peak,h[i]); stop=max(stop,peak-trailATR*atr[i])
            if l[i]<=stop: pnl.append((stop-ep)/ep-cost); pos=0
        elif pos==-1:
            peak=min(peak,l[i]); stop=min(stop,peak+trailATR*atr[i])
            if h[i]>=stop: pnl.append((ep-stop)/ep-cost); pos=0
    if len(pnl)<8: return None
    a=np.array(pnl)
    pf=a[a>0].sum()/-a[a<0].sum() if (a<0).any() else 99
    return dict(tr=len(a),win=(a>0).mean(),pf=pf,net=a.sum()*100,
                avgW=a[a>0].mean()*100 if (a>0).any() else 0,
                avgL=a[a<0].mean()*100 if (a<0).any() else 0)

def main():
    print("%-8s %-13s %6s %5s %6s %7s %12s" % ("mkt","N/init/trail","trades","win","PF","net%","avgW:avgL"))
    print("-"*62)
    for tk,(lab,cb) in TK.items():
        df=yh(tk)
        if df is None: continue
        h,l,c=df["h"].values,df["l"].values,df["c"].values
        bb=None
        for N in [20,40,55]:
            for ia in [1.0,1.5,2.0]:
                for ta in [3,4,6]:
                    r=trend(h,l,c,cb/1e4,N,ia,ta)
                    if r and (bb is None or r["pf"]>bb[0]["pf"]): bb=(r,N,ia,ta)
        if bb:
            r,N,ia,ta=bb
            flag = "  <== PF>=3 (beyond GridStat)" if r["pf"]>=3 else ""
            wl = "%.1f:%.1f" % (r["avgW"], r["avgL"])
            print("%-8s %-13s %6d %4.0f%% %6.2f %7.0f %12s%s" %
                  (lab, "%d/%.1f/%d"%(N,ia,ta), r["tr"], r["win"]*100, r["pf"], r["net"], wl, flag))
    print("\nPF from convexity (avgW >> avgL), NOT win-rate. PF>=5 = the goal.")
    print("Caveat: trend systems are regime-dependent -- high PF in trending eras, flat in chop.")

if __name__=="__main__": main()
