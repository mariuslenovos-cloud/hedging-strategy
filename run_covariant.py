"""run_covariant.py -- covariant density test: lots AND $-levers scale with balance (see make_covariant_cells.py). 2026-10-11."""
import io, os, sys, time
from datetime import datetime
from collections import OrderedDict
HERE=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,HERE); sys.path.insert(0,os.path.join(HERE,"factory_front"))
import rolling_retest as rr, run_frz_ab as F, cell_d_allocation as CD, pandas as pd
ZB=OrderedDict(TriggerMode="2",ZLookback="24",EntryZ="2.25",UseSessionFilter="true",SessionStartHour="18",SessionEndHour="23",UseDailyTrendFilter="true",AlignEmaPeriod="200",StagedCutCooldownMin="0",UseSignalLog="false",UseCompounding="false")
CELLS=OrderedDict([
 ("gc50_10k",("GOLD COV G50 X2","XAUUSD",None,10000)),("gc50_15k",("GOLD COV G50 X3","XAUUSD",None,15000)),("gc50_20k",("GOLD COV G50 X4","XAUUSD",None,20000)),
 ("gc37_10k",("GOLD COV G37 X2","XAUUSD",None,10000)),("gc62_10k",("GOLD COV G62 X2","XAUUSD",None,10000)),   # PT neighbours of gc50_10k at 0.04 (plateau or spike?)
 ("gc50cb_10k",("GOLD COV G50 X2 CB","XAUUSD",None,10000)),   # same geometry WITH compounding (cap 2 at base 3000 = x2 already at $10k -> 0.08?) = what attaching it live would do
 ("gc25_15k",("GOLD COV G25 X3","XAUUSD",None,15000)),("gc25_20k",("GOLD COV G25 X4","XAUUSD",None,20000)),
 ("zc_10k",("Marius ZGrid MT5 v1.0","XAUUSD",dict(ZB,LotSize="0.04",ProfitTargetUSD="100.0",RescueBookTargetUSD="40.0"),10000)),
 ("zc_15k",("Marius ZGrid MT5 v1.0","XAUUSD",dict(ZB,LotSize="0.06",ProfitTargetUSD="150.0",RescueBookTargetUSD="60.0"),15000)),
 ("zc_20k",("Marius ZGrid MT5 v1.0","XAUUSD",dict(ZB,LotSize="0.08",ProfitTargetUSD="200.0",RescueBookTargetUSD="80.0"),20000)),
 ("oc_15k",("OIL KP1 X5","SpotCrude",None,15000)),("oc_20k",("OIL KP1 X67","SpotCrude",None,20000)),
])
OUT=os.path.join(HERE,"analysis_data",f"covariant_{datetime.now():%Y%m%d}.txt")
def report(n): return next((p for p in rr.report_paths(f"retest_{n}") if os.path.exists(p)),None)
if __name__=="__main__":
    rr.WINDOW_DAYS=(datetime.now()-datetime(2025,12,1)).days+1
    names=sys.argv[1:] or list(CELLS)
    if "compose" not in names:
        for n in names:
            exp,sym,setl,dep=CELLS[n]
            for a in range(8):
                rr.run_job(n,dict(expert=exp,symbol=sym,deposit=dep,setlines=[f"{k}={v}" for k,v in setl.items()] if setl else None))
                rp=report(n); nd=len(CD.deals(rp)) if rp else 0; print(f"  [{n}] attempt {a+1}: deals {nd}",flush=True)
                if nd>0: break
                time.sleep(45)
    lines=[f"COVARIANT DENSITY TABLE -- runner paired bench, 2025-12-01 -> {datetime.now():%Y-%m-%d} (lots AND $-levers scale with balance; compounding OFF)",
           f"{'cell':<10}{'deposit':>8}{'net':>9}{'%ret':>7}{'PF':>6}{'RF':>6}{'eqDD%':>7}{'tr':>5}{'$/tday':>8}{'%/day':>7}{'realDD':>8}{'lots':>12}"]
    for n in list(CELLS):
        rp=report(n)
        if not rp: lines.append(f"{n:<10} NO REPORT"); continue
        s=F.parse(rp); d=CD.deals(rp); d=d[d.dir!="in"]; dep=CELLS[n][3]
        p=d.groupby(d.time.dt.date).net.sum(); p.index=pd.to_datetime(p.index); td=max(len(p),1); st=CD.stats(p); lot=sorted(set(round(x,2) for x in d.lots))
        lines.append(f"{n:<10}{dep:>8}{s['net'] or 0:>9,.0f}{100*(s['net'] or 0)/dep:>7.0f}{s['pf'] or 0:>6.2f}{s['rf'] or 0:>6.2f}{s['eqdd'] or 0:>7.1f}{s['trades'] or 0:>5}{(s['net'] or 0)/td:>8,.0f}{100*(s['net'] or 0)/td/dep:>7.2f}{st['maxdd']:>8,.0f}{(str(min(lot))+'-'+str(max(lot))) if lot else '-':>12}")
    txt="\n".join(lines); print(txt); io.open(OUT,"w",encoding="utf-8").write(txt+"\n")
