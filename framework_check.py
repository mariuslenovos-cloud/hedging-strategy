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
    # 2026-09-22: the fingerprint MINER feeds the register (the size-up / drop decisions). It was
    # NOT in this list, so the 09-01 oil repoint (66705 -> 77180) missed it and for three weeks the
    # register showed the retired RSQ2 build's July record as live-oil evidence. Same class, same fix.
    try:
        mi = importlib.import_module("gridstat_fingerprint_mi")
        out["gridstat_fingerprint_mi"] = {a: {c["magic"] for c in cfg["streams"].values()}
                                          for a, cfg in mi.ACCOUNTS.items()}
    except Exception as e:
        out["gridstat_fingerprint_mi"] = {"_error": str(e)}
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
    INFRA = {909090: "Book Guard v2 hedge", 909091: "kill-switch test (killtest_demo.py)"}
    # 2026-10-12: the first killtest (10-12 01:30) opened its throwaway 0.01 position with magic 0 on the DEMO = a manual-class
    # position, -$0.11. Future tests use 909091. On the DEMO only, magic 0 = hand/test positions (no engine opens magic 0) -> infra.
    DEMO_INFRA = {0: "manual / kill-switch test position (DEMO)"}
    for _t, _acc in watch.items():
        if isinstance(_acc, dict):
            for _a, _m in _acc.items():
                if isinstance(_m, set): _m.update(INFRA); _m.update(DEMO_INFRA if _a == "DEMO" else {})
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
            # 2026-09-22: a tool may declare magics OUTSIDE ITS SCOPE by design (the fingerprint miner mines
            # GridStat setup fingerprints; MM ladders, SessionDrift, LongVol, fib C carry none). Declared
            # explicitly in the tool (NON_FINGERPRINT_MAGICS), imported here -- never assumed.
            scope_out = set(getattr(importlib.import_module(tool), "OUT_OF_SCOPE_MAGICS", set())) if tool != "episode_auditor" else set()
            orphans = sorted(traded - seen - scope_out)
            covered = sum(v[1] for (m, _s), v in agg.items() if m in seen or m in scope_out)
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
    check_gate_db_instrument()


# 2026-09-28: gridstat_setups_oil_research.csv (the gate DB every oil engine reads) was found to hold GOLD rows
# (entry prices 3,972-5,516) since 07-29. A present, non-empty, correctly-named file is not proof it describes the
# instrument that reads it. Assert the price level of every setups file against its instrument's band.
PRICE_BANDS = {"gold": (1000, 10000), "oil": (20, 250), "silver": (10, 200)}

def check_gate_db_instrument():
    for label, fn in EA_FILES.items():
        if "setups" not in fn: continue
        inst = next((k for k in PRICE_BANDS if k in fn.lower()), None)
        p = os.path.join(COMMON, fn)
        if inst is None or not os.path.exists(p): continue
        try:
            with open(p, encoding="latin-1") as fh:
                hdr = fh.readline().strip().split(","); ei = hdr.index("entry_price")
                px = [float(r.split(",")[ei]) for r in fh if r.strip()]
        except Exception as e:
            check(f"{label}: {fn} describes {inst}", False, f"unreadable: {e}"); continue
        lo, hi = PRICE_BANDS[inst]
        ok = bool(px) and lo <= min(px) and max(px) <= hi
        check(f"{label}: {fn} describes {inst}", ok,
              f"entry prices {min(px):.2f}-{max(px):.2f} vs {inst} band {lo}-{hi}" if px else "no rows")


# 2026-09-06: the auditor's EVENT log only writes on episode closes/alerts, so "auditor log < 6h" failed on every
# quiet weekend (a check that cries wolf trains the operator to ignore it). The auditor's per-CYCLE heartbeat is
# family_heat.json (rewritten every 60s) -> that is the liveness signal; the event log gets a 7-day window.
LEDGER = os.path.join(ADIR, "episode_ledger.csv")
HEARTBEAT = os.path.join(ADIR, "family_heat.json")
HEARTBEAT_MAX_H = 6
LEDGER_HARD_MAX_H = 24 * 14

