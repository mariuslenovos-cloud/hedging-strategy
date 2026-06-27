"""
gridstat_rigor.py — AFML rigor layer for GridStat, used as a SIZING overlay.

DESIGN RULE (locked 2026-06-04): rigor SIZES bets, it does not add entry gates.
It may scale a bet up or down and may only zero a setup whose expected R is
NEGATIVE. It can never reduce us below current trade flow — every positive-
expectancy setup keeps trading. As live winning samples accumulate, a setup's
confidence rises and its size grows automatically. See memory
rigor-drives-sizing-not-gating.

Two AFML pieces feed the confidence score:

  Step 1  Sample-uniqueness weighting (AFML Ch. 4)
          Triple-barrier labels overlap: signals on the same trend leg share
          future bars, so they aren't independent. We weight each label by its
          average uniqueness (mean over its life of 1/concurrency) and use the
          Kish EFFECTIVE sample size, not the raw count — so a trend counted 5x
          stops masquerading as 5 independent wins.

  Step 2  Significance (AFML Ch. 8/11 spirit)
          Wilson lower bound on the weighted win rate + t-stat on the weighted R
          distribution (using effective n). Confidence = how sure we are the
          edge is real, NOT a pass/fail gate.

Output: a transparent lookup table  setup -> size multiplier  that the EA can
read to size each entry. Still a plain table of rules you can eyeball.

Usage:
    python gridstat_rigor.py                 # honest edge + sizing table
    python gridstat_rigor.py --write         # also write gridstat_sizing.csv
"""
import csv
import math
import os
import sys
from collections import defaultdict
from datetime import datetime

from gridstat_analyser import load_signals

EFF_N_MIN = 8.0       # below this, treat as thin -> probationary base size
T_CONFIRM = 2.0       # t-stat on R for "confirmed"
T_MARGINAL = 1.0      # t-stat floor for "marginal"

COMMON = r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\Common\Files"
SIZING_CSV = os.path.join(COMMON, "gridstat_sizing.csv")


def _parse(ts):
    return datetime.strptime(ts, "%Y.%m.%d %H:%M")


# ---------------------------------------------------------------------------
# Step 1: average uniqueness per label (duration-weighted 1/concurrency)
# ---------------------------------------------------------------------------
def compute_uniqueness(rows):
    spans = []
    for i, r in enumerate(rows):
        t0 = _parse(r["entry_time"])
        t1 = _parse(r["outcome_time"])
        if t1 < t0:
            t1 = t0
        spans.append((t0, t1, i))

    bks = sorted({t for s in spans for t in (s[0], s[1])})
    own = [0.0] * len(rows)     # exclusive-time numerator
    life = [0.0] * len(rows)    # total lifespan denominator

    for k in range(len(bks) - 1):
        a, b = bks[k], bks[k + 1]
        dur = (b - a).total_seconds()
        if dur <= 0:
            continue
        active = [i for (t0, t1, i) in spans if t0 <= a and t1 > a]
        c = len(active)
        if c == 0:
            continue
        contrib = dur / c
        for i in active:
            own[i] += contrib
            life[i] += dur
    return [(own[i] / life[i]) if life[i] > 0 else 1.0 for i in range(len(rows))]


# ---------------------------------------------------------------------------
# Step 2: weighted aggregation + significance
# ---------------------------------------------------------------------------
def wilson_lb(wins, n, z=1.96):
    if n <= 0:
        return 0.0
    p = wins / n
    d = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - margin) / d


