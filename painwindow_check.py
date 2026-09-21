#!/usr/bin/env python3
"""
PAIN-WINDOW CHECK (2026-08-17) — the standing gate for ANY new engine/lever candidate.

Buckets a strategy's closed trades into the documented grid-pain windows (the episodes the
live book actually suffered) + monthly P&L. Decisive twice in one weekend: TrendBreak
(negative in all three live-era pain windows) and the Counter-Thrust fade (2 of 3 negative).

A candidate pitched as a DIVERSIFIER/OFFSET must be net-positive in these windows —
standalone full-window net is secondary (Gate A before Gate B).

Usage:
  python painwindow_check.py <tester_report.htm>          # MT5 tester report (UTF-16)
  python painwindow_check.py <trades.csv> --time-col T --profit-col P   # any CSV

The windows list is append-only: when the book takes a new documented episode, add it here.
"""
import io, re, sys, csv
from datetime import datetime

# label -> (start incl, end excl)  — gold/book episodes on the deployment feed
WINDOWS = [
    ("Jan parabola+crash (01-20..02-06)", "2026-01-20", "2026-02-07"),
    ("Mar slide          (03-01..03-31)", "2026-03-01", "2026-04-01"),
    ("Apr whipsaw        (04-13..04-17)", "2026-04-13", "2026-04-18"),
    ("May event          (05-10..05-14)", "2026-05-10", "2026-05-15"),
    ("Jun oil crash      (06-01..06-30)", "2026-06-01", "2026-07-01"),
    ("Jul oil slide      (07-24..07-29)", "2026-07-24", "2026-07-30"),
    ("Aug meltup+whip    (08-03..08-07)", "2026-08-03", "2026-08-08"),
]


def parse_report(path):
    """MT5 tester report -> [(datetime, profit incl comm+swap)] from the deals table 'out' rows."""
    raw = io.open(path, encoding="utf-16", errors="replace").read()
    trades = []
    for row in re.findall(r"<tr[^>]*>.*?</tr>", raw, re.S):
        cells = [c.strip() for c in re.split(r"</?t[dh][^>]*>", re.sub(r"<(?!/?t[dh])[^>]+>", "", row)) if c.strip()]
        # deals table out-row: time, deal, symbol, type, direction, volume, price, order, comm, swap, profit, balance
        if len(cells) >= 12 and cells[4] == "out" and re.match(r"20\d\d\.\d\d\.\d\d", cells[0]):
            try:
                t = datetime.strptime(cells[0], "%Y.%m.%d %H:%M:%S")
                pnl = sum(float(cells[i].replace(" ", "").replace("\xa0", "")) for i in (8, 9, 10))
                trades.append((t, pnl))
            except ValueError:
                continue
    return trades


def parse_csv(path, time_col, profit_col):
    trades = []
    for r in csv.DictReader(io.open(path, encoding="utf-8", errors="replace")):
        ts = r.get(time_col, "")
        for fmt in ("%Y.%m.%d %H:%M", "%Y.%m.%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
            try:
                trades.append((datetime.strptime(ts, fmt), float(r[profit_col]))); break
            except (ValueError, KeyError):
                continue
    return trades


def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    path = sys.argv[1]
    if path.lower().endswith((".htm", ".html")):
        trades = parse_report(path)
    else:
        tc = sys.argv[sys.argv.index("--time-col") + 1] if "--time-col" in sys.argv else "close_time"
        pc = sys.argv[sys.argv.index("--profit-col") + 1] if "--profit-col" in sys.argv else "profit"
        trades = parse_csv(path, tc, pc)
    if not trades:
        print("no trades parsed"); sys.exit(1)

    total = sum(p for _, p in trades)
    print(f"source: {path}\ntrades: {len(trades)}   total net: {total:+,.2f}\n")
    print("=== PAIN WINDOWS (Gate A: an offset candidate must be POSITIVE here) ===")
    for label, a, b in WINDOWS:
        a_, b_ = datetime.fromisoformat(a), datetime.fromisoformat(b)
        w = [p for t, p in trades if a_ <= t < b_]
        flag = "" if not w else ("  <-- FAIL" if sum(w) < 0 else "  ok")
        print(f"  {label}  trades={len(w):3d}  net={sum(w):+10.2f}{flag}")
    print("\n=== MONTHLY ===")
    months = {}
    for t, p in trades:
        months.setdefault(t.strftime("%Y-%m"), []).append(p)
    for m in sorted(months):
        print(f"  {m}  trades={len(months[m]):3d}  net={sum(months[m]):+10.2f}")


if __name__ == "__main__":
    main()