FRESHNESS = [
    ("auditor heartbeat", os.path.join(ADIR, "family_heat.json"), 6),
    ("auditor event log", os.path.join(ADIR, "episode_auditor.log"), 24 * 7),
    ("morning brief",     max(glob.glob(os.path.join(ADIR, "morning_brief_*.txt")) or [""], default=""), 36),
    ("operator ledger",   os.path.join(ADIR, "operator_ledger.csv"), 24 * 14),
]

def check_ledger_freshness():
    """The episode ledger is EVENT-driven: a row appears only when an episode CLOSES. A flat
    48h clock therefore FAILS every quiet weekend even though the auditor is sampling fine --
    the same mis-specification fixed on episode_auditor.log on 2026-09-06, missed here. The
    liveness signal is the auditor's 60s heartbeat (family_heat.json); the ledger fails only
    when the auditor is not writing at all, or when it has been silent past the hard bound."""
    if not os.path.exists(LEDGER):
        check("episode ledger present", False, "missing"); return
    age_h = (time.time() - os.path.getmtime(LEDGER)) / 3600
    hb_h = ((time.time() - os.path.getmtime(HEARTBEAT)) / 3600
            if os.path.exists(HEARTBEAT) else None)
    if hb_h is None or hb_h > HEARTBEAT_MAX_H:
        check("episode ledger current", False,
              f"last row {age_h:.1f}h old and the auditor heartbeat is "
              + ("MISSING" if hb_h is None else f"{hb_h:.1f}h old")
              + " — no episode can be recorded while the auditor is down")
    elif age_h > LEDGER_HARD_MAX_H:
        check("episode ledger current", False,
              f"no episode closed in {age_h/24:.1f}d though the auditor is alive "
              f"({hb_h:.1f}h) — verify the ledger writer")
    else:
        check("episode ledger current", True,
              f"no episode closed in {age_h:.1f}h (auditor heartbeat {hb_h:.1f}h = alive)")


def check_freshness():
    """A monitor that stopped writing is indistinguishable from a calm market."""
    print("\n⑤ OUTPUT FRESHNESS (did the monitors actually run?)")
    check_ledger_freshness()
    for name, path, max_h in FRESHNESS:
        if not path or not os.path.exists(path):
            check(f"{name} present", False, "missing"); continue
        age_h = (time.time() - os.path.getmtime(path)) / 3600
        check(f"{name} fresh (< {max_h}h)", age_h <= max_h, f"{age_h:.1f}h old")



