#!/usr/bin/env python3
"""
ROLLING RE-TEST (Layer 3, 2026-08-08) — weekly headless re-test of the locked EAs on the
trailing window, so decay/feed-drift is caught by SCHEDULE, not by a loss.

Runs on the PEP RUNNER (portable clone of the demo install = the DEPLOYMENT feed), headless
via the tester-CLI pipeline (ini + ShutdownTerminal=1), Model=4 REAL TICKS. Never OHLC on a
grid: 1-min-OHLC invents intrabar paths and manufactures phantom disasters (the 08-26 XM
"GOLD-FIBC8 -$1,212 / 659 trades" reading was exactly that, on an engine that was healthy).
Runner tick quality ~46% on the recent window (9% deeper in history = broker depth), and the
bench is deterministic (same cell twice = identical to the cent), so PAIRED verdicts are valid;
long-window absolutes stay low-fidelity -> decisive calls go to the user's 100%-tick tester.

Jobs track the DEPLOYED geometries at their own balance classes (size is balance-gated on gold).
Per job: trailing-56d, parse the report, append to analysis_data/rolling_retest.csv, verdict vs
the job's own run-history median (needs >=3 runs; before that: "baseline building").

Run:      python rolling_retest.py            (all jobs)
Schedule: task "GridStat Rolling Retest", Saturdays 09:00.
Guardrail: DETECT AND QUEUE — a DEGRADED verdict is a morning-brief decision item,
never an auto-adjustment (20-close doctrine stands).
"""
import os, io, re, csv, sys, time, subprocess, statistics
from datetime import datetime, timedelta

try:
    from alerts import alert
except Exception:                                    # alerts is optional; never block the run
    def alert(msg, level="RED", **kw): print(f"[{level}] {msg}")

HERE = os.path.dirname(os.path.abspath(__file__))
ADIR = os.path.join(HERE, "analysis_data")
OUT = os.path.join(ADIR, "rolling_retest.csv")
# ---- BENCH RE-POINT (2026-08-26): XM -> the PEP RUNNER (portable clone, deployment feed).
# Why: the XM re-test ran Model=1 (1-min OHLC) on grid engines with a rescue overlay = the
# documented phantom-disaster mode (GOLD-FIBC8 "-1,212 / 659 trades / 58% DD" in 56 days was an
# OHLC churn spiral, not gold) on a retired feed. The runner: deployment feed, Model=4 real ticks
# (partial bases, but a CONSISTENT path -- fib C matched the user's 100%-tick bench to ~$3),
# zero-input lock-equivalent cells (no set files, nothing can leak). New bench = new baseline:
# job names carry "@PEP" so XM-era rows never mix into the medians.
BENCH = "PEP"
RUNNER_EXE = r"C:\MT5 Pepperstone Runner\terminal64.exe"
RUNNER_DATA = r"C:\MT5 Pepperstone Runner"            # portable: data dir = install dir (reports land here)
RUNNER_ARGS = ["/portable"]
SETDIR = os.path.join(RUNNER_DATA, r"MQL5\Profiles\Tester")
INIDIR = os.path.join(ADIR, "tester_ini")
WINDOW_DAYS = 56
DEPOSIT = 3000
MODEL = 4                                             # every tick based on real ticks (never OHLC on a grid)

# job -> Expert (zero-input cell on the runner = the locked config verbatim), symbol (PEP naming)
JOBS = {
    f"fibC-SR6@{BENCH}":    dict(expert="FIBC SR6",  symbol="XAUUSD",    setlines=None),  # the forward config (SR6F on demo)
    # (2026-08-27) fibC-XC RETIRED from the weekly run: the XC lock is no longer deployed anywhere
    # (SR6F carries the demo fib C slot since 08-24) and its NEGATIVE readings were nagging the brief
    # for a config nobody runs. History stays in the CSV; re-add if XC ever returns.
    # (2026-08-26) gold tracks the DEPLOYED geometries, each at its own balance class: the first PEP reading
    # showed full-lot @ $3k = staged-cut re-entry churn on the melt-up era (740tr/91% DD) while the live
    # HALF build @ $2,350 survives the same 56d at +$1,389/28% -- size is balance-gated, so the re-test is too.
    f"GOLD-HALF-live@{BENCH}": dict(expert="GOLD HALF56", symbol="XAUUSD", setlines=None, deposit=2350),  # = GOLD HALF LOCKED (live)
    f"GOLD-FULL-demo@{BENCH}": dict(expert="GOLD SRC",    symbol="XAUUSD", setlines=None, deposit=5700),  # = GOLD LOCKED @ the demo's balance
    f"OIL-SOLID@{BENCH}":      dict(expert="OIL TC0",     symbol="SpotCrude", setlines=None),              # = OIL SOLID LOCKED verbatim (cap inert)
}

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.makedirs(INIDIR, exist_ok=True); os.makedirs(SETDIR, exist_ok=True)


