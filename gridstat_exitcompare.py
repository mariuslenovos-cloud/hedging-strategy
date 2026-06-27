"""
gridstat_exitcompare.py — Fixed-barrier vs trailing exit, measured PER SYMBOL.

Answers the question raised by the live GOLD sell that closed at the fixed $100
target while the trend ran another ~130 pts: would letting winners run (a trailing
exit) actually raise expected R — and by how much, per setup, per symbol?

Requires a shadow pass from EA build 2026-06-05-L or later, which logs three extra
columns per signal:
  mfe_r     — max favorable excursion (peak R reached)
  trail_hit — how the trailing strategy exited (TRAIL/STOP/TIME/TEST_END)
  trail_r   — R captured by the trailing strategy (activate TrailActivateR,
              trail TrailDistanceR behind peak; same -1R adverse stop as fixed)

WHY THIS IS SYMBOL-ADAPTIVE
---------------------------
Everything is in R = (move / (ATR_D1 * BarrierATRMultiplier)). Because ATR is
symbol-specific, an R-distance trail auto-scales to each instrument's volatility:
the SAME TrailDistanceR is a wider dollar trail on GOLD than on SILVER. So the
MECHANISM adapts automatically. The optimal trail DISTANCE (how much give-back a
symbol's trends tolerate) still differs by symbol — GOLD trends hard, SILVER/OIL
may chop — so we MEASURE it per symbol here (the MFE sweep) rather than hardcode
one global value. Run this separately on each symbol's own shadow data.

Usage:
    python gridstat_exitcompare.py            # GOLD
    python gridstat_exitcompare.py silver     # SILVER (needs its own shadow run)
    python gridstat_exitcompare.py oil
"""
import csv
import os
import sys
from collections import defaultdict

COMMON = r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\Common\Files"
SETUPS = {
    "gold":   os.path.join(COMMON, "gridstat_setups.csv"),
    "silver": os.path.join(COMMON, "gridstat_setups_silver.csv"),
    "oil":    os.path.join(COMMON, "gridstat_setups_oil.csv"),
}
TRAIL_ACTIVATE_R = 1.0                       # mirror the EA input
SWEEP_DISTANCES = [0.3, 0.5, 0.75, 1.0, 1.5] # trail give-back values to model


def load(path):
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            if not r.get("setup_key"):
                continue
            rows.append(r)
    return rows


def has_trail(rows):
    return rows and "trail_r" in rows[0] and rows[0]["trail_r"] not in (None, "")


def model_trail_r(fixed_r, mfe_r, dist, activate=TRAIL_ACTIVATE_R):
    """Approximate trailing outcome for an ARBITRARY trail distance, from MFE.
    If the trade never reached the activation peak, trailing == fixed outcome.
    If it activated, it gives back `dist` from the peak (conservative: ignores
    trades that time-out still near their peak, so this UNDER-states trailing)."""
    if mfe_r >= activate:
        return mfe_r - dist
    return fixed_r


