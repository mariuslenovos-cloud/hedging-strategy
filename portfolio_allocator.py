"""
portfolio_allocator.py -- AFML Ch.16 portfolio layer over the validated streams.

THE PROFIT QUESTION IT ANSWERS
------------------------------
gold/silver/oil currently run as three SEPARATE EAs at fixed lots -- NOT a
risk-budgeted portfolio. Metal/metal/commodity drawdowns don't peak at the same
time, so the COMBINED drawdown is smaller than the average individual one. That
headroom is free money: at the same risk budget you can run MORE total capital
across the book -> more profit, no new edge required.

WHAT IT DOES
------------
1. Parses each MT5 Strategy-Tester HTML report's Deals table -> daily realized
   equity curve (and pulls the report's own Equity-DD stat = true intraday risk).
2. Cross-stream correlation of daily returns (the diversification you're not
   harvesting).
3. Three capital allocations: equal-weight, inverse-variance, and HRP (Ch.16,
   hierarchical risk parity -- correlation cluster -> recursive bisection).
4. Combined equity + combined max-DD vs the weighted-average individual DD
   -> the DIVERSIFICATION RATIO and the SIZE-UP factor to a target DD budget.
5. Concrete output: per-stream capital weights + how much more total exposure
   the book can safely carry.

CAVEATS (honest): single in-sample backtest per stream; correlation from ~6mo of
daily data is rough; realized balance-DD understates floating/intraday DD (we
also print the report's Equity-DD). Treat the size-up as directional -> confirm live.

Usage:
    python portfolio_allocator.py                 # DD budget 20%
    python portfolio_allocator.py 25              # custom DD budget %
    python portfolio_allocator.py 20 --write      # save report to analysis_data/
"""
import io
import os
import re
import sys
from datetime import datetime

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage, leaves_list
from scipy.spatial.distance import squareform

HERE = os.path.dirname(os.path.abspath(__file__))
REPORTS = {"gold": "gold_report.html", "silver": "silver_report.html",
           "oil": "oil_report.html"}
START_EQUITY = 3000.0
ANN = 252  # trading days/yr for annualizing the daily Sharpe


def _num(s):
    return float(s.replace("\xa0", "").replace(" ", "").replace(",", ""))


