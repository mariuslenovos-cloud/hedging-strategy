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
    # round 2 (2026-07-13): grisk re-tune -- MORE signals of RETUNED quality
    # (GridStat gold precedent: 7->4 = +52% net at same DD). Guards stay at
    # the F1 baseline (D1 on, gate 0.55/0.65) -- one variable per cell.
    "G5": {"grisk": "5"},
    "G4": {"grisk": "4"},
    # round 3 (2026-07-13, user directive: fib C frequency stays OPEN):
    # (i) EXIT-FLOW PAIRING -- rounds 1-2 changed entries against exits tuned
    #     for sparse flow (F2 harvested $17.1k gross at PF 1.25 = conversion
    #     problem, not flow problem). Pair denser streams with FASTER exits.
    "F1X": {"MinFloatToActivate": "40.0", "BasketTrailAmount": "10.0"},
    "F2X": {"UseDailyTrendFilter": "false",
            "MinFloatToActivate": "40.0", "BasketTrailAmount": "10.0"},
    "G4X": {"grisk": "4",
            "MinFloatToActivate": "40.0", "BasketTrailAmount": "10.0"},
    # (ii) SESSION WIDEN -- census: ~40% of signals fall outside 9-23.
    "F1S": {"SessionStartHour": "2"},
    # (iii) BREADTH -- fib C is symbol-agnostic; run these on a SILVER M5
    #     chart. SLV1 gates first entries on SILVER's own validated DB;
    #     SLV2 = gate off (fib C's original ungated design).
    "SLV1": {"FirstGateStatsCSV": '"gridstat_setups_silver_mt5.csv"'},
    "SLV2": {"UseFirstEntryGate": "false"},
    # round 4 (2026-07-13): F1X (trail 40/10) = best fib C on record
    # (RF 2.06->3.62, eqDD 27.5->17.9%, net UP). Plateau check around it:
    "XA": {"MinFloatToActivate": "30.0", "BasketTrailAmount": "10.0"},
    "XB": {"MinFloatToActivate": "50.0", "BasketTrailAmount": "10.0"},
    "XC": {"MinFloatToActivate": "40.0", "BasketTrailAmount": "15.0"},
    "XD": {"MinFloatToActivate": "60.0", "BasketTrailAmount": "10.0"},
    # round 5 (2026-07-14): the GridStat capital campaign's lesson flows BACK --
    # fib C's cap=3 was locked pre-XC-exit and cap 2 was NEVER tested (only 3/4/
    # uncapped). GridStat: cap 2 = growth-optimal, cap 1 = fortress. These cells
    # = the LOCKED XC config (trail 40/15) with only the cap changed.
    "CAP2": {"MinFloatToActivate": "40.0", "MaxCompoundScale": "2"},
    "CAP1": {"MinFloatToActivate": "40.0", "MaxCompoundScale": "1"},
    # round 6 (2026-07-14, build L): the $10k resolution levers -- staged floor
    # (gold SF12 port; the Apr-14 -$3,516 full-ladder floor realization is gold's
    # exact anatomy) + scale anchor (cold-start protection that PRESERVES fib C's
    # lot/threshold proportions, unlike the cap). All on the locked XC exit.
    "SF":   {"MinFloatToActivate": "40.0", "UseStagedFloor": "true"},
    "ANCH": {"MinFloatToActivate": "40.0", "ScaleAnchorBalance": "10000"},
    "SFA":  {"MinFloatToActivate": "40.0", "UseStagedFloor": "true",
             "ScaleAnchorBalance": "10000"},
    # round 7 (2026-07-20, user directive: fib C MUST trade more AND stay in
    # profit). Census finding: the ADX>25 trend-detection gate blocks 69% of
    # in-session Goldminer signals -- the single biggest throttle, and the ONLY
    # entry gate never swept for fib C. It sits UPSTREAM of the FirstEntryGate,
    # so relaxing it feeds ~2.5x more candidates into the WIN-RATE screen without
    # loosening quality (unlike grisk-down G4/G5, D1-off F2, sell-gate F3 -- all
    # rejected). Base = the LOCKED XC exit (trail 40/15); only ADX changes.
    "AX20": {"MinFloatToActivate": "40.0", "ADX_Threshold": "20.0"},
    "AX18": {"MinFloatToActivate": "40.0", "ADX_Threshold": "18.0"},
    "AX15": {"MinFloatToActivate": "40.0", "ADX_Threshold": "15.0"},
    # round 8 (2026-07-20): AX20 (ADX 20) hit the brief -- +57% trades, +26% net,
    # RF 3.03, extra flow net-POSITIVE (+$1k on 86 more trades). But 2 deep
    # weak-trend baskets (-$826/-$757) enlarged the loss tail. Cap the fib ladder
    # (gentler deep legs -> smaller floating baskets -> smaller floor losses) to
    # trim that tail while KEEPING the AX20 frequency. 3 = 1,1,2,3,3,3; 4 = 1,1,2,3,4,4.
    "AX20M3": {"MinFloatToActivate": "40.0", "ADX_Threshold": "20.0", "MaxFibMult": "3"},
    "AX20M4": {"MinFloatToActivate": "40.0", "ADX_Threshold": "20.0", "MaxFibMult": "4"},
    # round 9 (2026-08-08, build N WHIPSAW recalibration -- the Aug-5/6 V-reversal
    # floor autopsy + the N0 April/May episode census). Base = the LOCKED XC config
    # (MinFloat 40 / trail 15 / cap 3 / lot 0.02 = master defaults + MinFloat).
    # Ladder adds ONE lever per cell; run on BOTH feeds (PEP-STAGE primary, XM check).
    "N0": {"MinFloatToActivate": "40.0"},
    "N1": {"MinFloatToActivate": "40.0", "HedgeTriggerATRMult": "0.75"},
    "N2": {"MinFloatToActivate": "40.0", "HedgeTriggerATRMult": "0.75",
           "UseRideBrake": "true"},
    "N3": {"MinFloatToActivate": "40.0", "HedgeTriggerATRMult": "0.75",
           "UseRideBrake": "true", "RecoveryPeakBankPct": "75.0"},
    # round 9b (2026-08-08): P-N1 REJECTED the ATR trigger decisively (PEP: $3,979/RF 4.10/zero losing
    # episodes -> $887/RF 0.67/two -$1k floors). Delayed arming = deeper drowning before the rescue
    # starts; EARLY arming is a FEATURE on the deployment feed. The April-XM disease was the ride's
    # top-ADDS, not the arming -> test brake + peak-bank ALONE on the N0 base (no ATR trigger).
    "N2B": {"MinFloatToActivate": "40.0", "UseRideBrake": "true"},
    "N3B": {"MinFloatToActivate": "40.0", "RecoveryPeakBankPct": "75.0"},
    "N4":  {"MinFloatToActivate": "40.0", "UseRideBrake": "true", "RecoveryPeakBankPct": "75.0"},
    # round 10 (2026-08-08): the GOLD DB REFRESH A/B — one variable: the entry-gate DB.
    # Fresh 455-signal both-regime shadow (built headless via tester-CLI = the Layer-3 spike)
    # vs FIBC N0 (June DB). Audit verdict: table CONFIRMED (no oil-style inversion);
    # SELL|HR_NY|ATR_EXP 80%n5 -> 60%n10 = the thin cell properly demoted.
    "NDB": {"MinFloatToActivate": "40.0",
            "FirstGateStatsCSV": '"gridstat_setups_gold_research.csv"'},
    # round 11 (2026-08-24, build P STATE-RELEASE -- the adaptive rework's first lever;
    # pilots fibc_inflight*/fibc_policy_sim*: in-flight state separates V-turns from rescues
    # (p=0.000, halves stable); specimen replay releases the Aug-19 demo floor at -$233
    # instead of -$1,306 while leaving clean rescues untouched. Base = the XC lock (N0).
    "SR1": {"MinFloatToActivate": "40.0", "UseStateRelease": "true"},
    "SR2": {"MinFloatToActivate": "40.0", "UseStateRelease": "true",
            "StateReleaseMinMark": "-300.0"},
    # round 11b (2026-08-24): SR1's B-run = curb signature (worst ep -810 -> -269 and eqDD down,
    # but net $2,857 -> $974 = the per-tick trigger firing inside ordinary rescues, mostly via the
    # pos-leg on transient wobbles). Refinements: drop the pos leg / age-gate / persistence.
    "SR3": {"MinFloatToActivate": "40.0", "UseStateRelease": "true", "SR_UsePosLeg": "false"},
    "SR4": {"MinFloatToActivate": "40.0", "UseStateRelease": "true", "SR_MinAgeHours": "12.0"},
    "SR5": {"MinFloatToActivate": "40.0", "UseStateRelease": "true", "SR_UsePosLeg": "false",
            "SR_MinAgeHours": "12.0", "SR_ConfirmMins": "30.0"},
    # round 11c (2026-08-24): SR2 (release + MinMark -300) = the standout (net -5.7%% vs control,
    # PF 1.47->2.00, RF 1.84->2.95, worst ep -810->-169). Plateau check on the MinMark dial.
    "SR6": {"MinFloatToActivate": "40.0", "UseStateRelease": "true", "StateReleaseMinMark": "-200.0"},
    "SR7": {"MinFloatToActivate": "40.0", "UseStateRelease": "true", "StateReleaseMinMark": "-400.0"},
    # round 11d (2026-08-24): SR6 PASSED the PEP-STAGE full-tick confirm (N0 $2,860/PF 1.47/RF 1.83/
    # worst -810 vs SR6 $2,696/PF 2.00/RF 2.96/worst -169; locked-EA anchor byte-identical to N0).
    # SR6F = the FORWARD instance: own magic 4902 so it runs BESIDE the demo's fib C LOCKED (4901)
    # without the documented magic-collision disease (08-04/08-18 lesson).
    "SR6F": {"MinFloatToActivate": "40.0", "UseStateRelease": "true",
             "StateReleaseMinMark": "-200.0", "MagicSeed": "4902"},
}
PEP_EXPERTS = r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\C54C4DDE98E7B1FB905AFE04A9333631\MQL5\Experts"
PEP_METAED  = r"C:\Program Files\Pepperstone MetaTrader 5\MetaEditor64.exe"
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
    deltas = ", ".join(f"{k}={v}".replace('"', "'") for k, v in values.items()) or "none (baseline)"
    guard = f'\n   Print("FIBC TEST CELL {tag} -- zero-input build; deltas: {deltas}");\n'
    if anchor not in src2: raise SystemExit(f"{tag}: OnInit anchor missing")
    src2 = src2.replace(anchor, anchor + guard, 1)
    hdr = (f"//| GENERATED TEST CELL {tag} -- do not edit; regen via fibc_make_cells.py |\n")
    return hdr + src2 + "\n"

