#!/usr/bin/env python3
"""
run_frz_ab.py -- headless A/B of the OIL freeze-release cells on the PEP runner (2026-09-18).

Window is PINNED to the oil_solid_ctl anchor window (2025.12.01 -> 2026.08.19, SpotCrude M5,
Model=4 real ticks, $3,000) so `OIL FRZ0` must reproduce $3,033.81 / 134 trades. If it does not,
the whole table is VOID -- a cell table whose control does not reproduce a known result proves
nothing (the standing anchor rule).

Carries the runner guards the project learned the hard way:
  BOM-less ini · [Experts] Enabled=0 (the runner is a clone of the demo install with armed charts)
  · [Common] Login pinned (the 08-31->09-03 dead-login incident) · stale report purged first and
  the new one must post-date the launch · the run's OWN tester log must show login + history sync.
Also greps that log for the EA's freeze journal lines, which are the mechanism evidence.

usage:  python run_frz_ab.py [CELL ...]      (default: all cells in ORDER)
"""
import io, os, re, glob, subprocess, sys, time
from datetime import datetime

RUNNER_EXE = r"C:\MT5 Pepperstone Runner\terminal64.exe"
RUNNER_DATA = r"C:\MT5 Pepperstone Runner"
RUNNER_ARGS = ["/portable"]
INIDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "analysis_data", "tester_ini")
os.makedirs(INIDIR, exist_ok=True)

SYMBOL, PERIOD, MODEL, DEPOSIT = "SpotCrude", "M5", 4, 3000
FROM, TO = "2025.12.01", "2026.08.19"
ANCHOR_NET, ANCHOR_TR = 3033.81, 134          # oil_solid_ctl.htm
ORDER = ["OIL FRZ0", "OIL FRZPARK", "OIL FRZPARKRT15", "OIL FRZPARKT40"]
FRZ_RE = re.compile(r"(FREEZE HEDGE:|FREEZE RELEASED|FREEZE DISARMED|FREEZE HARVEST TRAIL|FREEZE BOOK EXIT)")


def paths(rep):
    return [os.path.join(RUNNER_DATA, rep + e) for e in (".htm", ".html")]


def parse(path):
    raw = None
    for enc in ("utf-16", "utf-8", "cp1252"):
        try:
            raw = io.open(path, encoding=enc, errors="strict").read(); break
        except Exception:
            continue
    t = re.sub(r"<[^>]+>", "|", raw)
    t = re.sub(r"(\s*\|\s*)+", "|", t)

    def num(label):
        m = re.search(re.escape(label) + r":?\|(-?[\d  ,]+\.\d+)", t)
        return float(m.group(1).replace(" ", "").replace("\u00a0", "").replace(",", "")) if m else None

    def ival(label):
        m = re.search(re.escape(label) + r":?\|(\d+)", t)
        return int(m.group(1)) if m else None

    q = re.search(r"(?:Quality|quality)[^|]*\|(\d+)%", t)
    eq = re.search(r"Equity Drawdown Maximal:?\|[\d  ,.]+ \((\d+\.\d+)%\)", t)
    return dict(net=num("Total Net Profit"), pf=num("Profit Factor"), rf=num("Recovery Factor"),
                trades=ival("Total Trades"), eqdd=float(eq.group(1)) if eq else None,
                quality=int(q.group(1)) if q else None)


def freeze_lines(cell, t0):
    logs = sorted(glob.glob(os.path.join(RUNNER_DATA, "Tester", "*", "logs", "*.log")),
                  key=os.path.getmtime)
    out = []
    for lg in logs[-4:]:
        if os.path.getmtime(lg) < t0 - 5:
            continue
        try:
            txt = io.open(lg, encoding="utf-16", errors="replace").read()
        except Exception:
            continue
        out += [l.split("\t")[-1].strip() for l in txt.splitlines() if FRZ_RE.search(l)]
    return out