def weighted_stats(rs, ws):
    sw = sum(ws)
    sw2 = sum(w * w for w in ws)
    eff_n = (sw * sw / sw2) if sw2 > 0 else 0.0
    mean = sum(w * r for w, r in zip(ws, rs)) / sw if sw > 0 else 0.0
    if eff_n > 1:
        var = sum(w * (r - mean) ** 2 for w, r in zip(ws, rs)) / sw
        sd = math.sqrt(var) if var > 0 else 1e-9
        t = mean / (sd / math.sqrt(eff_n))
    else:
        t = 0.0
    wwr = (sum(w for w, r in zip(ws, rs) if r > 0) / sw) if sw > 0 else 0.0
    return {"eff_n": eff_n, "raw_n": len(rs), "win_rate": wwr,
            "wilson_lb": wilson_lb(wwr * eff_n, eff_n), "avg_r": mean, "t": t}


# ---------------------------------------------------------------------------
# Confidence -> size multiplier (the exploitation layer)
# ---------------------------------------------------------------------------
def size_multiplier(s):
    """Transparent, bounded. Floor 0.75x for ANY positive expectancy (never
    kills trade flow; broker min-lot floors it further in practice). Only a
    NEGATIVE expected-R setup is zeroed. Confirmed + high-R earns up to 2.0x."""
    if s["avg_r"] <= 0:
        return 0.0, "NEGATIVE - skip"
    if s["eff_n"] < EFF_N_MIN:
        return 0.75, "thin/probationary"
    if s["t"] >= T_CONFIRM:
        if s["avg_r"] >= 0.30:
            return 2.0, "confirmed + strong R"
        return 1.5, "confirmed"
    if s["t"] >= T_MARGINAL:
        return 1.0, "marginal - base size"
    return 0.75, "weak+ - trimmed but trades"


def build(rows):
    uniq = compute_uniqueness(rows)
    by_r, by_w = defaultdict(list), defaultdict(list)
    for r, u in zip(rows, uniq):
        by_r[r["setup_key"]].append(r["r_multiple"])
        by_w[r["setup_key"]].append(u)
    out = {}
    for k in by_r:
        s = weighted_stats(by_r[k], by_w[k])
        s["mult"], s["tier"] = size_multiplier(s)
        out[k] = s
    return out


def print_table(results):
    print(f"\nHonest edge + sizing table (uniqueness-weighted, AFML Ch.4 + sig.)\n")
    print(f"{'SETUP':<24}{'rawN':>5}{'effN':>6}{'win%':>6}{'avgR':>7}"
          f"{'t(R)':>6}{'SIZEx':>7}  TIER")
    print("-" * 80)
    for k in sorted(results, key=lambda k: -results[k]["avg_r"] * results[k]["eff_n"]):
        s = results[k]
        print(f"{k:<24}{s['raw_n']:>5}{s['eff_n']:>6.1f}{s['win_rate']*100:>5.0f}%"
              f"{s['avg_r']:>+7.3f}{s['t']:>6.2f}{s['mult']:>6.2f}x  {s['tier']}")
    print("-" * 80)
    trading = [k for k, s in results.items() if s["mult"] > 0]
    print(f"Trading {len(trading)} of {len(results)} setups "
          f"(only negative-expectancy ones skipped). Trade flow preserved.")
    print("SIZEx multiplies the base lot. Floor 0.75x keeps positive setups live;")
    print("broker min-lot floors it further, so in practice nothing is removed.")


def write_sizing_csv(results, path=SIZING_CSV):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["setup_key", "size_mult", "eff_n", "avg_r", "t_stat", "tier"])
        for k, s in sorted(results.items()):
            w.writerow([k, f"{s['mult']:.2f}", f"{s['eff_n']:.1f}",
                        f"{s['avg_r']:.3f}", f"{s['t']:.2f}", s["tier"]])
    print(f"\nWrote sizing table -> {path}")


def main():
    r_col = "trail_r" if "--trail" in sys.argv else "r_multiple"
    rows = load_signals(r_col=r_col)
    results = build(rows)
    print(f"(R source: {r_col}{'  [TRAILING exit]' if r_col=='trail_r' else '  [fixed barrier]'})")
    print_table(results)
    if "--write" in sys.argv:
        write_sizing_csv(results)


if __name__ == "__main__":
    main()
