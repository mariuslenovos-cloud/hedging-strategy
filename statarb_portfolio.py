"""
statarb_portfolio.py -- quantify the stat-arb PORTFOLIO edge properly.

Takes the cointegrated pairs found by statarb_stocks/statarb_scan and runs a REALISTIC
backtest: ROLLING hedge-ratio + ROLLING z-score (no lookahead), enter at |z|>=ZIN,
exit at |z|<=ZOUT, hard-stop at |z|>=ZSTOP (cointegration-break protection), daily
mark-to-market, net of round-trip cost per leg. Then COMBINES all pairs into an
equal-risk portfolio -> the real metric: combined Sharpe / annual return / max DD.
That's where stat-arb makes money (many ~uncorrelated market-neutral pairs).

Run: python statarb_portfolio.py
"""
import sys, json, time, urllib.request
import numpy as np
import pandas as pd

try: sys.stdout.reconfigure(line_buffering=True)
except Exception: pass

# cointegrated pairs (ADF<-2.86) from the scans -- oil/gold/banks/tech/pharma + WTI/Brent commodity
PAIRS = [
    ("PNC","TFC"),("AMZN","NVDA"),("COP","OXY"),("PFE","ABBV"),("KGC","WPM"),
    ("USB","PNC"),("JPM","BAC"),("CVX","VLO"),("PFE","MRK"),("AEM","KGC"),
    ("PSX","VLO"),("JPM","WFC"),("AAPL","GOOGL"),("GS","MS"),("XOM","VLO"),
    ("ABBV","LLY"),("BAC","TFC"),("VLO","MPC"),
]
LOOKBACK = 60          # rolling window for hedge ratio + z (trading days)
ZIN, ZOUT, ZSTOP = 2.0, 0.5, 4.0
COST_BPS = 8.0         # per-leg round-trip cost (bps); charged on each entry+exit


def yahoo_close(t, rng="3y"):
    url=f"https://query1.finance.yahoo.com/v8/finance/chart/{t}?range={rng}&interval=1d"
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req,timeout=20) as r: j=json.load(r)
        res=j["chart"]["result"][0]
        s=pd.Series(res["indicators"]["quote"][0]["close"],index=res["timestamp"]).dropna()
        return s[s>0]
    except Exception: return None


def pair_daily_pnl(pa, pb):
    """rolling-z reversion; returns a daily PnL series (in fraction-of-capital units, market-neutral)."""
    df=pd.concat([np.log(pa),np.log(pb)],axis=1,join="inner").dropna()
    if len(df)<LOOKBACK+50: return None
    a=df.iloc[:,0].to_numpy(); b=df.iloc[:,1].to_numpy(); n=len(a)
    cost=2*COST_BPS/1e4
    pos=0.0; beta=1.0; pnl=np.zeros(n); ntr=0
    for i in range(LOOKBACK,n):
        aw=a[i-LOOKBACK:i]; bw=b[i-LOOKBACK:i]
        beta=np.cov(aw,bw)[0,1]/np.var(bw) if np.var(bw)>0 else 1.0
        spr=aw-beta*bw; mu=spr.mean(); sd=spr.std()
        if sd<=0: continue
        cur=a[i]-beta*b[i]; z=(cur-mu)/sd
        # daily MTM of an open position from yesterday's spread change
        if pos!=0.0:
            dspr=(a[i]-beta*b[i])-(a[i-1]-beta*b[i-1])
            pnl[i]=pos*dspr
        newpos=pos
        if pos==0.0:
            if z>=ZIN: newpos=-1.0
            elif z<=-ZIN: newpos=+1.0
        else:
            if abs(z)<=ZOUT or abs(z)>=ZSTOP: newpos=0.0
        if newpos!=pos:
            pnl[i]-=cost; ntr+=1     # charge cost on any position change
            pos=newpos
    return pd.Series(pnl,index=df.index), ntr


def stats(p):
    p=p[p!=0] if False else p
    ann=252
    mean=p.mean()*ann; vol=p.std()*np.sqrt(ann)
    sh=mean/vol if vol>0 else 0
    eq=p.cumsum(); dd=(eq-eq.cummax()).min()
    return mean,vol,sh,eq.iloc[-1],dd


def main():
    tickers=sorted({t for pr in PAIRS for t in pr})
    print(f"Pulling {len(tickers)} tickers (Yahoo daily 3y)...")
    data={}
    for t in tickers:
        s=yahoo_close(t)
        if s is not None and len(s)>300: data[t]=s
        time.sleep(0.12)
    print(f"  got {len(data)}/{len(tickers)}\n")

    series=[]; rows=[]
    for pa,pb in PAIRS:
        if pa not in data or pb not in data: continue
        out=pair_daily_pnl(data[pa],data[pb])
        if out is None: continue
        pl,ntr=out
        m,v,sh,tot,dd=stats(pl)
        rows.append((f"{pa}-{pb}",ntr,tot,sh,dd)); series.append(pl)
    print(f"{'pair':<14}{'pos-changes':>12}{'totRet':>9}{'Sharpe':>8}{'maxDD':>9}")
    for nm,ntr,tot,sh,dd in sorted(rows,key=lambda r:-r[3]):
        print(f"{nm:<14}{ntr:>12}{tot:>+9.2%}{sh:>+8.2f}{dd:>+9.2%}")

    # PORTFOLIO: equal-weight daily PnL across pairs (each ~market-neutral, ~uncorrelated)
    port=pd.concat(series,axis=1,join="outer").fillna(0.0)
    nactive=(port!=0).sum(axis=1).replace(0,1)
    pe=port.sum(axis=1)/len(series)         # equal-weight (1/N each)
    m,v,sh,tot,dd=stats(pe)
    yrs=len(pe)/252
    print(f"\n=== PORTFOLIO (equal-weight {len(series)} cointegrated pairs, net of {COST_BPS}bps/leg) ===")
    print(f"   annualized return {m:+.1%}  vol {v:.1%}  SHARPE {sh:+.2f}  maxDD {dd:+.1%}  totRet {tot:+.1%} over {yrs:.1f}y")
    # avg pairwise correlation of pair-returns (diversification check)
    cc=port.corr().to_numpy(); iu=np.triu_indices_from(cc,1)
    print(f"   avg pairwise corr of pair-PnLs: {np.nanmean(cc[iu]):+.2f}  (low = good diversification)")
    print("\n   Sharpe>1 net = a real market-neutral book (uncorrelated to the gold/oil momentum grid).")
    print("   Next: map tickers->MT5 CFDs, verify real CFD spreads, CPCV/holdout, then the pairs EA.")


if __name__=="__main__":
    main()