def run(cell):
    rep = "frz_" + cell.split()[-1].lower()
    ini = os.path.join(INIDIR, rep + ".ini")
    io.open(ini, "w", encoding="utf-8").write(
        "[Common]\nLogin=61586543\nServer=Pepperstone-Demo\n\n"
        "[Experts]\nEnabled=0\nAllowLiveTrading=0\n\n"
        f"[Tester]\nExpert={cell}\nSymbol={SYMBOL}\nPeriod={PERIOD}\nModel={MODEL}\n"
        f"FromDate={FROM}\nToDate={TO}\nDeposit={DEPOSIT}\nOptimization=0\n"
        f"Report={rep}\nReplaceReport=1\nShutdownTerminal=1\n")
    for p in paths(rep):
        if os.path.exists(p):
            try: os.remove(p)
            except OSError: pass
    t0 = time.time()
    print(f"  [{cell}] running...", flush=True)
    try:
        subprocess.run([RUNNER_EXE] + RUNNER_ARGS + [f"/config:{ini}"], timeout=3600)
    except subprocess.TimeoutExpired:
        print(f"  [{cell}] !! TIMEOUT"); return None, []
    # --- bench preconditions: this run's own log must prove login + synced history
    tl = sorted(glob.glob(os.path.join(RUNNER_DATA, "Tester", "logs", "*.log")), key=os.path.getmtime)
    ttxt = io.open(tl[-1], encoding="utf-16", errors="replace").read() if tl else ""
    syncs = re.findall(r"history synchronized from \S+ to (\d{4}\.\d\d\.\d\d)", ttxt)
    term = sorted(glob.glob(os.path.join(RUNNER_DATA, "logs", "*.log")), key=os.path.getmtime)
    ttermtxt = io.open(term[-1], encoding="utf-16", errors="replace").read()[-20000:] if term else ""
    if "Invalid account" in ttermtxt or "authorized on" not in ttermtxt:
        print(f"  [{cell}] !! VOID: runner login refused"); return None, []
    if syncs and syncs[-1] < TO:
        print(f"  [{cell}] !! history synced only to {syncs[-1]} (< {TO})")
    for p in paths(rep):
        if os.path.exists(p) and os.path.getmtime(p) >= t0 - 2:
            return parse(p), freeze_lines(cell, t0)
    print(f"  [{cell}] !! no fresh report ({time.time()-t0:.0f}s)")
    return None, []


def main():
    cells = [c for c in (sys.argv[1:] or ORDER)]
    print(f"OIL FREEZE-RELEASE A/B  {SYMBOL} {PERIOD} Model={MODEL} {FROM}->{TO} deposit={DEPOSIT}")
    print(f"anchor: OIL FRZ0 must reproduce net {ANCHOR_NET} / {ANCHOR_TR} trades\n")
    res = {}
    for c in cells:
        r, fl = run(c)
        res[c] = (r, fl)
        if r:
            print(f"  [{c}] net {r['net']} PF {r['pf']} RF {r['rf']} eqDD {r['eqdd']}% "
                  f"tr {r['trades']} quality {r['quality']}%  frzlines {len(fl)}", flush=True)
    print("\n%-14s %10s %6s %6s %8s %7s %8s %s" %
          ("cell", "net", "PF", "RF", "eqDD%", "trades", "quality", "freeze events"))
    print("-" * 92)
    for c in cells:
        r, fl = res.get(c, (None, []))
        if not r:
            print(f"{c:<14} {'RUN FAILED':>10}"); continue
        ev = {}
        for l in fl:
            k = FRZ_RE.search(l).group(1).replace("FREEZE ", "").replace(":", "")
            ev[k] = ev.get(k, 0) + 1
        print("%-14s %10.2f %6s %6s %8s %7s %8s %s" %
              (c, r["net"], r["pf"], r["rf"], r["eqdd"], r["trades"], r["quality"],
               " ".join(f"{k}={v}" for k, v in sorted(ev.items())) or "-"))
    ctl = res.get("OIL FRZ0", (None, []))[0]
    if ctl and ctl["net"] is not None and ANCHOR_NET is not None:
        gap = ctl["net"] - ANCHOR_NET
        ok = abs(gap) < 5.0 and ctl["trades"] == ANCHOR_TR
        print(f"\nCONTROL CELL: {ctl['net']:.2f} / {ctl['trades']} tr vs anchor {ANCHOR_NET} / {ANCHOR_TR}"
              f"  -> {'PASS' if ok else 'FAIL (gap %+.2f, %+d tr) -- TABLE VOID' % (gap, ctl['trades']-ANCHOR_TR)}")


if __name__ == "__main__":
    main()
