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
    # PEP-MT5 above = PRODUCTION (live 51511633 since 2026-07-14).
    # PEP-STAGE below = STAGING: 2nd Pepperstone install ("C:\MT5 Pepperstone
    # Instance 2"), demo 61552687, own data folder C54C4DDE... (Common\Files shared).
    "PEP-STAGE": {"experts": TERMDATA + r"\C54C4DDE98E7B1FB905AFE04A9333631\MQL5\Experts",
                  "me": r"C:\MT5 Pepperstone Instance 2\MetaEditor64.exe"},
    "XM-MT4":  {"experts": TERMDATA + r"\98A82F92176B73A2100FCD1F8ABD7255\MQL4\Experts\Adapted",
                "me": r"C:\Program Files (x86)\XM Global MT4\metaeditor.exe"},
    "PEP-MT4": {"experts": TERMDATA + r"\3294B546D50FEEDA6BF3CFC7CF858DB7\MQL4\Experts",
                "me": r"C:\Program Files (x86)\Pepperstone MetaTrader 4\metaeditor.exe"},
}
MASTER_MT5        = os.path.join(TERMINALS["XM-MT5"]["experts"], "Marius GridStat MT5 v1.0.mq5")
MASTER_MT4_GOLD   = os.path.join(TERMINALS["XM-MT4"]["experts"], "Marius GridStat GOLD v1.0.mq4")
MASTER_MT4_SILVER = os.path.join(TERMINALS["XM-MT4"]["experts"], "Marius GridStat SILVER v1.0.mq4")   # byte-identical to the PEP copy (md5-verified 07-12)
MASTER_MT4_OIL    = os.path.join(TERMINALS["PEP-MT4"]["experts"], "Marius GridStat OIL v1.0.mq4")      # MT4-conc port lives on PEP only (build 2026-07-01-P-MT4CONC)
MASTER_FIBC       = os.path.join(TERMINALS["XM-MT5"]["experts"], "Marius Hedger M5 fib C MT5 v1.0.mq5")  # fib C research master
EA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ea")
STAMP = "2026-07-12"
BASE_MT5, BASE_MT4 = "S25", "T"

# silver/oil keep the ACTIVE research levers visible; gold overrides keep per-config
# (staged locked SF12; conc=1 makes portfolio-staged unreachable + same-dir gate moot).
# Staged-floor levers: NOT-FOR-OIL verdict 2026-07-12 (per-basket inert, book-level cut
# recoverable floats -> net -14%) but kept visible for silver's pending sweep.
KEEP_MT5 = {"UseStagedFloor", "StagedFloorPct",
            "UseStagedFloorPortfolio", "StagedFloorPortfolioPct",
            "UseSameDirBasketGate", "SameDirGateLossPct",
            "UseSameDirTaper", "SameDirTaperMult",
            "AllowOppositeWhenDeep", "OppositeWhenDeepPct", "RescueBookTargetUSD", "RescueMaxBaskets",
            "DailyMA_Period", "UseSignalLog"}

