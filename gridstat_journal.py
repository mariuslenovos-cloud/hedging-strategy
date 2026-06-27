"""
gridstat_journal.py — Durable live-trade journal + live-vs-backtest learning loop
for the Marius GridStat EA (GOLD now; SILVER / OIL ready).

WHY THIS EXISTS
---------------
The EA's own files in Common\\Files (gridstat_setups.csv, gridstat_trades.csv)
are OVERWRITTEN every time you run a backtest. So live results die on the next
optimisation. This script snapshots closed live trades into a permanent JSON
journal that backtests cannot touch, tags each with the EA's setup fingerprint,
and compares LIVE win-rate against the BACKTEST win-rate per setup.

That comparison IS the learning loop:
  - backtest win% = the rule we believe in
  - live win%     = the rule meeting reality (spread, slippage, real fills)
  - drift         = how much the edge is decaying  -> keep / drop / re-study

The "model" is a transparent lookup table of rules (setup -> win rate), not a
black box. Preserving good rules = keeping approved fingerprints. The exact same
machinery transfers to SILVER / OIL: structure is identical, only the edge
NUMBERS differ, so each instrument keeps its own shadow-built setups DB.

This is analytics only. It never places or closes trades.

Usage:
    python gridstat_journal.py sync   gold     # ingest closed GOLD trades -> journal
    python gridstat_journal.py report gold     # live-vs-backtest comparison
    python gridstat_journal.py report          # all instruments
"""
import csv
import json
import os
import sys
from collections import defaultdict
from datetime import datetime

from gridstat_analyser import (
    aggregate, load_signals, session_tag, passes_filter,
    MIN_SAMPLES, MIN_WIN_RATE,
)

COMMON = r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\Common\Files"
JOURNAL_PATH = os.path.join(os.path.dirname(__file__), "live_journal.json")

# Per-instrument file map. SILVER / OIL slots are pre-wired: once you run a
# shadow pass on those symbols the EA writes the same-named files and this
# journal picks them up with zero code change.
# NOTE: trades_csv points at gridstat_live_*.csv — a LIVE-ONLY file the EA must
# write on each close (see LogLiveClose() in the EA). We deliberately do NOT read
# gridstat_trades.csv: that one is a backtest artifact and is overwritten every
# optimisation run, so ingesting it would contaminate the live journal.
INSTRUMENTS = {
    "gold": {
        "trades_csv": os.path.join(COMMON, "gridstat_live_gold.csv"),
        # LIVE grisk=4 filter DB (the actual config the live EA gates on).
        # Was pointed at the stale grisk=7 gridstat_setups.csv — fixed 2026-06-09.
        "setups_csv": os.path.join(COMMON, "gridstat_setups_gold.csv"),
    },
    "silver": {
        "trades_csv": os.path.join(COMMON, "gridstat_live_silver.csv"),
        "setups_csv": os.path.join(COMMON, "gridstat_setups_silver.csv"),
    },
    "oil": {
        "trades_csv": os.path.join(COMMON, "gridstat_live_oil.csv"),
        "setups_csv": os.path.join(COMMON, "gridstat_setups_oil.csv"),
    },
}


# ----------------------------------------------------------------------------
# Journal persistence
# ----------------------------------------------------------------------------
def load_journal():
    if not os.path.exists(JOURNAL_PATH):
        return {"version": 1, "instruments": {}}
    with open(JOURNAL_PATH) as f:
        return json.load(f)


def save_journal(j):
    with open(JOURNAL_PATH, "w") as f:
        json.dump(j, f, indent=2)


# ----------------------------------------------------------------------------
# Fingerprint reconstruction for a CLOSED live trade
# ----------------------------------------------------------------------------
def approved_regimes_for(setups_stats, direction, session):
    """Which ATR regimes are filter-approved for this direction+session.

    Lets us resolve the live trade's full fingerprint without ATR-at-entry:
    if only ONE regime is approved for the dir+session, the live fill must
    have matched it (the EA would not have fired otherwise)."""
    out = []
    for regime in ("ATR_NORM", "ATR_EXP", "ATR_COMP"):
        key = f"{direction}|{session}|{regime}"
        s = setups_stats.get(key)
        if s and passes_filter(s):
            out.append(key)
    return out


def trade_id(t):
    return f"{t['open_time']}|{t['open_price']}|{t['type']}"


def read_closed_trades(path):
    """gridstat_trades.csv columns:
    open_time, close_time, type, lots, open_price, close_price, profit, comment"""
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, newline="") as f:
        for r in csv.reader(f):
            if len(r) < 7 or r[0] in ("", "open_time"):
                continue
            rows.append({
                "open_time": r[0].strip(), "close_time": r[1].strip(),
                "type": r[2].strip().upper(), "lots": float(r[3]),
                "open_price": float(r[4]), "close_price": float(r[5]),
                "profit": float(r[6]),
                "comment": r[7].strip() if len(r) > 7 else "",
            })
    return rows


def is_contaminated(trades):
    """A live-only close log should march forward in time. If close_time ever
    jumps BACKWARDS, the file has had multiple backtest runs appended on top of
    each other (see gridstat_live_gold.csv: 24k rows / ~215 runs). Refuse to
    ingest such a file — it would flood the clean journal with backtest trades."""
    backsteps = sum(
        1 for i in range(1, len(trades))
        if trades[i]["close_time"][:10] < trades[i - 1]["close_time"][:10]
    )
    return backsteps > 0, backsteps


