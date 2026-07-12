"""
make_locked_eas.py -- generate + deploy per-symbol LOCKED GridStat EAs across
ALL FOUR terminals (XM MT4/MT5 + Pepperstone MT4/MT5).

WHY (2026-07-12, user directive): MT5 set files load unreliably, the tester
persists stale inputs, and source-default edits drift (MaxFibMult=1 leaked
twice) -- three silent input-leaks in one week. Fix = per-symbol EAs whose
LOCKED config is hard-coded as `const` (the Inputs tab CANNOT touch them),
leaving ONLY the levers under active validation as visible inputs.

WHY A GENERATOR (not hand copies): the MT4 GOLD/SILVER copy-drift debt is a
documented lesson. The masters stay the single source of truth; after any
master change run  `python make_locked_eas.py`  -> every locked EA regenerates,
deploys to every terminal in its manifest, compiles with THAT terminal's own
MetaEditor, and reports results. Never hand-edit a LOCKED file.

MASTERS (the all-inputs research EAs -- unchanged, still used for shadow runs,
sweeps and optimizations):
  MT5: XM-MT5  Experts\\Marius GridStat MT5 v1.0.mq5        (build S19+)
  MT4: XM-MT4  Experts\\Adapted\\Marius GridStat GOLD v1.0.mq4 (build T; edit HERE per standing rule 5)
  NOTE: the PEP-MT4 master copy intentionally differs from XM-MT4 by ONE line
  (XM source default MaxFibMult=1, a user edit) -- NOT auto-synced; locked EAs
  hard-code MaxFibMult=0 so the drift is neutralized where it matters.

DEPLOYMENT MANIFEST (mirrors what actually RUNS live per the user, 2026-07-12):
  MT5 locked GOLD/SILVER/OIL  -> XM-MT5 + PEP-MT5   (guards accept XM + Pepperstone symbol names)
  MT4 locked GOLD             -> XM-MT4 + PEP-MT4
  MT4 locked SILVER           -> XM-MT4 + PEP-MT4   (build-P vintage master: NO staged-floor inputs -> ZERO visible inputs)
  MT4 locked OIL              -> PEP-MT4 only       (MT4-conc port; ⚠ conc port never every-tick validated -- locking config != validation)
  MT5 master                  -> synced XM-MT5 -> PEP-MT5 (research parity; PEP copy was stale at 06-29)

MT4 locked GOLD config source of truth = the LIVE Pepperstone chart inputs
(read from profiles\\default\\chart01.chr 2026-07-10) = grisk 4 / gate 0.55 /
PT 100 / floor 20 / comp on / MaxFibMult 0 / all Session 22-24 levers OFF.
"""
import io, os, re, subprocess, sys, datetime

TERMDATA = r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal"
TERMINALS = {
    "XM-MT5":  {"experts": TERMDATA + r"\BB16F565FAAA6B23A20C26C49416FF05\MQL5\Experts",
                "me": r"C:\Program Files\XM Global MT5\MetaEditor64.exe"},
    "PEP-MT5": {"experts": TERMDATA + r"\73B7A2420D6397DFF9014A20F1201F97\MQL5\Experts",
                "me": r"C:\Program Files\Pepperstone MetaTrader 5\MetaEditor64.exe"},
    "XM-MT4":  {"experts": TERMDATA + r"\98A82F92176B73A2100FCD1F8ABD7255\MQL4\Experts\Adapted",
                "me": r"C:\Program Files (x86)\XM Global MT4\metaeditor.exe"},
    "PEP-MT4": {"experts": TERMDATA + r"\3294B546D50FEEDA6BF3CFC7CF858DB7\MQL4\Experts",
                "me": r"C:\Program Files (x86)\Pepperstone MetaTrader 4\metaeditor.exe"},
}
MASTER_MT5        = os.path.join(TERMINALS["XM-MT5"]["experts"], "Marius GridStat MT5 v1.0.mq5")
MASTER_MT4_GOLD   = os.path.join(TERMINALS["XM-MT4"]["experts"], "Marius GridStat GOLD v1.0.mq4")
MASTER_MT4_SILVER = os.path.join(TERMINALS["XM-MT4"]["experts"], "Marius GridStat SILVER v1.0.mq4")   # byte-identical to the PEP copy (md5-verified 07-12)
MASTER_MT4_OIL    = os.path.join(TERMINALS["PEP-MT4"]["experts"], "Marius GridStat OIL v1.0.mq4")      # MT4-conc port lives on PEP only (build 2026-07-01-P-MT4CONC)
EA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ea")
STAMP = "2026-07-12"
BASE_MT5, BASE_MT4 = "S19", "T"

KEEP_MT5 = {"UseStagedFloor", "StagedFloorPct", "UseSignalLog"}   # MT4 keep-sets live per job in MT4_JOBS

