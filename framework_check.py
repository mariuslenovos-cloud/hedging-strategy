#!/usr/bin/env python3
"""
FRAMEWORK CHECK — the control cell for the OBSERVABILITY layer (built 2026-09-01).

WHY THIS EXISTS
---------------
Three defects were found in two days, and all three were SILENT — the tools kept
printing plausible numbers while measuring nothing:

  1. episode_auditor.realized_net  read deal history up to LOCAL now() while MT5 stamps
     deals in SERVER time (+3h here) -> every episode's CLOSING batch was dropped.
     38 of 47 ledger rows read 0.00; the 08-21 oil floor read +938.49 with its
     -584.32 floor cut missing.
  2. gridstat_fingerprint_register judged oil against the win-rate gate, but oil's real
     selector is its SIZING TABLE -> the board showed 13 oil fingerprints as "Trading"
     with size-up progress when the engine can trade 2.
  3. mission_control / gridstat_dashboard / episode_auditor all keyed OIL to magic 66705
     (the retired RSQ2 build). Live oil is 77180 -> +$455 of live oil P&L across both
     accounts was invisible, and live oil had NO fragility ledger at all.

THE COMMON ROOT CAUSE: the house rule [[validate-pipeline-against-known-anchor]] — every
optimization table must contain a control cell reproducing a known result — was applied
religiously to BACKTESTS and never once to the MONITORING stack. A backtest that breaks
looks broken. A monitor that breaks looks calm.

So this is the monitoring layer's control cell. It reconciles each tool against the
account's own deal history and against the files the locked EAs actually name, and it
FAILS LOUDLY. Read-only; it never trades and never edits.

    python framework_check.py            # full check, exit 1 if anything FAILS
    python framework_check.py --quiet    # summary only (for the morning brief)

WHAT IT CANNOT DO: prove a number is economically right. It proves the plumbing carries
what it claims to carry. Judgement stays yours.
"""
import os, io, csv, sys, glob, time, importlib
from datetime import datetime, timedelta
from collections import defaultdict

import re
import MetaTrader5 as mt5

HERE = os.path.dirname(os.path.abspath(__file__))
ADIR = os.path.join(HERE, "analysis_data")
COMMON = os.path.expandvars(r"%APPDATA%\MetaQuotes\Terminal\Common\Files")
WINDOW_DAYS = 30
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass

ACCOUNTS = {
    "LIVE": (r"C:\Program Files\Pepperstone MetaTrader 5\terminal64.exe", 51511633),
    "DEON": (r"C:\MT5 Pepperstone Instance Deon\terminal64.exe", 51527827),
    "DEMO": (r"C:\MT5 Pepperstone Instance 2\terminal64.exe", 61586543),
}

# The files each LOCKED EA actually names. If one of these goes missing or gets renamed,
# the EA silently gates every signal out and the equity curve just flattens.
EA_FILES = {
    "oil gate DB  (OIL SOLID LOCKED)":   "gridstat_setups_oil_research.csv",
    "oil sizing   (OIL SOLID LOCKED)":   "gridstat_sizing_oil_research.csv",
    "gold gate DB (GOLD * LOCKED/fibC)": "gridstat_setups_gold.csv",
}

RESULTS = []
def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"\n         {detail}" if detail else ""))
    return ok


def connect(path, login):
    for _ in range(4):
        mt5.shutdown()
        if mt5.initialize(path=path):
            ai = mt5.account_info()
            if ai and ai.login == login:
                return ai
        time.sleep(1.5)
    return None


def truth_by_magic(days=WINDOW_DAYS):
    """GROUND TRUTH: closed positions per (magic, symbol), attributed by the OPENING deal's
    magic (a manual/forced close carries magic 0, so the closing deal cannot be trusted)."""
    frm = datetime.now() - timedelta(days=days)
    to = datetime.now() + timedelta(days=1)          # +1d: deal times are SERVER time
    deals = mt5.history_deals_get(frm, to) or []
    opens = {d.position_id: (d.magic, d.symbol) for d in deals if d.entry == 0}
    agg = defaultdict(lambda: [0, 0.0])
    total = 0.0
    for d in deals:
        if d.entry == 1 and d.position_id in opens:
            m, s = opens[d.position_id]
            net = d.profit + d.swap + d.commission
            agg[(m, s)][0] += 1
            agg[(m, s)][1] += net
            total += net
    return agg, round(total, 2)


