"""OIL NDB cells (2026-09-22): the trade-mode A/B the 09-01/09-07 refreshes said was required and never ran.
NDB0 = deployed tables (control, must reproduce oil_solid_ctl $3,033.81/134tr) · NDB1 = fresh setups + raw rigor sizing
· NDB2 = fresh setups + rigor sizing with the standing sells-zeroed override. Injected into the LOCKED SOLID4 source."""
import io, os, subprocess, sys
HERE=os.path.dirname(os.path.abspath(__file__)); SRC=os.path.join(HERE,"ea","Marius GridStat MT5 OIL SOLID LOCKED.mq5")
TARGETS=[(r"C:\MT5 Pepperstone Runner\MQL5\Experts", r"C:\MT5 Pepperstone Runner\MetaEditor64.exe","/portable"),
         (r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\C54C4DDE98E7B1FB905AFE04A9333631\MQL5\Experts", r"C:\Program Files\Pepperstone MetaTrader 5\MetaEditor64.exe","")]
CELLS={"OIL NDB0":("gridstat_setups_oil_research.csv","gridstat_sizing_oil_research.csv"),
       "OIL NDB1":("gridstat_setups_oil_ndb.csv","gridstat_sizing_oil_ndb_raw.csv"),
       "OIL NDB2":("gridstat_setups_oil_ndb.csv","gridstat_sizing_oil_ndb_ovr.csv")}
def build(tag, setups, sizing, src):
    out=src.replace('#define EA_BUILD_VERSION "MT5-2026-08-04-OIL-SOLID4-FWD-LOCKED"', f'#define EA_BUILD_VERSION "OIL-NDB-CELL-{tag.split()[-1]}-2026-09-22"')
    a='const string StatsCSVFile        = "gridstat_setups_oil_research.csv";'; assert out.count(a)==1
    out=out.replace(a, f'const string StatsCSVFile        = "{setups}";')
    b='const string SizingCSVFile         = "gridstat_sizing_oil_research.csv";'; assert out.count(b)==1
    out=out.replace(b, f'const string SizingCSVFile         = "{sizing}";')
    o='input bool UseSignalLog          = true;'; assert out.count(o)==1
    out=out.replace(o,'const bool UseSignalLog          = false;  // CELL')
    oi="int OnInit()\n{\n"; assert oi in out
    out=out.replace(oi, oi+f'   Print("OIL NDB CELL {tag} -- setups={setups} sizing={sizing}");\n',1)
    return out
src=io.open(SRC,encoding="utf-8",errors="replace").read()
for tag,(st,sz) in CELLS.items():
    if sys.argv[1:] and tag not in sys.argv[1:]: continue
    code=build(tag,st,sz,src)
    for expdir,me,extra in TARGETS:
        p=os.path.join(expdir,tag+".mq5"); io.open(p,"w",encoding="utf-8").write(code); log=p[:-4]+".clog"
        subprocess.run(f'"{me}" {extra} /compile:"{p}" /log:"{log}"',check=False)
        r=[l for l in io.open(log,encoding="utf-16",errors="replace").read().splitlines() if "Result" in l]; print(tag, r[-1].strip() if r else "?")
    io.open(os.path.join(HERE,"ea",tag+".mq5"),"w",encoding="utf-8").write(code)
