"""make_10k_size_cells.py -- the three SAFE-SIZE levers at $10k as zero-input cells on the runner (2026-10-11):
  GOLD HPIN12 FULL C3 = the FULL cell with MaxCompoundScale 2 -> 3 (lots 0.06 above $9k; the %-floors and the $100 target unchanged)
  OIL KP1 R20 / R15   = the deployed oil cell with RiskPctPerTrade 2.5 -> 2.0 / 1.5 (oil is the drawdown leg at $10k)
Text transforms of the runner's own cells (every anchor asserted), compiled with the runner's MetaEditor (/portable), copies in ea/."""
import io, os, re, subprocess
from datetime import date
HERE = os.path.dirname(os.path.abspath(__file__)); EXP = r"C:\MT5 Pepperstone Runner\MQL5\Experts"; ME = r"C:\MT5 Pepperstone Runner\MetaEditor64.exe"
TODAY = date.today().isoformat()

def rep1(s, old, new):
    assert s.count(old) == 1, f"anchor {old[:50]!r} found {s.count(old)}x"; return s.replace(old, new, 1)

def cell(src_name, new_name, edits, stamp_old, stamp_new):
    s = io.open(os.path.join(EXP, src_name + ".mq5"), encoding="utf-8", errors="replace").read()
    s = rep1(s, stamp_old, stamp_new)
    for old, new in edits: s = rep1(s, old, new)
    s = s.replace(f'TEST CELL {src_name}', f'TEST CELL {new_name}')
    p = os.path.join(EXP, new_name + ".mq5"); io.open(p, "w", encoding="utf-8").write(s)
    io.open(os.path.join(HERE, "ea", new_name + ".mq5"), "w", encoding="utf-8").write(s)
    log = p[:-4] + ".compile.log"
    subprocess.run(["powershell", "-NoProfile", "-Command", "Start-Process -FilePath '%s' -ArgumentList '%s' -Wait" %
                    (ME, f'/portable /compile:"{p}" /log:"{log}"'.replace("'", "''"))], timeout=300)
    res = "?"
    for enc in ("utf-16", "cp1252"):
        try:
            L = [l for l in io.open(log, encoding=enc).read().splitlines() if "Result" in l]
            if L: res = L[-1].strip(); break
        except Exception: pass
    print(f"{new_name:24s} {res}"); assert "0 errors" in res, res

cell("GOLD HPIN12 FULL", "GOLD HPIN12 FULL C3",
     [("const int MaxCompoundScale      = 2;        // cap floor(balance/CompoundingBase); 0 = uncapped  // CELL-LOCKED",
       "const int MaxCompoundScale      = 3;        // cap floor(balance/CompoundingBase); 0 = uncapped  // CELL-LOCKED (C3 size cell 2026-10-11)")],
     '#define EA_BUILD_VERSION "GS-CELL-GOLD-HPIN12-FULL-S39-2026-09-21"', f'#define EA_BUILD_VERSION "GS-CELL-GOLD-HPIN12-FULL-C3-S39-{TODAY}"')
for tag, v in (("R20", "2.0"), ("R15", "1.5")):
    cell("OIL FRZRT15KP1", f"OIL KP1 {tag}",
         [("const double RiskPctPerTrade       = 2.5;  // EXPOSED 2026-07-30",
           f"const double RiskPctPerTrade       = {v};  // {tag} size cell 2026-10-11; was 2.5 -- EXPOSED 2026-07-30")],
         '#define EA_BUILD_VERSION "OIL-FRZ-CELL-OIL-FRZRT15KP1-2026-09-18"', f'#define EA_BUILD_VERSION "OIL-FRZ-CELL-OIL-KP1-{tag}-{TODAY}"')
