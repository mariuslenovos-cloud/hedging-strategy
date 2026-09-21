#!/usr/bin/env python3
"""
make_oil_tc_cells.py -- OIL TIMECAP cells generated FROM THE LOCKED SOLID4 SOURCE (2026-08-24).

Why not gridstat_make_cells: the SOLID lineage FORKED from the master on 08-04 (UseRegimeSells/
RegimeSellMinWR live only in the fork) -- master-based cells cannot reproduce SOLID4. So the
TC cells are the deployed `Marius GridStat MT5 OIL SOLID LOCKED.mq5` verbatim, with the S32
time-cap INJECTED: a `MaxEpisodeDays` const per cell + the force-close check ahead of the
portfolio floor. TC0 (cap 0 = inert code) must reproduce the oil_solid_ctl anchor
($3,033.81 / 134tr to 2026-08-19) = injection no-harm + config fidelity in one check.
"""
import io, os, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "ea", "Marius GridStat MT5 OIL SOLID LOCKED.mq5")
TARGETS = [
    (r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\BB16F565FAAA6B23A20C26C49416FF05\MQL5\Experts",
     r"C:\Program Files\XM Global MT5\MetaEditor64.exe", []),
    (r"C:\MT5 Pepperstone Runner\MQL5\Experts",
     r"C:\MT5 Pepperstone Runner\MetaEditor64.exe", ["/portable"]),
    (r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\C54C4DDE98E7B1FB905AFE04A9333631\MQL5\Experts",
     r"C:\Program Files\Pepperstone MetaTrader 5\MetaEditor64.exe", []),
]
CELLS = {"OIL TC0": 0.0, "OIL TC7": 7.0, "OIL TC10": 10.0, "OIL TC15": 15.0}

CHECK = '''   // ---- [S32-INJECT] EPISODE TIME-CAP: realize the whole book at day N (priced smoother).
   if(MaxEpisodeDays > 0)
   {
      datetime tcOldest = 0;
      for(int tci=PositionsTotal()-1; tci>=0; tci--)
      {
         ulong tctk = PositionGetTicket(tci);
         if(tctk==0 || !PositionSelectByTicket(tctk)) continue;
         if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
         if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
         datetime tcot = (datetime)PositionGetInteger(POSITION_TIME);
         if(tcOldest == 0 || tcot < tcOldest) tcOldest = tcot;
      }
      if(tcOldest > 0 && (double)(TimeCurrent() - tcOldest) >= MaxEpisodeDays * 86400.0)
      {
         CloseEverything("EPISODE TIMECAP day " + DoubleToString((double)(TimeCurrent()-tcOldest)/86400.0,1) +
                         " book " + DoubleToString(PortfolioFloat(),2));
         g_peakBasketFloat = 0.0; g_rescueDir = -1; g_freezeDir = -1;
         return;
      }
   }

'''

def build(tag, days, src):
    out = src.replace('#define EA_BUILD_VERSION "MT5-2026-08-04-OIL-SOLID4-FWD-LOCKED"',
                      f'#define EA_BUILD_VERSION "OIL-TC-CELL-{tag.replace(" ","-")}-2026-08-24"')
    # inject the const + banner right after the build define
    anchor = f'#define EA_BUILD_VERSION "OIL-TC-CELL-{tag.replace(" ","-")}-2026-08-24"'
    out = out.replace(anchor, anchor +
        f'\nconst double MaxEpisodeDays = {days};   // [S32-INJECT] episode time-cap (0 = inert)')
    # tester rule: no signal-log pollution
    o = 'input bool UseSignalLog          = true;'
    assert out.count(o) == 1, "UseSignalLog anchor"
    out = out.replace(o, 'const bool UseSignalLog          = false;  // CELL: never pollute the shared CSV')
    # the check ahead of the portfolio floor
    floor_anchor = '   { CloseEverything("PORTFOLIO STOP"); g_peakBasketFloat=0.0; return; }'
    i = out.index(floor_anchor)
    # walk back to the start of the if() above it (2 lines up)
    j = out.rfind("   if(UseBasketStop", 0, i)
    assert j > 0, "portfolio floor if not found"
    out = out[:j] + CHECK + out[j:]
    # cell banner
    oninit = "int OnInit()\n{\n"
    assert oninit in out
    out = out.replace(oninit, oninit +
        f'   Print("OIL TIMECAP CELL {tag} -- SOLID4 LOCKED source + MaxEpisodeDays={days}");\n', 1)
    return f"//| GENERATED TC CELL {tag} from SOLID4 LOCKED -- regen via make_oil_tc_cells.py |\n" + out

def main():
    import sys
    only = set(sys.argv[1:])
    src = io.open(SRC, encoding="utf-8", errors="replace").read()
    for tag, days in CELLS.items():
        if only and tag not in only: continue
        code = build(tag, days, src)
        for expdir, metaed, extra in TARGETS:
            path = os.path.join(expdir, f"{tag}.mq5")
            io.open(path, "w", encoding="utf-8").write(code)
            log = path[:-4] + ".clog"
            extraflags = " ".join(extra)
            subprocess.run(f'"{metaed}" {extraflags} /compile:"{path}" /log:"{log}"', check=False)
            res = "?"
            for enc in ("utf-16", "cp1252"):
                try:
                    lines = [l for l in io.open(log, encoding=enc).read().splitlines() if "Result" in l]
                    if lines: res = lines[-1].strip(); break
                except Exception: continue
            print(f"{tag} [{os.path.basename(os.path.dirname(os.path.dirname(expdir)))}] {res}")
        io.open(os.path.join(HERE, "ea", f"{tag}.mq5"), "w", encoding="utf-8").write(code)

if __name__ == "__main__":
    main()
