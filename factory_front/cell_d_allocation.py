#!/usr/bin/env python3
"""
cell_d_allocation.py -- Cell D on the search map: the ALLOCATION LAYER, measured.

No new signal. Takes the deployment-feed tester reports of the engines the book
already owns, converts each to a DAILY P&L series at the LIVE GEOMETRY ($2,390,
0.01-lot floor), and scores every book composition on return-over-drawdown.

Streams (all Pepperstone feed, Dec-01-2025 onward):
  gold      pep_gui_HPIN12_20260904.html      (GUI, 100% ticks)  flat 0.01-lot HALF geometry;
                                              lots step with compounding in the $3k run ->
                                              normalised to per-0.01-lot (deposit-invariant)
  oil       C:\\MT5 Pepperstone Runner\\rmb3.htm (SOLID4 control, Model 4) risk-normed 2.5% ->
                                              normalised to a fixed $2,390 balance
  longvol   pep_gui_longvol_A_20260906.html   (GUI, 100% ticks)  flat 0.01 lot, as is
  sessdrift C:\\MT5 Pepperstone Runner\\sd_h4.htm (exit 04:00 cell) risk-normed 2% -> $2,390
  fibc      C:\\MT5 Pepperstone Runner\\fibc_sr_G.htm (SR6, demo only) compounding 0.02 base ->
                                              per-0.02 base (off live; shown for the record)

Normalisation rule: a flat-lot engine's P&L scales with LOTS; a risk-normed engine's
P&L scales with BALANCE. Both are undone so every stream reads at the live account.
Realized (deal-level) P&L only: floating drawdown is deeper -- the ranking of
compositions is what this measures, not the absolute DD (portfolio_allocator lesson).

Output: correlation matrix, per-stream stats, and the composition table:
  net / maxDD / RF / worst day / pain-window sum, for the books you can actually run.
"""
import io, re, sys, itertools
import numpy as np, pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
LIVE_BAL = 2390.0
ROW = re.compile(r"(20\d\d\.\d\d\.\d\d \d\d:\d\d:\d\d) \d+ (\S+) (buy|sell) (in|out|in/out) ([\d.]+) ([\d.]+) \d+ (-?[\d.]+) (-?[\d.]+) (-?[\d.]+) (-?[\d ]+\.\d\d)")

STREAMS = {
    "gold":      (r"C:\Users\mariu\Downloads\hedging_strategy\analysis_data\pep_gui_HPIN12_20260904.html", "lots", 0.01),
    "oil":       (r"C:\MT5 Pepperstone Runner\rmb3.htm", "balance", None),
    "longvol":   (r"C:\Users\mariu\Downloads\hedging_strategy\analysis_data\pep_gui_longvol_A_20260906.html", "lots", 0.01),
    "sessdrift": (r"C:\MT5 Pepperstone Runner\sd_h4.htm", "balance", None),
    "fibc":      (r"C:\MT5 Pepperstone Runner\fibc_sr_G.htm", "lots", 0.02),
}
PAIN = {"Jan": ("2026-01-26", "2026-02-06"), "Mar": ("2026-03-10", "2026-03-20"), "Apr": ("2026-04-13", "2026-04-17"),
        "May": ("2026-05-05", "2026-05-13"), "Jun-oil": ("2026-06-08", "2026-06-12"), "Aug-3": ("2026-08-03", "2026-08-06"),
        "Aug-19": ("2026-08-18", "2026-08-20"), "Sep-3": ("2026-09-02", "2026-09-04")}


def deals(path):
    h = io.open(path, encoding="utf-16", errors="replace").read()
    i = h.find(">Deals<")
    txt = re.sub(r"<[^>]+>", " ", h[i:])
    txt = re.sub(r"\s+", " ", txt)
    out = []
    for m in ROW.finditer(txt):
        t, sym, side, d, vol, px, comm, swap, prof, bal = m.groups()
        out.append(dict(time=pd.Timestamp(t.replace(".", "-")), sym=sym, side=side, dir=d, lots=float(vol),
                        net=float(comm) + float(swap) + float(prof), bal=float(bal.replace(" ", ""))))
    return pd.DataFrame(out)


def daily(name, path, mode, base):
    d = deals(path)
    d = d[d.dir != "in"]  # P&L lands on out / in-out rows; 'in' rows carry only commission
    if mode == "lots":
        scale = base / d.lots.clip(lower=1e-9)          # bring every deal to base lots
    else:
        bal_before = d.bal - d.net                       # balance at the moment of the deal
        scale = LIVE_BAL / bal_before.clip(lower=100)   # risk-normed: P&L proportional to balance
    d["net_live"] = d.net * scale
    s = d.groupby(d.time.dt.date).net_live.sum()
    s.index = pd.to_datetime(s.index)
    return s, d