def sync(instrument):
    cfg = INSTRUMENTS[instrument]
    trades = read_closed_trades(cfg["trades_csv"])
    bad, backsteps = is_contaminated(trades)
    if bad:
        print(f"[{instrument}] REFUSED: '{os.path.basename(cfg['trades_csv'])}' "
              f"is contaminated ({len(trades)} rows, {backsteps} time-reversals = "
              f"stacked backtest runs). Auto-sync disabled to protect the clean "
              f"journal. Record genuine live trades explicitly in live_journal.json "
              f"(any EA-written CSV is overwritten/appended by backtests).")
        return
    setups_stats = {}
    if os.path.exists(cfg["setups_csv"]):
        setups_stats = aggregate(load_signals(cfg["setups_csv"]))

    journal = load_journal()
    inst = journal["instruments"].setdefault(instrument, {"trades": []})
    seen = {trade_id(t): t for t in inst["trades"]}

    added = 0
    for t in read_closed_trades(cfg["trades_csv"]):
        tid = trade_id(t)
        if tid in seen:
            continue
        try:
            hour = datetime.strptime(t["open_time"], "%Y.%m.%d %H:%M").hour
        except ValueError:
            hour = datetime.strptime(t["open_time"], "%Y-%m-%d %H:%M").hour
        sess = session_tag(hour)
        direction = "BUY" if t["type"].startswith("BUY") else "SELL"
        approved = approved_regimes_for(setups_stats, direction, sess)
        # resolve full fingerprint only when unambiguous
        if len(approved) == 1:
            setup_key, regime = approved[0], approved[0].split("|")[2]
        else:
            setup_key = f"{direction}|{sess}|?"
            regime = "UNRESOLVED"
        # backtest expectation for the (best) matching setup
        bt = setups_stats.get(approved[0]) if approved else None
        rec = {
            "id": tid,
            "open_time": t["open_time"], "close_time": t["close_time"],
            "direction": direction, "session": sess, "atr_regime": regime,
            "setup_key": setup_key,
            "lots": t["lots"], "open_price": t["open_price"],
            "close_price": t["close_price"], "profit": round(t["profit"], 2),
            "win": t["profit"] > 0,
            "comment": t["comment"],
            "bt_win_rate": round(bt["win_rate"], 3) if bt else None,
            "bt_samples": bt["samples"] if bt else None,
        }
        inst["trades"].append(rec)
        seen[tid] = rec
        added += 1

    save_journal(journal)
    print(f"[{instrument}] synced: +{added} new closed trade(s), "
          f"{len(inst['trades'])} total in journal")


# ----------------------------------------------------------------------------
# Live-vs-backtest comparison report (the learning loop output)
# ----------------------------------------------------------------------------
def report(instrument):
    cfg = INSTRUMENTS[instrument]
    setups_stats = {}
    if os.path.exists(cfg["setups_csv"]):
        setups_stats = aggregate(load_signals(cfg["setups_csv"]))

    journal = load_journal()
    inst = journal["instruments"].get(instrument)
    if not inst or not inst["trades"]:
        print(f"\n[{instrument}] no live trades journalled yet. "
              f"Run: python gridstat_journal.py sync {instrument}")
        return

    by = defaultdict(list)
    for t in inst["trades"]:
        by[t["setup_key"]].append(t)

    total_profit = sum(t["profit"] for t in inst["trades"])
    total_n = len(inst["trades"])
    total_wins = sum(1 for t in inst["trades"] if t["win"])

    print(f"\n=== {instrument.upper()} live-vs-backtest "
          f"({total_n} trades, net ${total_profit:+.2f}) ===")
    print(f"{'SETUP':<24} {'live n':>6} {'live%':>6} {'bt%':>6} "
          f"{'drift':>7} {'net$':>9}  STATUS")
    print("-" * 74)
    for key in sorted(by, key=lambda k: sum(t['profit'] for t in by[k]),
                      reverse=True):
        ts = by[key]
        n = len(ts)
        live_wr = sum(1 for t in ts if t["win"]) / n
        net = sum(t["profit"] for t in ts)
        bt_wr = next((t["bt_win_rate"] for t in ts if t["bt_win_rate"]), None)
        if bt_wr is None:
            drift_s, status = "  n/a", "no bt match"
        else:
            drift = live_wr - bt_wr
            drift_s = f"{drift*100:+5.0f}%"
            if n < 5:
                status = "too few (need >=5)"
            elif drift < -0.20:
                status = "DECAYING - review"
            elif drift < -0.10:
                status = "watch"
            else:
                status = "holding"
        bt_s = f"{bt_wr*100:>5.0f}%" if bt_wr is not None else "   --"
        print(f"{key:<24} {n:>6} {live_wr*100:>5.0f}% {bt_s} "
              f"{drift_s:>7} {net:>+9.2f}  {status}")
    print("-" * 74)
    print(f"Overall: {total_wins}/{total_n} wins "
          f"({total_wins/total_n*100:.0f}%), net ${total_profit:+.2f}")
    print("Drift = live win% - backtest win%. Need >=5 live trades/setup before "
          "trusting it.\nDECAYING (>20% below backtest) = edge may not survive "
          "live; restudy or drop.")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    inst = sys.argv[2] if len(sys.argv) > 2 else None
    if cmd == "sync":
        sync(inst) if inst else [sync(i) for i in INSTRUMENTS]
    elif cmd == "report":
        report(inst) if inst else [report(i) for i in INSTRUMENTS]
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