def compile_log(log):
    for enc in ("utf-16", "cp1252"):
        try:
            lines = [l for l in io.open(log, encoding=enc).read().splitlines() if "Result" in l]
            if lines: return lines[-1].strip()
        except Exception: continue
    return "?"

def main():
    import sys
    only = set(sys.argv[1:])            # e.g. `python fibc_make_cells.py N0 N1 N2 N3`
    src = io.open(MASTER, encoding="utf-8", errors="replace").read()
    results = []
    for tag, values in CELLS.items():
        if only and tag not in only: continue
        fname = f"FIBC {tag}.mq5"
        path = os.path.join(EXPERTS, fname)
        io.open(path, "w", encoding="utf-8").write(transform(src, tag, values))
        log = path[:-4] + "_compile.log"
        subprocess.run(f'"{METAED}" /compile:"{path}" /log:"{log}"', check=False)
        results.append((fname + " [XM]", compile_log(log)))
        # deploy to PEP-STAGE + compile with ITS MetaEditor (PEP = primary fib C bench)
        ppath = os.path.join(PEP_EXPERTS, fname)
        io.open(ppath, "w", encoding="utf-8").write(io.open(path, encoding="utf-8").read())
        plog = ppath[:-4] + "_compile.log"
        subprocess.run(f'"{PEP_METAED}" /compile:"{ppath}" /log:"{plog}"', check=False)
        results.append((fname + " [PEP]", compile_log(plog)))
        io.open(os.path.join(EA_DIR, fname), "w", encoding="utf-8").write(
            io.open(path, encoding="utf-8").read())
    print("\n=== FIBC CELL BUILDS ===")
    for f, r in results: print(f"{f:22s} {r}")

if __name__ == "__main__":
    main()