def runner_busy():
    """MT5 exits IMMEDIATELY if an instance is already running -- the /config run then
    produces no report at all. Pre-flight so that shows up as a named cause, not a
    mystery. (2026-08-22)"""
    # (2026-08-26) match the RUNNER's own exe path -- the live/demo/Deon terminals are
    # always running on this machine and are a different install; only a second instance
    # of the runner itself makes the /config launch no-op.
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "Get-Process terminal64 -ErrorAction SilentlyContinue | ForEach-Object { $_.Path }"],
                             capture_output=True, text=True, timeout=30).stdout
        return RUNNER_EXE.lower() in out.lower()
    except Exception:
        return False                                 # can't tell -> don't block


def report_paths(report):
    return [os.path.join(RUNNER_DATA, report + ext) for ext in (".html", ".htm")]


def run_job(name, cfg):
    frm = datetime.now() - timedelta(days=WINDOW_DAYS)
    setref = ""
    if cfg["setlines"]:
        sf = f"retest_{name}.set"
        io.open(os.path.join(SETDIR, sf), "w", encoding="utf-16-le").write(
            "﻿" + "\n".join(cfg["setlines"]) + "\n")
        setref = f"ExpertParameters={sf}\n"
    report = f"retest_{name}"
    ini = os.path.join(INIDIR, f"retest_{name}.ini")
    io.open(ini, "w", encoding="utf-8").write(
        # [Experts] kill-switch (2026-08-18: never launch a terminal with armed chart EAs unguarded)
        # [Common] login (2026-09-03): the runner still logged in as the broker-EXPIRED demo 61552687
        "[Common]\nLogin=61586543\nServer=Pepperstone-Demo\n\n"
        "[Experts]\nEnabled=0\nAllowLiveTrading=0\n\n"
        f"[Tester]\nExpert={cfg['expert']}\n{setref}Symbol={cfg['symbol']}\nPeriod=M5\n"
        f"Model={MODEL}\nFromDate={frm:%Y.%m.%d}\nToDate={datetime.now():%Y.%m.%d}\n"
        f"Deposit={cfg.get('deposit', DEPOSIT)}\nOptimization=0\nReport={report}\nReplaceReport=1\nShutdownTerminal=1\n")
    # ---- FRESHNESS GUARD (2026-08-22) -------------------------------------------------
    # Root cause of the 08-15 -> 08-22 stale-result incident: the old code parsed whatever
    # retest_<name>.htm happened to be on disk. A run that produced NOTHING therefore
    # re-published the PREVIOUS week's numbers as the current reading -- byte-identical
    # net/PF/RF/eqDD/trades -- and the engine looked healthy while it was blind.
    # Two defences: purge the old report first, then require the new one to post-date t0.
    for rp in report_paths(report):
        if os.path.exists(rp):
            try: os.remove(rp)
            except OSError as e: print(f"[{name}] !! cannot clear stale report {rp}: {e}")
    print(f"[{name}] running trailing-{WINDOW_DAYS}d headless...")
    t0 = time.time()
    try:
        subprocess.run([RUNNER_EXE] + RUNNER_ARGS + [f"/config:{ini}"], timeout=1200)
    except subprocess.TimeoutExpired:
        print(f"[{name}] !! tester timeout"); return None
    elapsed = time.time() - t0
    # report lands in the runner data dir -- and must be NEWER than this run
    for rp in report_paths(report):
        if os.path.exists(rp) and os.path.getmtime(rp) >= t0 - 2:
            return parse_report(rp)
        if os.path.exists(rp):
            print(f"[{name}] !! report is STALE (mtime "
                  f"{datetime.fromtimestamp(os.path.getmtime(rp)):%Y-%m-%d %H:%M}) -- refusing it")
    why = ("runner terminal was already running (MT5 /config exits instantly)"
           if runner_busy() else
           "tester produced no report -- check [Experts] Enabled=0 vs the tester expert, "
           "the symbol name on the runner feed, and that the EA exists there")
    alert(f"ROLLING RE-TEST [{name}] RUN-FAILED after {elapsed:.1f}s: {why}. "
          f"No row written -- the last CSV row for this job is NOT current.", "RED")
    return None


