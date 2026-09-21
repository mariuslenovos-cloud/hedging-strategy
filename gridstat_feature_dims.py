#!/usr/bin/env python3
"""
NEW FINGERPRINT DIMENSIONS — feature-importance study.
The gate currently selects on DIR|session|ATR-regime (a coarse 3-feature cut).
The shadow DB logs richer per-signal features. This asks: does any of them predict
WIN (r_multiple>0) *beyond* the current fingerprint, STABLY over time? If yes, that
feature is a candidate to JOIN ClassifySetup (sharper selection -> higher PF).

Honest gates (features died before on time-instability / binning artifacts):
  1. a clear win-rate GRADIENT across the feature (not a lone bin)
  2. it holds in first-half AND second-half (kills regime/overfit spikes)
  3. it adds power CONDITIONAL on the fingerprint (refines the cut, isn't just a proxy for it)
Pooled gold+oil (grisk-4, comparable feature scales) for n~600; per-symbol as a check.
Read-only on analysis_data snapshots / the shadow DBs. Run: python gridstat_feature_dims.py
"""
import csv, io, os
import statistics as st
from collections import defaultdict
CF = r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\Common\Files"
DBS = {"GOLD": "gridstat_setups_gold.csv", "OIL": "gridstat_setups_oil_mt5.csv"}

def load(name):
    rows = list(csv.reader(io.open(os.path.join(CF, name), encoding="utf-8", errors="replace")))
    hdr = [h.strip() for h in rows[0]]; ix = {h: i for i, h in enumerate(hdr)}
    out = []
    for r in rows[1:]:
        if len(r) < len(hdr): continue
        try:
            d = dict(
                key=r[ix["setup_key"]].strip(), t=r[ix["entry_time"]].strip(),
                dirn=("BUY" if "BUY" in r[ix["setup_key"]] else "SELL"),
                r=float(r[ix["r_multiple"]]), win=1 if float(r[ix["r_multiple"]]) > 0 else 0,
                wpr=float(r[ix["wpr"]]), adx=float(r[ix["adx"]]),
                angle=float(r[ix["ma_angle"]]), runup=float(r[ix["runup"]]),
                bars=float(r[ix["bars_in_band"]]),
            )
        except (ValueError, KeyError):
            continue
        # derived, direction-aware
        d["angle_abs"] = abs(d["angle"])
        d["angle_aligned"] = 1 if ((d["dirn"] == "BUY" and d["angle"] > 0) or
                                   (d["dirn"] == "SELL" and d["angle"] < 0)) else 0
        out.append(d)
    return out

def terciles(rows, feat):
    """win-rate in low/mid/high thirds of a feature + monotonic gradient size."""
    xs = sorted(r[feat] for r in rows)
    n = len(xs); q1, q2 = xs[n//3], xs[2*n//3]
    bins = {"low": [], "mid": [], "high": []}
    for r in rows:
        b = "low" if r[feat] <= q1 else ("high" if r[feat] > q2 else "mid")
        bins[b].append(r["win"])
    wr = {b: (100*sum(v)/len(v) if v else 0, len(v)) for b, v in bins.items()}
    grad = wr["high"][0] - wr["low"][0]
    return wr, grad, (q1, q2)

def stability(rows, feat):
    """gradient (high-third minus low-third win%) in the first vs second time-half."""
    rr = sorted(rows, key=lambda r: r["t"]); h = len(rr)//2
    return terciles(rr[:h], feat)[1], terciles(rr[h:], feat)[1]

def conditional(rows, feat):
    """within each well-sampled fingerprint, does the feature's top-half beat its bottom-half?"""
    byfp = defaultdict(list)
    for r in rows: byfp[r["key"]].append(r)
    lifts = []
    for fp, rs in byfp.items():
        if len(rs) < 24: continue
        med = st.median(r[feat] for r in rs)
        hi = [r["win"] for r in rs if r[feat] > med]; lo = [r["win"] for r in rs if r[feat] <= med]
        if len(hi) >= 6 and len(lo) >= 6:
            lifts.append((100*sum(hi)/len(hi)) - (100*sum(lo)/len(lo)))
    return (st.mean(lifts) if lifts else 0.0), len(lifts)

def study(label, rows):
    print(f"\n{'='*70}\n{label}  (n={len(rows)}, base win {100*sum(r['win'] for r in rows)/len(rows):.0f}%)")
    feats = ["runup", "wpr", "angle_abs", "adx", "bars", "angle_aligned"]
    print(f"{'feature':14}{'low%':>7}{'mid%':>7}{'high%':>7}{'grad':>7}{'h1grad':>8}{'h2grad':>8}{'condLift':>9}  verdict")
    for f in feats:
        wr, grad, _ = terciles(rows, f)
        g1, g2 = stability(rows, f)
        cl, nfp = conditional(rows, f)
        stable = (g1 * g2 > 0) and abs(g1) > 4 and abs(g2) > 4          # same-sign, non-trivial both halves
        strong = abs(grad) >= 8 and stable and abs(cl) >= 4
        verdict = "** CANDIDATE" if strong else ("stable-weak" if stable else "noise/unstable")
        print(f"{f:14}{wr['low'][0]:>6.0f}%{wr['mid'][0]:>6.0f}%{wr['high'][0]:>6.0f}%{grad:>+7.0f}{g1:>+8.0f}{g2:>+8.0f}{cl:>+9.0f}  {verdict}")

def binary_test(label, rows, feat):
    a = [r["win"] for r in rows if r[feat] == 1]; b = [r["win"] for r in rows if r[feat] == 0]
    if not a or not b: return
    wa, wb = 100*sum(a)/len(a), 100*sum(b)/len(b)
    print(f"  {label:16} {feat}=1: {wa:.0f}% win (n={len(a)})  vs  =0: {wb:.0f}% (n={len(b)})  gap {wa-wb:+.0f}pp")

def wpr_dive(label, rows):
    xs = sorted(rows, key=lambda r: r["wpr"]); n = len(xs); q = n//4
    print(f"  {label:16}", end="")
    for i, name in enumerate(("Q1-low", "Q2", "Q3", "Q4-high")):
        seg = xs[i*q:(i+1)*q] if i < 3 else xs[3*q:]
        w = 100*sum(r["win"] for r in seg)/len(seg)
        print(f"  {name} {w:.0f}%(n{len(seg)})", end="")
    print()

def main():
    allrows = []
    per = {}
    for label, name in DBS.items():
        rows = load(name)
        for r in rows: r["sym"] = label
        per[label] = rows; allrows += rows
        study(label, rows)
    study("POOLED gold+oil", allrows)

    print(f"\n{'='*70}\nANGLE_ALIGNED — proper binary test (MA sloping WITH the trade vs against):")
    for label, rows in list(per.items()) + [("POOLED", allrows)]:
        binary_test(label, rows, "angle_aligned")
    print(f"\nWPR — win-rate by quartile of signal extremity (the standout candidate):")
    for label, rows in list(per.items()) + [("POOLED", allrows)]:
        wpr_dive(label, rows)
    print(f"\n{'-'*70}")
    print("READ: 'grad' = high-third minus low-third win%. A CANDIDATE needs a real gradient")
    print("(|grad|>=8), same-signed & non-trivial in BOTH halves (time-stable), AND a conditional")
    print("lift within fingerprints (|condLift|>=4 = refines the cut, not a proxy). Anything else")
    print("is noise/regime. A CANDIDATE -> add to ClassifySetup, rebuild the gate DB, CPCV before live.")

if __name__ == "__main__":
    main()
