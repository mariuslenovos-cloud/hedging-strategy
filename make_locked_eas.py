"""
make_locked_eas.py -- generate per-symbol LOCKED GridStat MT5 EAs from the master.

WHY (2026-07-12, user directive): MT5 set files load unreliably and the tester
persists stale inputs between sessions -- three silent input-leaks in one week
(oil leftovers in the gold regression, MaxFibMult=1 source-default leak, the
Session-24 panel chaos). Fix = per-symbol EAs whose LOCKED config is hard-coded
as `const` (the Inputs tab CANNOT touch them), leaving ONLY the levers under
active validation as visible inputs.

WHY A GENERATOR (not hand copies): the MT4 GOLD/SILVER copy-drift debt is a
documented lesson. Here the master stays the single source of truth; after any
master change: run  `python make_locked_eas.py`  -> 3 files regenerate -> the
script compiles each via MetaEditor CLI and reports errors.

The master (all-inputs research EA) is UNCHANGED and remains the tool for
shadow runs, sweeps and optimizations.

Outputs (MT5 Experts folder + ea/ backup):
  Marius GridStat MT5 GOLD LOCKED.mq5
  Marius GridStat MT5 SILVER LOCKED.mq5
  Marius GridStat MT5 OIL LOCKED.mq5
"""
import io, os, re, subprocess, sys, datetime

EXPERTS = r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\BB16F565FAAA6B23A20C26C49416FF05\MQL5\Experts"
MASTER  = os.path.join(EXPERTS, "Marius GridStat MT5 v1.0.mq5")
EA_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ea")
METAED  = r"C:\Program Files\XM Global MT5\MetaEditor64.exe"
STAMP   = "2026-07-12"          # regeneration date -> build tag
BASE    = "S19"                 # master build this was generated from

# Levers that STAY visible in the tester Inputs tab (everything else -> const).
KEEP_AS_INPUT = {"UseStagedFloor", "StagedFloorPct", "UseSignalLog"}

# The locked configs (CLAUDE.md locks). Anything not listed keeps the master
# default -- which IS the validated shared default the lock runs used.
CONFIGS = {
    "GOLD": {   # $7,908 / PF 3.92 / 20.2% eqDD / 157tr anchor (build S9, re-confirmed S18 07-07)
        "symbols": ["GOLD", "XAUUSD"],
        "values": {
            "StatsCollectionMode": "false",
            "StatsCSVFile": '"gridstat_setups_gold.csv"',
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
            "StagedFloorPct": "12.0",     # swept gold plateau (input, default only)
        },
    },
    "SILVER": {  # $2,574 / PF 2.60 / 8.66% eqDD / Rec 5.79 lock (conc=4, 2026-06-12)
        "symbols": ["SILVER", "XAGUSD"],
        "values": {
            "StatsCollectionMode": "false",
            "StatsCSVFile": '"gridstat_setups_silver_mt5.csv"',
            "grisk": "14", "StatsFilterEnabled": "true", "MinWinRate": "0.50", "MinSamples": "10",
            "UseSizingTable": "false", "LotSize": "0.02",
            "UseRiskNormalizedLots": "true", "RiskPctPerTrade": "2.0",
            "MaxConcurrentBaskets": "4", "ProfitTargetUSD": "75.0",
            "UseEntrySL": "true", "UseBasketStop": "true", "BasketMaxLossPct": "20.0",
            "UseTrailingExit": "false", "UseLockTrailExit": "false",
            "UseOverextensionFilter": "false", "UseRegimeBasketExit": "false",
            "MaxFibMult": "0",
            "StagedFloorPct": "12.0",     # sweep pending (~8-16) -- input, default only
        },
    },
    "OIL": {     # $7,567 / PF 2.29 / 14.85% eqDD / Rec 4.17 lock (floor 10, sizing on, 2026-06-11)
        "symbols": ["OILCash", "SpotCrude"],
        "values": {
            "StatsCollectionMode": "false",
            "StatsCSVFile": '"gridstat_setups_oil_mt5.csv"',
            "grisk": "4", "StatsFilterEnabled": "false", "MinWinRate": "0.50", "MinSamples": "10",
            "UseSizingTable": "true", "SizingCSVFile": '"gridstat_sizing_oil.csv"', "MaxSizeMult": "2.0",
            "LotSize": "0.02",
            "UseRiskNormalizedLots": "true", "RiskPctPerTrade": "2.5",
            "MaxConcurrentBaskets": "3", "ProfitTargetUSD": "100.0",
            "UseEntrySL": "false", "UseBasketStop": "true", "BasketMaxLossPct": "10.0",
            "UseTrailingExit": "false", "UseLockTrailExit": "false",
            "UseOverextensionFilter": "false", "UseRegimeBasketExit": "false",
            "MaxFibMult": "0",
            "StagedFloorPct": "8.0",      # must sit BELOW oil's 10% floor; sweep pending (~5-8)
        },
    },
}