def watched_magics():
    """What each tool claims to watch. Imported, not re-declared, so this can never drift
    from the tools themselves."""
    out = {}
    try:
        ea = importlib.import_module("episode_auditor")
        out["episode_auditor"] = {a: set(c["streams"]) for a, c in ea.ACCOUNTS.items()}
    except Exception as e:
        out["episode_auditor"] = {"_error": str(e)}
    try:
        mc = importlib.import_module("mission_control")
        out["mission_control"] = {"LIVE": set(mc.STREAMS)}
    except Exception as e:
        out["mission_control"] = {"_error": str(e)}
    try:
        gd = importlib.import_module("gridstat_dashboard")
        out["gridstat_dashboard"] = {"LIVE": set(gd.MAGICS)}
    except Exception as e:
        out["gridstat_dashboard"] = {"_error": str(e)}
    return out


def check_time_basis():
    """CLASS 1 — a deal-history query bounded by LOCAL now() silently drops everything that
    closed within the server offset. Probe the offset, then assert every call site is safe."""
    print("\n① TIME BASIS (the realized_net bug class)")
    tick = mt5.symbol_info_tick("XAUUSD") or mt5.symbol_info_tick("SpotCrude")
    off = (tick.time - time.time()) / 3600 if tick else 0.0
    check(f"server clock offset measured ({off:+.1f}h vs local)", tick is not None,
          "any deal query bounded by datetime.now() loses the last "
          f"{abs(off):.1f}h — which is exactly where an episode's closing batch lives")
    bad = []
    for f in sorted(glob.glob(os.path.join(HERE, "*.py"))):
        if os.path.basename(f) == os.path.basename(__file__):
            continue
        src = io.open(f, encoding="utf-8", errors="replace").read()
        for i, line in enumerate(src.splitlines(), 1):
            if "history_deals_get" not in line and "history_orders_get" not in line:
                continue
            window = " ".join(src.splitlines()[i - 1:i + 2])
            if "datetime.now()" in window and "timedelta(days=" not in window.split("datetime.now()")[-1][:40]:
                if "now() +" not in window:
                    bad.append(f"{os.path.basename(f)}:{i}")
    check("every deal-history query uses a server-safe upper bound", not bad,
          ("unsafe call sites: " + ", ".join(bad)) if bad else
          "all call sites bound with now()+timedelta(days=1)")


def check_coverage_and_attribution():
    """CLASS 3 — a watcher keyed to a magic that no longer trades observes nothing, quietly.
    CLASS 1 again — per-stream nets must reconcile to the account's own total."""
    print("\n② COVERAGE + ATTRIBUTION (the stale-magic / dropped-leg classes)")
    watch = watched_magics()
    # 2026-09-04: Book Guard v2 hedges with its own magic on WHATEVER symbol tripped -> it cannot live in a
    # per-(magic,symbol) stream map. It is attributed here explicitly (its P&L is the guard's cost) rather
    # than flagged as an orphan. Anything ELSE unwatched still FAILS.
    INFRA = {909090: "Book Guard v2 hedge"}
    for _t, _acc in watch.items():
        if isinstance(_acc, dict):
            for _a, _m in _acc.items():
                if isinstance(_m, set): _m.update(INFRA)
    for acct, (path, login) in ACCOUNTS.items():
        ai = connect(path, login)
        if ai is None:
            check(f"{acct}: terminal reachable", False, "not connected — cannot verify this account")
            continue
        agg, total = truth_by_magic()
        traded = {m for (m, _s) in agg}
        print(f"  -- {acct} (login {ai.login}): {len(traded)} magic(s) traded in {WINDOW_DAYS}d, "
              f"realised {total:+.2f}")
        for tool, per_acct in watch.items():
            if "_error" in per_acct:
                check(f"{acct}: {tool} importable", False, per_acct["_error"]); continue
            if acct not in per_acct:
                continue                       # tool legitimately does not claim this account
            seen = per_acct[acct]
            orphans = sorted(traded - seen)
            covered = sum(v[1] for (m, _s), v in agg.items() if m in seen)
            check(f"{acct}: {tool} watches every magic that traded",
                  not orphans,
                  (f"UNWATCHED magic(s) {orphans} -> "
                   f"{total - covered:+.2f} of realised P&L invisible to this tool")
                  if orphans else f"covers {covered:+.2f} of {total:+.2f}")
        mt5.shutdown()


