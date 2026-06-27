#!/usr/bin/env python3
"""
two_engine_lab.py  --  HARVESTER + TREND-RIDER pairing lab (the book-level hedge test)

THESIS (session 2026-06-22): fib C (the grid HARVESTER) and GoldTrend (the breakout
TREND-RIDER) are NEGATIVELY correlated by construction -- the harvester wins ranging
gold and bleeds in trends; the trend-rider does the opposite. So when the harvester
hits the "market-shift landmine" (a sustained move that floats its grid deep), the
trend-rider should be making its big winner AT THE SAME TIME. Run BOTH and the
combined equity curve is smooth: whichever side of the landmine the market picks,
one engine is on it.

This tool reads each engine's per-bar FLOATING-equity log (written when UseEquityLog=true
in the tester), aligns them in time, and answers one question precisely:
    >>> When the harvester is bleeding, is the trend-rider making money?

Why FLOATING equity (not realized balance): the landmine is a floating event -- the grid
floats deep underwater before it floors. Realized balance only shows the floor-fire step
and would hide the deep float the trend-rider is meant to cover in real time. (Same lesson
as portfolio_allocator.py: feed floating eqDD, not realized balance-DD.)

RUN RECIPE (each EA standalone, SAME gold window, SAME $3,000 start, hedging acct):
  1. fib C MT5 (build >= D): GOLD M5, Every tick, UseEquityLog=true, EquityLogFile=fibc_equity.csv
  2. GoldTrend MT5 (build >= C): Symbols="GOLD", chart GOLD (H1 or M5), Every tick,
     UseEquityLog=true, EquityLogFile=goldtrend_equity.csv
  3. python two_engine_lab.py
Each engine sits on its own $3,000 slice (portfolio Option A) -> combined book = $6,000.

Usage:
  python two_engine_lab.py [fibc_csv] [goldtrend_csv]
  (defaults: the two files in the MT5 Common\\Files folder)
"""
import sys, os
import numpy as np
import pandas as pd

COMMON = os.path.expandvars(r"%APPDATA%\MetaQuotes\Terminal\Common\Files")
DEF_HARV  = os.path.join(COMMON, "fibc_equity.csv")
DEF_TREND = os.path.join(COMMON, "goldtrend_equity.csv")
START_CAP = 3000.0          # per engine
MIN_DD_USD = 200.0          # ignore drawdown episodes shallower than this (noise)


def load(path, name):
    if not os.path.exists(path):
        sys.exit(f"[!] {name} equity log not found: {path}\n"
                 f"    Run the {name} backtest with UseEquityLog=true first.")
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    if "time" not in df or "equity" not in df:
        sys.exit(f"[!] {name}: expected columns time,balance,equity -> got {list(df.columns)}")
    df["time"] = pd.to_datetime(df["time"], format="%Y.%m.%d %H:%M:%S", errors="coerce")
    df = df.dropna(subset=["time"]).drop_duplicates("time", keep="last").set_index("time").sort_index()
    return df["equity"].astype(float)


def max_dd(equity):
    """max floating drawdown ($ and %), from running peak."""
    peak = equity.cummax()
    dd = equity - peak
    ddpct = dd / peak * 100.0
    i = dd.idxmin()
    return -dd.loc[i], -ddpct.loc[i], i  # positive magnitudes, trough time


def dd_episodes(equity, min_usd=MIN_DD_USD):
    """Find peak->trough->recovery drawdown episodes deeper than min_usd."""
    peak = equity.cummax()
    underwater = equity < peak - 1e-9
    eps, in_ep, start = [], False, None
    for t, uw in underwater.items():
        if uw and not in_ep:
            in_ep, start = True, prev_peak_time(equity, peak, t)
        elif not uw and in_ep:
            in_ep = False
            seg = equity.loc[start:t]
            depth = (peak.loc[start] - seg.min())
            if depth >= min_usd:
                eps.append((start, seg.idxmin(), t, depth))
        prev = t
    if in_ep:  # still underwater at end
        seg = equity.loc[start:]
        depth = peak.loc[start] - seg.min()
        if depth >= min_usd:
            eps.append((start, seg.idxmin(), seg.index[-1], depth))
    return eps


def prev_peak_time(equity, peak, t):
    pv = peak.loc[t]
    before = equity.loc[:t]
    hit = before[before >= pv - 1e-9]
    return hit.index[-1] if len(hit) else before.index[0]