INPUT_RE = re.compile(r"^input\s+(\w+)\s+(\w+)(\s*)=\s*([^;]+);(.*)$")

def transform(master_src: str, tag: str, cfg: dict) -> str:
    lines = master_src.splitlines()
    out, seen = [], set()
    for ln in lines:
        m = INPUT_RE.match(ln)
        if m:
            typ, name, pad, default, tail = m.groups()
            val = cfg["values"].get(name, default.strip())
            seen.add(name)
            if name in KEEP_AS_INPUT:
                out.append(f"input {typ} {name}{pad}= {val};{tail}")
            else:
                out.append(f"const {typ} {name}{pad}= {val};{tail}  // LOCKED (was input)")
            continue
        if 'EA_BUILD_VERSION' in ln and '#define' in ln:
            out.append(f'#define EA_BUILD_VERSION "MT5-{STAMP}-{BASE}-{tag}-LOCKED"')
            continue
        out.append(ln)
    missing = set(cfg["values"]) - seen
    if missing:
        raise SystemExit(f"{tag}: config keys not found in master inputs: {missing}")
    src = "\n".join(out)

    # symbol guard + banner, injected at the top of OnInit
    syms = cfg["symbols"]
    cond = " && ".join(f'_Symbol != "{s}"' for s in syms)
    guard = (
        "\n   // ---- LOCKED-EA GUARD (generated by make_locked_eas.py; do NOT edit this file by hand)\n"
        f"   if({cond})\n"
        "   {\n"
        f'      Print("LOCKED {tag} EA attached to WRONG symbol: ", _Symbol, '
        f'" (accepts: {"/".join(syms)}). ABORTING.");\n'
        "      return(INIT_FAILED);\n"
        "   }\n"
        f'   Print("LOCKED {tag} EA -- all inputs hard-coded (generated {STAMP} from master {BASE}); '
        'only StagedFloor/SignalLog visible");\n'
    )
    anchor = "int OnInit()\n{\n"
    if anchor not in src:
        raise SystemExit(f"{tag}: OnInit anchor not found")
    src = src.replace(anchor, anchor + guard, 1)

    header = (
        "//+------------------------------------------------------------------+\n"
        f"//| GENERATED FILE -- LOCKED {tag} config. Do NOT edit by hand.       \n"
        f"//| Source of truth: Marius GridStat MT5 v1.0.mq5 (build {BASE}).     \n"
        "//| Regenerate after any master change:  python make_locked_eas.py    \n"
        "//+------------------------------------------------------------------+\n"
    )
    return header + src + "\n"

def main():
    master = io.open(MASTER, encoding="utf-8", errors="replace").read()
    results = []
    for tag, cfg in CONFIGS.items():
        fname = f"Marius GridStat MT5 {tag} LOCKED.mq5"
        path = os.path.join(EXPERTS, fname)
        io.open(path, "w", encoding="utf-8").write(transform(master, tag, cfg))
        log = path[:-4] + "_compile.log"
        # single command STRING with embedded quotes -- list form wraps whole args
        # in quotes ("/compile:C:\...") which MetaEditor fails to parse silently
        subprocess.run(f'"{METAED}" /compile:"{path}" /log:"{log}"', check=False)
        res = ""
        try:
            for enc in ("utf-16", "utf-8"):
                try:
                    res = [l for l in io.open(log, encoding=enc).read().splitlines() if "Result" in l][-1]
                    break
                except Exception:
                    continue
        except Exception:
            res = "log unreadable"
        results.append((fname, res))
        # sync to ea/ backup
        io.open(os.path.join(EA_DIR, fname), "w", encoding="utf-8").write(
            io.open(path, encoding="utf-8").read())
    print("\n=== GENERATION + COMPILE SUMMARY ===")
    for f, r in results:
        print(f"{f:45s} {r}")

if __name__ == "__main__":
    main()
