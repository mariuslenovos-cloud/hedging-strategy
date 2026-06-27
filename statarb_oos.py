"""
statarb_oos.py -- the DECISIVE test: does PAIR SELECTION persist out-of-sample?
Rank pairs by IN-SAMPLE Sharpe (first 60%), trade only the top-K on the UNSEEN last 40%,
measure the OOS portfolio Sharpe. If the selected book stays strong OOS -> real edge
(not in-sample luck). Benchmark vs trading ALL pairs OOS.

Run: python statarb_oos.py
"""
import sys, json, time, urllib.request, itertools
import numpy as np, pandas as pd

try: sys.stdout.reconfigure(line_buffering=True)
except Exception: pass

# broad cointegrated/near-cointegrated candidate pairs across sectors (more pairs = better selection)
PAIRS = [
    ("PNC","TFC"),("AMZN","NVDA"),("COP","OXY"),("PFE","ABBV"),("KGC","WPM"),("USB","PNC"),
    ("JPM","BAC"),("CVX","VLO"),("PFE","MRK"),("AEM","KGC"),("PSX","VLO"),("JPM","WFC"),
    ("AAPL","GOOGL"),("GS","MS"),("XOM","VLO"),("ABBV","LLY"),("BAC","TFC"),("VLO","MPC"),
    ("RY","CM"),("BNS","BMO"),("TD","BMO"),("AMD","MU"),("DAL","LUV"),("V","MA"),
    ("HD","LOW"),("WMT","COST"),("META","NVDA"),("XOM","CVX"),("MPC","PSX"),("NEM","AEM"),
]
LOOKBACK=60; ZIN,ZOUT,ZSTOP=2.0,0.5,4.0; COST_BPS=8.0; SPLIT=0.60; TOPK=8

def yclose(t,rng="4y"):
    u=f"https://query1.finance.yahoo.com/v8/finance/chart/{t}?range={rng}&interval=1d"
    r=urllib.request.Request(u,headers={"User-Agent":"Mozilla/5.0"})
    try:
        with urllib.request.urlopen(r,timeout=20) as x: j=json.load(x)
        res=j["chart"]["result"][0]
        s=pd.Series(res["indicators"]["quote"][0]["close"],index=res["timestamp"]).dropna()
        return s[s>0]
    except Exception: return None

def pair_pnl(pa,pb):
    df=pd.concat([np.log(pa),np.log(pb)],axis=1,join="inner").dropna()
    if len(df)<LOOKBACK+120: return None
    a=df.iloc[:,0].to_numpy(); b=df.iloc[:,1].to_numpy(); n=len(a)
    cost=2*COST_BPS/1e4; pos=0.0; pnl=np.zeros(n)
    for i in range(LOOKBACK,n):
        aw=a[i-LOOKBACK:i]; bw=b[i-LOOKBACK:i]
        beta=np.cov(aw,bw)[0,1]/np.var(bw) if np.var(bw)>0 else 1.0
        spr=aw-beta*bw; mu=spr.mean(); sd=spr.std()
        if sd<=0: continue
        z=((a[i]-beta*b[i])-mu)/sd
        if pos!=0.0: pnl[i]=pos*((a[i]-beta*b[i])-(a[i-1]-beta*b[i-1]))
        np_=pos
        if pos==0.0: np_=-1.0 if z>=ZIN else (1.0 if z<=-ZIN else 0.0)
        elif abs(z)<=ZOUT or abs(z)>=ZSTOP: np_=0.0
        if np_!=pos: pnl[i]-=cost; pos=np_
    return pd.Series(pnl,index=df.index)

def sharpe(p):
    return (p.mean()*252)/(p.std()*np.sqrt(252)) if p.std()>0 else 0.0

def main():
    tk=sorted({t for pr in PAIRS for t in pr})
    print(f"Pulling {len(tk)} tickers (Yahoo daily 4y)...")
    data={}
    for t in tk:
        s=yclose(t)
        if s is not None and len(s)>400: data[t]=s
        time.sleep(0.12)
    print(f"  got {len(data)}/{len(tk)}\n")

    pnls={}
    for pa,pb in PAIRS:
        if pa in data and pb in data:
            p=pair_pnl(data[pa],data[pb])
            if p is not None: pnls[f"{pa}-{pb}"]=p
    # common index
    M=pd.concat(pnls,axis=1,join="outer").fillna(0.0)
    cut=int(len(M)*SPLIT)
    IS=M.iloc[:cut]; OOS=M.iloc[cut:]
    isS={c:sharpe(IS[c]) for c in M.columns}
    sel=sorted(isS,key=lambda c:-isS[c])[:TOPK]
    print(f"split: IS={cut}d  OOS={len(M)-cut}d   TOPK={TOPK} by IN-SAMPLE Sharpe")
    print(f"\n{'pair':<13}{'IS Sharpe':>10}{'OOS Sharpe':>11}{'selected':>10}")
    for c in sorted(M.columns,key=lambda c:-isS[c]):
        print(f"{c:<13}{isS[c]:>+10.2f}{sharpe(OOS[c]):>+11.2f}{'  <SEL' if c in sel else '':>10}")

    def port(cols,df):
        pe=df[cols].sum(axis=1)/len(cols); return sharpe(pe),pe.sum(),(pe.cumsum()-pe.cumsum().cummax()).min()
    sS,sR,sD=port(sel,OOS)
    aS,aR,aD=port(list(M.columns),OOS)
    print(f"\n=== OUT-OF-SAMPLE portfolio (last {len(M)-cut}d, net {COST_BPS}bps/leg) ===")
    print(f"   SELECTED top-{TOPK} (by IS Sharpe):  OOS Sharpe {sS:+.2f}  totRet {sR:+.1%}  maxDD {sD:+.1%}")
    print(f"   ALL {len(M.columns)} pairs (benchmark):     OOS Sharpe {aS:+.2f}  totRet {aR:+.1%}  maxDD {aD:+.1%}")
    print(f"\n   VERDICT: selection {'PERSISTS OOS -> real edge (build it)' if sS>aS+0.2 and sS>0.7 else 'does NOT clearly persist -> in-sample luck / marginal'}.")

if __name__=="__main__": main()