def main():
    hp = sys.argv[1] if len(sys.argv) > 1 else DEF_HARV
    tp = sys.argv[2] if len(sys.argv) > 2 else DEF_TREND
    harv = load(hp, "HARVESTER (fib C)")
    trend = load(tp, "TREND-RIDER (GoldTrend)")

    # align on union of timestamps, forward-fill (each holds last-known equity between its bars)
    grid = harv.index.union(trend.index)
    H = harv.reindex(grid).ffill().bfill()
    T = trend.reindex(grid).ffill().bfill()
    C = H + T                                   # combined $6k book

    span = f"{grid[0]:%Y-%m-%d} -> {grid[-1]:%Y-%m-%d}"
    hN, tN, cN = H.iloc[-1]-START_CAP, T.iloc[-1]-START_CAP, C.iloc[-1]-2*START_CAP
    hDD,hDDp,hI = max_dd(H); tDD,tDDp,tI = max_dd(T); cDD,cDDp,cI = max_dd(C)

    print("="*70)
    print(f"TWO-ENGINE LAB  |  {span}  |  {len(grid):,} aligned bars")
    print("="*70)
    print(f"{'engine':<22}{'net $':>12}{'maxFloatDD $':>15}{'maxFloatDD %':>14}")
    print("-"*63)
    print(f"{'HARVESTER (fib C)':<22}{hN:>12,.0f}{hDD:>15,.0f}{hDDp:>13.1f}%")
    print(f"{'TREND-RIDER (GoldTr)':<22}{tN:>12,.0f}{tDD:>15,.0f}{tDDp:>13.1f}%")
    print(f"{'COMBINED BOOK':<22}{cN:>12,.0f}{cDD:>15,.0f}{cDDp:>13.1f}%")
    print("-"*63)

    # diversification: did combining cut the drawdown vs the worst single engine?
    worst_single_pct = max(hDDp, tDDp)
    div_ratio = (hDD + tDD) / cDD if cDD > 0 else float("nan")
    print(f"\nDIVERSIFICATION:")
    print(f"  worst single-engine floatDD : {worst_single_pct:5.1f}%  "
          f"(harvester {hDDp:.1f}% / trend {tDDp:.1f}%)")
    print(f"  COMBINED floatDD            : {cDDp:5.1f}%   "
          f"<-- {'LOWER (landmine softened)' if cDDp < worst_single_pct-0.5 else 'NOT lower'}")
    print(f"  diversification ratio        : {div_ratio:4.2f}x  (>1 = the curves offset)")

    # correlation of daily returns (the structural claim)
    dH = H.resample("1D").last().pct_change().dropna()
    dT = T.resample("1D").last().pct_change().dropna()
    j = pd.concat([dH, dT], axis=1, keys=["h", "t"]).dropna()
    corr = j["h"].corr(j["t"]) if len(j) > 5 else float("nan")
    print(f"\nDAILY-RETURN CORRELATION (harvester vs trend): {corr:+.2f}   "
          f"({'negatively correlated -- IDEAL' if corr < -0.05 else 'uncorrelated -- good' if corr < 0.3 else 'POSITIVELY correlated -- weak hedge'})")

    # THE CRUX: during the harvester's drawdown episodes, what did the trend-rider do?
    eps = dd_episodes(H)
    print(f"\nLANDMINE COVERAGE  --  harvester drawdowns >= ${MIN_DD_USD:.0f} (the crux):")
    if not eps:
        print("  (no drawdown episodes that deep -- harvester was calm this window)")
    else:
        print(f"  {'harvester DD window':<26}{'harv loss':>11}{'trend P&L':>11}{'covered?':>10}")
        print("  " + "-"*56)
        cov_loss = cov_gain = 0.0
        for start, trough, end, depth in eps:
            h_loss = H.loc[trough] - H.loc[start]                 # negative
            t_pl   = T.loc[trough] - T.loc[start]                 # trend P&L over the SAME peak->trough window
            cov_loss += -h_loss; cov_gain += max(t_pl, 0)
            tag = "YES" if t_pl > 0 else "no"
            print(f"  {start:%Y-%m-%d}->{trough:%m-%d}{'':<6}{h_loss:>11,.0f}{t_pl:>11,.0f}{tag:>10}")
        ratio = cov_gain / cov_loss * 100 if cov_loss > 0 else 0
        print("  " + "-"*56)
        print(f"  trend-rider offset {cov_gain:,.0f} of {cov_loss:,.0f} harvester drawdown "
              f"= {ratio:.0f}% covered")

    # verdict
    print("\n" + "="*70)
    smooth = cDDp < worst_single_pct - 0.5 and cN > 0
    print("VERDICT: " + (
        "TWO-ENGINE BOOK WORKS -- combined DD lower than either engine, net positive."
        if smooth else
        "MIXED -- see numbers above; the pairing did not clearly smooth the curve."))
    print("  (Caveat: each engine on its own $3k slice; one window; in-sample. "
          "Confirm OOS / on more windows before sizing.)")
    print("="*70)

    plot(H, T, C, eps)


def plot(H, T, C, eps):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        print("\n(matplotlib not available -- skipping chart; numbers above stand.)")
        return
    fig, ax = plt.subplots(2, 1, figsize=(14, 8), sharex=True,
                           gridspec_kw={"height_ratios": [2, 1]})
    ax[0].plot(C.index, C, lw=1.6, color="black", label="COMBINED book ($6k)")
    ax[0].plot(H.index, H, lw=1.0, color="#1f77b4", label="Harvester fib C ($3k)")
    ax[0].plot(T.index, T, lw=1.0, color="#2ca02c", label="Trend-rider GoldTrend ($3k)")
    for start, trough, end, depth in eps:
        ax[0].axvspan(start, end, color="red", alpha=0.08)
    ax[0].set_title("Two-engine book: harvester + trend-rider (red = harvester drawdowns)")
    ax[0].legend(loc="upper left"); ax[0].grid(alpha=0.3)
    # drawdown panel
    ax[1].fill_between(H.index, (H - H.cummax()), 0, color="#1f77b4", alpha=0.4, label="harvester DD")
    ax[1].fill_between(C.index, (C - C.cummax()), 0, color="black", alpha=0.3, label="combined DD")
    ax[1].set_title("Floating drawdown ($)"); ax[1].legend(loc="lower left"); ax[1].grid(alpha=0.3)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "two_engine_overlay.png")
    fig.tight_layout(); fig.savefig(out, dpi=110)
    print(f"\nchart saved -> {out}")


if __name__ == "__main__":
    main()
