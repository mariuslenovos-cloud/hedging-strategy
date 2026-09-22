#!/usr/bin/env python3
"""
make_frzrt15_locked.py -- regenerate the INERT deploy file
    `Marius GridStat MT5 OIL SOLID LOCKED FRZRT15.mq5`
from the SOLID4 LOCKED source via make_oil_frz_cells.build(), then apply the three deploy edits
(deploy stamp, UseSignalLog back to an INPUT defaulting true so the monitors keep reading it,
deploy banner) and compile it on every terminal with THAT terminal's MetaEditor.

The file is a NEW NAME -> compiling it never hot-reloads the running `OIL SOLID LOCKED` charts
(standing item 2026-09-21: never recompile the running oil EA while a book is open). It stays
inert until dragged over a SpotCrude chart on a FLAT day; magic 77180 auto-derives.

usage:  python make_frzrt15_locked.py [--keep 0|1|2]
    --keep 1 = FreezeKeepMode 1 (rebalance the _FRZ legs as covered legs close) -- the 2026-09-22
               fix for the broker-TP leak that broke the demo's freeze (Bug Log 2026-09-22).
    --keep 2 = strip broker TPs off every non-_FRZ leg at arm.
    --keep 0 = the 2026-09-21 FRZRT15 build verbatim (no keep lever).
"""
import io, os, subprocess, sys
from datetime import date
import make_oil_frz_cells as M

HERE = os.path.dirname(os.path.abspath(__file__))
BASENAME = "Marius GridStat MT5 OIL SOLID LOCKED FRZRT15"
TERMDATA = r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal"
TARGETS = [
    ("MAIN 73B7A242", TERMDATA + r"\73B7A2420D6397DFF9014A20F1201F97\MQL5\Experts",
     r"C:\Program Files\Pepperstone MetaTrader 5\MetaEditor64.exe", []),
    ("DEON 942C8C7E", TERMDATA + r"\942C8C7E5F6C67C7F9D9D82245E68176\MQL5\Experts",
     r"C:\MT5 Pepperstone Instance Deon\MetaEditor64.exe", []),
    ("DEMO C54C4DDE", TERMDATA + r"\C54C4DDE98E7B1FB905AFE04A9333631\MQL5\Experts",
     r"C:\MT5 Pepperstone Instance 2\MetaEditor64.exe", []),
    ("RUNNER", r"C:\MT5 Pepperstone Runner\MQL5\Experts",
     r"C:\MT5 Pepperstone Runner\MetaEditor64.exe", ["/portable"]),
]


def main():
    keep = 0
    if "--keep" in sys.argv:
        keep = int(sys.argv[sys.argv.index("--keep") + 1])
    NAME = BASENAME + ("KP%d" % keep if keep else "")   # keep-mode builds get their OWN inert filename
    src = io.open(M.SRC, encoding="utf-8", errors="replace").read()
    # disarm=True, capBE=False, trail=0, cooldown=0, retrace=1.5, park=False = FRZRT15
    code = M.build("OIL FRZRT15", True, False, 0.0, 0, 1.5, False, src, keep)

    today = date.today().isoformat()
    stamp = f"MT5-{today}-OIL-SOLID4-FRZRT15{'-KP%d' % keep if keep else ''}-LOCKED"
    old = '#define EA_BUILD_VERSION "OIL-FRZ-CELL-OIL-FRZRT15-2026-09-18"'
    assert code.count(old) == 1, "cell stamp anchor"
    code = code.replace(old, f'#define EA_BUILD_VERSION "{stamp}"')

    old = "const bool UseSignalLog          = false;  // CELL: never pollute the shared CSV"
    assert code.count(old) == 1, "UseSignalLog anchor"
    code = code.replace(old, "input bool UseSignalLog          = true;")

    old = f'   Print("OIL FREEZE CELL OIL FRZRT15 -- SOLID4 LOCKED + disarm=true capBE=false trail=0.0% keep={keep}");'
    assert code.count(old) == 1, "banner anchor"
    what = {0: "stuck-freeze fix + trailing post-floor gate",
            1: "stuck-freeze fix + trailing post-floor gate + KEEP 1:1 (rebalance _FRZ as covered legs close)",
            2: "stuck-freeze fix + trailing post-floor gate + strip broker TPs at arm"}[keep]
    code = code.replace(old, f'   Print("OIL SOLID4 LOCKED + FRZRT15 ({what}) -- SOLID4 LOCKED + disarm=true capBE=false trail=0.0% keep={keep}");')
    code = code.replace("//| GENERATED FRZ CELL OIL FRZRT15 from SOLID4 LOCKED -- regen via make_oil_frz_cells.py |",
                        "//| DEPLOY FILE: SOLID4 LOCKED + FRZRT15 -- regen via make_frzrt15_locked.py --keep N |", 1)

    io.open(os.path.join(HERE, "ea", NAME + ".mq5"), "w", encoding="utf-8").write(code)
    print("stamp:", stamp)
    for label, expdir, metaed, extra in TARGETS:
        if not os.path.isdir(expdir):
            print(f"{label:<14} SKIP (no Experts dir)"); continue
        path = os.path.join(expdir, NAME + ".mq5")
        io.open(path, "w", encoding="utf-8").write(code)
        log = path[:-4] + ".clog"
        subprocess.run(f'"{metaed}" {" ".join(extra)} /compile:"{path}" /log:"{log}"', check=False)
        res = "?"
        for enc in ("utf-16", "cp1252"):
            try:
                lines = [l for l in io.open(log, encoding=enc).read().splitlines() if "Result" in l]
                if lines:
                    res = lines[-1].strip(); break
            except Exception:
                continue
        print(f"{label:<14} {res}")


if __name__ == "__main__":
    main()