MT5_CONFIGS = {
    "GOLD": {   # STAGED FLOOR LOCKED 2026-07-12 (real-tick gate PASSED both venues: XM eqDD 20.21->11.59%,
                # PEP 19.15->11.33%, net -4%, RF 4.98->6.49 / 5.46->6.67; same 3 cut events on both feeds).
                # New anchors (Dec-01->Jul-12, $3k): XM $9,082/PF3.29/11.59%/194tr; PEP $9,342/PF3.39/11.33%/195tr.
                # Pre-staged anchors (archived): XM $9,479/PF3.52/20.21%/191tr; PEP $9,741/PF3.63/19.15%/192tr.
        "symbols": ["GOLD", "XAUUSD"],
        "keep": {"UseSignalLog"},          # staged floor now part of the lock -> hard-coded (A/B via the master)
        "buildsuffix": "-SF12",
        "values": {
            "UseStagedFloor": "true",      # LOCKED 2026-07-12 (gate: MT5 real-tick A/B both venues)
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
                 # + RESCUE LOCKED 2026-07-12 (the fib C recovery-hedge transplant, full choreography:
                 #   S23 unblock + S24 stop-feeding/book-exit + S25 ramp). Cross-venue gate PASSED at
                 #   2/3/50: PEP RF 3.23->3.63 / eqDD 19.47->16.92%; XM RF 2.78->3.08 / eqDD
                 #   20.46->18.24%. Full inverted-U curve: cliff at 1% (RF 2.17), plateau 2-3%
                 #   (4 cells RF 3.46-3.63), fade by 5% (3.06). New anchors (Dec-01->Jul-12, $3k):
                 #   PEP $8,188/PF2.04/16.92%/RF3.63/166tr; XM $6,117/PF1.85/18.24%/RF3.08/159tr.
                 #   Staged/gate/taper levers = NOT-FOR-OIL (6 rejections 07-12) -> hard-coded OFF.
        "symbols": ["OILCash", "SpotCrude"],
        "keep": {"UseSignalLog"},
        "buildsuffix": "-RSQ2",
        "values": {
            "AllowOppositeWhenDeep": "true",   # LOCKED 2026-07-12 (cross-venue gate)
            "OppositeWhenDeepPct": "2.0",
            "RescueMaxBaskets": "3",
            "RescueBookTargetUSD": "50.0",
            "UseStagedFloor": "false", "UseStagedFloorPortfolio": "false",
            "UseSameDirBasketGate": "false", "UseSameDirTaper": "false",
            "DailyMA_Period": "50",            # D1-speed sweep closed: 50 validated (20/30 strictly worse)
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
        # + STAGED FLOOR LOCKED 2026-07-12 (MT5 real-tick gate passed both venues; MT4 evidence:
        #   156-trade-panel sweep RF 3.74->4.99 @12 + the live -$28 episode)
        "tag": "GOLD", "master": MASTER_MT4_GOLD, "base": BASE_MT4,
        "deploy": ["XM-MT4", "PEP-MT4"],
        "keep": set(), "buildsuffix": "-SF12",
        "symbols": ["GOLD", "XAUUSD"],
        "values": {
            "UseStagedFloor": "true",      # LOCKED 2026-07-12
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
        # deployed to XM-MT4 too: PEP-MT4 lacks SpotCrude M1 history, so the conc-port
        # validation runs on XM's OILCash data (guard accepts both symbol names)
        "tag": "OIL", "master": MASTER_MT4_OIL, "base": "P-MT4CONC",
        "deploy": ["PEP-MT4", "XM-MT4"],
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
        if '#define' in ln and 'EA_BUILD_VERSION' in ln:
            out.append(f'#define EA_BUILD_VERSION "{build_tag}"')
            continue
        if ln.startswith('#define BUILD '):
            out.append(f'#define BUILD "{build_tag}"')
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
    for _t in ("PEP-MT5", "PEP-STAGE"):
      pep_master = os.path.join(TERMINALS[_t]["experts"], "Marius GridStat MT5 v1.0.mq5")
      io.open(pep_master, "w", encoding="utf-8").write(read_src(MASTER_MT5))
      results.append((_t, "Marius GridStat MT5 v1.0.mq5 (master sync)",
                      compile_one(TERMINALS[_t]["me"], pep_master)))

    # --- job 2: MT5 locked EAs -> XM-MT5 + PEP-MT5
    mt5_master = read_src(MASTER_MT5)
    for tag, cfg in MT5_CONFIGS.items():
        fname = f"Marius GridStat MT5 {tag} LOCKED.mq5"
        body = transform(mt5_master, tag, cfg, cfg.get("keep", KEEP_MT5),
                         f"MT5-{STAMP}-{BASE_MT5}-{tag}{cfg.get('buildsuffix','')}-LOCKED")
        for term in ("XM-MT5", "PEP-MT5", "PEP-STAGE"):
            path = os.path.join(TERMINALS[term]["experts"], fname)
            io.open(path, "w", encoding="utf-8").write(body)
            results.append((term, fname, compile_one(TERMINALS[term]["me"], path)))
        io.open(os.path.join(EA_DIR, fname), "w", encoding="utf-8").write(body)

    # --- job 2b: fib C LOCKED (exit XC=40/15, locked 2026-07-13; cross-venue gate
    #     PASSED: XM RF 2.06->3.93 / eqDD 27.5->17.0%; PEP RF 1.58->3.85 / 31.4->17.3%;
    #     8-leg cluster events deleted on BOTH feeds. Full inverted-U: 30/40/50/60-arm
    #     curve, twin-cell plateau XB/XC. Anchors: XM $3,859/PF2.16/17.0%/RF3.93/150tr;
    #     PEP $3,734/PF2.19/17.3%/RF3.85/135tr. All other values = the live chart
    #     config verified by screenshot 2026-07-13, pinned explicitly vs default drift.)
    fibc_cfg = {
        "symbols": ["GOLD", "XAUUSD"],
        "values": {
            "LotSize": "0.02", "UseFibonacci": "true", "UseCompounding": "true",
            "CompoundingBase": "3000.0", "MaxSameTrades": "5", "MaxFibMult": "0",
            "MaxCompoundScale": "3", "RecoverySizeMode": "1", "RecoveryRR": "3.0",
            "RecoveryCostBuffer": "1.1", "grisk": "7",
            "MA_Angle_Threshold": "20.0", "ADX_Threshold": "25.0",
            "UseSessionFilter": "true", "SessionStartHour": "9", "SessionEndHour": "23",
            "UseBasketTrail": "true",
            "MinFloatToActivate": "40.0",   # THE LOCK (was 80)
            "BasketTrailAmount": "15.0",
            "UseBuySellProfitThreshold": "true", "BuySellProfitThreshold": "50.0",
            "UseBasketStop": "true", "BasketMaxLossPct": "20.0",
            "UseDailyTrendFilter": "true", "DailyMA_Period": "50",
            "UseImbalanceLock": "true", "ImbalanceThreshold": "2",
            "UseVolRegimeFilter": "true", "VolRegimeMult": "2.5",
            "VolBlockAllEntries": "true", "VolScaledFloor": "false",
            "UseOverextFilter": "false",
            "UseFirstEntryGate": "true", "FirstGateStatsCSV": '"gridstat_setups_gold.csv"',
            "FirstGateMinWinRate": "0.55", "FirstGateSellMinWinRate": "0.65",
            "FirstGateMinSamples": "10",
            "UseRecoveryHedge": "true", "HedgeTriggerLoss": "0.0",
            "HedgeTriggerPctBal": "3.0", "RecoveryTargetUSD": "40.0",
            "UseRecoveryTrail": "true", "RecoveryTrailGiveback": "20.0",
            "RecoveryTargetPct": "10.0",
        },
    }
    fibc_body = transform(read_src(MASTER_FIBC), "FIBC", fibc_cfg, {"UseEquityLog"},
                          "FIBC-2026-07-13-XC4015-LOCKED")
    for term in ("XM-MT5", "PEP-MT5", "PEP-STAGE"):
        fpath = os.path.join(TERMINALS[term]["experts"], "Marius Hedger fib C LOCKED.mq5")
        io.open(fpath, "w", encoding="utf-8").write(fibc_body)
        results.append((term, "Marius Hedger fib C LOCKED.mq5", compile_one(TERMINALS[term]["me"], fpath)))
    io.open(os.path.join(EA_DIR, "Marius Hedger fib C LOCKED.mq5"), "w", encoding="utf-8").write(fibc_body)

    # --- job 3: MT4 locked EAs, per-job master + deploy list
    for job in MT4_JOBS:
        tag = job["tag"]
        fname = f"Marius GridStat {tag} LOCKED.mq4"
        body = transform(read_src(job["master"]), tag, job, job["keep"],
                         f"{STAMP}-{job['base']}-{tag}{job.get('buildsuffix','')}-LOCKED")
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
