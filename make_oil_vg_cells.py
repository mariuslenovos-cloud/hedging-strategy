#!/usr/bin/env python3
"""
make_oil_vg_cells.py -- OIL VELOCITY-GUARD cells injected into the LOCKED SOLID4 source (2026-09-04).
Same pattern as make_oil_tc_cells.py (the SOLID lineage is a fork; master cells cannot reproduce it).
Gate = S38's rule ported: no NEW basket start while |price / D1 close N bars back - 1| >= pct.
Oil's own percentiles (live D1, 400d): 3d p80 5.7 / p90 8.4 / p95 12.0 ; 5d p80 8.0 / p90 11.0 / p95 13.2.
  OIL VG0    pct 0  = inert control (must reproduce the SOLID4 anchors)
  OIL VG6-3  3d 6%  (~p80: catches the 09-03 buy +6.1%/3d)
  OIL VG8-3  3d 8%  (~p90: catches the 08-05 crash sells -12.6%/3d, not 09-03)
  OIL VG11-5 5d 11% (~p90 on the 5-day window)
Applies to ALL new starts incl. regime sells (VelocityGuardRegimeSells=true) -- the Aug-5 regime sells
into the crash ARE the target class; a variant can exempt them later.
"""
import io, os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "ea", "Marius GridStat MT5 OIL SOLID LOCKED.mq5")
TARGETS = [
    (r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\BB16F565FAAA6B23A20C26C49416FF05\MQL5\Experts", r"C:\Program Files\XM Global MT5\MetaEditor64.exe", ""),
    (r"C:\MT5 Pepperstone Runner\MQL5\Experts", r"C:\MT5 Pepperstone Runner\MetaEditor64.exe", "/portable "),
    (r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\C54C4DDE98E7B1FB905AFE04A9333631\MQL5\Experts", r"C:\MT5 Pepperstone Instance 2\MetaEditor64.exe", ""),
]
CELLS = {"OIL VG0": (0.0, 3), "OIL VG6-3": (6.0, 3), "OIL VG8-3": (8.0, 3), "OIL VG11-5": (11.0, 5)}
CHECK = '''   if(skip=="" && !rescue && VelocityGuardPct > 0 && (VelocityGuardRegimeSells || !regimeSell))   // [S38-INJECT] sit out the storm
   {
      double vgC[];
      if(CopyClose(_Symbol, PERIOD_D1, VelocityGuardDays, 1, vgC)==1 && vgC[0] > 0)
      {
         double vgVel = (SymbolInfoDouble(_Symbol, SYMBOL_BID)/vgC[0] - 1.0)*100.0;
         if(MathAbs(vgVel) >= VelocityGuardPct) skip = "velocity("+DoubleToString(vgVel,1)+"%/"+IntegerToString(VelocityGuardDays)+"d)";
      }
   }
'''
def build(tag, pct, days, src):
    stamp = f'OIL-VG-CELL-{tag.replace(" ","-")}-2026-09-04'
    out = src.replace('#define EA_BUILD_VERSION "MT5-2026-08-04-OIL-SOLID4-FWD-LOCKED"', f'#define EA_BUILD_VERSION "{stamp}"')
    out = out.replace(f'#define EA_BUILD_VERSION "{stamp}"', f'#define EA_BUILD_VERSION "{stamp}"\n'
        f'const double VelocityGuardPct = {pct};   // [S38-INJECT] 0 = inert\nconst int VelocityGuardDays = {days};\nconst bool VelocityGuardRegimeSells = true;')
    o = 'input bool UseSignalLog          = true;'
    assert out.count(o) == 1, "UseSignalLog anchor"
    out = out.replace(o, 'const bool UseSignalLog          = false;  // CELL: never pollute the shared CSV')
    a = '   if(skip=="" && !rescue && IsOverextended()) skip = "overextended";\n'
    assert out.count(a) == 1, "overextended anchor"
    out = out.replace(a, a + CHECK)
    oninit = "int OnInit()\n{\n"; assert oninit in out
    out = out.replace(oninit, oninit + f'   Print("OIL VELOCITY CELL {tag} -- SOLID4 LOCKED source + VelocityGuardPct={pct} days={days}");\n', 1)
    return f"//| GENERATED VG CELL {tag} from SOLID4 LOCKED -- regen via make_oil_vg_cells.py |\n" + out
def main():
    only = set(sys.argv[1:])
    src = io.open(SRC, encoding="utf-8", errors="replace").read()
    for tag, (pct, days) in CELLS.items():
        if only and tag not in only: continue
        body = build(tag, pct, days, src)
        io.open(os.path.join(HERE, "ea", tag + ".mq5"), "w", encoding="utf-8").write(body)
        for exp, me, extra in TARGETS:
            p = os.path.join(exp, tag + ".mq5"); io.open(p, "w", encoding="utf-8").write(body); log = p[:-4] + "_compile.log"
            subprocess.run(f'"{me}" {extra}/compile:"{p}" /log:"{log}"', check=False)
            res = "?"
            for enc in ("utf-16", "cp1252"):
                try:
                    L = [l for l in io.open(log, encoding=enc).read().splitlines() if "Result" in l]
                    if L: res = L[-1].strip(); break
                except Exception: pass
            print(f"{tag:11s} {os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(exp)))) if 'Terminal' in exp else exp[:22]:32s} {res}")
if __name__ == "__main__":
    main()