# ---- (9) LIVE SIGNAL LOG (2026-09-06): the fingerprint miner, the SLOT-QUALITY assertion and the register all read
#      Common\Files\gridstat_signals_<symbol>.csv. A zero-input CELL is generated with UseSignalLog=false (the tester
#      rule), so the day GOLD HPIN12 went live the live gold signal stream went silent and nothing said so. Per live
#      terminal, the watched gold build on disk must have UseSignalLog true (const or input default).
def check_live_signal_log():
    print("\n(9) LIVE SIGNAL LOG (does the attached gold build write the log the monitors read?)")
    for ea, terms in WATCH_EAS.items():
        if "GOLD" not in ea.upper(): continue
        for term in terms:
            if term not in ("LIVE", "DEON"): continue
            exps = os.path.join(TERMINAL_DATA[term], "MQL5", "Experts")
            src = os.path.join(exps, ea + ".mq5")
            if not os.path.exists(src):
                check(f"{term} {ea}: source on disk", False, "missing"); continue
            txt = io.open(src, encoding="utf-8", errors="replace").read()
            m = re.search(r"(?:const|input)\s+bool\s+UseSignalLog\s*=\s*(true|false)", txt)
            ok = bool(m) and m.group(1) == "true"
            check(f"{term} {ea}: UseSignalLog=true on disk", ok,
                  f"UseSignalLog={m.group(1) if m else '?'}" + ("" if ok else " -> live gold fingerprints unattributed, SLOT-QUALITY blind"))

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
    "GOLD HPIN12": ("LIVE", "DEON"),      # 2026-09-04 15:08 swap (velocity guard rejected on the PEP full curve)
    "Marius GridStat MT5 OIL SOLID LOCKED FRZRT15KP1": ("LIVE", "DEON", "DEMO"),   # 2026-09-23 MAIN 14:58 / DEON 15:02 (banners verified); DEMO swap staged 2026-10-05 (user flattened the book) -- reads FAIL until the attach banner prints
    "Marius GridStat MT5 GOLD LOCKED": ("DEMO",),
    "Marius ZGrid MT5 v1.0": ("DEMO",),   # 2026-10-09 21:17 attached on the demo (banner ZGRID-2026-10-09-B + CONFIG | ZGRID | TriggerMode=2 ZLookback=24 EntryZ=2.25 verified)
    "MM t2one LIVE": ("LIVE", "DEON"),   # 2026-10-14 RE-ATTACHED by the user 08:03 (both banners verified); history: 2026-10-05 attached; 2026-10-08 REMOVED by the user (journals: DEON 17:17:11, MAIN 17:17:23) after 25 ladders / -$90 per account; auditor maps keep 954801 for attribution
    # 2026-10-05: GOLD DAYRANK + LongVol demo charts RETIRED (size lever decided by the GUI pairs; LongVol = capital question) -- unwatched
    "MM_ShadowLogger": ("DEMO",),  # 2026-09-07 MM V5 forward test. Places NO orders (no trade functions compiled in),
                                   # so it carries no magic and cannot reach the auditor -- but a silently-dead logger
                                   # reads exactly like a quiet market, so running-vs-disk is the only thing guarding
                                   # the claim that the 100-fire sample is real. Reads FAIL until it is attached.
}
STAMP_RE = re.compile(r"([A-Za-z0-9][A-Za-z0-9-]*20\d\d-\d\d-\d\d[A-Za-z0-9-]*)")
def _disk_stamp(src):
    """Build stamp of an EA source: EA_BUILD_VERSION / #define EA_BUILD / #define BUILD (any dated stamp)."""
    txt = io.open(src, encoding="utf-8", errors="replace").read()
    m = re.search(r'(?:EA_BUILD_VERSION|#define\s+EA_BUILD|#define\s+BUILD)\s+"([^"]+)"', txt)
    return m.group(1) if m else "?"
def _read16(path):
    for enc in ("utf-16", "cp1252"):
        try: return io.open(path, encoding=enc, errors="replace").read()
        except Exception: continue
    return ""
