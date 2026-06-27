#!/usr/bin/env python3
"""
The "hedge fund method" (Markov regime transition matrix) -- tested with OUR rigor:
WALK-FORWARD (no lookahead) + NET OF REAL COST. Is it a real edge or dressed-up trend?

Method (per the video): state = 20-day return -> bull(>+5%)/bear(<-5%)/sideways.
Walk-forward: at each day t, build the transition matrix from PAST days only, read
today's state, signal = P(bull tomorrow|state) - P(bear tomorrow|state), position =
signal (conviction-sized, clipped [-1,1]). Trade next day. Charge real spread on
position changes. Compare to buy&hold and to our trend baseline (Sharpe ~0.6).
"""
import json, numpy as np, pandas as pd, urllib.request

ASSETS = {"GC=F":("GOLD",1.38),"SI=F":("SILVER",10.62),"CL=F":("WTI",6.61),
          "^GSPC":("SP500",0.94),"^NDX":("NAS100",0.86),"BTC-USD":("BTCUSD",7.70),
          "EURUSD=X":("EURUSD",1.75),"USDJPY=X":("USDJPY",1.55)}
LOOK=20; BULL=0.05; BEAR=-0.05; BURN=400

def yh(tk,rng="10y"):
    url=f"https://query1.finance.yahoo.com/v8/finance/chart/{tk}?range={rng}&interval=1d"
    try:
        req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req,timeout=20) as r: j=json.load(r)
        q=j["chart"]["result"][0]["indicators"]["quote"][0]
        return pd.Series(q["close"]).dropna().reset_index(drop=True)
    except Exception as e: print(f"  {tk} FAIL {str(e)[:40]}",flush=True); return None

def states(c):
    r20=c.pct_change(LOOK)
    s=np.where(r20>BULL,2, np.where(r20<BEAR,0,1))  # 0=bear,1=side,2=bull
    s[:LOOK]=1
    return s

def sharpe(x):
    x=np.asarray(x); return x.mean()/x.std()*np.sqrt(252) if x.std()>0 else 0

def backtest(c, cost):
    c=c.reset_index(drop=True); n=len(c); s=states(c)
    ret=c.pct_change().fillna(0).values
    pos=np.zeros(n); sig=np.zeros(n)
    for t in range(BURN,n-1):
        # transition matrix from PAST only (days BURN-window .. t-1)
        cnt=np.ones((3,3))  # Laplace prior
        for k in range(LOOK+1,t):
            cnt[s[k-1],s[k]]+=1
        row=cnt[s[t]]/cnt[s[t]].sum()
        pbull,pbear=row[2],row[0]
        sig[t]=pbull-pbear
        pos[t]=np.clip(pbull-pbear,-1,1)            # conviction-sized
    # strategy return next day, minus spread on position change
    dpos=np.abs(np.diff(np.concatenate([[0],pos])))
    stratret=np.zeros(n)
    for t in range(BURN,n-1):
        stratret[t+1]=pos[t]*ret[t+1]-dpos[t]*cost
    sr=stratret[BURN:]
    bh=ret[BURN:]
    eq=np.cumsum(sr); dd=-(eq-np.maximum.accumulate(eq)).min()
    trades=int((dpos[BURN:]>0.05).sum())
    return dict(sharpe=sharpe(sr),ann=sr.mean()*252*100,dd=dd*100,
                bh_sharpe=sharpe(bh),bh_ann=bh.mean()*252*100,trades=trades,
                pct_long=(pos[BURN:n-1]>0.1).mean()*100,pct_flat=(np.abs(pos[BURN:n-1])<=0.1).mean()*100)

def main():
    print(f"{'asset':<9}{'cost':>6}{'MK_Sharpe':>11}{'MK_ann%':>9}{'MK_DD%':>8}{'trades':>7}{'B&H_Sharpe':>12}{'B&H_ann%':>10}")
    print("-"*73)
    res=[]
    for tk,(lab,cb) in ASSETS.items():
        c=yh(tk)
        if c is None or len(c)<BURN+200: continue
        b=backtest(c,cb/1e4)
        res.append((lab,b))
        flag="  <= beats B&H + Sharpe>0.8" if (b['sharpe']>0.8 and b['sharpe']>b['bh_sharpe']) else ""
        print(f"{lab:<9}{cb:>6.2f}{b['sharpe']:>11.2f}{b['ann']:>9.1f}{b['dd']:>8.1f}{b['trades']:>7}{b['bh_sharpe']:>12.2f}{b['bh_ann']:>10.1f}{flag}")
    avg=np.mean([b['sharpe'] for _,b in res]) if res else 0
    print("-"*73)
    print(f"avg Markov Sharpe across assets: {avg:.2f}   (our trend baseline = 0.60; GridStat gold = far higher)")
    print("Verdict: MK_Sharpe>>B&H and >0.8 = a real regime edge. ~0.5-0.7 = it IS trend-following")
    print("dressed up (matches our trend screen). <0 or ~B&H = no edge net of cost.")
    print("NOTE: net of SPREAD only; multi-week holds add SWAP (not charged) -> real is LOWER.")

if __name__=="__main__": main()
