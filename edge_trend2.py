#!/usr/bin/env python3
"""
NIGHT BATCH 4 -- harden the trend lead (Yahoo data):
 (1) JPY-cross ROBUSTNESS: USDJPY/EURJPY/AUDJPY across Donchian N={20,40,55} +
     first-half vs second-half stability (is the edge persistent or one lucky trend?).
 (2) DIVERSIFIED TREND PORTFOLIO: equal-weight daily trend returns across all markets ->
     portfolio Sharpe / maxDD / avg pairwise corr (the real CTA edge = diversification).
"""
import json, numpy as np, pandas as pd
import urllib.request

TKMAP = {"USDJPY=X":"USDJPY","EURJPY=X":"EURJPY","AUDJPY=X":"AUDJPY","GBPJPY=X":"GBPJPY",
 "EURUSD=X":"EURUSD","GBPUSD=X":"GBPUSD","AUDUSD=X":"AUDUSD","USDCAD=X":"USDCAD","USDCHF=X":"USDCHF",
 "GC=F":"GOLD","SI=F":"SILVER","CL=F":"WTI","NG=F":"NATGAS","HG=F":"COPPER",
 "^NDX":"NAS100","^GSPC":"SP500","^GDAXI":"DAX40","^N225":"NIK225","BTC-USD":"BTCUSD","ETH-USD":"ETHUSD"}
COST = {"USDJPY":1.55,"EURJPY":1.73,"AUDJPY":3.27,"GBPJPY":1.82,"EURUSD":1.75,"GBPUSD":1.81,
 "AUDUSD":3.43,"USDCAD":1.98,"USDCHF":2.97,"GOLD":1.29,"SILVER":10.62,"WTI":6.61,"NATGAS":49.49,
 "COPPER":2.0,"NAS100":0.86,"SP500":0.94,"DAX40":2.0,"NIK225":2.0,"BTCUSD":7.70,"ETHUSD":27.91}

def fetch(tk,rng="10y"):
    url=f"https://query1.finance.yahoo.com/v8/finance/chart/{tk}?range={rng}&interval=1d"
    try:
        req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req,timeout=15) as r: j=json.load(r)
        res=j["chart"]["result"][0];q=res["indicators"]["quote"][0]
        df=pd.DataFrame({"h":q["high"],"l":q["low"],"c":q["close"]}).dropna()
        return df if len(df)>400 else None
    except Exception as e: print(f"  {tk} FAIL {str(e)[:30]}",flush=True);return None

def trend_pnl(h,l,c,cost,N,Nx):
    n=len(c);pos=0;ep=0;pnl=[];ei=0
    hh=pd.Series(h).rolling(N).max().shift(1).values;ll=pd.Series(l).rolling(N).min().shift(1).values
    xh=pd.Series(h).rolling(Nx).max().shift(1).values;xl=pd.Series(l).rolling(Nx).min().shift(1).values
    idx=[]
    for i in range(N,n):
        if pos==0:
            if c[i]>hh[i]:pos=1;ep=c[i];ei=i
            elif c[i]<ll[i]:pos=-1;ep=c[i];ei=i
        elif pos==1 and c[i]<xl[i]:pnl.append((c[i]-ep)/ep-cost);idx.append(i);pos=0
        elif pos==-1 and c[i]>xh[i]:pnl.append((ep-c[i])/ep-cost);idx.append(i);pos=0
    return np.array(pnl),idx

def stats(a):
    if len(a)<5: return (0,0,0)
    sh=a.mean()/a.std()*np.sqrt(len(a)) if a.std()>0 else 0
    pf=(a[a>0].sum()/-a[a<0].sum()) if (a<0).any() else 9.9
    return (len(a),round(sh,2),round(pf,2))

