#!/usr/bin/env python3
"""
gridstat_make_cells.py -- zero-input GOLD capital-cure test cells (2026-07-14).

C1/C2 capital cells showed uncapped compounding re-inflates gold's risk at
$5k/$10k deposits (eqDD 36.9% / give-back $8k of $13k gross). Two cures, both
already in code, both untested on gold at scale:

  GOLD CAP2  locked gold + MaxCompoundScale=2   (fib C's cap transplant, S26)
  GOLD CAP1  locked gold + MaxCompoundScale=1   (flat 0.02 forever = comp-off-like;
             the capital recipe's historic $10k answer)
  GOLD RSQ   locked gold + the S23-25 rescue ON (2/3/50) -- the user's hedge
             instinct; gate-RESPECTING (rescue entries still need the 0.55
             win-rate gate; only D1 + slots are waived). Never tested on gold.

All other values = the SF12 locked gold config verbatim. Run each at $5,000
and $10,000 deposits (deposit is a tester-panel setting, not an input).
"""
import io, os, re, subprocess

EXPERTS = r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\BB16F565FAAA6B23A20C26C49416FF05\MQL5\Experts"
MASTER  = os.path.join(EXPERTS, "Marius GridStat MT5 v1.0.mq5")
METAED  = r"C:\Program Files\XM Global MT5\MetaEditor64.exe"
EA_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ea")

GOLD_LOCK = {   # = the SF12 locked gold config (mirrors make_locked_eas.py GOLD values)
    "UseStagedFloor": "true", "StagedFloorPct": "12.0",
    "StatsCollectionMode": "false", "StatsCSVFile": '"gridstat_setups_gold.csv"',
    "grisk": "4", "StatsFilterEnabled": "true", "MinWinRate": "0.55", "MinSamples": "10",
    "UseSizingTable": "false", "LotSize": "0.02",
    "UseCompounding": "true", "CompoundingBase": "3000.0", "MaxFibMult": "0",
    "UseRiskNormalizedLots": "false", "MaxConcurrentBaskets": "1",
    "ProfitTargetUSD": "100.0", "UseEntrySL": "true",
    "UseBasketStop": "true", "BasketMaxLossPct": "20.0",
    "UseTrailingExit": "false", "UseLockTrailExit": "false",
    "UseOverextensionFilter": "false", "UseRegimeBasketExit": "false",
    "BarrierATRMultiplier": "0.8", "BarrierATRUpper": "0", "BarrierATRLower": "0",
    "ATRSpacingMultiplier": "0.5", "MaxGridLevels": "6",
    "UseSignalLog": "false",
}
CELLS = {
    "GOLD CAP2": dict(GOLD_LOCK, MaxCompoundScale="2"),
    "GOLD CAP1": dict(GOLD_LOCK, MaxCompoundScale="1"),
    "GOLD RSQ":  dict(GOLD_LOCK, AllowOppositeWhenDeep="true",
                      OppositeWhenDeepPct="2.0", RescueMaxBaskets="3",
                      RescueBookTargetUSD="50.0"),
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
        if '#define' in ln and 'EA_BUILD_VERSION' in ln:
            out.append(f'#define EA_BUILD_VERSION "GS-CELL-{tag.replace(" ","-")}-2026-07-14"')
            continue
        out.append(ln)
    missing = set(values) - seen
    if missing: raise SystemExit(f"{tag}: unknown inputs {missing}")
    src2 = "\n".join(out)
    anchor = "int OnInit()\n{\n"
    deltas = ", ".join(f"{k}={v}" for k, v in values.items()
                       if k in ("MaxCompoundScale","AllowOppositeWhenDeep",
                                "OppositeWhenDeepPct","RescueMaxBaskets","RescueBookTargetUSD"))
    guard = f'\n   Print("GRIDSTAT TEST CELL {tag} -- zero-input; deltas vs SF12 lock: {deltas}");\n'
    if anchor not in src2: raise SystemExit(f"{tag}: OnInit anchor missing")
    src2 = src2.replace(anchor, anchor + guard, 1)
    return f"//| GENERATED TEST CELL {tag} -- regen via gridstat_make_cells.py |\n" + src2 + "\n"

def main():
    src = io.open(MASTER, encoding="utf-8", errors="replace").read()
    for tag, values in CELLS.items():
        fname = f"{tag}.mq5"
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
        print(f"{fname:16s} {res}")
        io.open(os.path.join(EA_DIR, fname), "w", encoding="utf-8").write(
            io.open(path, encoding="utf-8").read())

if __name__ == "__main__":
    main()