def parse_report(path):
    raw = io.open(path, encoding="utf-16", errors="replace").read()
    txt = re.sub(r"<[^>]+>", "|", raw); txt = re.sub(r"(\s*\|\s*)+", "|", txt)
    def num(key):
        m = re.search(re.escape(key) + r":\|([^|(]{0,40})", txt)
        if not m: return None
        try: return float(m.group(1).replace(" ", "").replace(" ", ""))
        except ValueError: return None
    def pct(key):
        m = re.search(re.escape(key) + r":\|[^|]*\(([\d.]+)%\)", txt)
        return float(m.group(1)) if m else None
    return dict(net=num("Total Net Profit"), pf=num("Profit Factor"),
                rf=num("Recovery Factor"), eqdd=pct("Equity Drawdown Maximal"),
                trades=num("Total Trades"))


def history(name):
    if not os.path.exists(OUT): return []
    rows = [r for r in csv.DictReader(io.open(OUT, encoding="utf-8")) if r["job"] == name]
    return rows


def main():
    print(f"=== ROLLING RE-TEST {datetime.now():%Y-%m-%d %H:%M} (trailing {WINDOW_DAYS}d) ===")
    only = set(sys.argv[1:])                     # e.g. `python rolling_retest.py fibC-XC`
    if runner_busy():
        alert("ROLLING RE-TEST aborted: a terminal64.exe is already running, so every "
              "/config run would exit instantly and produce no report. Close the runner "
              "install and re-run.", "RED")
        print("!! runner terminal is open -- aborting before it silently no-ops."); return 2
    new = not os.path.exists(OUT)
    results = []
    for name, cfg in JOBS.items():
        if only and name not in only: continue
        r = run_job(name, cfg)
        if r is None or r["net"] is None:
            results.append((name, None, "RUN-FAILED")); continue
        hist = history(name)
        verdict = "baseline-building"
        if len(hist) >= 3:
            med_net = statistics.median(float(h["net"]) for h in hist)
            med_rf = statistics.median(float(h["rf"] or 0) for h in hist)
            if r["net"] < 0 or (med_net > 0 and r["net"] < 0.4 * med_net) or \
               (med_rf > 0 and (r["rf"] or 0) < 0.4 * med_rf):
                verdict = "DEGRADED — decision item"
            else:
                verdict = "OK"
        elif r["net"] is not None and r["net"] < 0:
            verdict = "NEGATIVE — watch"
        with open(OUT, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["date", "job", "window_days", "net", "pf", "rf", "eqdd", "trades", "verdict"])
                new = False
            w.writerow([datetime.now().strftime("%Y-%m-%d"), name, WINDOW_DAYS,
                        r["net"], r["pf"], r["rf"], r["eqdd"], r["trades"], verdict])
        results.append((name, r, verdict))
        print(f"[{name}] net {r['net']:+,.2f} PF {r['pf']} RF {r['rf']} eqDD {r['eqdd']}% "
              f"({r['trades']:.0f} tr) -> {verdict}")
    print("\nSUMMARY:")
    for name, r, v in results:
        print(f"  {name:12} {v}")
    failed = [n for n, _, v in results if v == "RUN-FAILED"]
    if failed:
        # A silent RUN-FAILED is what let the stale rows stand for a week. Make it loud
        # and make the exit code non-zero so the scheduled task shows a failure.
        print(f"\n!! {len(failed)} job(s) DID NOT RUN: {', '.join(failed)}")
        print("   Their last CSV rows are stale -- do NOT read them as current.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
