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
# --- S31 STATE-RELEASE round (2026-08-24): fib C build P validated (PF 1.47->2.00, RF 1.83->2.96,
#     worst ep -810->-169 at -5.7% net) -> port the lever onto the GOLD FIBC8 lock's rescue.
#     GOLD_FIBC8 = the CURRENT locked gold (SF12C2 + fib C overlay, mirrors make_locked_eas GOLD).
GOLD_FIBC8 = dict(GOLD_LOCK,
    MaxCompoundScale="2",
    RescueBookTargetUSD="40.0", RescueBookTrailPct="20.0", RescueMaxBaskets="5",
    RescueOnlyInCrashState="false", UseCrashGuard="false", CrashGuardGateOnly="false",
    UseFreezeHedge="false", UseCrashStateSells="false", CrossCrashSymbol='""',
    RescueOnDrawdownPct="8.0")
# --- S32 TIMECAP cells: NOT generated here. The SOLID lineage FORKED from the master 08-04
#     (UseRegimeSells/RegimeSellMinWR live only in the fork) -> master-based cells cannot
#     reproduce SOLID4. Use make_oil_tc_cells.py (injects the cap into the LOCKED SOLID source).
CELLS.update({
    # control = the FIBC8 lock verbatim (must reproduce the locked character on the bench)
    "GOLD SRC":  dict(GOLD_FIBC8),
    # no-harm overlay: state-release on the 8% disaster-class rescue
    "GOLD SRO":  dict(GOLD_FIBC8, UseStateRelease="true"),
    # the sub-8 unlock attempt: earlier protection (5%) + tick-arm resolution (S27) + state-release
    # as the anti-churn device the 08-06 cliff autopsy said sub-8 triggers need. Known answer:
    # 5% WITHOUT these = death spiral (-$2,193/99.8% DD); the cell must beat the 8% passenger or die.
    "GOLD SR5T": dict(GOLD_FIBC8, RescueOnDrawdownPct="5.0", RescueTickArm="true",
                      RescueTargetPctDeepest="10.0", RescueRearmCooldownBars="288",
                      UseStateRelease="true"),
    # 2026-08-26: the LIVE geometry cell -- GOLD HALF LOCKED verbatim (0.01 lots, PT 50, RBT 20 =
    # halve every $-lever; %-levers unchanged). Built to answer the re-test's churn-spiral finding
    # (GOLD SRC @ $3k, trailing 56d = 740 trades / 91% DD via staged-cut re-entry loop) at the
    # balance the live accounts actually run (~$2,350) -- does HALF's headroom avoid the loop?
    "GOLD HALF56": dict(GOLD_FIBC8, LotSize="0.01", ProfitTargetUSD="50.0",
                        RescueBookTargetUSD="20.0"),
    # 2026-09-03 (the double guard-trip autopsy): the LIVE HALF geometry + the S27 sub-8 package.
    # Last night both live accounts' Book Guards flattened the gold sell grid at -8.2%/-8.3%
    # (03:09/04:09) while the FIBC8 rescue -- the organ built for exactly this melt-up class --
    # NEVER ARMED: it sits at the SAME 8% depth but is sampled only at signal times, so the
    # tick-evaluated guard wins the race every time; overnight there are no signals at all.
    # This cell arms the ride EARLIER (5%) with tick resolution + the anti-churn devices, i.e.
    # the treatment gets 3pp of room BELOW the amputation line. Judge vs GOLD HALF56 control:
    # (a) the 09-02/03 episode (guard-line loss must become a rescued/small outcome),
    # (b) the Aug-19 and Aug-4/5 episodes, (c) full-window net/RF/eqDD not materially worse.
    # Known answers: 5% WITHOUT tick-arm+cooldown = death spiral; on partial-tick benches the
    # deep-float trigger may under-arm -> confirm on the 100%-tick demo tester if it wins here.
    "GOLD HRES5T": dict(GOLD_FIBC8, LotSize="0.01", ProfitTargetUSD="50.0",
                        RescueBookTargetUSD="20.0",
                        RescueOnDrawdownPct="5.0", RescueTickArm="true",
                        RescueTargetPctDeepest="10.0", RescueBookSingle="true", RescueLockDir="true", RescueRearmCooldownBars="288"),
    # 2026-09-03 S36 PIN-THEN-RIDE (user: "replace the floor with a solution to turn the DD around").
    # First-order sim on the REAL 09-02/03 bars at the live HALF book (4 sells, 0.07 lots, bal $2,592):
    #   as deployed / HRES5T (tick-arm, rides need signals)  -> guard trip -$223 (NO signals for 15h overnight)
    #   + immediate 1.5x overtake leg                          -> guard trip -$209 on the first pullback (07-29 oil again)
    #   + immediate 1:1 PIN, rides flat 0.01                   -> guard trip -$210 (rides add exposure, never overtake)
    #   + immediate 1:1 PIN, rides FIB-RAMPED                  -> BOOK EXIT +$160 @13:00 (deepest -$203)
    # Two code gaps closed by S36: (a) the pin = a hedge leg opened AT the arm without a signal (any hour);
    # (b) RescueRampByLegs = in single-basket mode CountSameDirBaskets is always 1, so the fib overtake
    # NEVER stepped (demo 09-03: ten identical 0.02 ride legs). Staged floor suspended while riding.
    # Judge vs GOLD HALF56 (control) and GOLD HRES5T: (a) the 09-02/03 episode must resolve green/small,
    # (b) Aug-19 + Aug-4/5, (c) full window net/RF/eqDD not materially worse, (d) count RESCUE PIN lines
    # (must be RARE -- a pin per ordinary pullback = the 5% freeze-churn signature). ⚠ deep-float trigger:
    # the runner's partial ticks under-arm -> the 100%-tick demo GUI tester is the decisive bench.
    "GOLD HPIN":   dict(GOLD_FIBC8, LotSize="0.01", ProfitTargetUSD="50.0", RescueBookTargetUSD="20.0",
                        RescueOnDrawdownPct="5.0", RescueTickArm="true",
                        RescueTargetPctDeepest="10.0", RescueBookSingle="true", RescueLockDir="true", RescueRearmCooldownBars="288",
                        RescueImmediateLeg="true", RescueImmediateRatio="1.0",
                        RescueRampByLegs="true", RescueSuspendsStaged="true"),
    "GOLD HPIN3":  dict(GOLD_FIBC8, LotSize="0.01", ProfitTargetUSD="50.0", RescueBookTargetUSD="20.0",
                        RescueOnDrawdownPct="3.0", RescueTickArm="true",
                        RescueTargetPctDeepest="10.0", RescueBookSingle="true", RescueLockDir="true", RescueRearmCooldownBars="288",
                        RescueImmediateLeg="true", RescueImmediateRatio="1.0",
                        RescueRampByLegs="true", RescueSuspendsStaged="true"),
    # + the SR6-validated cheap-release (fib C build P): realizes a pinned/riding book at the first bad
    # state while the loss is still small (float >= -200) = the bounded whipsaw exit; costs the 09-02 win
    # in the sim (would release -$130 at the 21:00 pullback) -> the tester prices that trade.
    # 2026-09-04: the 5% pin fired 28x/9mo on XM (-$787 vs +$6,019 control) = the freeze-at-noise verdict again.
    # The mechanism argument: ordinary baskets float to ~5% and recover; disasters run past 8%. Pin at the
    # DISASTER line (where the guard/staged floor amputate today), not the noise line.
    "GOLD HPIN8":  dict(GOLD_FIBC8, LotSize="0.01", ProfitTargetUSD="50.0", RescueBookTargetUSD="20.0",
                        RescueOnDrawdownPct="8.0", RescueTickArm="true", RescueBookSingle="true", RescueLockDir="true",
                        RescueTargetPctDeepest="10.0", RescueRearmCooldownBars="288",
                        RescueImmediateLeg="true", RescueImmediateRatio="1.0",
                        RescueRampByLegs="true", RescueSuspendsStaged="true"),
    "GOLD HPIN10": dict(GOLD_FIBC8, LotSize="0.01", ProfitTargetUSD="50.0", RescueBookTargetUSD="20.0",
                        RescueOnDrawdownPct="10.0", RescueTickArm="true", RescueBookSingle="true", RescueLockDir="true",
                        RescueTargetPctDeepest="10.0", RescueRearmCooldownBars="288",
                        RescueImmediateLeg="true", RescueImmediateRatio="1.0",
                        RescueRampByLegs="true", RescueSuspendsStaged="true"),
    "GOLD HPIN12": dict(GOLD_FIBC8, LotSize="0.01", ProfitTargetUSD="50.0", RescueBookTargetUSD="20.0",
                        RescueOnDrawdownPct="12.0", RescueTickArm="true", RescueBookSingle="true", RescueLockDir="true",
                        RescueTargetPctDeepest="10.0", RescueRearmCooldownBars="288",
                        RescueImmediateLeg="true", RescueImmediateRatio="1.0",
                        RescueRampByLegs="true", RescueSuspendsStaged="true"),
    # demo side-by-side twin of the HPIN12 candidate (own magic, like FIBC SR6F / GOLD DAYRANK 59956)
    "GOLD HPIN12F": dict(GOLD_FIBC8, LotSize="0.01", ProfitTargetUSD="50.0", RescueBookTargetUSD="20.0",
                        RescueOnDrawdownPct="12.0", RescueTickArm="true", RescueBookSingle="true", RescueLockDir="true",
                        RescueTargetPctDeepest="10.0", RescueRearmCooldownBars="288",
                        RescueImmediateLeg="true", RescueImmediateRatio="1.0",
                        RescueRampByLegs="true", RescueSuspendsStaged="true", MagicSeed="59957"),
    # 2026-09-04 S37 RANGE GUARD: the two live specimens (gold sold within 1-2% of its 10d low; oil bought 0.7%
    # below its 10d high) = fading at the range edge. Gate on NEW basket starts only.
    "GOLD HRG2":  dict(GOLD_FIBC8, LotSize="0.01", ProfitTargetUSD="50.0", RescueBookTargetUSD="20.0",
                       UseRangeGuard="true", RangeGuardPct="2.0", RangeGuardDays="10"),
    "GOLD HRG3":  dict(GOLD_FIBC8, LotSize="0.01", ProfitTargetUSD="50.0", RescueBookTargetUSD="20.0",
                       UseRangeGuard="true", RangeGuardPct="3.0", RangeGuardDays="10"),
    "GOLD HPIN12RG2": dict(GOLD_FIBC8, LotSize="0.01", ProfitTargetUSD="50.0", RescueBookTargetUSD="20.0",
                        RescueOnDrawdownPct="12.0", RescueTickArm="true", RescueBookSingle="true", RescueLockDir="true",
                        RescueTargetPctDeepest="10.0", RescueRearmCooldownBars="288",
                        RescueImmediateLeg="true", RescueImmediateRatio="1.0",
                        RescueRampByLegs="true", RescueSuspendsStaged="true",
                        UseRangeGuard="true", RangeGuardPct="2.0", RangeGuardDays="10"),
    # 2026-09-04 S38 VELOCITY GUARD (gold |3d| percentiles: p90 3.7 / p95 4.6 / p98 5.7; Aug-5 +5.3, 09-02 ~-7.5)
    "GOLD HVG3":  dict(GOLD_FIBC8, LotSize="0.01", ProfitTargetUSD="50.0", RescueBookTargetUSD="20.0",
                       UseVelocityGuard="true", VelocityGuardPct="3.0", VelocityGuardDays="3"),
    "GOLD HVG4":  dict(GOLD_FIBC8, LotSize="0.01", ProfitTargetUSD="50.0", RescueBookTargetUSD="20.0",
                       UseVelocityGuard="true", VelocityGuardPct="4.0", VelocityGuardDays="3"),
    "GOLD HVG5":  dict(GOLD_FIBC8, LotSize="0.01", ProfitTargetUSD="50.0", RescueBookTargetUSD="20.0",
                       UseVelocityGuard="true", VelocityGuardPct="5.0", VelocityGuardDays="3"),
    "GOLD HVG4D45": dict(GOLD_FIBC8, LotSize="0.01", ProfitTargetUSD="50.0", RescueBookTargetUSD="20.0",
                       UseVelocityGuard="true", VelocityGuardPct="4.5", VelocityGuardDays="4"),
    "GOLD HVG4D5":  dict(GOLD_FIBC8, LotSize="0.01", ProfitTargetUSD="50.0", RescueBookTargetUSD="20.0",
                       UseVelocityGuard="true", VelocityGuardPct="5.0", VelocityGuardDays="4"),
    "GOLD HVG5D5":  dict(GOLD_FIBC8, LotSize="0.01", ProfitTargetUSD="50.0", RescueBookTargetUSD="20.0",
                       UseVelocityGuard="true", VelocityGuardPct="5.0", VelocityGuardDays="5"),
    # the stack: pin at the staged line (passenger on XM, -$37 on the PEP night) + 5d/5% velocity guard (XM RF 7.0->10.7, eqDD 12.1->7.2%)
    "GOLD HPIN12VG5": dict(GOLD_FIBC8, LotSize="0.01", ProfitTargetUSD="50.0", RescueBookTargetUSD="20.0",
                        RescueOnDrawdownPct="12.0", RescueTickArm="true", RescueBookSingle="true", RescueLockDir="true",
                        RescueTargetPctDeepest="10.0", RescueRearmCooldownBars="288",
                        RescueImmediateLeg="true", RescueImmediateRatio="1.0",
                        RescueRampByLegs="true", RescueSuspendsStaged="true",
                        UseVelocityGuard="true", VelocityGuardPct="5.0", VelocityGuardDays="5"),
    "GOLD HPIN12VG5F": dict(GOLD_FIBC8, LotSize="0.01", ProfitTargetUSD="50.0", RescueBookTargetUSD="20.0",
                        RescueOnDrawdownPct="12.0", RescueTickArm="true", RescueBookSingle="true", RescueLockDir="true",
                        RescueTargetPctDeepest="10.0", RescueRearmCooldownBars="288",
                        RescueImmediateLeg="true", RescueImmediateRatio="1.0",
                        RescueRampByLegs="true", RescueSuspendsStaged="true",
                        UseVelocityGuard="true", VelocityGuardPct="5.0", VelocityGuardDays="5", MagicSeed="59957"),
    "GOLD HPINSR": dict(GOLD_FIBC8, LotSize="0.01", ProfitTargetUSD="50.0", RescueBookTargetUSD="20.0",
                        RescueOnDrawdownPct="5.0", RescueTickArm="true",
                        RescueTargetPctDeepest="10.0", RescueBookSingle="true", RescueLockDir="true", RescueRearmCooldownBars="288",
                        RescueImmediateLeg="true", RescueImmediateRatio="1.0",
                        RescueRampByLegs="true", RescueSuspendsStaged="true",
                        UseStateRelease="true", StateReleaseMinMark="-200.0"),
    # 2026-08-26 (user directive): GOLD must get oil's tail organ — drawdown detected -> 1:1 freeze
    # -> hold -> release on a confirmed turn -> book recovers unhedged. The machinery is already in
    # the master (oil uses it: 34 freezes / 32 releases Dec->Aug, ZERO floors in the last 56d); gold
    # simply has UseFreezeHedge=false and runs the fib C RIDE instead. ⚠ They are MUTUALLY EXCLUSIVE
    # (`!UseFreezeHedge` gates the ride's loss-gated arm) -> this is a straight A/B of gold's PROTECT
    # organ, never tested directly on gold (the 08-06 doctrine inferred it from oil tests + fib C's
    # live record). Known answers on the 56d window: full-lot ride @3k = 740tr/91%DD staged-cut loop
    # (rescue NEVER armed); HALF ride @2350 = +$1,389/28%.
    "GOLD FRZ":  dict(GOLD_FIBC8, UseFreezeHedge="true"),                       # full lot, freeze instead of ride
    "GOLD FRZH": dict(GOLD_FIBC8, UseFreezeHedge="true", LotSize="0.01",
                      ProfitTargetUSD="50.0", RescueBookTargetUSD="20.0"),
    # round 2 (same day): the 8%-trigger freeze NEVER ARMED on gold (journal-verified) -> the FRZ/FRZH
    # cells accidentally measured something else: turning UseFreezeHedge ON also disables the RIDE's
    # deep-book gate-BYPASS (`!UseFreezeHedge` gates bookDeep), and THAT bypass is what generates the
    # extra flow (779 vs 59 trades at HALF). To test the freeze itself, the trigger must be low enough
    # to fire: gold's book rarely floats past -8% of balance once the bypass is off.
    "GOLD FRZ5":  dict(GOLD_FIBC8, UseFreezeHedge="true", RescueOnDrawdownPct="5.0"),
    "GOLD FRZ3":  dict(GOLD_FIBC8, UseFreezeHedge="true", RescueOnDrawdownPct="3.0"),
    "GOLD FRZ5H": dict(GOLD_FIBC8, UseFreezeHedge="true", RescueOnDrawdownPct="5.0",
                       LotSize="0.01", ProfitTargetUSD="50.0", RescueBookTargetUSD="20.0"),
    "GOLD FRZ3H": dict(GOLD_FIBC8, UseFreezeHedge="true", RescueOnDrawdownPct="3.0",
                       LotSize="0.01", ProfitTargetUSD="50.0", RescueBookTargetUSD="20.0"),
    # S34 (2026-08-27, user: "there is a gold version we haven't figured out yet"): the verbatim oil
    # freeze failed on gold for two OIL design choices (entries blocked while frozen = turnover starved;
    # release-on-bounce = re-drown on gold's sustained moves). One dial each, live HALF geometry, 5%%:
    "GOLD FZC2":  dict(GOLD_FIBC8, UseFreezeHedge="true", RescueOnDrawdownPct="5.0",
                       LotSize="0.01", ProfitTargetUSD="50.0", RescueBookTargetUSD="20.0",
                       MaxConcurrentBaskets="2", FreezeAllowEntries="true"),          # keep trading around the frozen basket
    "GOLD FZX":   dict(GOLD_FIBC8, UseFreezeHedge="true", RescueOnDrawdownPct="5.0",
                       LotSize="0.01", ProfitTargetUSD="50.0", RescueBookTargetUSD="20.0",
                       FreezeReleaseMode="1"),                                         # release only on EXHAUSTION
    "GOLD FZC2X": dict(GOLD_FIBC8, UseFreezeHedge="true", RescueOnDrawdownPct="5.0",
                       LotSize="0.01", ProfitTargetUSD="50.0", RescueBookTargetUSD="20.0",
                       MaxConcurrentBaskets="2", FreezeAllowEntries="true", FreezeReleaseMode="1"),      # live HALF geometry + freeze
    # S34 round 2 (user: "run the 8% cell"): exhaustion-release freeze at the RIDE's own 8% arm depth ->
    # fires only in the disaster class (5% fired 14-19x/9mo = every ordinary pullback). Last placement
    # not covered by the 08-27 table before the gold-freeze question closes.
    "GOLD FZX8":  dict(GOLD_FIBC8, UseFreezeHedge="true", RescueOnDrawdownPct="8.0",
                       LotSize="0.01", ProfitTargetUSD="50.0", RescueBookTargetUSD="20.0",
                       FreezeReleaseMode="1"),
})
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
            # 2026-09-04: stamp = master build + generation date, so a regenerated cell is DISTINGUISHABLE
            # from its predecessor (running-vs-disk check ⑥ needs it; the fixed 07-14 stamp hid the S36d gap)
            mb = re.search(r'EA_BUILD_VERSION\s+"MT5-(\d{4}-\d\d-\d\d)-(S\d+)', src)
            stamp = (mb.group(2) + "-" + __import__("datetime").date.today().strftime("%Y-%m-%d")) if mb else "2026-07-14"
            out.append(f'#define EA_BUILD_VERSION "GS-CELL-{tag.replace(" ","-")}-{stamp}"')
            continue
        out.append(ln)
    missing = set(values) - seen
    if missing: raise SystemExit(f"{tag}: unknown inputs {missing}")
    src2 = "\n".join(out)
    anchor = "int OnInit()\n{\n"
    deltas = ", ".join(f"{k}={v}" for k, v in values.items()
                       if k in ("MaxCompoundScale","AllowOppositeWhenDeep",
                                "OppositeWhenDeepPct","RescueMaxBaskets","RescueBookTargetUSD",
                                "RescueOnDrawdownPct","UseStateRelease","RescueTickArm",
                                "RescueTargetPctDeepest","RescueRearmCooldownBars",
                                "RescueImmediateLeg","RescueImmediateRatio","RescueRampByLegs",
                                "RescueSuspendsStaged","RescueBookSingle","RescueLockDir","UseRangeGuard","RangeGuardPct","UseVelocityGuard","VelocityGuardPct","StateReleaseMinMark","LotSize","ProfitTargetUSD"))
    guard = f'\n   Print("GRIDSTAT TEST CELL {tag} -- zero-input; deltas vs SF12 lock: {deltas}");\n'
    if anchor not in src2: raise SystemExit(f"{tag}: OnInit anchor missing")
    src2 = src2.replace(anchor, anchor + guard, 1)
    return f"//| GENERATED TEST CELL {tag} -- regen via gridstat_make_cells.py |\n" + src2 + "\n"

def main():
    import sys
    only = set(sys.argv[1:])
    src = io.open(MASTER, encoding="utf-8", errors="replace").read()
    for tag, values in CELLS.items():
        if only and tag not in only: continue
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
