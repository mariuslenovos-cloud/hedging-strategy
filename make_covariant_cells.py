"""make_covariant_cells.py -- the COVARIANT density cells (2026-10-11): lots AND dollar levers scale together with balance.
run_density.py showed lots-only scaling de-tunes the machine (gold 0.08 lots / PT100 at $20k = $1,674, eqDD 30%; capped = a plateau).
The validated transform is covariant (HALF 0.01/PT50/RBT20 <-> FULL 0.02/PT100/RBT40 = the same geometry per lot). Cells, compounding OFF
so the lots are exact:  G50 geometry ($50 per 0.01): 10k 0.04/200/80 · 15k 0.06/300/120 · 20k 0.08/400/160
                       G25 geometry ($25 per 0.01 = what the capped FULL cell actually runs at $10k): 15k 0.06/150/60 · 20k 0.08/200/80
                       OIL KP1 with PT/RBT scaled by balance/3000: X5 (15k) PT500/RBT250 · X67 (20k) PT667/RBT333."""
import io, os, subprocess
from datetime import date
HERE=os.path.dirname(os.path.abspath(__file__)); EXP=r"C:\MT5 Pepperstone Runner\MQL5\Experts"; ME=r"C:\MT5 Pepperstone Runner\MetaEditor64.exe"; TODAY=date.today().isoformat()
def rep1(s,o,n):
    assert s.count(o)==1,(o[:60],s.count(o)); return s.replace(o,n,1)
def compile_(p):
    log=p[:-4]+".compile.log"
    subprocess.run(["powershell","-NoProfile","-Command","Start-Process -FilePath '%s' -ArgumentList '%s' -Wait"%(ME,f'/portable /compile:"{p}" /log:"{log}"'.replace("'","''"))],timeout=300)
    L=[l for l in io.open(log,encoding="utf-16",errors="ignore").read().splitlines() if "Result" in l]; r=L[-1] if L else "NO RESULT"
    print(f"{os.path.basename(p):28s} {r}"); assert "0 errors" in r, r
gsrc=io.open(os.path.join(EXP,"GOLD HPIN12 FULL.mq5"),encoding="utf-8",errors="replace").read()
for name,lot,pt,rbt in [("GOLD COV G50 X2","0.04","200.0","80.0"),("GOLD COV G50 X3","0.06","300.0","120.0"),("GOLD COV G50 X4","0.08","400.0","160.0"),
                        ("GOLD COV G25 X3","0.06","150.0","60.0"),("GOLD COV G25 X4","0.08","200.0","80.0")]:
    s=rep1(gsrc,'#define EA_BUILD_VERSION "GS-CELL-GOLD-HPIN12-FULL-S39-2026-09-21"',f'#define EA_BUILD_VERSION "GS-CELL-{name.replace(" ","-")}-S39-{TODAY}"')
    s=rep1(s,"const double LotSize               = 0.02;  // CELL-LOCKED",f"const double LotSize               = {lot};  // COVARIANT cell")
    s=rep1(s,"const bool UseCompounding        = true;  // CELL-LOCKED","const bool UseCompounding        = false;  // COVARIANT cell: exact lots")
    s=rep1(s,"const double ProfitTargetUSD       = 100.0;   // basket recovery escape + single-position $ cap  // CELL-LOCKED",f"const double ProfitTargetUSD       = {pt};   // COVARIANT cell")
    s=rep1(s,"const double RescueBookTargetUSD   = 40.0;     // close the whole book at +this while rescued (0 = off)  // CELL-LOCKED",f"const double RescueBookTargetUSD   = {rbt};     // COVARIANT cell")
    s=s.replace("TEST CELL GOLD HPIN12 FULL",f"TEST CELL {name}")
    p=os.path.join(EXP,name+".mq5"); io.open(p,"w",encoding="utf-8").write(s); io.open(os.path.join(HERE,"ea",name+".mq5"),"w",encoding="utf-8").write(s); compile_(p)
osrc=io.open(os.path.join(EXP,"OIL FRZRT15KP1.mq5"),encoding="utf-8",errors="replace").read()
for name,pt,rbt in [("OIL KP1 X5","500.0","250.0"),("OIL KP1 X67","667.0","333.0")]:
    s=rep1(osrc,'#define EA_BUILD_VERSION "OIL-FRZ-CELL-OIL-FRZRT15KP1-2026-09-18"',f'#define EA_BUILD_VERSION "OIL-FRZ-CELL-{name.replace(" ","-")}-{TODAY}"')
    s=rep1(s,"const double ProfitTargetUSD       = 100.0;   // basket recovery escape + single-position $ cap  // LOCKED (was input)",f"const double ProfitTargetUSD       = {pt};   // COVARIANT cell (balance/3000 x 100)")
    s=rep1(s,"const double RescueBookTargetUSD   = 50.0;     // close the whole book at +this while rescued/frozen (0 = off)  // FWD-LOCKED (was input)",f"const double RescueBookTargetUSD   = {rbt};     // COVARIANT cell")
    p=os.path.join(EXP,name+".mq5"); io.open(p,"w",encoding="utf-8").write(s); io.open(os.path.join(HERE,"ea",name+".mq5"),"w",encoding="utf-8").write(s); compile_(p)