# 2026-10-07: the Experts-log windows below scan the last 10 files (were 3): a terminal up more than three days lost its
# init banner from the window and read FAIL on a healthy deploy (the 09-17 ⑧ cry-wolf class, one tool over).
def check_running_vs_disk():
    print("\n(6) RUNNING-vs-DISK (is the attached instance the build on disk?)")
    for ea, terms in WATCH_EAS.items():
        for term in terms:
            data = TERMINAL_DATA[term]
            src = os.path.join(data, "MQL5", "Experts", ea + ".mq5")
            if not os.path.exists(src):
                check(f"{term} {ea}: source on disk", False, "missing .mq5"); continue
            # 2026-09-06 (Bug Log): the stamp lived in EA_BUILD_VERSION and the banner in "MARIUS GRIDSTAT MT5 <stamp>"
            # only for the GridStat family. LongVol (#define EA_BUILD, banner "MARIUS LONGVOL BRACKET <stamp>") could
            # never PASS -> its 09-06 "negative test" failed for the wrong reason. Now: any #define/const carrying a
            # dated stamp on disk; any init line printed by this EA that carries a dated stamp in the log.
            disk = _disk_stamp(src)
            logs = sorted(glob.glob(os.path.join(data, "MQL5", "Logs", "*.log")))[-10:]
            running = None
            for lg in logs:
                for line in _read16(lg).splitlines():
                    if line.find(ea + " (") >= 0 and "MARIUS" in line.upper():
                        mm = STAMP_RE.search(line.split("\t")[-1])
                        if mm: running = mm.group(1)
            check(f"{term} {ea}: running == disk", running is not None and running == disk,
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
    # 2026-09-18: take the FURTHEST sync reached across the last few tester logs, not the last line.
    # A deliberate research run on a HISTORICAL window (e.g. the freeze-release A/B pinned to
    # 2025.12.01->2026.08.19) syncs only to its own ToDate, which made this check read "30d stale"
    # on a perfectly healthy runner -- it cannot tell a stale bench from a deliberate back-window.
    # What the check actually wants to know is "can the runner still reach current bars", so take the
    # max over the recent logs; a genuinely stale runner never produces a fresh sync line at all.
    syncs = []
    for lg in logs[-3:]:
        syncs += re.findall(r"history synchronized from \S+ to (\d{4}\.\d\d\.\d\d)", _read16(lg))
    syncs = sorted(syncs)
    tl = sorted(glob.glob(os.path.join(RUNNER_DATA, "logs", "*.log")), key=os.path.getmtime)
    # 2026-09-07: assert the MOST RECENT authorization outcome, not "no failure all day".
    # Scanning the whole log meant one failed launch kept the check red for the rest of the
    # day even after the cause was fixed and a clean run had happened -- the same cry-wolf
    # disease as the old event-driven-file-on-a-clock check. A superseded failure is
    # reported in the detail line; only a CURRENTLY refused login fails.
    last_ok, n_fail = None, 0
    if tl:
        for ln in _read16(tl[-1]).splitlines():
            if "authorization on" in ln and "failed" in ln:
                last_ok, n_fail = False, n_fail + 1
            elif re.search(r"':\s*authorized on ", ln):
                last_ok = True
    bad_login = (last_ok is False)
    detail = (os.path.basename(tl[-1]) if tl else "no terminal log")
    if bad_login:
        detail = "the LAST authorization in " + detail + " was REFUSED (Invalid account)"
    elif n_fail:
        detail += f" (last auth OK; {n_fail} earlier failure(s) today, superseded)"
    check("runner login valid (no 'Invalid account')", not bad_login, detail)
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
        for lg in sorted(glob.glob(os.path.join(data, "MQL5", "Logs", "*.log")))[-10:]:
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
        # 2026-09-17: dated journals ONLY, last 10 -- `metaeditor.log` sorts after the dates and was
        # eating one of the three slots, so a guard loaded 3 days ago read as "0 instances" (cry-wolf)
        for lg in sorted(f for f in glob.glob(os.path.join(data, "logs", "*.log")) if re.search(r"\d{8}\.log$", f))[-10:]:
            for line in _read16(lg).splitlines():
                m = re.search(r"expert (" + re.escape(GUARD_EA) + r" \([^)]*\)) (loaded successfully|removed)", line)
                # key by SYMBOL, not (symbol,period): a chart timeframe change re-inits the EA with a new period
                # and NO journal removed/loaded pair (MAIN 11:52 H1->M5 read as two instances)
                if m: live[re.sub(r",[A-Z0-9]+\)", ")", m.group(1))] = 1 if m.group(2) == "loaded successfully" else 0
        n = sum(live.values())
        check(f"{term} exactly one guard instance", n == 1, f"{n} live: {[k for k, v in live.items() if v]}")
        src = os.path.join(data, "MQL5", "Experts", GUARD_EA + ".mq5")
        md = re.search(r'#define BUILD "([^"]+)"', io.open(src, encoding="utf-8", errors="replace").read()) if os.path.exists(src) else None
        disk = md.group(1) if md else "?"; running = None
        for lg in sorted(glob.glob(os.path.join(data, "MQL5", "Logs", "*.log")))[-10:]:
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
    check_live_signal_log()

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
