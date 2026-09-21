#!/usr/bin/env python3
"""
make_oil_rmb_cells.py -- OIL RESCUE-PILE-IN cells from the LOCKED SOLID4 source (2026-08-27).

User's lever (2026-08-27, watching the first live RSQ2 episode flip the book net-LONG):
"an option is to limit the amount of trades on a freeze". The live specimen: the book crossed
-2% -> OPPOSITE-WHEN-DEEP opened FIVE rescue BUY baskets (RescueMaxBaskets=3 grants 3 slots
beyond MaxConcurrentBaskets=3 = up to 6 open), flipping a -0.25 short book into +0.69 net long
into a confirmed crash-state DOWN regime.

`RescueMaxBaskets` is an EXISTING const in the locked source -- no build needed, only a value
swap per cell. RMB3 = the deployed config = the CONTROL and MUST reproduce the SOLID4 anchor
character ([[validate-pipeline-against-known-anchor]]).

Note the two readings of "limit trades on a freeze":
  (a) cap the rescue pile-in BEFORE the freeze arms  <- THIS sweep (live lever, untested)
  (b) trades WHILE frozen -> already zero on every deployed oil EA (FreezeAllowEntries=false)
"""
import io, os, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "ea", "Marius GridStat MT5 OIL SOLID LOCKED.mq5")
TARGETS = [
    (r"C:\MT5 Pepperstone Runner\MQL5\Experts",
     r"C:\MT5 Pepperstone Runner\MetaEditor64.exe", ["/portable"]),
    (r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\C54C4DDE98E7B1FB905AFE04A9333631\MQL5\Experts",
     r"C:\Program Files\Pepperstone MetaTrader 5\MetaEditor64.exe", []),
]
CELLS = {"OIL RMB0": 0, "OIL RMB1": 1, "OIL RMB2": 2, "OIL RMB3": 3}  # RMB3 = deployed control

OLD_BUILD = '#define EA_BUILD_VERSION "MT5-2026-08-04-OIL-SOLID4-FWD-LOCKED"'


def build(tag, n, src):
    out = src.replace(OLD_BUILD, f'#define EA_BUILD_VERSION "OIL-RMB-CELL-{tag.replace(" ", "-")}-2026-08-27"')

    # the only value that changes between cells
    old = "const int RescueMaxBaskets      = 3;"
    assert src.count(old) == 1, "RescueMaxBaskets anchor"
    out = out.replace(old, f"const int RescueMaxBaskets      = {n};   // [RMB-CELL] rescue pile-in cap")

    # tester rule: never pollute the shared signal CSV
    o = "input bool UseSignalLog          = true;"
    assert out.count(o) == 1, "UseSignalLog anchor"
    out = out.replace(o, "const bool UseSignalLog          = false;  // CELL: never pollute the shared CSV")

    oninit = "int OnInit()\n{\n"
    assert oninit in out
    out = out.replace(oninit, oninit +
                      f'   Print("OIL RESCUE-CAP CELL {tag} -- SOLID4 LOCKED source + RescueMaxBaskets={n}");\n', 1)
    return f"//| GENERATED RMB CELL {tag} from SOLID4 LOCKED -- regen via make_oil_rmb_cells.py |\n" + out


def main():
    import sys
    only = set(sys.argv[1:])
    src = io.open(SRC, encoding="utf-8", errors="replace").read()
    for tag, n in CELLS.items():
        if only and tag not in only:
            continue
        code = build(tag, n, src)
        for expdir, metaed, extra in TARGETS:
            path = os.path.join(expdir, f"{tag}.mq5")
            io.open(path, "w", encoding="utf-8").write(code)
            log = path[:-4] + ".clog"
            subprocess.run(f'"{metaed}" {" ".join(extra)} /compile:"{path}" /log:"{log}"', check=False)
            res = "?"
            for enc in ("utf-16", "cp1252"):
                try:
                    lines = [l for l in io.open(log, encoding=enc).read().splitlines() if "Result" in l]
                    if lines:
                        res = lines[-1].strip()
                        break
                except Exception:
                    continue
            print(f"{tag:10s} [{expdir.split(chr(92))[2][:14]}] {res}")
        io.open(os.path.join(HERE, "ea", f"{tag}.mq5"), "w", encoding="utf-8").write(code)


if __name__ == "__main__":
    main()
