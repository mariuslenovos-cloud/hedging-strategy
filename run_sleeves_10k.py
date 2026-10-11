"""run_sleeves_10k.py -- the three capital-map sleeves priced AT $10k on the runner (2026-10-11, user: "lets look at the following").
  SessionDrift GOLD (the Asia-hours drift family's built member): FixedLots 0.04 (= 0.01 per $2.5k) long-only and with the
     give-back short 16->20 (the 10-09 best cell); clock-exit engine = runner is a valid bench (08-23: runner-demo ~1%).
  fib C SR6 on a $2,500 sub-account slice (the 25% doctrine); grid = generated ticks -> paired reading only.
  ON-4 overnight index premium on US500 and NAS100, NotionalPct 50, deposit 10000 (brief #1 downgraded it; price it anyway).
Each is composed against the $10k book in book_10k_daily_<date>.csv afterwards."""
import io, os, sys, time
from datetime import datetime
from collections import OrderedDict
HERE=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,HERE); sys.path.insert(0,os.path.join(HERE,"factory_front"))
import rolling_retest as rr, run_frz_ab as F, cell_d_allocation as CD, pandas as pd
SD=OrderedDict(EntryHour="1",ExitHour="4",UseGiveBackShort="false",ShortEntryHour="16",ShortExitHour="20",FixedLots="0.04",RiskPctPerTrade="2.0",StopATRMult="1.5",TargetATRMult="0.0",ATRPeriod="14",MaxLots="5.0",MagicNumber="88231")
CELLS=OrderedDict([
 ("sd10k_long",("Marius SessionDrift GOLD","XAUUSD",SD,10000)),
 ("sd10k_gb20",("Marius SessionDrift GOLD","XAUUSD",dict(SD,UseGiveBackShort="true"),10000)),
 ("fibc_2500",("FIBC SR6","XAUUSD",None,2500)),
 ("on4_us500",("Marius Overnight ON4 v1.0","US500",OrderedDict(NotionalPct="50.0",MaxSpreadBp="5.0",SkipFridayEntry="false",UseTradeLog="false"),10000)),
 ("on4_nas100",("Marius Overnight ON4 v1.0","NAS100",OrderedDict(NotionalPct="50.0",MaxSpreadBp="5.0",SkipFridayEntry="false",UseTradeLog="false"),10000)),
])
OUT=os.path.join(HERE,"analysis_data",f"sleeves_10k_{datetime.now():%Y%m%d}.txt")
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
    lines=[f"SLEEVES AT $10k -- runner paired bench, 2025-12-01 -> {datetime.now():%Y-%m-%d}",
           f"{'cell':<12}{'deposit':>8}{'net':>9}{'PF':>6}{'RF':>6}{'eqDD%':>7}{'tr':>5}{'$/tday':>8}{'realDD':>8}{'worst d':>8}"]
    series={}
    for n in list(CELLS):
        rp=report(n)
        if not rp: lines.append(f"{n:<12} NO REPORT"); continue
        s=F.parse(rp); d=CD.deals(rp); d=d[d.dir!="in"]; dep=CELLS[n][3]
        p=d.groupby(d.time.dt.date).net.sum(); p.index=pd.to_datetime(p.index); st=CD.stats(p); series[n]=p
        lines.append(f"{n:<12}{dep:>8}{s['net'] or 0:>9,.0f}{s['pf'] or 0:>6.2f}{s['rf'] or 0:>6.2f}{s['eqdd'] or 0:>7.1f}{s['trades'] or 0:>5}{st['net']/max(len(p),1):>8,.0f}{st['maxdd']:>8,.0f}{st['worst']:>8,.0f}")
    # compose with the $10k book (latest daily csv)
    import glob
    bk=sorted(glob.glob(os.path.join(HERE,"analysis_data","book_10k_daily_*.csv")))[-1]
    B=pd.read_csv(bk,index_col=0,parse_dates=True); book=B["g10k_full"]+B["z10k_lot02"]+B["o10k_kp1"]
    idx=pd.bdate_range(min(book.index[0],*[s.index[0] for s in series.values()]),max(book.index[-1],*[s.index[-1] for s in series.values()]))
    P=pd.DataFrame({"book":book.reindex(idx).fillna(0.0),**{k:v.reindex(idx).fillna(0.0) for k,v in series.items()}})
    lines.append("\ncorrelation with the $10k book (gold FULL + ZGrid + oil):"); lines.append(P.corr().round(2)["book"].to_string())
    lines.append(f"\n{'composition':<40}{'net':>9}{'realDD':>8}{'RF':>7}{'$/tday':>8}{'worst d':>9}{'pain':>8}")
    st=CD.stats(P.book); lines.append(f"{'book':<40}{st['net']:>9,.0f}{st['maxdd']:>8,.0f}{st['rf']:>7.2f}{st['net']/len(idx):>8,.0f}{st['worst']:>9,.0f}{CD.pain_sum(P.book):>8,.0f}")
    for add in [["sd10k_gb20"],["sd10k_long"],["fibc_2500"],["on4_us500","on4_nas100"],["sd10k_gb20","fibc_2500"],["sd10k_gb20","fibc_2500","on4_us500","on4_nas100"]]:
        if not all(a in P for a in add): continue
        p=P.book+sum(P[a] for a in add); st=CD.stats(p)
        lines.append(f"{'book+'+'+'.join(add):<40}{st['net']:>9,.0f}{st['maxdd']:>8,.0f}{st['rf']:>7.2f}{st['net']/len(idx):>8,.0f}{st['worst']:>9,.0f}{CD.pain_sum(p):>8,.0f}")
    txt="\n".join(lines); print(txt); io.open(OUT,"w",encoding="utf-8").write(txt+"\n")
