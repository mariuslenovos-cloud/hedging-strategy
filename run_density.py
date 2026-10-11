"""run_density.py -- does income scale with BALANCE when lots track balance at the validated density? (2026-10-11, user: "$100/day on $10k is not investment sense")
Cells: GOLD HPIN12 FULL (cap 2 = lots stop at 0.04 above $6k) vs GOLD HPIN12 FULL B5 (CompoundingBase 5000, uncapped = 0.02 per $5k, the 08-26 density),
and ZGrid at the demo preset with base 5000 uncapped -- each at deposits 10k / 15k / 20k. Oil is risk-normed and scales by itself.
Judge: $/day and eqDD% per deposit. A density that holds = same eqDD% at every deposit with net proportional to deposit."""
import io, os, sys, time
from datetime import datetime
from collections import OrderedDict
HERE=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,HERE); sys.path.insert(0,os.path.join(HERE,"factory_front"))
import rolling_retest as rr, run_frz_ab as F, cell_d_allocation as CD, pandas as pd
ZB=OrderedDict(TriggerMode="2",ZLookback="24",EntryZ="2.25",UseSessionFilter="true",SessionStartHour="18",SessionEndHour="23",UseDailyTrendFilter="true",AlignEmaPeriod="200",StagedCutCooldownMin="0",UseSignalLog="false",LotSize="0.02",ProfitTargetUSD="100.0",RescueBookTargetUSD="40.0")
CELLS=OrderedDict([
 ("gcap2_15k",("GOLD HPIN12 FULL","XAUUSD",None,15000)),("gcap2_20k",("GOLD HPIN12 FULL","XAUUSD",None,20000)),
 ("gb5_10k",("GOLD HPIN12 FULL B5","XAUUSD",None,10000)),("gb5_15k",("GOLD HPIN12 FULL B5","XAUUSD",None,15000)),("gb5_20k",("GOLD HPIN12 FULL B5","XAUUSD",None,20000)),
 ("zb5_10k",("Marius ZGrid MT5 v1.0","XAUUSD",dict(ZB,CompoundingBase="5000.0",MaxCompoundScale="0"),10000)),
 ("zb5_15k",("Marius ZGrid MT5 v1.0","XAUUSD",dict(ZB,CompoundingBase="5000.0",MaxCompoundScale="0"),15000)),
 ("zb5_20k",("Marius ZGrid MT5 v1.0","XAUUSD",dict(ZB,CompoundingBase="5000.0",MaxCompoundScale="0"),20000)),
 ("o_15k",("OIL FRZRT15KP1","SpotCrude",None,15000)),("o_20k",("OIL FRZRT15KP1","SpotCrude",None,20000)),
])
OUT=os.path.join(HERE,"analysis_data",f"density_{datetime.now():%Y%m%d}.txt")
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
    lines=[f"DENSITY TABLE -- runner paired bench, 2025-12-01 -> {datetime.now():%Y-%m-%d} (generated ticks before 08-28)",
           f"{'cell':<12}{'deposit':>8}{'net':>9}{'%ret':>7}{'PF':>6}{'RF':>6}{'eqDD%':>7}{'tr':>5}{'$/tday':>8}{'%/day':>7}{'lots':>12}"]
    for n in list(CELLS):
        rp=report(n)
        if not rp: lines.append(f"{n:<12} NO REPORT"); continue
        s=F.parse(rp); d=CD.deals(rp); d=d[d.dir!="in"]; dep=CELLS[n][3]
        p=d.groupby(d.time.dt.date).net.sum(); td=max(len(p),1); lot=sorted(set(round(x,2) for x in d.lots))
        lines.append(f"{n:<12}{dep:>8}{s['net']:>9,.0f}{100*s['net']/dep:>7.0f}{s['pf'] or 0:>6.2f}{s['rf'] or 0:>6.2f}{s['eqdd'] or 0:>7.1f}{s['trades'] or 0:>5}{s['net']/td:>8,.0f}{100*s['net']/td/dep:>7.2f}{(str(min(lot))+'-'+str(max(lot))) if lot else '-':>12}")
    txt="\n".join(lines); print(txt); io.open(OUT,"w",encoding="utf-8").write(txt+"\n")