def main():
    sym = (sys.argv[1] if len(sys.argv) > 1 else "gold").lower()
    path = SETUPS.get(sym)
    if not path or not os.path.exists(path):
        print(f"No setups file for '{sym}' at {path}.")
        print("Run a SHADOW pass for this symbol first (build 2026-06-05-L+).")
        return
    rows = load(path)
    if not has_trail(rows):
        print(f"[{sym}] {os.path.basename(path)} has no trail columns yet.")
        print("This is OLD shadow data. Recompile EA build 2026-06-05-L and re-run")
        print("a SHADOW pass (StatsCollectionMode=true) to log fixed vs trailing.")
        return

    for r in rows:
        r["fixed_r"] = float(r["r_multiple"])
        r["mfe_r"] = float(r["mfe_r"])
        r["trail_r"] = float(r["trail_r"])

    # ---- accurate comparison at the EA's configured trail distance ----
    by = defaultdict(list)
    for r in rows:
        by[r["setup_key"]].append(r)

    print(f"\n=== {sym.upper()} exit comparison — {len(rows)} signals "
          f"(EA-logged trailing vs fixed barrier) ===\n")
    print(f"{'SETUP':<24}{'n':>4}{'fixedR':>9}{'trailR':>9}{'delta':>9}  winner")
    print("-" * 64)
    tot_fixed = tot_trail = 0.0
    for k in sorted(by, key=lambda k: sum(x['trail_r']-x['fixed_r'] for x in by[k]),
                    reverse=True):
        rs = by[k]
        f = sum(x["fixed_r"] for x in rs)
        t = sum(x["trail_r"] for x in rs)
        tot_fixed += f
        tot_trail += t
        win = "TRAIL" if t > f + 1e-9 else ("fixed" if f > t + 1e-9 else "tie")
        print(f"{k:<24}{len(rs):>4}{f:>+9.2f}{t:>+9.2f}{t-f:>+9.2f}  {win}")
    print("-" * 64)
    print(f"{'TOTAL':<24}{len(rows):>4}{tot_fixed:>+9.2f}{tot_trail:>+9.2f}"
          f"{tot_trail-tot_fixed:>+9.2f}")
    verdict = ("TRAILING wins — worth deploying for this symbol"
               if tot_trail > tot_fixed else
               "FIXED wins — keep the fixed target for this symbol")
    print(f"\nAt EA trail settings: {verdict}")

    # ---- whipsaw diagnostic: how did the trailing strategy exit? ----
    hits = defaultdict(lambda: [0, 0.0])   # type -> [count, sum trail_r]
    activated = [r for r in rows if r["mfe_r"] >= TRAIL_ACTIVATE_R]
    for r in rows:
        h = r.get("trail_hit", "?")
        hits[h][0] += 1
        hits[h][1] += r["trail_r"]
    print("\nTrailing exit breakdown (whipsaw check):")
    print(f"{'exit type':<12}{'count':>7}{'avg trailR':>12}")
    for h in sorted(hits, key=lambda h: -hits[h][0]):
        c, s = hits[h]
        print(f"{h:<12}{c:>7}{s/c:>+12.3f}")
    if activated:
        cap = sum(r["trail_r"] for r in activated) / sum(r["mfe_r"] for r in activated)
        early = sum(1 for r in activated if r.get("trail_hit") == "TRAIL"
                    and r["trail_r"] < r["mfe_r"] - 1e-9)
        print(f"activated trades: {len(activated)}  | peak-capture efficiency "
              f"= {cap*100:.0f}% of MFE  | TRAIL-stopped after activation: {early}")
        print("(tighter trail -> higher % captured per trade, but more TRAIL exits "
              "= more whipsaw risk live)")

    # ---- per-symbol trail-distance sweep (find this symbol's optimal) ----
    print(f"\nTrail-distance sweep (modeled from MFE, activate at "
          f"{TRAIL_ACTIVATE_R}R) — finds {sym.upper()}'s optimal give-back:")
    print(f"{'trail dist (R)':>14}{'total R':>10}{'vs fixed':>10}")
    print("-" * 34)
    best = (None, -1e9)
    for d in SWEEP_DISTANCES:
        tot = sum(model_trail_r(r["fixed_r"], r["mfe_r"], d) for r in rows)
        print(f"{d:>14.2f}{tot:>+10.2f}{tot-tot_fixed:>+10.2f}")
        if tot > best[1]:
            best = (d, tot)
    print("-" * 34)
    print(f"Fixed-barrier baseline total R = {tot_fixed:+.2f}")
    print(f"Best modeled trail distance for {sym.upper()} = {best[0]}R "
          f"(total R {best[1]:+.2f})")
    print("\nNote: sweep is a conservative MFE model (under-states trailing). The")
    print("EA-logged trail_r above is the accurate number at the configured")
    print("TrailDistanceR. Deploy per symbol only if BOTH agree trailing wins.")


if __name__ == "__main__":
    main()
