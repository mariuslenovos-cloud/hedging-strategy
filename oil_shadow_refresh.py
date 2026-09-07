#!/usr/bin/env python3
"""
OIL SHADOW REFRESH — the missing half of the fingerprint cycle (built 2026-09-01).

Gold has had an automated weekly shadow refresh since 08-08 (morning_check Mondays), so
its research table is a day old. Oil never got one: its table was last rebuilt 2026-07-29
and is a month stale — through a crash-and-recovery cycle it actually traded. That matters
more on oil than anywhere else, because oil's live selector allows exactly TWO fingerprints
(both NY buys), so it has the least selection redundancy in the book. The project's own
verdict on this class is blunt: a stale, single-regime gate DB CAUSED the original live oil
bleed, and "live DB-refresh cadence" was greenlit on 07-30 and never built.

  python oil_shadow_refresh.py              # run the headless shadow, then audit
  python oil_shadow_refresh.py --audit-only # re-audit the last run without re-running it

⚠ THE NAMING TRAP THIS SCRIPT IS BUILT AROUND
Oil's LIVE files are literally named "_research":
    StatsCSVFile  = gridstat_setups_oil_research.csv     <- the live gate DB
    SizingCSVFile = gridstat_sizing_oil_research.csv     <- the live selector
So anything that "writes the research file" silently rewrites what the live EA trades off,
with no A/B. This script therefore writes ONLY to *_fresh.csv (shadow DB in Common\\Files so
the tester can reach it; candidate sizing in analysis_data/, never Common) and never touches
the deployed pair. Promotion stays manual, through gridstat_db_version.py, after a won A/B
(the 2026-08-08 NDB lesson: a fresh table must WIN, never auto-promote — promoting one there
produced a NEW 9-leg floor at -$1,197).

GEOMETRY is matched to the deployed table so the two are comparable: grisk=4, symmetric
barrier 0.8xATR, M5, from 2025.12.01 (verified against the deployed CSV: 438 rows,
2025.12.01 -> 2026.07.27, barrier/ATR ratio 0.80).

⚠ THE RUNNER IS THE WEAK LINK — AND THE FIRST RUN PROVED IT (2026-09-01)
Re-running the DEPLOYED WINDOW EXACTLY on XM today returns 348 signals where the deployed
table has 438: -20.5%, and XM's OILCash history now ends 4 days earlier. XM is formally
retired from testing precisely because its tick history revises. The consequence is not
academic: BUY|HR_NY|ATR_EXP (one of oil's only two tradeable fingerprints) reads
avgR +0.312 / mult 1.00 on the deployed data and avgR -0.192 / mult 0.00 on the re-run --
IDENTICALLY in the control and the extended run, i.e. the "flip" is 100% feed drift and 0%
new information. Acting on it would have dropped a live fingerprint for nothing.

So this script now runs its OWN CONTROL CELL first (same geometry, the deployed window
exactly) and VOIDS its report if the signal count has moved more than DRIFT_TOL. A refresh
whose baseline cannot be reproduced is not evidence.

RESOLVED 2026-09-01: the runner IS now the deployment feed. The long-standing blocker --
"the PEP tester agent does not land FILE_COMMON CSVs in shared Common\Files" (the copper
gotcha) -- was tested directly and does NOT hold for this portable install: a SpotCrude
shadow run wrote 62 KB straight to the shared folder. XM is retired from this pipeline.
"""
import os, io, csv, sys, time, subprocess
from datetime import datetime

import gridstat_rigor as rigor
from gridstat_analyser import load_signals

HERE = os.path.dirname(os.path.abspath(__file__))
ADIR = os.path.join(HERE, "analysis_data")
COMMON = r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\Common\Files"
SCRATCH = os.path.join(ADIR, "tester_ini")
# Launch stamps (2026-09-07). A tool that checks only that a CSV EXISTS re-reads the LAST
# run's table when a launch fails and presents it as today's certified read -- which is
# exactly what happened on 09-07 (the runner could not authorize, the tester never ran, and
# the brief published the 09-01 numbers as today's). A produced file must be NEWER than the
# launch that was supposed to write it.
LAUNCH_T = {}
MTIME_SLACK = 5.0   # seconds; clock/FS granularity
# RUNNER = the PEP Runner (2026-09-01 migration). The documented blocker — "the PEP tester
# agent does not land FILE_COMMON CSVs in shared Common\Files" — was tested and is NOT true
# of this portable install: a shadow run wrote 62 KB straight to the shared folder. XM is
# retired (its oil history drifted -20.5% in a month) and must not be used again.
RUNNER   = r"C:\MT5 Pepperstone Runner\terminal64.exe"
SETDIR   = r"C:\MT5 Pepperstone Runner\MQL5\Profiles\Tester"
SYMBOL   = "SpotCrude"                 # PEP name (XM called it OILCash)
BASE_END = "2026.08.27"                # the window the stored PEP baseline covers

