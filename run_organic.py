"""run_organic.py -- ORGANIC compounding (2026-10-11): lots step 0.01 per $2.5k (not per $3k capped at x2) and the $-targets scale with the lots,
so the account grows continuously from $2.7k instead of earning at the 0.01 rate until $6k. Cells at TODAY's MAIN balance, Dec-01 -> today:
  g_half   GOLD HPIN12 (live cell, base 3000 cap 2, PT50 fixed)          = control
  g_org    GOLD ORG    (base 2500 cap 4, PT/RBT x LotScale)              = the organic cell
  g_org_ns GOLD ORG NS (base 2500 cap 4, PT/RBT fixed)                   = lots-only stepping (separates the two effects)"""
import io, os, sys, time
from datetime import datetime
from collections import OrderedDict
HERE=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,HERE); sys.path.insert(0,os.path.join(HERE,"factory_front"))
import rolling_retest as rr, run_frz_ab as F, cell_d_allocation as CD, pandas as pd
DEP=int(sys.argv[1]) if len(sys.argv)>1 and sys.argv[1].isdigit() else 2767
CELLS=OrderedDict([("g_half",("GOLD HPIN12","XAUUSD")),("g_org",("GOLD ORG","XAUUSD")),("g_org_ns",("GOLD ORG NS","XAUUSD"))])
OUT=os.path.join(HERE,"analysis_data",f"organic_{DEP}_{datetime.now():%Y%m%d}.txt")
def report(n): return next((p for p in rr.report_paths(f"retest_{n}_{DEP}") if os.path.exists(p)),None)
if __name__=="__main__":
    rr.WINDOW_DAYS=(datetime.now()-datetime(2025,12,1)).days+1
    if "compose" not in sys.argv:
        for n,(exp,sym) in CELLS.items():
            for a in range(8):
                rr.run_job(f"{n}_{DEP}",dict(expert=exp,symbol=sym,deposit=DEP,setlines=None))
                rp=report(n); nd=len(CD.deals(rp)) if rp else 0; print(f"  [{n}] attempt {a+1}: deals {nd}",flush=True)
                if nd>0: break
                time.sleep(45)
    lines=[f"ORGANIC COMPOUNDING -- runner paired bench, 2025-12-01 -> {datetime.now():%Y-%m-%d}, deposit {DEP}",
           f"{'cell':<10}{'net':>9}{'final':>9}{'PF':>6}{'RF':>6}{'eqDD%':>7}{'tr':>5}{'$/bday':>8}{'realDD':>8}{'lots':>12}"]
    series={}
    for n in CELLS:
        rp=report(n)
        if not rp: lines.append(f"{n:<10} NO REPORT"); continue
        s=F.parse(rp); d=CD.deals(rp); d=d[d.dir!="in"]; p=d.groupby(d.time.dt.date).net.sum(); p.index=pd.to_datetime(p.index); series[n]=p
        st=CD.stats(p); lot=sorted(set(round(x,2) for x in d.lots)); bd=len(pd.bdate_range(p.index[0],p.index[-1]))
        lines.append(f"{n:<10}{s['net'] or 0:>9,.0f}{DEP+(s['net'] or 0):>9,.0f}{s['pf'] or 0:>6.2f}{s['rf'] or 0:>6.2f}{s['eqdd'] or 0:>7.1f}{s['trades'] or 0:>5}{(s['net'] or 0)/bd:>8,.0f}{st['maxdd']:>8,.0f}{(str(min(lot))+'-'+str(max(lot))) if lot else '-':>12}")
    if series:
        idx=pd.bdate_range(min(s.index[0] for s in series.values()),max(s.index[-1] for s in series.values()))
        P=pd.DataFrame({k:v.reindex(idx).fillna(0) for k,v in series.items()}); M=P.resample("ME").sum(); M.index=M.index.strftime("%Y-%m")
        lines.append("\nmonthly net ($):"); lines.append(M.round(0).astype(int).to_string())
        lines.append("\nbalance path (end of month, $):"); lines.append((DEP+P.cumsum().resample("ME").last()).round(0).astype(int).set_axis(M.index).to_string())
    txt="\n".join(lines); print(txt); io.open(OUT,"w",encoding="utf-8").write(txt+"\n")