def check_selector_parity():
    """CLASS 2 — the register must judge each engine against the selector the EA actually
    uses, not a different file that happens to be nearby."""
    print("\n③ SELECTOR PARITY (the register-vs-sizing class)")
    try:
        reg = importlib.import_module("gridstat_fingerprint_register")
    except Exception as e:
        check("register importable", False, str(e)); return
    for label, cfg in reg.REG.items():
        sizing = cfg.get("sizing")
        if not sizing:
            check(f"{label}: selector declared (win-rate gate {cfg.get('gate')})",
                  cfg.get("gate") is not None,
                  "gate is the selector for this stream")
            continue
        mults = reg.sizing_mults(sizing)
        check(f"{label}: sizing table '{sizing}' readable", bool(mults),
              f"{len(mults)} fingerprints, {sum(1 for v in mults.values() if v > 0)} tradeable"
              if mults else "MISSING — register would fall back to the gate and over-report")
    # the register must not show size-up progress on a fingerprint the engine skips
    snaps = sorted(glob.glob(os.path.join(ADIR, "fingerprint_register_*.csv")))
    snaps = [s for s in snaps if "history" not in os.path.basename(s)]
    if snaps:
        rows = list(csv.DictReader(io.open(snaps[-1], encoding="utf-8")))
        bad = [r for r in rows
               if r.get("sizeMult", "").strip() not in ("", "-")
               and float(r.get("sizeMult") or 0) == 0
               and r.get("status") in ("ACCUMULATE", "GOOD", "IDLE", "OK")]
        check("no zeroed fingerprint is shown as trading/size-up", not bad,
              ", ".join(f"{r['stream']} {r['fingerprint']} ({r['status']})" for r in bad)
              if bad else f"checked {len(rows)} rows in {os.path.basename(snaps[-1])}")


def check_ea_inputs():
    """A locked EA that cannot open its gate/sizing file does not error — it just stops
    qualifying signals. That looks like a quiet market."""
    print("\n④ EA INPUT FILES (silent-starvation class)")
    for label, fn in EA_FILES.items():
        p = os.path.join(COMMON, fn)
        ok = os.path.exists(p) and os.path.getsize(p) > 0
        age = (time.time() - os.path.getmtime(p)) / 86400 if ok else 0
        check(f"{label}: {fn}", ok,
              f"{os.path.getsize(p):,} bytes, {age:.0f}d old" if ok else "MISSING or empty in Common\\Files")


def check_freshness():
    """A monitor that stopped writing is indistinguishable from a calm market."""
    print("\n⑤ OUTPUT FRESHNESS (did the monitors actually run?)")
    for name, path, max_h in [
        ("episode ledger",   os.path.join(ADIR, "episode_ledger.csv"), 48),
        ("auditor log",      os.path.join(ADIR, "episode_auditor.log"), 6),
        ("morning brief",    max(glob.glob(os.path.join(ADIR, "morning_brief_*.txt")) or [""], default=""), 36),
        ("operator ledger",  os.path.join(ADIR, "operator_ledger.csv"), 24 * 14),
    ]:
        if not path or not os.path.exists(path):
            check(f"{name} present", False, "missing"); continue
        age_h = (time.time() - os.path.getmtime(path)) / 3600
        check(f"{name} fresh (< {max_h}h)", age_h <= max_h, f"{age_h:.1f}h old")



