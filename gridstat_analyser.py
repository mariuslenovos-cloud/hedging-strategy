"""
gridstat_analyser.py — Edge analysis for the Marius GridStat GOLD EA.

Mirrors the EA's own fingerprint + filter logic EXACTLY so Python conclusions
match what the live EA decides:

  fingerprint = DIRECTION | SESSION | ATR_REGIME
  session by broker hour:  hr<9 ASIA | hr<14 LDN | hr<18 OVL | else NY
  atr regime vs 14-avg:    >1.3x EXP | <0.7x COMP | else NORM
  win        = r_multiple > 0
  filter PASS = samples >= MinSamples (10) AND win_rate >= MinWinRate (0.55)

Two jobs:
  1. aggregate the shadow-mode signal DB (gridstat_setups.csv) into per-setup
     edge stats and show which setups the live filter approves.
  2. classify a specific live entry (time + direction) and report its edge so
     we can confirm, going forward, that every live fill matched a good setup.

Usage:
    python gridstat_analyser.py                 # full edge table
    python gridstat_analyser.py --classify "2026-06-04 16:55" SELL
"""
import csv
import sys
from collections import defaultdict
from datetime import datetime

SETUPS_CSV = (r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal"
              r"\Common\Files\gridstat_setups.csv")

MIN_SAMPLES = 10      # EA input: MinSamples
MIN_WIN_RATE = 0.55   # EA input: MinWinRate


def session_tag(hour):
    """Mirror EA ClassifySetup() session bucketing (broker time)."""
    if hour < 9:
        return "HR_ASIA"
    if hour < 14:
        return "HR_LDN"
    if hour < 18:
        return "HR_OVL"
    return "HR_NY"


def load_signals(path=SETUPS_CSV, r_col="r_multiple"):
    """r_col selects which outcome column drives R: "r_multiple" = fixed barrier
    (default), "trail_r" = trailing-exit outcome (build-L+ data). The chosen
    column is mapped onto r["r_multiple"] so all downstream tools are unchanged."""
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            if not r.get("setup_key"):
                continue
            r["r_multiple"] = float(r.get(r_col, r["r_multiple"]))
            r["atr_at_entry"] = float(r["atr_at_entry"])
            rows.append(r)
    return rows


def aggregate(rows):
    """Per-fingerprint: samples, wins, win_rate, avg_R, total_R, decisive%."""
    by = defaultdict(list)
    for r in rows:
        by[r["setup_key"]].append(r)
    out = {}
    for key, rs in by.items():
        n = len(rs)
        wins = sum(1 for r in rs if r["r_multiple"] > 0)
        decisive = sum(1 for r in rs if r["barrier_hit"] in ("UPPER", "LOWER"))
        total_r = sum(r["r_multiple"] for r in rs)
        out[key] = {
            "samples": n,
            "wins": wins,
            "win_rate": wins / n,
            "avg_r": total_r / n,
            "total_r": total_r,
            "decisive_pct": decisive / n,
        }
    return out


def passes_filter(stat):
    return stat["samples"] >= MIN_SAMPLES and stat["win_rate"] >= MIN_WIN_RATE


def print_table(stats):
    rows = sorted(stats.items(), key=lambda kv: kv[1]["total_r"], reverse=True)
    print(f"\n{'SETUP':<26} {'n':>4} {'win%':>6} {'avgR':>7} {'totR':>8} "
          f"{'dec%':>6}  FILTER")
    print("-" * 72)
    for key, s in rows:
        flag = "PASS ***" if passes_filter(s) else (
            "n<10" if s["samples"] < MIN_SAMPLES else "wr<.55")
        print(f"{key:<26} {s['samples']:>4} {s['win_rate']*100:>5.0f}% "
              f"{s['avg_r']:>+7.3f} {s['total_r']:>+8.2f} "
              f"{s['decisive_pct']*100:>5.0f}%  {flag}")
    approved = [k for k, s in rows if passes_filter(s)]
    print("-" * 72)
    print(f"Filter approves {len(approved)} setup(s): "
          f"{', '.join(approved) if approved else '(none)'}")


def classify_entry(stats, when_str, direction):
    """Report the edge for a specific live entry (time + direction)."""
    when = datetime.strptime(when_str, "%Y-%m-%d %H:%M")
    direction = direction.upper()
    sess = session_tag(when.hour)
    print(f"\nLive entry: {direction} @ {when_str} (broker) -> session {sess}")
    print("ATR regime depends on ATR-at-entry vs 14-avg; checking all regimes:\n")
    any_hit = False
    for regime in ("ATR_NORM", "ATR_EXP", "ATR_COMP"):
        key = f"{direction}|{sess}|{regime}"
        s = stats.get(key)
        if not s:
            print(f"  {key:<26} no historical samples")
            continue
        any_hit = True
        verdict = "APPROVED" if passes_filter(s) else "REJECTED"
        print(f"  {key:<26} n={s['samples']:>2} win={s['win_rate']*100:>3.0f}% "
              f"avgR={s['avg_r']:+.3f} totR={s['total_r']:+.2f}  -> {verdict}")
    if not any_hit:
        print("  (no history for this session/direction at any ATR regime)")
    print("\nNote: EA filters on the SINGLE regime live at fill time. Match the")
    print("ATR-at-entry the EA logged to pick the row that actually gated this trade.")


def main():
    rows = load_signals()
    stats = aggregate(rows)
    print(f"Loaded {len(rows)} signals across {len(stats)} fingerprints "
          f"from gridstat_setups.csv")
    if len(sys.argv) >= 4 and sys.argv[1] == "--classify":
        classify_entry(stats, sys.argv[2], sys.argv[3])
    else:
        print_table(stats)


if __name__ == "__main__":
    main()