FRESH_DB     = "gridstat_setups_oil_fresh.csv"            # written by the tester (Common\Files)
DEPLOYED_DB  = "gridstat_setups_oil_research.csv"         # what the live EA reads — READ ONLY
DEPLOYED_SZ  = "gridstat_sizing_oil_research.csv"         # what the live EA reads — READ ONLY
CAND_SZ      = os.path.join(ADIR, "gridstat_sizing_oil_fresh.csv")   # candidate, never Common
CTL_DB       = "gridstat_setups_oil_ctl.csv"              # control: the deployed window, re-run
DRIFT_TOL    = 0.05                                       # >5% signal-count move = feed drift
PEP_BASE     = "gridstat_setups_oil_pepbase.csv"          # the PEP-built baseline the control reproduces

# ---------------------------------------------------------------------------------
# ⚠ THE DEPLOYED OIL SIZING TABLE IS HAND-CURATED, NOT rigor's OUTPUT.
# Control cell run 2026-09-01: rebuilding it from its own shadow DB with gridstat_rigor
# reproduces only 3 of 15 multipliers. The other 12 are deliberate TRADE-MODE overrides
# from the 07-30 redesign, and the deployed tier text carries the reasons:
#   - every SELL is shadow-POSITIVE and grid-NEGATIVE ("R11: drowned+starved slots",
#     measured -$418) -> zeroed, reachable only via UseRegimeSells in a down regime
#   - BUY|HR_OVL|ATR_EXP = the old 2x star, measured DEAD (uptrend beta)
#   - BUY|HR_NY|ATR_NORM trimmed 1.50 -> 1.00
# rigor scores SHADOW expected-R; it cannot see what a fingerprint does inside a grid.
# So a mechanical diff re-proposes exactly what was rejected. These are listed as
# OVERRIDE RE-PROPOSAL and must never be read as candidates.
OVERRIDES = {
    "SELL|HR_OVL|ATR_EXP":  "S18 law: shadow-positive, grid-negative (R11 -$418) — crash-state only",
    "SELL|HR_OVL|ATR_NORM": "crash-state only (UseRegimeSells bypass)",
    "SELL|HR_NY|ATR_COMP":  "crash-state only (UseRegimeSells bypass)",
    "SELL|HR_LDN|ATR_NORM": "crash-state only (UseRegimeSells bypass)",
    "SELL|HR_NY|ATR_NORM":  "S18 law: oil sells are grid-negative unconditionally",
    "SELL|HR_NY|ATR_EXP":   "thin + S18 law",
    "SELL|HR_LDN|ATR_EXP":  "thin + S18 law",
    "SELL|HR_LDN|ATR_COMP": "thin + S18 law",
    "BUY|HR_OVL|ATR_EXP":   "measured DEAD 07-30 (old 2x star = pure uptrend beta)",
    "BUY|HR_OVL|ATR_NORM":  "measured DEAD 07-30",
    "BUY|HR_LDN|ATR_NORM":  "measured DEAD 07-30 (9/mo bleeder)",
    "BUY|HR_LDN|ATR_EXP":   "measured NEGATIVE 07-30 (thin)",
    "BUY|HR_NY|ATR_COMP":   "measured DEAD 07-30",
}

try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass


def run_shadow():
    os.makedirs(SCRATCH, exist_ok=True)
    setf = os.path.join(SETDIR, "oil_shadow.set")
    ini = os.path.join(SCRATCH, "oil_shadow.ini")
    # geometry matched to the deployed table (grisk 4, symmetric 0.8xATR)
    lines = ["StatsCollectionMode=true", f"StatsCSVFile={FRESH_DB}", "grisk=4",
             "BarrierATRMultiplier=0.8", "BarrierATRUpper=0", "BarrierATRLower=0",
             "UseSignalLog=false"]
    io.open(setf, "w", encoding="utf-16-le").write("\ufeff" + "\n".join(lines) + "\n")
    # BOM-LESS utf-8 (a BOM makes MT5 silently ignore [Tester] and start NORMALLY) +
    # the [Experts] kill-switch (XM charts carry ARMED locked EAs — 2026-08-18 incident).
    io.open(ini, "w", encoding="utf-8").write(
        "[Experts]\nEnabled=0\nAllowLiveTrading=0\n\n"
        # [Common] login (2026-09-07): without this the runner authorizes as its STORED
        # account -- the broker-EXPIRED demo 61552687 -- and the tester never starts
        # ("Invalid account" -> "terminal is not synchronized with the trade server").
        # The same fix went into rolling_retest.py on 09-03 and was never applied here.
        "[Common]\nLogin=61586543\nServer=Pepperstone-Demo\n\n"
        "[Tester]\nExpert=Marius GridStat MT5 v1.0\nExpertParameters=oil_shadow.set\n"
        f"Symbol={SYMBOL}\nPeriod=M5\nModel=1\nFromDate=2025.12.01\n"
        f"ToDate={datetime.now():%Y.%m.%d}\nDeposit=3000\nOptimization=0\n"
        "Report=oil_shadow_report\nReplaceReport=1\nShutdownTerminal=1\n")
    print(f"launching headless oil shadow on the XM runner (OILCash M5, "
          f"2025.12.01 -> {datetime.now():%Y.%m.%d}) ...")
    LAUNCH_T["fresh"] = time.time()
    try:
        r = subprocess.run([RUNNER, "/portable", f"/config:{ini}"], timeout=1800)
        LAUNCH_T["fresh_end"] = time.time()
        print(f"  tester exit code {r.returncode}")
        ok_log, note_log = runner_log_ok(LAUNCH_T["fresh"], LAUNCH_T["fresh_end"])
        print(f"  run precondition: {note_log}")
        return True
    except Exception as e:
        print(f"  !! shadow run failed: {e}")
        return False


def run_control():
    """THE CONTROL CELL: identical geometry, the DEPLOYED window exactly. If today's runner
    cannot reproduce the signal count the deployed table was built from, the feed has moved
    and no comparison against that table means anything."""
    os.makedirs(SCRATCH, exist_ok=True)
    setf = os.path.join(SETDIR, "oil_ctl.set")
    ini = os.path.join(SCRATCH, "oil_ctl.ini")
    lines = ["StatsCollectionMode=true", f"StatsCSVFile={CTL_DB}", "grisk=4",
             "BarrierATRMultiplier=0.8", "BarrierATRUpper=0", "BarrierATRLower=0",
             "UseSignalLog=false"]
    io.open(setf, "w", encoding="utf-16-le").write("\ufeff" + "\n".join(lines) + "\n")
    io.open(ini, "w", encoding="utf-8").write(
        "[Experts]\nEnabled=0\nAllowLiveTrading=0\n\n"
        # [Common] login (2026-09-07): without this the runner authorizes as its STORED
        # account -- the broker-EXPIRED demo 61552687 -- and the tester never starts
        # ("Invalid account" -> "terminal is not synchronized with the trade server").
        # The same fix went into rolling_retest.py on 09-03 and was never applied here.
        "[Common]\nLogin=61586543\nServer=Pepperstone-Demo\n\n"
        "[Tester]\nExpert=Marius GridStat MT5 v1.0\nExpertParameters=oil_ctl.set\n"
        f"Symbol={SYMBOL}\nPeriod=M5\nModel=1\nFromDate=2025.12.01\nToDate={BASE_END}\n"
        "Deposit=3000\nOptimization=0\nReport=oil_ctl_report\nReplaceReport=1\n"
        "ShutdownTerminal=1\n")
    print(f"control cell: re-running the PEP baseline window (2025.12.01 -> {BASE_END}) ...")
    LAUNCH_T["ctl"] = time.time()
    try:
        subprocess.run([RUNNER, "/portable", f"/config:{ini}"], timeout=1800)
        LAUNCH_T["ctl_end"] = time.time()
        ok_log, note_log = runner_log_ok(LAUNCH_T["ctl"], LAUNCH_T["ctl_end"])
        print(f"  run precondition: {note_log}")
        return True
    except Exception as e:
        print(f"  !! control run failed: {e}")
        return False


RUNNER_LOGS = os.path.join(os.path.dirname(RUNNER), "logs")