MT5_CONFIGS = {
    "GOLD": {   # $7,908 / PF 3.92 / 20.2% eqDD / 157tr anchor (re-confirmed S18 07-07)
        "symbols": ["GOLD", "XAUUSD"],
        "values": {
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
            "StagedFloorPct": "12.0",     # swept gold plateau (input, default only)
        },
    },
    "SILVER": {  # $2,574 / PF 2.60 / 8.66% eqDD / Rec 5.79 lock (conc=4, 2026-06-12)
        "symbols": ["SILVER", "XAGUSD"],
        "values": {
            "StatsCollectionMode": "false", "StatsCSVFile": '"gridstat_setups_silver_mt5.csv"',
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
            "StatsCollectionMode": "false", "StatsCSVFile": '"gridstat_setups_oil_mt5.csv"',
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

MT4_JOBS = [
    {   # = the LIVE Pepperstone chart inputs 2026-07-10 (grisk 4 superseded the old grisk-7 lock)
        "tag": "GOLD", "master": MASTER_MT4_GOLD, "base": BASE_MT4,
        "deploy": ["XM-MT4", "PEP-MT4"],
        "keep": {"UseStagedFloor", "StagedFloorPct"},
        "symbols": ["GOLD", "XAUUSD"],
        "values": {
            "StatsCollectionMode": "false", "StatsCSVFile": '"gridstat_setups.csv"',
            "grisk": "4", "StatsFilterEnabled": "true", "MinWinRate": "0.55", "MinSamples": "10",
            "UseSizingTable": "false", "LotSize": "0.02",
            "UseCompounding": "true", "CompoundingBase": "3000.0", "MaxFibMult": "0",
            "UseRiskNormalizedLots": "false",
            "ProfitTargetUSD": "100.0", "UseBasketStop": "true", "BasketMaxLossPct": "20.0",
            "UseTrailingExit": "false", "ATRSpacingMultiplier": "0.5", "MaxGridLevels": "6",
            "UseRecoveryRide": "false", "UseRecoveryTrail": "false",
            "UseFloorHedge": "false", "FH_OvertakeStep": "0",
            "BarrierATRMultiplier": "0.8",
            "StagedFloorPct": "12.0",     # MT4 156-trade-panel plateau 12-14 (input, default only)
        },
    },
    {   # $2,747 / PF 2.79 / 11.1% DD MT4 lock (2026-06-05) = the master's own source defaults (verified 07-12)
        "tag": "SILVER", "master": MASTER_MT4_SILVER, "base": "P",
        "deploy": ["XM-MT4", "PEP-MT4"],
        "keep": set(),                    # build-P vintage: no staged-floor inputs -> fully locked, zero visible
        "symbols": ["SILVER", "XAGUSD"],
        "values": {
            "StatsCollectionMode": "false", "StatsCSVFile": '"gridstat_setups_silver.csv"',
            "grisk": "14", "StatsFilterEnabled": "true", "MinWinRate": "0.50", "MinSamples": "10",
            "UseSizingTable": "false", "LotSize": "0.02",
            "UseCompounding": "true", "CompoundingBase": "3000.0",
            "UseRiskNormalizedLots": "true", "RiskPctPerTrade": "2.0",
            "ProfitTargetUSD": "75.0", "UseBasketStop": "true", "BasketMaxLossPct": "20.0",
            "UseTrailingExit": "false", "ATRSpacingMultiplier": "0.5", "MaxGridLevels": "6",
        },
    },
    {   # mirrors the MT5 oil lock ($7,567/PF2.29/14.85%DD) = the conc-port's source defaults (verified 07-12)
        # ⚠ the MT4-conc port itself was never every-tick validated -- locking the config is not validation
        "tag": "OIL", "master": MASTER_MT4_OIL, "base": "P-MT4CONC",
        "deploy": ["PEP-MT4"],
        "keep": set(),
        "symbols": ["OILCash", "SpotCrude"],
        "values": {
            "StatsCollectionMode": "false", "StatsCSVFile": '"gridstat_setups_oil_mt5.csv"',
            "grisk": "4", "StatsFilterEnabled": "false", "MinWinRate": "0.50", "MinSamples": "10",
            "UseSizingTable": "true", "SizingCSVFile": '"gridstat_sizing_oil.csv"', "MaxSizeMult": "2.0",
            "LotSize": "0.02", "UseCompounding": "true", "CompoundingBase": "3000.0",
            "UseRiskNormalizedLots": "true", "RiskPctPerTrade": "2.5",
            "MaxConcurrentBaskets": "3", "ProfitTargetUSD": "100.0",
            "UseEntrySL": "false", "UseBasketStop": "true", "BasketMaxLossPct": "10.0",
            "UseTrailingExit": "false", "ATRSpacingMultiplier": "0.5", "MaxGridLevels": "6",
        },
    },
]

INPUT_RE = re.compile(r"^input\s+(\w+)\s+(\w+)(\s*)=\s*([^;]+);(.*)$")

def transform(master_src, tag, cfg, keep_inputs, build_tag):
    lines = master_src.splitlines()
    out, seen = [], set()
    for ln in lines:
        m = INPUT_RE.match(ln)
        if m:
            typ, name, pad, default, tail = m.groups()
            val = cfg["values"].get(name, default.strip())
            seen.add(name)
            if name in keep_inputs:
                out.append(f"input {typ} {name}{pad}= {val};{tail}")
            else:
                out.append(f"const {typ} {name}{pad}= {val};{tail}  // LOCKED (was input)")
            continue
        if 'EA_BUILD_VERSION' in ln and '#define' in ln:
            out.append(f'#define EA_BUILD_VERSION "{build_tag}"')
            continue
        out.append(ln)
    missing = set(cfg["values"]) - seen
    if missing:
        raise SystemExit(f"{tag}: config keys not found in master inputs: {missing}")
    src = "\n".join(out)

    # symbol guard + banner at the top of OnInit (anchor handles both brace styles)
    syms = cfg["symbols"]
    cond = " && ".join(f'_Symbol != "{s}"' for s in syms)
    guard = (
        "\n   // ---- LOCKED-EA GUARD (generated by make_locked_eas.py; do NOT edit this file by hand)\n"
        f"   if({cond})\n"
        "   {\n"
        f'      Print("LOCKED {tag} EA attached to WRONG symbol: ", _Symbol,'
        f' " (accepts: {"/".join(syms)}). ABORTING.");\n'
        "      return(INIT_FAILED);\n"
        "   }\n"
        f'   Print("LOCKED {tag} EA -- all inputs hard-coded (generated {STAMP}); '
        'only StagedFloor levers visible");\n'
    )
    injected = False
    for anchor in ("int OnInit()\n{\n", "int OnInit() {\n"):
        if anchor in src:
            src = src.replace(anchor, anchor + guard, 1); injected = True; break
    if not injected:
        raise SystemExit(f"{tag}: OnInit anchor not found")

    header = (
        "//+------------------------------------------------------------------+\n"
        f"//| GENERATED FILE -- LOCKED {tag} config. Do NOT edit by hand.       \n"
        "//| Regenerate after any master change:  python make_locked_eas.py    \n"
        "//+------------------------------------------------------------------+\n"
    )
    return header + src + "\n"

def compile_one(me, path):
    log = path[:-4] + "_compile.log"
    # single command STRING with embedded quotes -- list form wraps whole args
    # in quotes ("/compile:C:\...") which MetaEditor fails to parse silently
    subprocess.run(f'"{me}" /compile:"{path}" /log:"{log}"', check=False)
    for enc in ("utf-16", "utf-8", "cp1252"):
        try:
            lines = [l for l in io.open(log, encoding=enc).read().splitlines() if "Result" in l]
            if lines: return lines[-1].strip()
        except Exception:
            continue
    return "log unreadable / no Result line"

def read_src(path):
    return io.open(path, encoding="utf-8", errors="replace").read()

def main():
    results = []

    # --- job 1: sync MT5 master -> PEP-MT5 (research parity) + compile there
    pep_master = os.path.join(TERMINALS["PEP-MT5"]["experts"], "Marius GridStat MT5 v1.0.mq5")
    io.open(pep_master, "w", encoding="utf-8").write(read_src(MASTER_MT5))
    results.append(("PEP-MT5", "Marius GridStat MT5 v1.0.mq5 (master sync)",
                    compile_one(TERMINALS["PEP-MT5"]["me"], pep_master)))

    # --- job 2: MT5 locked EAs -> XM-MT5 + PEP-MT5
    mt5_master = read_src(MASTER_MT5)
    for tag, cfg in MT5_CONFIGS.items():
        fname = f"Marius GridStat MT5 {tag} LOCKED.mq5"
        body = transform(mt5_master, tag, cfg, KEEP_MT5, f"MT5-{STAMP}-{BASE_MT5}-{tag}-LOCKED")
        for term in ("XM-MT5", "PEP-MT5"):
            path = os.path.join(TERMINALS[term]["experts"], fname)
            io.open(path, "w", encoding="utf-8").write(body)
            results.append((term, fname, compile_one(TERMINALS[term]["me"], path)))
        io.open(os.path.join(EA_DIR, fname), "w", encoding="utf-8").write(body)

    # --- job 3: MT4 locked EAs, per-job master + deploy list
    for job in MT4_JOBS:
        tag = job["tag"]
        fname = f"Marius GridStat {tag} LOCKED.mq4"
        body = transform(read_src(job["master"]), tag, job, job["keep"],
                         f"{STAMP}-{job['base']}-{tag}-LOCKED")
        for term in job["deploy"]:
            path = os.path.join(TERMINALS[term]["experts"], fname)
            io.open(path, "w", encoding="utf-8").write(body)
            results.append((term, fname, compile_one(TERMINALS[term]["me"], path)))
        io.open(os.path.join(EA_DIR, fname), "w", encoding="utf-8").write(body)

    print("\n=== GENERATION + COMPILE SUMMARY ===")
    fail = 0
    for term, f, r in results:
        ok = "0 errors" in r
        fail += (not ok)
        print(f"{'OK ' if ok else 'FAIL'} {term:8s} {f:45s} {r}")
    sys.exit(1 if fail else 0)

if __name__ == "__main__":
    main()
