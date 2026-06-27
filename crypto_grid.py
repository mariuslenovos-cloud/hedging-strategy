#!/usr/bin/env python3
"""
CRYPTO GRID analysis (thorough, cost-first) -- does an INTRADAY grid on crypto beat
GridStat-gold? The grid needs: BIG moves (harvest>tail) + reversion/random-walk (price
comes back) + cheap-enough cost + dodge the brutal crypto overnight swap (intraday-only).
Compare crypto vs GOLD (the proven substrate) on the metrics that ACTUALLY decide a grid:
 - real spread + swap (MT5)
 - VR (reversion: <1 reverts, ~1 random-walk like gold, >1 trends = grid death)
 - amplitude/cost = harvest-per-spread
 - TAIL: 95th-pctile sustained N-bar run (the blow-up the grid stacks into)
Data: Yahoo hourly (fast). Honest: a bar grid-P&L SIM is unreliable (failed gold sanity),
so this reports the RELIABLE decision metrics, not a fake PF.
"""
import json, numpy as np, pandas as pd, urllib.request
import MetaTrader5 as mt5

CRYPTO_TK = {"BTC-USD":"BTCUSD","ETH-USD":"ETHUSD","SOL-USD":"SOLUSD","XRP-USD":"XRPUSD",
             "DOGE-USD":"DOGEUSD","BNB-USD":"BNBUSD","LTC-USD":"LTCUSD","ADA-USD":"ADAUSD"}
GOLD_TK = "GC=F"

def yh(tk, rng="730d", iv="1h"):
    url=f"https://query1.finance.yahoo.com/v8/finance/chart/{tk}?range={rng}&interval={iv}"
    try:
        req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req,timeout=20) as r: j=json.load(r)
        res=j["chart"]["result"][0];q=res["indicators"]["quote"][0]
        df=pd.DataFrame({"h":q["high"],"l":q["low"],"c":q["close"]}).dropna()
        return df if len(df)>500 else None
    except Exception as e: print(f"  {tk} FAIL {str(e)[:40]}",flush=True);return None

def vr(r,q):
    r=np.asarray(r,float);n=len(r)
    if n<q*3:return np.nan
    mu=r.mean();v1=((r-mu)**2).sum()/(n-1)
    rq=np.convolve(r,np.ones(q),"valid");vq=((rq-q*mu)**2).sum()/(len(rq)-1)
    return vq/(q*v1) if v1>0 else np.nan

def metrics(df,cost_bps):
    c=df["c"].values
    ret=np.diff(np.log(c))
    amp=np.median(np.abs(ret))*1e4                       # median |H1 move| bps
    mps=amp/cost_bps if cost_bps>0 else 0
    # tail: 95th pctile of |24-bar cumulative move| (a sustained ~1-day run the grid stacks into)
    cum24=np.array([ (c[i+24]-c[i])/c[i] for i in range(0,len(c)-24,6) ])
    tail95=np.percentile(np.abs(cum24),95)*1e4
    return dict(VR6=vr(ret,6),VR24=vr(ret,24),amp_bps=amp,mps=mps,tail95_bps=tail95,
                harvest_to_tail=amp/ (tail95/1e4*1e4) if tail95>0 else 0)

def main():
    # real costs from MT5 (symbol_info only = fast)
    mt5.initialize(); have={s.name for s in mt5.symbols_get()}
    costs={}
    for tk,sym in CRYPTO_TK.items():
        if sym in have:
            mt5.symbol_select(sym,True); si=mt5.symbol_info(sym)
            if si and si.ask>0:
                mid=(si.ask+si.bid)/2
                costs[sym]=dict(spread_bps=(si.ask-si.bid)/mid*1e4, swapL=si.swap_long, swapS=si.swap_short)
    mt5.shutdown()
    print("=== REAL CRYPTO COSTS (MT5; market may be open -> live spread) ===")
    for s,c in costs.items(): print(f"  {s:<9} spread={c['spread_bps']:7.2f}bps  swapLong={c['swapL']:.1f} swapShort={c['swapS']:.1f}")
    print("  (crypto swap is PUNITIVE + often paid BOTH ways -> grid MUST be intraday-only)\n")

    print("=== GRID-DECISION METRICS (Yahoo hourly) vs GOLD benchmark ===")
    print(f"{'sym':<9}{'cost_bps':>9}{'VR6':>7}{'VR24':>7}{'amp_bps':>9}{'moves/spr':>10}{'tail95_bps':>11}")
    g=yh(GOLD_TK)
    rows=[]
    if g is not None:
        gm=metrics(g, 1.38)
        print(f"{'GOLD':<9}{1.38:>9.2f}{gm['VR6']:>7.2f}{gm['VR24']:>7.2f}{gm['amp_bps']:>9.0f}{gm['mps']:>10.1f}{gm['tail95_bps']:>11.0f}  <= benchmark")
    for tk,sym in CRYPTO_TK.items():
        cb=costs.get(sym,{}).get("spread_bps")
        if cb is None: continue
        df=yh(tk)
        if df is None: continue
        m=metrics(df,cb)
        flag=""
        if g is not None and m['mps']>gm['mps'] and 0.85<m['VR24']<1.15: flag="  <= gold-like+cheaper-relative"
        print(f"{sym:<9}{cb:>9.2f}{m['VR6']:>7.2f}{m['VR24']:>7.2f}{m['amp_bps']:>9.0f}{m['mps']:>10.1f}{m['tail95_bps']:>11.0f}{flag}")
    print("\nREAD: grid wants moves/spread >= gold's AND VR ~1 (random walk, not trending VR>1.2).")
    print("tail95 = a typical sustained 1-day run (bps) the grid stacks into = the blow-up size to survive.")
    print("If crypto's moves/spread >> gold AND VR~1 AND tail manageable -> real intraday-grid lead.")
    print("If VR>1.2 (trends) or tail95 huge vs amp -> the grid blows up worse than gold. (intraday-only assumed; swap dodged.)")

if __name__=="__main__": main()
