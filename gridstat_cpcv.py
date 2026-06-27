"""
gridstat_cpcv.py — Combinatorial Purged Cross-Validation for the GridStat
sizing table (AFML Ch. 7 & 12).

THE QUESTION IT ANSWERS
-----------------------
gridstat_sizing.csv is currently computed from ALL 226 signals — fully in-sample.
The +221% backtest is one in-sample path with unknown variance. CPCV asks: if we
build the sizing table on PART of the data and trade it on the held-out rest that
it never saw, does the edge survive? It produces a DISTRIBUTION of out-of-sample
outcomes + an overfitting read, instead of one hopeful number.

METHOD
------
- Sort signals by time, split into N contiguous blocks.
- For every combination of k blocks held out as TEST (C(N,k) folds):
    * TRAIN = the other blocks.
    * PURGE: drop TRAIN signals whose triple-barrier window [entry, outcome]
      overlaps any TEST signal's window (label leakage).
    * EMBARGO: drop TRAIN signals entering shortly after a TEST label resolves
      (serial-correlation leakage).
    * Build the sizing table from purged TRAIN only (same rigor: uniqueness
      weighting + significance + size multiplier).
    * "Trade" each TEST signal with the TRAIN-derived multiplier:
      contribution = size_mult * R_test. Unknown fingerprint -> mult 0 -> skip
      (exactly what the live EA does).
- Aggregate across folds: OOS R distribution, % positive folds, degradation vs
  in-sample, and a PBO-style failure rate.

Reuses gridstat_rigor.build() so the CV "model" is byte-identical to what ships
in gridstat_sizing.csv.

Usage:
    python gridstat_cpcv.py                 # N=8, k=2 (28 folds)
    python gridstat_cpcv.py 6 2             # custom N, k
"""
import statistics
import sys
from itertools import combinations

from gridstat_analyser import load_signals
from gridstat_rigor import build, _parse

EMBARGO_PCT = 0.02     # embargo window = 2% of total timeline after a test label


def _windows(rows):
    return [(_parse(r["entry_time"]), _parse(r["outcome_time"])) for r in rows]


def purge_embargo(train_idx, test_idx, win, embargo_secs):
    """Return train indices surviving purge + embargo against the test set."""
    test_spans = [win[j] for j in test_idx]
    kept = []
    for i in train_idx:
        t0, t1 = win[i]
        leak = False
        for (s0, s1) in test_spans:
            # purge: overlapping label windows
            if not (t1 < s0 or s1 < t0):
                leak = True
                break
            # embargo: train entry shortly after a test label resolves
            if 0 <= (t0 - s1).total_seconds() <= embargo_secs:
                leak = True
                break
        if not leak:
            kept.append(i)
    return kept


def evaluate(test_rows, table):
    """Trade each test signal with the train-derived sizing table."""
    total_r = 0.0
    traded = 0
    for r in test_rows:
        s = table.get(r["setup_key"])
        mult = s["mult"] if s else 0.0
        if mult <= 0:
            continue
        traded += 1
        total_r += mult * r["r_multiple"]
    avg_r = (total_r / traded) if traded else 0.0
    return {"total_r": total_r, "traded": traded, "avg_r": avg_r,
            "n_test": len(test_rows)}


def run_cpcv(rows, N=8, k=2):
    rows = sorted(rows, key=lambda r: _parse(r["entry_time"]))
    win = _windows(rows)
    span = (win[-1][1] - win[0][0]).total_seconds()
    embargo_secs = span * EMBARGO_PCT

    # contiguous blocks by signal count
    bounds = [round(i * len(rows) / N) for i in range(N + 1)]
    blocks = [list(range(bounds[b], bounds[b + 1])) for b in range(N)]

    folds = []
    for test_blocks in combinations(range(N), k):
        test_idx = [i for b in test_blocks for i in blocks[b]]
        train_idx = [i for b in range(N) if b not in test_blocks
                     for i in blocks[b]]
        train_kept = purge_embargo(train_idx, test_idx, win, embargo_secs)
        train_rows = [rows[i] for i in train_kept]
        test_rows = [rows[i] for i in test_idx]
        if not train_rows:
            continue
        table = build(train_rows)
        res = evaluate(test_rows, table)
        res["purged"] = len(train_idx) - len(train_kept)
        res["train_n"] = len(train_rows)
        folds.append(res)
    return folds


def in_sample_reference(rows):
    table = build(rows)
    return evaluate(rows, table)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    N = int(args[0]) if len(args) > 0 else 8
    k = int(args[1]) if len(args) > 1 else 2
    r_col = "trail_r" if "--trail" in sys.argv else "r_multiple"
    rows = load_signals(r_col=r_col)
    print(f"(R source: {r_col}"
          f"{'  [TRAILING exit]' if r_col=='trail_r' else '  [fixed barrier]'})")
    ref = in_sample_reference(rows)
    folds = run_cpcv(rows, N, k)

    avgs = [f["avg_r"] for f in folds]
    totals = [f["total_r"] for f in folds]
    pos = sum(1 for t in totals if t > 0)
    med_avg = statistics.median(avgs)
    degradation = med_avg / ref["avg_r"] if ref["avg_r"] else 0.0

    print(f"\nCPCV - {len(folds)} folds (N={N} blocks, k={k} held out / fold)")
    print(f"Signals={len(rows)}, embargo={EMBARGO_PCT*100:.0f}% of timeline\n")
    print(f"{'fold':>4} {'trainN':>7} {'purged':>7} {'testN':>6} "
          f"{'traded':>7} {'totR':>8} {'avgR/trade':>11}")
    print("-" * 56)
    for i, f in enumerate(folds):
        print(f"{i:>4} {f['train_n']:>7} {f['purged']:>7} {f['n_test']:>6} "
              f"{f['traded']:>7} {f['total_r']:>+8.2f} {f['avg_r']:>+11.3f}")
    print("-" * 56)
    print(f"\nIN-SAMPLE reference (full data, traded on itself):")
    print(f"  avg R/trade = {ref['avg_r']:+.3f}   total R = {ref['total_r']:+.2f}   "
          f"trades = {ref['traded']}")
    print(f"\nOUT-OF-SAMPLE (CPCV distribution):")
    print(f"  median avg R/trade = {med_avg:+.3f}  "
          f"(IQR {statistics.quantiles(avgs, n=4)[0]:+.3f} .. "
          f"{statistics.quantiles(avgs, n=4)[2]:+.3f})")
    print(f"  median total R/fold = {statistics.median(totals):+.2f}")
    print(f"  folds with positive total R = {pos}/{len(folds)} "
          f"({pos/len(folds)*100:.0f}%)")
    print(f"  degradation (OOS median / in-sample) = {degradation:.2f}x")
    print(f"\nVERDICT:")
    fail = len(folds) - pos
    pbo = fail / len(folds)
    if med_avg > 0 and pos / len(folds) >= 0.8 and degradation >= 0.5:
        v = "EDGE HOLDS OOS - scale gradually / diversify justified"
    elif med_avg > 0 and pos / len(folds) >= 0.6:
        v = "EDGE LIKELY but soft - proceed small, keep validating"
    else:
        v = "OVERFIT RISK - edge does not survive OOS; do NOT scale"
    print(f"  PBO-style failure rate = {pbo*100:.0f}%  ->  {v}")


if __name__ == "__main__":
    main()
