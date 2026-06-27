#!/usr/bin/env python3
"""
B: NON-INVASIVE signal/decision monitor for the live GridStat streams.
Pulls recent M5 bars via the MT5 API, FAITHFULLY reproduces the embedded
Goldminer signal + the EA's gate sequence, and logs per signal event:
   TRADE  or  SKIP:<reason>
then CROSS-CHECKS each event against the actual deal history (did the EA
really open a trade near it?) -- so the known ADX/ATR parity gap can't
silently mislead us. Touches nothing live (read-only).

Faithful: Goldminer signal, session, fingerprint, DB win-rate, D1 trend.
Approx (parity gap, flagged): ADX, ATR-regime boundary, MA-angle.

Run: python gridstat_signalscan.py [days]      (default 10)
Writes gridstat_signals_recent.csv + console table.
"""
import sys, csv, math
from datetime import datetime, timedelta
from collections import defaultdict
try:
    import MetaTrader5 as mt5
except Exception as e:
    print("MetaTrader5 not available:", e); sys.exit(1)

COMMON = r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\Common\Files"
# per-stream live config (CLAUDE.md locks + Experts-log CONFIG)
STREAMS = {
    "GOLD":    dict(magic=57502, grisk=4,  db="gridstat_setups_gold.csv",      stats_filter=True,  min_wr=0.55, min_n=10, d1filter=False, sizing=False),
    "SILVER":  dict(magic=59917, grisk=14, db="gridstat_setups_silver_mt5.csv",stats_filter=True,  min_wr=0.50, min_n=10, d1filter=False, sizing=False),
    "OILCash": dict(magic=62092, grisk=4,  db="gridstat_setups_oil_mt5.csv",   stats_filter=False, min_wr=0.50, min_n=10, d1filter=False, sizing=True),
}
ADX_THR=25.0; ANG_THR=20.0; DAILY_MA=50; GM_GAPMULT=2.0; GM_FASTMULT=4.6

def connect():
    for _ in range(3):
        if mt5.initialize(): return True
    print("MT5 init failed:", mt5.last_error()); return False

def ema(vals, period):
    k=2/(period+1); out=[None]*len(vals); s=None
    for i,v in enumerate(vals):
        s=v if s is None else v*k+s*(1-k); out[i]=s
    return out

def wilder_adx(h,l,c,n=14):
    """Wilder ADX (approximate vs MT5 iADX -- parity gap, flagged)."""
    N=len(c); tr=[0.0]*N; pdm=[0.0]*N; ndm=[0.0]*N
    for i in range(1,N):
        up=h[i]-h[i-1]; dn=l[i-1]-l[i]
        pdm[i]=up if (up>dn and up>0) else 0.0
        ndm[i]=dn if (dn>up and dn>0) else 0.0
        tr[i]=max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1]))
    def rma(x):
        out=[None]*N; s=None
        for i in range(1,N):
            if i<=n:
                if i==n: s=sum(x[1:n+1]); out[i]=s
            else: s=s-(s/n)+x[i]; out[i]=s
        return out
    atr=rma(tr); pdmr=rma(pdm); ndmr=rma(ndm); adx=[None]*N; dx=[None]*N
    for i in range(N):
        if atr[i] and atr[i]>0:
            pdi=100*pdmr[i]/atr[i]; ndi=100*ndmr[i]/atr[i]
            dx[i]=100*abs(pdi-ndi)/(pdi+ndi) if (pdi+ndi)>0 else 0
    # ADX = Wilder-smoothed DX
    s=None
    for i in range(N):
        if dx[i] is None: continue
        if s is None:
            j=[k for k in range(i,min(i+n,N)) if dx[k] is not None]
            if len(j)>=n: s=sum(dx[k] for k in j[:n])/n; adx[j[n-1]]=s
        else:
            s=(s*(n-1)+dx[i])/n; adx[i]=s
    return adx

