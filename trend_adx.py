#!/usr/bin/env python3
"""
Test the trend-vs-chop regime filter: only take the breakout when ADX (trend strength)
is high. Question = does it KEEP the orange (trends) and CUT the chop? Donchian(55)
breakout + 1R stop + chandelier(5xATR) trail, net of spread+swap. ADX(14) entry gate
swept. Reported on the BROKER window (2024-2026) AND the full history -- honestly.
"""
import json, urllib.request, numpy as np, pandas as pd

def yh(tk, rng="11y"):
    req=urllib.request.Request(f"https://query1.finance.yahoo.com/v8/finance/chart/{tk}?range={rng}&interval=1d",
                               headers={"User-Agent":"Mozilla/5.0"})
    res=json.load(urllib.request.urlopen(req,timeout=25))["chart"]["result"][0]
    ts=res["timestamp"]; q=res["indicators"]["quote"][0]
    df=pd.DataFrame({"t":pd.to_datetime(ts,unit="s"),"h":q["high"],"l":q["low"],"c":q["close"]}).dropna().reset_index(drop=True)
    return df

def adx(h,l,c,n=14):
    h,l,c=map(np.asarray,(h,l,c))
    pdm=np.zeros(len(c)); ndm=np.zeros(len(c)); tr=np.zeros(len(c))
    for i in range(1,len(c)):
        up=h[i]-h[i-1]; dn=l[i-1]-l[i]
        pdm[i]=up if (up>dn and up>0) else 0
        ndm[i]=dn if (dn>up and dn>0) else 0
        tr[i]=max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1]))
    atr=pd.Series(tr).ewm(alpha=1/n,adjust=False).mean()
    pdi=100*pd.Series(pdm).ewm(alpha=1/n,adjust=False).mean()/atr
    ndi=100*pd.Series(ndm).ewm(alpha=1/n,adjust=False).mean()/atr
    dx=100*(pdi-ndi).abs()/(pdi+ndi).replace(0,np.nan)
    return dx.ewm(alpha=1/n,adjust=False).mean().values

def bt(df, spread, swapday, N=55, ia=1.0, ta=5.0, adx_min=0):
    h,l,c=df["h"].values,df["l"].values,df["c"].values
    A=adx(h,l,c)
    atr=pd.Series(np.maximum(h-l,np.abs(pd.Series(c).diff()))).rolling(20).mean().values
    up=pd.Series(h).rolling(N).max().shift(1).values; dn=pd.Series(l).rolling(N).min().shift(1).values
    pos=0;ep=0;stop=0;peak=0;ei=0;pnl=[]
    for i in range(N,len(c)):
        if np.isnan(atr[i]) or atr[i]<=0 or np.isnan(A[i]): continue
        if pos==0:
            if adx_min>0 and A[i]<adx_min: continue        # regime filter: only trade when trending
            if c[i]>up[i]: pos=1;ep=c[i];peak=c[i];ei=i;stop=c[i]-ia*atr[i]
            elif c[i]<dn[i]: pos=-1;ep=c[i];peak=c[i];ei=i;stop=c[i]+ia*atr[i]
        else:
            if pos==1: peak=max(peak,h[i]);stop=max(stop,peak-ta*atr[i]); hit=l[i]<=stop
            else: peak=min(peak,l[i]);stop=min(stop,peak+ta*atr[i]); hit=h[i]>=stop
            if hit:
                gross=pos*(stop-ep)/ep; cost=spread/1e4+swapday/1e4*(i-ei)
                pnl.append(gross-cost); pos=0
    if len(pnl)<5: return None
    a=np.array(pnl); pf=a[a>0].sum()/-a[a<0].sum() if (a<0).any() else 99
    return dict(tr=len(a),win=(a>0).mean(),pf=pf,net=a.sum()*100)

def report(df,label,spread,swap):
    print(f"\n=== {label} ({df['t'].iloc[0]:%Y-%m} to {df['t'].iloc[-1]:%Y-%m}, {len(df)} bars) ===")
    print(f"{'ADX gate':>9}{'trades':>8}{'win':>6}{'PF':>7}{'net%':>8}")
    for am in [0,20,25,30]:
        r=bt(df,spread,swap,adx_min=am)
        if r: print(f"{('none' if am==0 else '>='+str(am)):>9}{r['tr']:>8}{r['win']:>6.0%}{r['pf']:>7.2f}{r['net']:>8.0f}")

def main():
    df=yh("BTC-USD")
    sp,sw=7.7,4.0
    report(df,"BTC FULL history",sp,sw)
    win=df[df["t"]>="2024-01-01"].reset_index(drop=True)
    report(win,"BTC broker window 2024-2026",sp,sw)
    print("\nRead: does ADX gate KEEP PF (orange/trends) while raising it (cut chop)? Or just cut everything?")

if __name__=="__main__": main()