def runner_log_ok(t0, t1=None):
    """(ok, note) -- did the launch that started at t0 AUTHORIZE and SYNCHRONIZE?

    2026-09-07: this tool launched the runner with no [Common] Login, so it authorized as the
    broker-EXPIRED demo 61552687, logged "Invalid account" and "terminal is not synchronized
    with the trade server before start automatic testing [0]" -- and then RAN ANYWAY on
    whatever offline history was on disk, writing a CSV that looked like a normal result.
    That is the same silent failure that froze the runner's history at 2026-08-28 for four
    days (Bug Log 09-03). A produced file is not evidence; the run's own log is.
    Mirrors framework_check (7)."""
    log = os.path.join(RUNNER_LOGS, f"{datetime.now():%Y%m%d}.log")
    if not os.path.exists(log):
        return False, f"no runner log {os.path.basename(log)} -- cannot certify the run"
    try:
        txt = io.open(log, encoding="utf-16", errors="replace").read()
    except Exception as e:
        return False, f"runner log unreadable: {e}"
    start = datetime.fromtimestamp(t0 - MTIME_SLACK).strftime("%H:%M:%S")
    end = datetime.fromtimestamp((t1 or time.time()) + MTIME_SLACK).strftime("%H:%M:%S")
    bad = []
    for ln in txt.splitlines():
        parts = ln.split("\t")
        if len(parts) < 3:
            continue
        stamp = parts[2].strip()[:8]
        if len(stamp) != 8 or stamp[2] != ":" or not (start <= stamp <= end):
            continue
        if "Invalid account" in ln or "authorization on" in ln and "failed" in ln:
            bad.append("login REFUSED (" + ln.split("Network")[-1].strip()[:70] + ")")
        elif "not synchronized with the trade server" in ln:
            bad.append("history NOT synchronized before the test started")
    if bad:
        return False, "; ".join(dict.fromkeys(bad))
    return True, "runner authorized and synchronized"


def produced_by_this_run(path, key):
    """(ok, note). ok=False means the file on disk is a PREVIOUS run's output and must not
    be read as today's result. With no launch stamp (--audit-only) nothing is voided, but
    the file's age is always reported so a stale re-read is visible rather than silent."""
    age_h = (time.time() - os.path.getmtime(path)) / 3600
    if key not in LAUNCH_T:
        return True, f"written {age_h:.1f}h ago (no launch this run)"
    if os.path.getmtime(path) < LAUNCH_T[key] - MTIME_SLACK:
        return False, (f"STALE: written {age_h:.1f}h ago, BEFORE this run's launch -- "
                       f"the tester did not produce it")
    return True, f"written {age_h*60:.0f} min ago by this run"


def drift_gate():
    """Returns (ok, message). ok=False means the report must be treated as VOID."""
    cp, dp = os.path.join(COMMON, CTL_DB), os.path.join(COMMON, PEP_BASE)
    if not os.path.exists(cp):
        return False, "control cell did not produce a CSV — cannot certify the feed"
    fresh_ok, note = produced_by_this_run(cp, "ctl")
    if not fresh_ok:
        return False, f"control CSV {note} — cannot certify the feed"
    if "ctl" in LAUNCH_T:
        log_ok, log_note = runner_log_ok(LAUNCH_T["ctl"], LAUNCH_T.get("ctl_end"))
        if not log_ok:
            return False, (f"the control run did not authorize/synchronize: {log_note} — it\n           tested on whatever offline history was on disk, so the table it produced is not a\n           certified read of the deployment feed")
    if not os.path.exists(dp):
        return False, f"no PEP baseline ({PEP_BASE}) — run once to establish it"
    c, d = len(load_signals(path=cp)), len(load_signals(path=dp))
    drift = (c - d) / d
    msg = (f"control {c} signals vs deployed {d} on the SAME window "
           f"({drift:+.1%})")
    return abs(drift) <= DRIFT_TOL, msg


def table(path):
    """fingerprint -> rigor stats (expected R, t, eff_n, candidate multiplier)."""
    if not os.path.exists(path):
        return None
    return rigor.build(load_signals(path=path))