# ---- (6) RUNNING-vs-DISK (2026-09-04): a CLI compile writes a new .ex5 but the ATTACHED instance keeps
#      running the OLD code until someone re-attaches it. Found the hard way: the demo's GOLD LOCKED kept
#      churning in the permanent-rescue state for hours after the S36d fix was "deployed". Per terminal,
#      the build stamp the running EA PRINTED at its last init must equal the stamp in the .mq5 on disk.
TERMINAL_DATA = {
    "LIVE": r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\73B7A2420D6397DFF9014A20F1201F97",
    "DEON": r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\942C8C7E5F6C67C7F9D9D82245E68176",
    "DEMO": r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\C54C4DDE98E7B1FB905AFE04A9333631",
}
WATCH_EAS = {   # EA file name -> attached on which terminals (the book as deployed)
    "GOLD HPIN12VG5": ("LIVE", "DEON"),
    "Marius GridStat MT5 OIL SOLID LOCKED": ("LIVE", "DEON", "DEMO"),
    "Marius GridStat MT5 GOLD LOCKED": ("DEMO",),
    "GOLD DAYRANK": ("DEMO",),
}
def _read16(path):
    for enc in ("utf-16", "cp1252"):
        try: return io.open(path, encoding=enc, errors="replace").read()
        except Exception: continue
    return ""
def check_running_vs_disk():
    print("\n(6) RUNNING-vs-DISK (is the attached instance the build on disk?)")
    for ea, terms in WATCH_EAS.items():
        for term in terms:
            data = TERMINAL_DATA[term]
            src = os.path.join(data, "MQL5", "Experts", ea + ".mq5")
            if not os.path.exists(src):
                check(f"{term} {ea}: source on disk", False, "missing .mq5"); continue
            m = re.search(r'EA_BUILD_VERSION\s+"([^"]+)"', io.open(src, encoding="utf-8", errors="replace").read())
            disk = m.group(1) if m else "?"
            logs = sorted(glob.glob(os.path.join(data, "MQL5", "Logs", "*.log")))[-3:]
            running = None
            for lg in logs:
                for line in _read16(lg).splitlines():
                    if line.find(ea + " (") >= 0 and "MARIUS GRIDSTAT MT5" in line:
                        mm = re.search(r"MARIUS GRIDSTAT MT5 (\S+)", line)
                        if mm: running = mm.group(1)
            check(f"{term} {ea}: running == disk", running == disk,
                  f"running {running or 'no init banner in the last 3 logs'} | disk {disk}")

# ---- (7) BENCH DATA FRESHNESS (2026-09-04): the runner logged in as a broker-expired demo for FOUR DAYS
#      ("Invalid account") and every headless run silently used bars frozen at 08-28; the weekly re-test
#      rows and a whole A/B were computed on stale data. The runner's own tester log says what it synced.
RUNNER_DATA = r"C:\MT5 Pepperstone Runner"
def check_bench_freshness():
    print("\n(7) BENCH DATA FRESHNESS (does the runner test on current bars?)")
    logs = sorted(glob.glob(os.path.join(RUNNER_DATA, "Tester", "logs", "*.log")), key=os.path.getmtime)
    if not logs:
        check("runner tester log present", False, "no logs"); return
    t = _read16(logs[-1])
    syncs = re.findall(r"history synchronized from \S+ to (\d{4}\.\d\d\.\d\d)", t)
    tl = sorted(glob.glob(os.path.join(RUNNER_DATA, "logs", "*.log")), key=os.path.getmtime)
    bad_login = ("Invalid account" in _read16(tl[-1])) if tl else False
    check("runner login valid (no 'Invalid account')", not bad_login,
          "last terminal log shows an authorization failure" if bad_login else (os.path.basename(tl[-1]) if tl else ""))
    if syncs:
        last = datetime.strptime(syncs[-1], "%Y.%m.%d")
        age = (datetime.now() - last).days
        check("runner history reaches the last closed day (<= 4d)", age <= 4, f"synced to {syncs[-1]} ({age}d ago)")
    else:
        check("runner history sync line found", False, "no 'history synchronized' line in the latest tester log")