def stats(p):
    eq = p.cumsum(); dd = (eq - eq.cummax()).min()
    return dict(net=p.sum(), maxdd=-dd, rf=(p.sum() / -dd) if dd < 0 else np.inf, worst=p.min(),
                days=len(p), pos_days=(p > 0).mean())


def pain_sum(p):
    return sum(p[(p.index >= a) & (p.index <= b)].sum() for a, b in PAIN.values())


def main():
    series, raw = {}, {}
    for name, (path, mode, base) in STREAMS.items():
        try:
            s, d = daily(name, path, mode, base)
        except Exception as e:
            print(f"{name}: SKIP ({e})"); continue
        series[name] = s; raw[name] = d
        st = stats(s)
        print(f"{name:<10} {s.index[0].date()} -> {s.index[-1].date()}  deals-out {len(d):>4}  net@live ${st['net']:>7,.0f}  maxDD(realized) ${st['maxdd']:>6,.0f}  RF {st['rf']:>5.2f}  worst day ${st['worst']:>7,.0f}  pain-sum ${pain_sum(s):>6,.0f}")
    # common window
    lo = max(s.index[0] for s in series.values()); hi = min(s.index[-1] for s in series.values())
    idx = pd.bdate_range(lo, hi)
    P = pd.DataFrame({k: v.reindex(idx).fillna(0.0) for k, v in series.items()})
    print(f"\ncommon window {lo.date()} -> {hi.date()} ({len(idx)} bdays); daily-P&L correlation at live geometry:")
    print(P.corr().round(2).to_string())
    act = (P != 0)
    print("\ncorrelation on days when BOTH streams traded (removes the zero-days inflation):")
    for a, b in itertools.combinations(P.columns, 2):
        m = act[a] & act[b]
        print(f"  {a:<10}{b:<10} n={m.sum():>3}  corr {P.loc[m, a].corr(P.loc[m, b]):+.2f}")

    # compositions the book can actually run at $2,390: flat-lot legs are 0/1, oil risk% scales 0..2x
    print("\nBOOK COMPOSITIONS at $2,390 (realized daily P&L; Dec-01 -> common end). oil weight = multiple of the live 2.5% risk:")
    print(f"{'book':<42}{'net':>9}{'maxDD':>8}{'RF':>7}{'worst day':>11}{'pain-sum':>10}{'+days':>7}")
    rows = []
    legs = [k for k in ("gold", "longvol", "sessdrift") if k in P]
    for r in itertools.product([0, 1], repeat=len(legs)):
        for ow in (0.0, 0.5, 1.0, 1.5, 2.0):
            w = {k: v for k, v in zip(legs, r)}; w["oil"] = ow
            if sum(w.values()) == 0: continue
            p = sum(P[k] * v for k, v in w.items())
            st = stats(p)
            label = "+".join([k for k in legs if w[k]] + ([f"oil×{ow:g}"] if ow else []))
            rows.append((label, st, pain_sum(p)))
    rows.sort(key=lambda x: -x[1]["rf"])
    for label, st, ps in rows[:14]:
        print(f"{label:<42}{st['net']:>9,.0f}{st['maxdd']:>8,.0f}{st['rf']:>7.2f}{st['worst']:>11,.0f}{ps:>10,.0f}{st['pos_days']:>7.0%}")
    cur = [x for x in rows if x[0] == "gold+oil×1"]
    if cur:
        label, st, ps = cur[0]
        print(f"\nLIVE BOOK TODAY = {label}: net {st['net']:,.0f}  maxDD {st['maxdd']:,.0f}  RF {st['rf']:.2f}  worst {st['worst']:,.0f}  pain-sum {ps:,.0f}")
    # vol-parity oil weight: scale oil so its daily vol matches gold's
    if "gold" in P and "oil" in P:
        vg, vo = P.gold[act.gold].std(), P.oil[act.oil].std()
        print(f"\nvol-parity check: gold daily sd ${vg:,.0f} vs oil ${vo:,.0f} at live risk -> oil at vol parity = ×{vg / vo:.2f} of the live 2.5%")
    # the pain-window column per stream
    print("\npain windows, per stream at live geometry ($):")
    print(f"{'window':<8}" + "".join(f"{k:>11}" for k in P.columns))
    for name, (a, b) in PAIN.items():
        seg = P[(P.index >= a) & (P.index <= b)]
        print(f"{name:<8}" + "".join(f"{seg[k].sum():>11,.0f}" for k in P.columns))
    P.to_csv(r"C:\Users\mariu\Downloads\hedging_strategy\factory_front\cell_d_daily_pnl_live.csv")
    print("\nwritten: factory_front/cell_d_daily_pnl_live.csv (daily P&L per stream at live geometry)")


if __name__ == "__main__":
    main()
