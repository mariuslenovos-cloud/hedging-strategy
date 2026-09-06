#!/usr/bin/env python3
"""
stage1_tsmom.py — Stage 1 test for SLOW momentum (cell A on the search map).

The M1-derived harness cannot see daily momentum: it lives in 1-12 month
lookbacks, shows as t ~ 2-3 over years, and lag-1 autocorrelation on a few
hundred daily bars is the wrong instrument. This is the right one.

Test: for lookback L days and hold h days, does sign(past L-day return)
predict the next h-day return?  (Moskowitz-Ooi-Pedersen time-series momentum)

Reports per (L, h):
  t_nw        Newey-West t-stat of sign(past_L) * fwd_h  (lag h-1, overlap-safe)
  t_1st/t_2nd same, on each half of the history. CARD requires > 1.0 in both.
              Every (L,h) cell shares one price path, so adjacent-cell agreement
              cannot catch a fluke path; the split-half can.
  hit         fraction of hold windows where the sign was right
  mean_pu     mean signed forward move per window, in price units
  cost_pu     spread + commission + |swap| * h, in price units, per window
  edge/C      mean_pu / cost_pu  -- must clear 3.0 (same rule as everywhere)
  vr          variance ratio at q=h on daily returns, for context

Input: D1 bars. Export straight from the terminal -- the 100k-bar cap is
irrelevant at D1, twenty years is ~5,000 bars. Need >= 5 years for any
lookback >= 120; 10+ is better.

Usage:
  python stage1_tsmom.py XAUUSD_D1.csv --spread 0.30 --swap-long 0.55 --swap-short 0.35
  swap-* are the terminal's overnight charge per 1.00 lot, converted to price
  units per day (USD per oz). Charge whichever side the signal would hold;
  the script uses the worse of the two by default (--swap-mode worst).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

TIME_CANDIDATES = ["timestamp", "datetime", "time", "date", "dt", "bar_time", "open_time"]
PRICE_CANDIDATES = ["mid", "close", "price", "last", "bid", "c", "close_price"]


def sniff(cols, cands, kind):
    lower = {c.lower().strip(): c for c in cols}
    for c in cands:
        if c in lower:
            return lower[c]
    for c in cands:
        for lc, o in lower.items():
            if c in lc:
                return o
    raise SystemExit(f"no {kind} column in {list(cols)}")


def load(path, tcol, pcol):
    df = pd.read_csv(path, sep=None, engine="python")
    tcol = tcol or sniff(df.columns, TIME_CANDIDATES, "time")
    pcol = pcol or sniff(df.columns, PRICE_CANDIDATES, "price")
    d = pd.DataFrame({"ts": pd.to_datetime(df[tcol], errors="coerce"),
                      "px": pd.to_numeric(df[pcol], errors="coerce")}).dropna()
    d = d[d.px > 0].sort_values("ts").drop_duplicates("ts").set_index("ts")["px"]
    # collapse to one bar per calendar day in case an intraday file was passed
    return d.resample("1D").last().dropna()


def newey_west_t(x, lag):
    x = np.asarray(x, float)
    n = len(x)
    if n < 30:
        return np.nan
    mu = x.mean()
    e = x - mu
    s = np.sum(e * e) / n
    for j in range(1, lag + 1):
        w = 1 - j / (lag + 1)
        s += 2 * w * np.sum(e[j:] * e[:-j]) / n
    if s <= 0:
        return np.nan
    return mu / np.sqrt(s / n)


def variance_ratio(r, q):
    n = len(r)
    if n < 10 * q:
        return np.nan
    mu = r.mean()
    var1 = np.sum((r - mu) ** 2) / (n - 1)
    cs = np.cumsum(np.insert(r, 0, 0.0))
    rq = cs[q:] - cs[:-q]
    m = q * (n - q + 1) * (1 - q / n)
    return np.sum((rq - q * mu) ** 2) / m / var1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", type=Path)
    ap.add_argument("--time-col")
    ap.add_argument("--price-col")
    ap.add_argument("--spread", type=float, default=0.0, help="round-turn spread+commission, price units")
    ap.add_argument("--swap-long", type=float, default=0.0, help="per-day long charge, price units (positive = cost)")
    ap.add_argument("--swap-short", type=float, default=0.0, help="per-day short charge, price units")
    ap.add_argument("--swap-mode", choices=["worst", "avg"], default="worst")
    ap.add_argument("--lookbacks", type=int, nargs="+", default=[20, 60, 120, 250])
    ap.add_argument("--holds", type=int, nargs="+", default=[5, 10, 20])
    ap.add_argument("--min-edge", type=float, default=3.0)
    a = ap.parse_args()

    px = load(a.csv, a.time_col, a.price_col)
    lp = np.log(px.to_numpy())
    r = np.diff(lp)
    level = float(px.iloc[-1])
    years = (px.index[-1] - px.index[0]).days / 365.25
    swap = max(a.swap_long, a.swap_short) if a.swap_mode == "worst" else (a.swap_long + a.swap_short) / 2

    print(f"{a.csv.name}: {len(px):,} daily bars, {years:.1f} years, "
          f"{px.index[0].date()} -> {px.index[-1].date()}   last {level:.2f}")
    if years < 5:
        print("!! under 5 years. Lookbacks >= 120 are underpowered; treat results as a look, not a verdict.")
    print(f"cost model: spread {a.spread:g} + swap {swap:g}/day ({a.swap_mode})\n")

    print(f"{'L':>5}{'h':>4}{'n':>7}{'t_nw':>8}{'t_1st':>7}{'t_2nd':>7}{'hit':>7}{'mean_pu':>10}{'cost_pu':>9}{'edge/C':>8}{'vr_h':>7}  verdict")
    best = []
    for L in a.lookbacks:
        for h in a.holds:
            # signal at t uses returns up to t; forward return t+1..t+h
            past = lp[L:-h] - lp[:-L - h]
            fwd = lp[L + h:] - lp[L:-h]
            if len(past) < 60:
                continue
            sig = np.sign(past)
            sig[sig == 0] = 1
            pnl = sig * fwd
            t = newey_west_t(pnl, h - 1)
            half = len(pnl) // 2
            t1, t2 = newey_west_t(pnl[:half], h - 1), newey_west_t(pnl[half:], h - 1)
            both = np.isfinite(t1) and np.isfinite(t2) and t1 > 1.0 and t2 > 1.0
            hit = float((pnl > 0).mean())
            mean_pu = float(pnl.mean() * level)
            cost_pu = a.spread + swap * h
            edge = mean_pu / cost_pu if cost_pu > 0 else np.nan
            vr = variance_ratio(r, h)
            if np.isfinite(t) and t >= 2.0 and np.isfinite(edge) and edge >= a.min_edge and both:
                v = "CARD"
            elif np.isfinite(t) and t >= 2.0 and np.isfinite(edge) and edge >= a.min_edge:
                v = "one half only"
            elif np.isfinite(t) and t >= 2.0:
                v = "signature, cost fails"
            elif np.isfinite(t) and t <= -2.0:
                v = "reversal"
            else:
                v = "none"
            print(f"{L:>5}{h:>4}{len(pnl):>7,}{t:>8.2f}{t1:>7.2f}{t2:>7.2f}{hit:>7.1%}{mean_pu:>10.2f}{cost_pu:>9.2f}{edge:>8.2f}{vr:>7.2f}  {v}")
            best.append((t, L, h, edge, v))
    print()
    cards = [b for b in best if b[4] == "CARD"]
    if cards:
        print("Cells clearing t >= 2.0, edge >= %.1fx cost, AND t > 1.0 in BOTH halves of the history:" % a.min_edge)
        for t, L, h, edge, _ in sorted(cards, reverse=True):
            print(f"  L={L:>3} h={h:>2}  t={t:.2f}  edge/C={edge:.2f}")
        print("\nStage 1 pass needs the same sign in adjacent (L, h) cells. One isolated CARD is a look.")
        print("All cells share one price path; the split-half column is what protects against a fluke path.")
    else:
        print("No (L, h) cell clears both the statistic and the cost term.")
        sigs = [b for b in best if b[0] >= 2.0]
        if sigs:
            print("Signature exists but swap+spread over the hold eats it -- venue problem, not signal problem.")
        elif years < 5:
            print("Not enough history to say. Export more D1 before calling this cell.")
        else:
            print("Cell A closed on this feed at this history length.")


if __name__ == "__main__":
    main()
