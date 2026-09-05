#!/usr/bin/env python3
"""
vr_precheck.py - Gate 0 for Marius RevScalp MT5.

Tests the premise the strategy rests on, before any MQL5 gets written:
  GOLD mean-reverts intraday  ->  VR(q) < 1, Lo-MacKinlay z < -2
  OIL  trends intraday        ->  VR(q) > 1, Lo-MacKinlay z > +2

Also reports:
  - Hurst exponent (R/S), as a noisy cross-check only
  - lag-1 autocorrelation of returns bucketed by SAST hour  <- the tradeable part
  - cost-feasibility: the minimum TP the arithmetic permits

Usage
-----
  python vr_precheck.py bars.csv --symbol XAUUSD --cost 0.30
  python vr_precheck.py gold.csv oil.csv --tz-shift 0
  python vr_precheck.py bars.csv --price-col mid --time-col timestamp

Input: any CSV with a timestamp column and a price column. Column names are
sniffed (time/date/timestamp/datetime, close/mid/bid/price/last). Override with
--time-col / --price-col. Bars are assumed already uniformly spaced (M1 or M5);
gaps across sessions are handled by dropping cross-gap returns.

IMPORTANT: run this on MID price if you have it. Negative lag-1 autocorrelation
on bid or last prices is partly bid-ask bounce -- a microstructure artefact you
cannot trade. If gold's mean reversion only appears on bid, Engine A is dead.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

TIME_CANDIDATES = ["timestamp", "datetime", "time", "date", "dt", "bar_time", "open_time"]
PRICE_CANDIDATES = ["mid", "close", "price", "last", "bid", "c", "close_price"]


# --------------------------------------------------------------------------- #
# loading
# --------------------------------------------------------------------------- #
def sniff_col(cols, candidates, kind):
    lower = {c.lower().strip(): c for c in cols}
    for cand in candidates:
        if cand in lower:
            return lower[cand]
    for cand in candidates:
        for lc, orig in lower.items():
            if cand in lc:
                return orig
    raise SystemExit(
        f"Could not find a {kind} column. Looked for {candidates}.\n"
        f"Columns present: {list(cols)}\nPass --{kind}-col explicitly."
    )


def load(path: Path, time_col: str | None, price_col: str | None, tz_shift: float):
    # tolerate comma, tab and semicolon separated exports
    df = pd.read_csv(path, sep=None, engine="python")
    tcol = time_col or sniff_col(df.columns, TIME_CANDIDATES, "time")
    pcol = price_col or sniff_col(df.columns, PRICE_CANDIDATES, "price")

    ts = pd.to_datetime(df[tcol], errors="coerce", utc=False)
    px = pd.to_numeric(df[pcol], errors="coerce")

    out = pd.DataFrame({"ts": ts, "px": px}).dropna()
    out = out[out["px"] > 0].sort_values("ts").reset_index(drop=True)
    if tz_shift:
        out["ts"] = out["ts"] + pd.Timedelta(hours=tz_shift)
    if len(out) < 500:
        raise SystemExit(f"{path.name}: only {len(out)} usable rows. Need >= 500.")
    return out, tcol, pcol


def log_returns(d: pd.DataFrame):
    """Log returns, with returns spanning a session gap dropped.

    A 'gap' is any interval > 5x the median bar spacing -- weekend and daily
    breaks would otherwise inject fake mean reversion into the statistics.
    """
    lp = np.log(d["px"].to_numpy())
    r = np.diff(lp)
    dt = d["ts"].diff().dt.total_seconds().to_numpy()[1:]
    med = np.nanmedian(dt)
    keep = dt <= 5 * med if np.isfinite(med) and med > 0 else np.ones_like(r, dtype=bool)
    return r[keep], d["ts"].to_numpy()[1:][keep], med


# --------------------------------------------------------------------------- #
# Lo-MacKinlay variance ratio, heteroskedasticity-robust
# --------------------------------------------------------------------------- #
def variance_ratio(r: np.ndarray, q: int):
    """Return (VR, z_robust). r = log returns, q = aggregation horizon in bars."""
    n = len(r)
    if n < q * 10:
        return np.nan, np.nan

    mu = r.mean()
    # 1-period variance (unbiased)
    var1 = np.sum((r - mu) ** 2) / (n - 1)
    if var1 <= 0:
        return np.nan, np.nan

    # q-period variance via overlapping sums, Lo-MacKinlay bias correction
    cs = np.cumsum(np.insert(r, 0, 0.0))
    rq = cs[q:] - cs[:-q]                      # overlapping q-bar returns
    m = q * (n - q + 1) * (1 - q / n)
    varq = np.sum((rq - q * mu) ** 2) / m
    vr = varq / var1

    # heteroskedasticity-robust variance of VR (Lo & MacKinlay 1988, theorem 1)
    dev2 = (r - mu) ** 2
    theta = 0.0
    for j in range(1, q):
        num = np.sum(dev2[j:] * dev2[:-j])
        delta = num / (np.sum(dev2) ** 2)
        theta += ((2 * (q - j) / q) ** 2) * delta
    z = (vr - 1) / np.sqrt(theta) if theta > 0 else np.nan
    return vr, z


def hurst_rs(r: np.ndarray, min_n: int = 16, max_splits: int = 12):
    """Hurst via rescaled range. Noisy on intraday data -- cross-check only."""
    n = len(r)
    sizes, rs_vals = [], []
    size = min_n
    while size <= n // 4 and len(sizes) < max_splits:
        chunks = n // size
        vals = []
        for i in range(chunks):
            x = r[i * size:(i + 1) * size]
            y = x - x.mean()
            z = np.cumsum(y)
            rng = z.max() - z.min()
            s = x.std(ddof=1)
            if s > 0 and rng > 0:
                vals.append(rng / s)
        if vals:
            sizes.append(size)
            rs_vals.append(np.mean(vals))
        size *= 2
    if len(sizes) < 4:
        return np.nan
    return float(np.polyfit(np.log(sizes), np.log(rs_vals), 1)[0])


def autocorr_by_hour(r: np.ndarray, ts: np.ndarray, min_obs: int = 200):
    """Lag-1 autocorrelation of returns per clock hour. This is the tradeable cut."""
    hours = pd.DatetimeIndex(ts).hour
    rows = []
    for h in range(24):
        m = hours == h
        x = r[m]
        if len(x) < min_obs:
            continue
        a, b = x[:-1], x[1:]
        if a.std() == 0 or b.std() == 0:
            continue
        ac = float(np.corrcoef(a, b)[0, 1])
        se = 1.0 / np.sqrt(len(x))          # approximate SE under the null
        rows.append({"hour": h, "n": len(x), "lag1_ac": ac, "t": ac / se})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #
def verdict(vr, z):
    if not np.isfinite(z):
        return "insufficient data"
    if z < -2.0:
        return "MEAN REVERTING"
    if z > 2.0:
        return "TRENDING"
    return "random walk (no edge)"


def report(path: Path, args):
    d, tcol, pcol = load(path, args.time_col, args.price_col, args.tz_shift)
    r, ts, med = log_returns(d)
    sym = args.symbol or path.stem

    print("=" * 72)
    print(f"{sym}   [{path.name}]")
    print(f"  columns used     : time={tcol}  price={pcol}")
    print(f"  bars             : {len(r):,}   median spacing: {med/60:.1f} min")
    print(f"  span             : {d['ts'].iloc[0]}  ->  {d['ts'].iloc[-1]}")
    if pcol.lower() not in ("mid",):
        print(f"  !! price column is '{pcol}', not mid. Negative autocorrelation here")
        print(f"     may be bid-ask bounce rather than tradeable mean reversion.")
    print()

    print("  Variance ratio (Lo-MacKinlay, heteroskedasticity-robust)")
    print(f"  {'q':>4} {'VR':>8} {'z':>8}   verdict")
    gate_row = None
    for q in (2, 5, 10, 30):
        vr, z = variance_ratio(r, q)
        print(f"  {q:>4} {vr:>8.4f} {z:>8.2f}   {verdict(vr, z)}")
        if q == 5:
            gate_row = (vr, z)
    print()

    h = hurst_rs(r)
    print(f"  Hurst (R/S)      : {h:.3f}   ({'<0.5 reverting' if h < 0.5 else '>0.5 trending'}) "
          f"-- noisy, cross-check only")
    print()

    ac = autocorr_by_hour(r, ts)
    if not ac.empty:
        print(f"  Lag-1 autocorrelation by hour (clock of the data, shifted {args.tz_shift:+g}h)")
        print(f"  {'hr':>4} {'n':>8} {'lag1':>9} {'t':>7}  signal")
        for _, row in ac.iterrows():
            sig = ""
            if row["t"] < -2:
                sig = "<- reversion"
            elif row["t"] > 2:
                sig = "<- momentum"
            print(f"  {int(row['hour']):>4} {int(row['n']):>8} {row['lag1_ac']:>9.4f} "
                  f"{row['t']:>7.2f}  {sig}")
        lo, hi = ac.loc[ac["t"].idxmin()], ac.loc[ac["t"].idxmax()]
        print()
        if lo["t"] < -2:
            print(f"  strongest reversion hour: {int(lo['hour']):02d}:00 (t={lo['t']:.2f})")
        else:
            print(f"  no hour shows significant reversion (min t={lo['t']:.2f})")
        if hi["t"] > 2:
            print(f"  strongest momentum  hour: {int(hi['hour']):02d}:00 (t={hi['t']:.2f})")
        else:
            print(f"  no hour shows significant momentum  (max t={hi['t']:.2f})")
        print("  -> trade the hours that pass, not the average of all of them")
    print()

    if args.cost:
        px = d["px"].iloc[-1]
        bar_sd = r.std() * px
        print(f"  Cost feasibility (round-turn cost C = {args.cost:g} price units)")
        print(f"  1-bar sigma      : {bar_sd:.4f} price units")
        print(f"  min TP (3.0 x C) : {3.0*args.cost:.4f}  = {3.0*args.cost/bar_sd:.2f} bar-sigma")
        need = 3.0 * args.cost / bar_sd
        if need > 4:
            print(f"  !! that target is {need:.1f} sigma away. Too far for a scalp at this")
            print(f"     bar size -- either move to a higher timeframe or drop the symbol.")
        elif need < 1:
            print(f"  target is inside 1 bar-sigma: reachable, but check fill realism.")
        else:
            print(f"  target sits in a workable band ({need:.2f} sigma).")
    print()

    vr5, z5 = gate_row
    exp = args.expect
    if exp:
        ok = (z5 < -2.0) if exp == "revert" else (z5 > 2.0)
        print(f"  GATE 0 [{exp}]: {'PASS' if ok else 'FAIL'}   (VR(5)={vr5:.4f}, z={z5:.2f})")
        if not ok:
            print("  -> premise not supported. Per spec Section 1, this engine is not built.")
    print()


def main():
    p = argparse.ArgumentParser(description="Gate 0 premise test for RevScalp.")
    p.add_argument("csv", nargs="+", type=Path)
    p.add_argument("--symbol", help="label for the report")
    p.add_argument("--time-col")
    p.add_argument("--price-col", help="use 'mid' if you have it")
    p.add_argument("--tz-shift", type=float, default=0.0,
                   help="hours to add to timestamps to reach SAST (UTC+2)")
    p.add_argument("--cost", type=float, default=0.0,
                   help="round-turn cost in price units (gold ~0.30, WTI ~0.05)")
    p.add_argument("--expect", choices=["revert", "trend"],
                   help="pre-commit the expected direction; prints PASS/FAIL")
    args = p.parse_args()

    for path in args.csv:
        if not path.exists():
            print(f"skip: {path} not found", file=sys.stderr)
            continue
        try:
            report(path, args)
        except SystemExit as e:
            print(f"{path.name}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