def audit():
    fresh_path = os.path.join(COMMON, FRESH_DB)
    if not os.path.exists(fresh_path):
        print(f"!! {FRESH_DB} not found in Common\\Files — did the tester run land?")
        print("   (the PEP tester agent does NOT write FILE_COMMON; that is why this runs on XM)")
        return 2
    fresh_ok, note = produced_by_this_run(fresh_path, "fresh")
    print(f"   {FRESH_DB}: {note}")
    if fresh_ok and "fresh" in LAUNCH_T:
        lok, lnote = runner_log_ok(LAUNCH_T["fresh"], LAUNCH_T.get("fresh_end"))
        if not lok:
            fresh_ok, note = False, (f"the shadow run did not authorize/synchronize: {lnote}"
                                     " — it tested on offline history")
    if not fresh_ok:
        print(f"!! ⛔ REPORT VOID: {FRESH_DB} is a PREVIOUS run's table. The launch did not")
        print("   land (check the runner's Tester log for 'Invalid account' / 'not synchronized').")
        print("   Nothing below would be today's read. Deployed config stands unchanged.")
        return 2
    fresh = table(fresh_path)
    if not fresh:
        print("!! fresh shadow produced no usable rows"); return 2

    ok, msg = drift_gate()
    print(f"\n=== FEED CONTROL === {msg}")
    if not ok:
        print("  ⛔ VOID: the runner cannot reproduce the table this comparison is against.")
        print("     Every 'would-change' below would be feed drift, not signal. The deployed")
        print("     config stands unchanged. Fix the runner (see the module docstring) before")
        print("     reading anything from this refresh.")
    else:
        print("  ✓ feed reproduces the deployed baseline — differences below are real change.")

    rows = load_signals(path=fresh_path)
    print(f"\nFRESH oil shadow: {len(rows)} signals, "
          f"{rows[0]['entry_time']} -> {rows[-1]['entry_time']}")
    dep_rows = load_signals(path=os.path.join(COMMON, DEPLOYED_DB))
    print(f"DEPLOYED table  : {len(dep_rows)} signals, "
          f"{dep_rows[0]['entry_time']} -> {dep_rows[-1]['entry_time']}  (what the EA trades)")

    # candidate sizing (analysis_data only — NEVER Common)
    rigor.write_sizing_csv(fresh, CAND_SZ)

    deployed = {r["setup_key"].strip(): float(r["size_mult"])
                for r in csv.DictReader(io.open(os.path.join(COMMON, DEPLOYED_SZ),
                                                encoding="utf-8", errors="replace"))}
    print("\n=== WOULD-CHANGE REPORT (fresh vs deployed selector) ===")
    print(f"{'fingerprint':30}{'depl':>6}{'fresh':>7}{'effN':>7}{'avgR':>8}{'t':>6}  verdict")
    flips, moves, news = [], [], []
    for k in sorted(set(fresh) | set(deployed)):
        d = deployed.get(k)
        f = fresh.get(k)
        fm = f["mult"] if f else None
        if d is None:
            news.append(k)
            verdict = "NEW FINGERPRINT — not in the deployed table"
        elif fm is None:
            verdict = "absent from fresh window (no signals)"
        elif (d > 0) != (fm > 0):
            if fm > 0 and k in OVERRIDES:
                verdict = f"override re-proposal — {OVERRIDES[k]}"
            elif fm > 0:
                flips.append(k)
                verdict = "WOULD ADMIT (deployed skips it, no standing override)"
            else:
                flips.append(k)
                verdict = "⚠ WOULD DROP — a fingerprint the engine CURRENTLY TRADES"
        elif fm != d:
            moves.append(k)
            verdict = f"size change {d:.2f} -> {fm:.2f}"
        else:
            verdict = "unchanged"
        print(f"{k:30}{('  -' if d is None else f'{d:.2f}'):>6}"
              f"{('   -' if fm is None else f'{fm:.2f}'):>7}"
              f"{(f['eff_n'] if f else 0):>7.1f}{(f['avg_r'] if f else 0):>8.3f}"
              f"{(f['t'] if f else 0):>6.2f}  {verdict}")

    print("\n--- SUMMARY (override re-proposals excluded: rigor scores SHADOW R and cannot"
          "\n    see grid behaviour, so it re-proposes what trade-mode already rejected) ---")
    print(f"  side flips (admit/drop): {len(flips)}  {flips if flips else ''}")
    print(f"  size changes only      : {len(moves)}  {moves if moves else ''}")
    print(f"  new fingerprints       : {len(news)}  {news if news else ''}")
    if not ok:
        print("\n  ⛔ REPORT VOID (feed control failed) — do NOT action any line above.")
    elif flips or news:
        print("\n  ⚠ A/B REQUIRED before any promote. A side flip changes which signals the")
        print("    engine takes; the 2026-08-08 NDB lesson is that a fresh table must WIN an")
        print("    A/B on the deployment feed, never be promoted because it looks better.")
        print("    Candidate sizing written to analysis_data/ only — live config untouched.")
    else:
        print("\n  ✓ no side flips and no new fingerprints: the deployed selector still")
        print("    reflects the fresh window. Production stands, no action.")
    print(f"\ncandidate sizing -> {CAND_SZ}")
    print(f"deployed pair UNTOUCHED: {DEPLOYED_DB} / {DEPLOYED_SZ}")
    return 0


def main():
    if "--audit-only" not in sys.argv:
        if not run_control():
            return 2
        if not run_shadow():
            return 2
    return audit()


if __name__ == "__main__":
    sys.exit(main())