def gm_val_series(o,h,l,c,grisk):
    """reproduce GMValueAt for every bar (chronological arrays, 0=oldest)."""
    N=len(c); val=[50.0]*N; base=grisk*2+3
    for p in range(N):
        if p<base: continue
        ar=sum(abs(h[p-k]-l[p-k]) for k in range(10))/10.0
        gap=any(abs(o[p-k]-c[p-k-1])>=GM_GAPMULT*ar for k in range(9) if p-k-1>=0)   # GM_GapMode=0
        fast=any(p-k-3>=0 and abs(c[p-k]-c[p-k-3])>=GM_FASTMULT*ar for k in range(6))
        period=3 if gap else (4 if fast else base)
        hh=max(h[p-period+1:p+1]); ll=min(l[p-period+1:p+1]); cl=c[p]
        wpr=-100.0*(hh-cl)/(hh-ll) if (hh-ll)!=0 else 0
        val[p]=100.0-abs(wpr)
    return val

def gm_signals(val,grisk):
    """band-traverse: returns dir per bar (1=BUY,-1pos? use 'BUY'/'SELL'/None)."""
    upper=grisk+67; lower=33-grisk; N=len(val); out=[None]*N; LB=40
    for p in range(N):
        if p<LB: continue
        d=None; li=1
        if val[p]>upper:
            while li<LB-1 and lower<=val[p-li]<=upper: li+=1
            if val[p-li]<lower: d="BUY"
        elif val[p]<lower:
            while li<LB-1 and lower<=val[p-li]<=upper: li+=1
            if val[p-li]>upper: d="SELL"
        out[p]=d
    return out

def load_db(name):
    """return {setup_key:(winrate,n)} from the GridStat shadow DB (faithful)."""
    import os
    p=os.path.join(COMMON,name); tot=defaultdict(int); win=defaultdict(int)
    try:
        with open(p,newline="") as f:
            r=csv.DictReader(f)
            for row in r:
                k=row["setup_key"]; tot[k]+=1
                if float(row["r_multiple"])>0: win[k]+=1
    except Exception as e:
        print(f"  (DB {name} not read: {e})")
    return {k:(win[k]/tot[k],tot[k]) for k in tot}

def session(hr): return "HR_ASIA" if hr<9 else "HR_LDN" if hr<14 else "HR_OVL" if hr<18 else "HR_NY"

def scan(sym, cfg, days, deals_by_sym):
    info=mt5.symbol_info(sym)
    if info is None:
        if not mt5.symbol_select(sym,True): print(f"  {sym}: not available"); return []
        info=mt5.symbol_info(sym)
    point=info.point*10 if info.digits in (3,5) else info.point
    need=int(days*24*12)+300
    r=mt5.copy_rates_from_pos(sym,mt5.TIMEFRAME_M5,0,need)
    if r is None or len(r)<200: print(f"  {sym}: no rates"); return []
    o=[x['open'] for x in r]; h=[x['high'] for x in r]; l=[x['low'] for x in r]; c=[x['close'] for x in r]; t=[x['time'] for x in r]
    # ATR(M5,20)/ATR(M5,100) for regime; EMA20 angle; EMA50 D1 via D1 rates
    def atr(n):
        tr=[0.0]*len(c)
        for i in range(1,len(c)): tr[i]=max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1]))
        out=[None]*len(c); s=None
        for i in range(1,len(c)):
            if i<=n:
                if i==n: s=sum(tr[1:n+1])/n; out[i]=s
            else: s=(s*(n-1)+tr[i])/n; out[i]=s
        return out
    atr20=atr(20); atr100=atr(100)
    ema20=ema(c,20); adx=wilder_adx(h,l,c)
    val=gm_val_series(o,h,l,c,cfg["grisk"]); sig=gm_signals(val,cfg["grisk"])
    # D1 trend
    rd=mt5.copy_rates_from_pos(sym,mt5.TIMEFRAME_D1,0,DAILY_MA+60)
    d1bull=None
    if rd is not None and len(rd)>DAILY_MA+2:
        dc=[x['close'] for x in rd]; e=ema(dc,DAILY_MA); d1bull=e[-1]>e[-2]
    db=load_db(cfg["db"])
    cutoff=datetime.now()-timedelta(days=days)
    events=[]
    for p in range(40, len(c)):
        if sig[p] is None or (sig[p]==sig[p-1]):   # new fire only
            continue
        tt=datetime.fromtimestamp(t[p])
        if tt<cutoff: continue
        dirn=sig[p]; hr=tt.hour
        an,aa=atr20[p],atr100[p]
        reg="ATR_NA" if not aa else ("ATR_EXP" if an>aa*1.3 else "ATR_COMP" if an<aa*0.7 else "ATR_NORM")
        key=f"{dirn}|{session(hr)}|{reg}"
        wr,ns=db.get(key,(0.0,0))
        ang=(ema20[p]-ema20[p-5])/(5*point) if ema20[p-5] else 0
        ang=math.degrees(math.atan(ang)); ang=ang if dirn=="BUY" else -ang
        ax=adx[p] or 0
        bull = d1bull if d1bull is not None else True
        # gate sequence (same order as the EA)
        skip=""
        insess = 9<=hr<23
        if not insess: skip="offSession"
        elif cfg["d1filter"] and ((dirn=="BUY" and not bull) or (dirn=="SELL" and bull)): skip="D1trend"
        elif not (ax>ADX_THR and abs(ang)>ANG_THR): skip=f"trendWeak~(adx{ax:.0f},ang{abs(ang):.0f})"
        elif cfg["stats_filter"] and key not in db: skip="setupUnknown"
        elif cfg["stats_filter"] and ns<cfg["min_n"]: skip=f"lowSamples(n={ns})"
        elif cfg["stats_filter"] and wr<cfg["min_wr"]: skip=f"lowWinRate({wr:.2f}<{cfg['min_wr']})"
        decision="TRADE" if skip=="" else "SKIP:"+skip
        # cross-check: did the EA open this symbol within +90 min?
        traded=any(0<=(dt-t[p])<=5400 for dt in deals_by_sym.get(sym,[]))
        events.append(dict(time=tt,sym=sym,dir=dirn,key=key,wr=wr,ns=ns,adx=ax,ang=abs(ang),
                           d1="bull" if bull else "bear",decision=decision,ea_traded="Y" if traded else "n"))
    return events