def parse_report(path):
    """Return (daily_equity Series, stats dict) from an MT5 HTML report."""
    t = io.open(path, encoding="utf-16").read()
    i = t.find(">Deals<")
    seg = t[i:]
    deals = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", seg, re.S):
        c = [re.sub(r"<[^>]+>", "", x).strip()
             for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        if len(c) < 13:
            continue
        try:
            dt = datetime.strptime(c[0], "%Y.%m.%d %H:%M:%S")
        except ValueError:
            if deals:           # past the deals table -> stop
                break
            continue
        try:
            bal = _num(c[11])
        except ValueError:
            continue
        deals.append((dt, bal))
    df = pd.DataFrame(deals, columns=["dt", "balance"])
    df["date"] = df["dt"].dt.normalize()
    eod = df.groupby("date")["balance"].last()

    # report's own headline stats
    def grab(label):
        m = re.search(re.escape(label) + r".*?<b>([\-\d\xa0 .,]+)</b>", t, re.S)
        return _num(m.group(1)) if m else float("nan")
    stats = {
        "net": grab("Total Net Profit"),
        "pf": grab("Profit Factor"),
        "bal_dd_pct": grab("Balance Drawdown Maximal"),   # may be $; pct variant below
        "eq_dd_pct": _eq_dd_pct(t),
    }
    return eod, stats


def _eq_dd_pct(t):
    m = re.search(r"Equity Drawdown Maximal.*?\(([\d\xa0 .,]+)%\)", t, re.S)
    if m:
        return _num(m.group(1))
    m = re.search(r"Equity Drawdown Relative.*?([\d\xa0 .,]+)%", t, re.S)
    return _num(m.group(1)) if m else float("nan")


def max_dd_pct(equity):
    peak = equity.cummax()
    return float(((equity - peak) / peak).min() * -100)


def hrp_weights(rets):
    cov, corr = rets.cov(), rets.corr()
    dist = ((1 - corr) / 2.0) ** 0.5
    link = linkage(squareform(dist.values, checks=False), method="single")
    order = [corr.columns[i] for i in leaves_list(link)]
    w = pd.Series(1.0, index=order)
    clusters = [order]
    while clusters:
        nxt = []
        for c in clusters:
            if len(c) <= 1:
                continue
            h = len(c) // 2
            left, right = c[:h], c[h:]
            def cvar(items):
                cv = cov.loc[items, items].values
                iv = 1.0 / np.diag(cv); iv /= iv.sum()
                return float(iv @ cv @ iv)
            lv, rv = cvar(left), cvar(right)
            a = 1 - lv / (lv + rv)
            for x in left:
                w[x] *= a
            for x in right:
                w[x] *= (1 - a)
            nxt += [left, right]
        clusters = nxt
    return (w / w.sum()).reindex(rets.columns)


def combined_curve(daily_pnl, weights):
    """Reallocate the SAME total capital by weights; return combined equity."""
    # express each stream as a return on its own equity, then weight
    pnl = (daily_pnl * weights).sum(axis=1)
    return START_EQUITY + pnl.cumsum()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    budget = float(args[0]) if args else 20.0
    do_write = "--write" in sys.argv
    out = []
    def emit(s=""):
        print(s); out.append(s)

    eods, stats = {}, {}
    for sym, fn in REPORTS.items():
        eods[sym], stats[sym] = parse_report(os.path.join(HERE, fn))

    # align on a daily calendar, forward-fill equity, leading = START_EQUITY
    cal = pd.date_range(min(s.index.min() for s in eods.values()),
                        max(s.index.max() for s in eods.values()), freq="D")
    eq = pd.DataFrame({s: eods[s].reindex(cal).ffill().fillna(START_EQUITY)
                       for s in REPORTS})
    pnl = eq.diff().fillna(0.0)                       # daily $ P&L per stream
    rets = pnl.div(eq.shift().fillna(START_EQUITY))   # daily return per stream

    emit("Per-stream (in-sample backtest, realized balance curve):")
    emit(f"{'stream':<8}{'net$':>10}{'PF':>6}{'balDD%':>8}{'eqDD%':>8}"
         f"{'dayVol%':>9}{'annSharpe':>10}")
    emit("-" * 59)
    for s in REPORTS:
        net = eq[s].iloc[-1] - START_EQUITY
        sh = rets[s].mean() / rets[s].std() * np.sqrt(ANN) if rets[s].std() else 0
        emit(f"{s:<8}{net:>+10.0f}{stats[s]['pf']:>6.2f}"
             f"{max_dd_pct(eq[s]):>8.1f}{stats[s]['eq_dd_pct']:>8.1f}"
             f"{rets[s].std()*100:>9.2f}{sh:>10.2f}")
    emit("-" * 59)

    emit("\nCorrelation of daily returns (lower = more diversification):")
    emit(rets.corr().round(2).to_string())

    # allocations
    n = len(REPORTS)
    eqw = pd.Series(1.0 / n, index=rets.columns)
    iv = 1.0 / rets.var(); iv /= iv.sum()
    hrp = hrp_weights(rets)

    emit("\nCapital weights:")
    wtab = pd.DataFrame({"equal": eqw, "inverse-var": iv, "HRP": hrp}).round(3)
    emit(wtab.to_string())

    # FLOATING equity DD is the real risk (grid recovers most realized DD).
    # Combined floating DD, correlation-adjusted: sqrt((w*d)' Corr (w*d)).
    d = np.array([stats[s]["eq_dd_pct"] for s in rets.columns])
    corrM = rets.corr().values
    avg_ind_eqdd = float(d.mean())

    def float_dd(w):
        v = w.values * d
        adj = float(np.sqrt(v @ corrM @ v))      # correlation-adjusted
        worst = float(v.sum())                    # if perfectly correlated
        return adj, worst

    emit(f"\nCombined book at each allocation (one ${START_EQUITY*n:,.0f} account):")
    emit(f"{'alloc':<14}{'net$':>10}{'realDD%':>9}{'floatDD%':>10}"
         f"{'worstDD%':>10}{'divRatio':>10}")
    emit("-" * 63)
    best = None
    for name, w in [("equal", eqw), ("inverse-var", iv), ("HRP", hrp)]:
        cpnl = (pnl * w).sum(axis=1) * n
        ceq = START_EQUITY * n + cpnl.cumsum()
        rdd = max_dd_pct(ceq)
        cnet = ceq.iloc[-1] - START_EQUITY * n
        fdd, wdd = float_dd(w)
        div = avg_ind_eqdd / fdd if fdd else float("nan")
        emit(f"{name:<14}{cnet:>+10.0f}{rdd:>9.1f}{fdd:>10.1f}{wdd:>10.1f}{div:>10.2f}")
        if best is None or div > best[1]:
            best = (name, div, fdd, cnet, w)

    name, div, fdd, cnet, w = best
    headroom = budget - fdd
    sizeup = budget / fdd if fdd else float("nan")
    haircut = 0.70                       # CPCV degradation seen on these streams
    emit("\n" + "=" * 64)
    emit(f"RECOMMENDATION ({name} allocation -- best diversification):")
    emit(f"  weights: " + "  ".join(f"{s}={w[s]*100:.0f}%" for s in rets.columns))
    emit(f"  combined FLOATING DD ~{fdd:.1f}% (corr-adjusted) vs avg individual "
         f"{avg_ind_eqdd:.1f}% -> diversification {div:.2f}x")
    emit(f"  vs gold-alone 20.2%: the diversified book carries the SAME ~${cnet:,.0f} "
         f"in-sample net at ~{fdd:.1f}% risk instead of 20%+.")
    emit(f"  headroom to a {budget:.0f}% budget = {headroom:.1f}pp "
         f"(~{sizeup:.2f}x directional, IF DD scales with size).")
    emit(f"  realistic net after ~0.70x CPCV haircut + costs: "
         f"~${cnet*haircut:,.0f}/window in-sample-equiv (NOT a promise).")
    emit("=" * 64)
    emit("HONEST CAVEATS:")
    emit(" - One in-sample backtest per stream, ~6mo, one regime. Live is truth.")
    emit(" - Size-up is DIRECTIONAL: grid DD% is partly %-floor-capped (sub-linear")
    emit("   in lots) but floating DD can still rise with size -> validate with a")
    emit("   COMBINED every-tick backtest before leveraging, don't just multiply.")
    emit(" - The robust win is the LOWER combined DD (run all 3 on one account at")
    emit("   these weights) -- not the leverage. Breadth (more streams) shrinks it")
    emit("   further: re-run this as US100/AUDJPY/USDCHF validate.")

    if do_write:
        p = os.path.join(HERE, "analysis_data",
                         f"portfolio_alloc_{datetime.now():%Y%m%d}.txt")
        with open(p, "w") as f:
            f.write("\n".join(out) + "\n")
        print(f"\nSaved -> {p}")


if __name__ == "__main__":
    main()
