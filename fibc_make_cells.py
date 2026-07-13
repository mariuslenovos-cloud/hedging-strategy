#!/usr/bin/env python3
"""
fibc_make_cells.py -- generate ONE-SHOT fib C test EAs (2026-07-13).

User pain: the MT5 tester persists stale inputs and set files are unreliable ->
hand-checking 70 rows per cell. Fix: each sweep cell becomes its own EA with
the ENTIRE config hard-coded (const, zero visible inputs). Pick the Expert in
the tester dropdown, press Start. The report's Inputs section will be EMPTY --
nothing can leak.

Base config = the fib C master's source defaults, which are byte-identical to
the LIVE chart config (verified against the user's screenshots 2026-07-13).

Cells (fib C trade-frequency experiment; funnel evidence in CLAUDE.md 07-13):
  F1  baseline (live config verbatim)          -- the reference
  F2  D1 trend filter OFF                      -- hedge replaces D1 protection
  F3  gate sell threshold 0.65 -> 0.55         -- wake the sell side
  F4  F2 + F3                                  -- deadlock fully broken
  F2A F2 + ADX 15                              -- funnel-top widened
  F4A F4 + ADX 15
"""
import io, os, re, subprocess

EXPERTS = r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\BB16F565FAAA6B23A20C26C49416FF05\MQL5\Experts"
MASTER  = os.path.join(EXPERTS, "Marius Hedger M5 fib C MT5 v1.0.mq5")
METAED  = r"C:\Program Files\XM Global MT5\MetaEditor64.exe"
EA_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ea")

CELLS = {
    "F1":  {},
    "F2":  {"UseDailyTrendFilter": "false"},
    "F3":  {"FirstGateSellMinWinRate": "0.55"},
    "F4":  {"UseDailyTrendFilter": "false", "FirstGateSellMinWinRate": "0.55"},
    "F2A": {"UseDailyTrendFilter": "false", "ADX_Threshold": "15.0"},
    "F4A": {"UseDailyTrendFilter": "false", "FirstGateSellMinWinRate": "0.55",
            "ADX_Threshold": "15.0"},
}
INPUT_RE = re.compile(r"^input\s+(\w+)\s+(\w+)(\s*)=\s*([^;]+);(.*)$")

def transform(src, tag, values):
    out, seen = [], set()
    for ln in src.splitlines():
        m = INPUT_RE.match(ln)
        if m:
            typ, name, pad, default, tail = m.groups()
            val = values.get(name, default.strip())
            seen.add(name)
            out.append(f"const {typ} {name}{pad}= {val};{tail}  // CELL-LOCKED")
            continue
        if ln.startswith('#define BUILD'):
            out.append(f'#define BUILD "FIBC-CELL-{tag}-2026-07-13"')
            continue
        out.append(ln)
    missing = set(values) - seen
    if missing: raise SystemExit(f"{tag}: unknown inputs {missing}")
    src2 = "\n".join(out)
    anchor = "int OnInit()\n{\n"
    guard = (f'\n   Print("FIBC TEST CELL {tag} -- zero-input build; deltas: '
             + (", ".join(f"{k}={v}" for k, v in values.items()) or "none (baseline)")
             + '");\n')
    if anchor not in src2: raise SystemExit(f"{tag}: OnInit anchor missing")
    src2 = src2.replace(anchor, anchor + guard, 1)
    hdr = (f"//| GENERATED TEST CELL {tag} -- do not edit; regen via fibc_make_cells.py |\n")
    return hdr + src2 + "\n"

def main():
    src = io.open(MASTER, encoding="utf-8", errors="replace").read()
    results = []
    for tag, values in CELLS.items():
        fname = f"FIBC {tag}.mq5"
        path = os.path.join(EXPERTS, fname)
        io.open(path, "w", encoding="utf-8").write(transform(src, tag, values))
        log = path[:-4] + "_compile.log"
        subprocess.run(f'"{METAED}" /compile:"{path}" /log:"{log}"', check=False)
        res = "?"
        for enc in ("utf-16", "cp1252"):
            try:
                lines = [l for l in io.open(log, encoding=enc).read().splitlines() if "Result" in l]
                if lines: res = lines[-1].strip(); break
            except Exception: continue
        results.append((fname, res))
        io.open(os.path.join(EA_DIR, fname), "w", encoding="utf-8").write(
            io.open(path, encoding="utf-8").read())
    print("\n=== FIBC CELL BUILDS ===")
    for f, r in results: print(f"{f:16s} {r}")

if __name__ == "__main__":
    main()