LB=40
def main():
    days=int(sys.argv[1]) if len(sys.argv)>1 and sys.argv[1].isdigit() else 10
    if not connect(): return
    # actual opening-deal times per symbol (ground truth)
    to=datetime.now()+timedelta(days=1); frm=datetime.now()-timedelta(days=days+2)
    deals=mt5.history_deals_get(frm,to) or []
    dbs=defaultdict(list)
    for d in deals:
        if d.entry==mt5.DEAL_ENTRY_IN and d.type in (mt5.DEAL_TYPE_BUY,mt5.DEAL_TYPE_SELL):
            dbs[d.symbol].append(d.time)
    allev=[]
    for sym,cfg in STREAMS.items():
        print(f"scanning {sym} (grisk {cfg['grisk']}, filter={cfg['stats_filter']})...")
        allev+=scan(sym,cfg,days,dbs)
    allev.sort(key=lambda e:e["time"])
    # write csv
    with open("gridstat_signals_recent.csv","w",newline="") as f:
        w=csv.writer(f); w.writerow(["time","symbol","dir","setup_key","winrate","n","adx~","ang~","d1","decision","ea_traded"])
        for e in allev:
            w.writerow([e["time"].strftime("%Y-%m-%d %H:%M"),e["sym"],e["dir"],e["key"],f"{e['wr']:.2f}",e["ns"],f"{e['adx']:.0f}",f"{e['ang']:.0f}",e["d1"],e["decision"],e["ea_traded"]])
    # console
    print(f"\n=== signal events, last {days}d  ({len(allev)} fires) ===")
    print(f"{'time':16}{'sym':>8}{'dir':>5}{'fingerprint':>22}{'wr':>5}{'n':>4}{'adx~':>5}{'d1':>5}  {'decision':24}{'EA?':>4}")
    for e in allev:
        print(f"{e['time']:%Y-%m-%d %H:%M}{e['sym']:>8}{e['dir']:>5}{e['key']:>22}{e['wr']:>5.2f}{e['ns']:>4}{e['adx']:>5.0f}{e['d1']:>5}  {e['decision']:24}{e['ea_traded']:>4}")
    # validation: TRADE-decisions that matched an actual EA open
    tr=[e for e in allev if e["decision"]=="TRADE"]
    matched=sum(1 for e in tr if e["ea_traded"]=="Y")
    print(f"\nVALIDATION: repro said TRADE on {len(tr)} fires; EA actually opened near {matched} of them.")
    print("(divergence = parity gap on ADX/ATR, or a gate I don't have exactly. The EA?='Y/n' column is ground truth.)")
    mt5.shutdown()

if __name__=="__main__": main()