def daily_pos_ret(h,l,c,cost,N=40,Nx=20):
    n=len(c);pos=np.zeros(n);p=0
    hh=pd.Series(h).rolling(N).max().shift(1).values;ll=pd.Series(l).rolling(N).min().shift(1).values
    xh=pd.Series(h).rolling(Nx).max().shift(1).values;xl=pd.Series(l).rolling(Nx).min().shift(1).values
    for i in range(N,n):
        if p==0:
            if c[i]>hh[i]:p=1
            elif c[i]<ll[i]:p=-1
        elif p==1 and c[i]<xl[i]:p=0
        elif p==-1 and c[i]>xh[i]:p=0
        pos[i]=p
    pct=np.zeros(n);pct[1:]=(c[1:]-c[:-1])/c[:-1]
    chg=np.abs(np.diff(np.concatenate([[0],pos])))
    vol=pd.Series(pct).rolling(50).std().values; sc=np.clip(np.nanmedian(vol)/vol,0.2,5.0); sc=np.nan_to_num(sc,nan=1.0)
    r=np.zeros(n)
    for i in range(1,n): r[i]=pos[i-1]*pct[i]*sc[i-1]-chg[i]*cost
    return r

def main():
    data={}
    for tk,lab in TKMAP.items():
        df=fetch(tk)
        if df is not None: data[lab]=df; print(f"  {lab}: {len(df)}",flush=True)
    print("\n"+"="*70);print("(1) JPY-CROSS TREND ROBUSTNESS (Sharpe across N, + half-stability)");print("="*70)
    print(f"{'mkt':<8}{'N20':>14}{'N40':>14}{'N55':>14}{'1stHalf/2nd Sh':>20}")
    for lab in ["USDJPY","EURJPY","AUDJPY","GBPJPY"]:
        if lab not in data: continue
        d=data[lab];h,l,c=d['h'].values,d['l'].values,d['c'].values;cost=COST[lab]/1e4
        cells=[]
        for N,Nx in [(20,10),(40,20),(55,20)]:
            a,_=trend_pnl(h,l,c,cost,N,Nx); cells.append(stats(a))
        a,idx=trend_pnl(h,l,c,cost,40,20); mid=len(c)//2
        h1=np.array([a[k] for k,i in enumerate(idx) if i<mid]); h2=np.array([a[k] for k,i in enumerate(idx) if i>=mid])
        s1=stats(h1)[1] if len(h1)>=5 else 0; s2=stats(h2)[1] if len(h2)>=5 else 0
        print(f"{lab:<8}{str(cells[0]):>14}{str(cells[1]):>14}{str(cells[2]):>14}{f'{s1}/{s2}':>20}")
    print("  (cell = (trades,Sharpe,PF). Want Sharpe>1 across N AND positive in BOTH halves = robust)")
    print("\n"+"="*70);print("(2) DIVERSIFIED TREND PORTFOLIO (equal-risk Donchian 40/20, net spread)");print("="*70)
    R={}
    for lab,d in data.items():
        R[lab]=pd.Series(daily_pos_ret(d['h'].values,d['l'].values,d['c'].values,COST[lab]/1e4))
    M=pd.DataFrame(R).fillna(0.0); w=1.0/len(R); port=M.sum(axis=1)*w
    ann=port.mean()*252; vol=port.std()*np.sqrt(252); sh=ann/vol if vol>0 else 0
    eq=port.cumsum(); maxdd=-(eq-eq.cummax()).min()
    cc=M.corr().values; iu=np.triu_indices_from(cc,1); avgc=np.nanmean(cc[iu])
    print(f"  markets {len(R)} | annual {ann*100:.1f}% | vol {vol*100:.1f}% | Sharpe {sh:.2f} | maxDD {maxdd*100:.1f}% | avgCorr {avgc:+.3f}")
    perm=[(lab,round(M[lab].mean()*252/(M[lab].std()*np.sqrt(252)),2)) for lab in R if M[lab].std()>0]
    perm.sort(key=lambda x:-x[1])
    print("  per-market annual Sharpe:", ", ".join(f"{l}:{s}" for l,s in perm))
    print("\ndone.",flush=True)

if __name__=="__main__": main()