# ---- (8) BOOK GUARD SHAPE (2026-09-04, user: "the 8 will bite us"): the guard's daily cap must sit ABOVE the gold
#      engine's pin/ride band (12%) with freeze-on-trip, or the guard amputates the treatment it was reordered
#      behind (the 09-03 double trip). The source default was 8/flatten -> any fresh attach silently regressed.
#      Reads the RUNNING instance's own CONFIG line (latest init wins) + counts instances from the journal.
GUARD_EA = "Marius Book Guard v2"
GUARD_MIN_DAILY_PCT = 12.0     # the gold pin line; the cap must be strictly above it
def check_guard_shape():
    print("\n(8) BOOK GUARD SHAPE (cap above the pin band, freeze on, exactly one instance)")
    for term in ("LIVE", "DEON"):
        data = TERMINAL_DATA[term]
        pct = frz = None; last_init = None
        for lg in sorted(glob.glob(os.path.join(data, "MQL5", "Logs", "*.log")))[-3:]:
            for line in _read16(lg).splitlines():
                if GUARD_EA + " (" not in line: continue
                m = re.search(r"CONFIG \| MaxDailyLossPct=([\d.]+)%", line)
                if m: pct = float(m.group(1)); last_init = line[:32]
                m = re.search(r"FreezeOnDailyTrip=(true|false)", line)
                if m: frz = (m.group(1) == "true")
        check(f"{term} guard daily cap > {GUARD_MIN_DAILY_PCT:.0f}% (pin band)", pct is not None and pct > GUARD_MIN_DAILY_PCT,
              f"running MaxDailyLossPct={pct} (init {last_init})" if pct is not None else "no guard CONFIG line in the last 3 logs")
        check(f"{term} guard FreezeOnDailyTrip=true", frz is True, f"running FreezeOnDailyTrip={frz}")
        live = {}
        for lg in sorted(glob.glob(os.path.join(data, "logs", "*.log")))[-3:]:
            for line in _read16(lg).splitlines():
                m = re.search(r"expert (" + re.escape(GUARD_EA) + r" \([^)]*\)) (loaded successfully|removed)", line)
                if m: live[m.group(1)] = 1 if m.group(2) == "loaded successfully" else 0
        n = sum(live.values())
        check(f"{term} exactly one guard instance", n == 1, f"{n} live: {[k for k, v in live.items() if v]}")
        src = os.path.join(data, "MQL5", "Experts", GUARD_EA + ".mq5")
        md = re.search(r'#define BUILD "([^"]+)"', io.open(src, encoding="utf-8", errors="replace").read()) if os.path.exists(src) else None
        disk = md.group(1) if md else "?"; running = None
        for lg in sorted(glob.glob(os.path.join(data, "MQL5", "Logs", "*.log")))[-3:]:
            for line in _read16(lg).splitlines():
                mb = re.search(r"MARIUS BOOK GUARD (BOOKGUARD-\S+)", line)
                if mb and GUARD_EA + " (" in line: running = mb.group(1)
        check(f"{term} guard running build == disk", running == disk, f"running {running} | disk {disk} (re-attach to load the new default set)")

def main():
    quiet = "--quiet" in sys.argv
    print(f"FRAMEWORK CHECK | {datetime.now():%Y-%m-%d %H:%M} | window {WINDOW_DAYS}d")
    print("the control cell for the monitoring layer — proves the plumbing carries what it claims\n")
    ai = None
    for path, login in ACCOUNTS.values():
        ai = connect(path, login)
        if ai: break
    if ai is None:
        print("no terminal reachable — cannot run the live reconciliations."); return 2
    check_time_basis()
    check_selector_parity()
    check_ea_inputs()
    check_freshness()
    check_coverage_and_attribution()
    mt5.shutdown()
    check_running_vs_disk()
    check_bench_freshness()
    check_guard_shape()

    fails = [n for n, ok, _ in RESULTS if not ok]
    print(f"\n{'='*78}")
    print(f"{len(RESULTS) - len(fails)}/{len(RESULTS)} checks passed")
    if fails:
        print("FAILED:")
        for f in fails: print(f"  - {f}")
        print("\nA FAIL here means a tool is reporting something it cannot see. Fix the tool")
        print("before reading any number it produces, and log it in the CLAUDE.md Bug Log.")
    else:
        print("All green: every watcher sees every magic that traded, every deal query is")
        print("server-time safe, every engine is judged on its own selector, and every input")
        print("file the locked EAs name is present.")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
