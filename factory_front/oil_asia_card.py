#!/usr/bin/env python3
"""
oil_asia_card.py -- the oil Asia LOOK, carded (2026-09-06).

Stage-1 harness read: SpotCrude H1 Asia (00-08 SAST) t_m20 -4.49 / t_m5 -3.22 (n 2,268):
the prior 20 hours' oil move reverses during Asian hours. The standing claim was
"already monetised by SOLID's base-and-bounce organs". That is a hypothesis until the
number exists: the correlation of this signature's hypothetical daily P&L with SOLID's
own daily ledger. Rule (pre-committed by the outside read): ~0.9 = same bet, closed;
~0.4 = a leg.

Replay on analysis_data/spotcrude_m5_export.csv (Pepperstone bid, server time -> SAST = -1h):
  A  hourly: at each H1 close inside Asia, position = -sign(close - close[-20h]), hold 1h;
     cost charged on every position CHANGE (spread 0.024/bbl).
  B  daily:  at 00:00 SAST position = -sign(prior 20h move), hold to 09:00 SAST, cost once.
Both in $/bbl; the $ column is at 0.25 lots (25 bbl) = SOLID's typical live basket.
SOLID daily P&L = factory_front/cell_d_allocation.deals() on the rmb3.htm control run,
normalised to the $2,390 balance (risk-normed engine).
"""
import sys, io, os
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
from cell_d_allocation import daily as cd_daily

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
COST = 0.024        # $/bbl round turn (spread 24 pts + ~0 commission on SpotCrude)
LOTS = 0.25         # SOLID's live basket size, for the $ column (100 bbl/lot)
ASIA = range(0, 9)  # SAST 00:00-08:59 (harness SESSIONS)


def h1(path):
    d = pd.read_csv(path)
    d["ts"] = pd.to_datetime(d["time"]) - pd.Timedelta(hours=1)   # server -> SAST
    h = d.set_index("ts")["close"].resample("1h").last().dropna()
    return h


def t_stat(x):
    x = np.asarray(x, float); n = len(x)
    return x.mean() / (x.std(ddof=1) / np.sqrt(n)) if n > 2 and x.std(ddof=1) > 0 else 0.0


def variant_a(h):
    c = h.values; ts = h.index
    pos = np.zeros(len(c)); 
    for i in range(20, len(c) - 1):
        if ts[i].hour in ASIA:
            pos[i] = -np.sign(c[i] - c[i - 20])
    fwd = np.append(np.diff(c), 0.0)
    gross = pos * fwd
    chg = np.abs(np.diff(np.append(0.0, pos)))            # 0->1, 1->0, 1->-1 (=2 = close+open)
    cost = chg * COST / 1.0 * 0.5 * 2                     # each unit change = one side... approximate: |dpos| * half-RT
    cost = np.abs(np.diff(np.append(0.0, pos))) * COST / 2 * 1.0
    net = gross - cost
    df = pd.DataFrame({"gross": gross, "net": net, "pos": pos}, index=ts)
    return df


def variant_b(h):
    c = h; rows = []
    days = sorted(set(h.index.date))
    for dday in days:
        t0 = pd.Timestamp(dday)                      # 00:00 SAST
        t1 = t0 + pd.Timedelta(hours=9)              # 09:00 SAST
        tm = t0 - pd.Timedelta(hours=20)
        if t0 not in c.index or t1 not in c.index or tm not in c.index: continue
        sig = -np.sign(c[t0] - c[tm])
        if sig == 0: continue
        g = sig * (c[t1] - c[t0])
        rows.append((t0, sig, g, g - COST))
    return pd.DataFrame(rows, columns=["day", "pos", "gross", "net"]).set_index("day")


def report(name, dly, gross_col="gross", net_col="net"):
    n = len(dly); g = dly[gross_col]; nt = dly[net_col]
    half = n // 2
    print(f"{name}: days {n}  gross/day ${g.mean()*100*LOTS:+.2f}  net/day ${nt.mean()*100*LOTS:+.2f}  "
          f"t(net) {t_stat(nt):+.2f}  win {(nt>0).mean():.0%}  h1 t {t_stat(nt.iloc[:half]):+.2f}  h2 t {t_stat(nt.iloc[half:]):+.2f}  "
          f"net total ${nt.sum()*100*LOTS:+,.0f} at {LOTS} lots")


def main():
    h = h1(r"C:\Users\mariu\Downloads\hedging_strategy\analysis_data\spotcrude_m5_export.csv")
    print(f"H1 bars {len(h)}  {h.index[0]} -> {h.index[-1]} (SAST)")
    A = variant_a(h)
    A_d = A.groupby(A.index.date)[["gross", "net"]].sum(); A_d.index = pd.to_datetime(A_d.index)
    A_d = A_d[(A_d.gross != 0)]
    B = variant_b(h)
    print("\nSIGNATURE REPLAY (hypothetical, bid closes, cost = spread):")
    report("A hourly-rebalanced Asia MR ", A_d)
    report("B one trade/day 00->09 SAST ", B)
    # the harness stat, reproduced: corr(past-20h move, next-1h move) inside Asia
    c = h.values; ts = h.index
    past = np.array([c[i] - c[i-20] for i in range(20, len(c)-1)]); fwd = np.array([c[i+1]-c[i] for i in range(20, len(c)-1)])
    m = np.array([ts[i].hour in ASIA for i in range(20, len(c)-1)])
    r = np.corrcoef(past[m], fwd[m])[0, 1]; n = m.sum()
    print(f"\nharness check: corr(past20h, next1h) in Asia = {r:+.3f}, n={n}, t={r*np.sqrt(n)/np.sqrt(1-r*r):+.2f}")
    # SOLID daily ledger
    solid, _ = cd_daily("oil", r"C:\MT5 Pepperstone Runner\rmb3.htm", "balance", None)
    for name, sig in (("A", A_d.net * 100 * LOTS), ("B", B.net * 100 * LOTS)):
        idx = pd.bdate_range(max(sig.index[0], solid.index[0]), min(sig.index[-1], solid.index[-1]))
        s = sig.reindex(idx).fillna(0.0); o = solid.reindex(idx).fillna(0.0)
        both = (s != 0) & (o != 0)
        # rolling 5-day sums remove the day-boundary mismatch between an intraday signal and a multi-day basket ledger
        s5 = s.rolling(5).sum().dropna(); o5 = o.rolling(5).sum().dropna()
        print(f"\nvariant {name} vs SOLID daily P&L, overlap {idx[0].date()} -> {idx[-1].date()} ({len(idx)} bdays):")
        print(f"  daily corr (all days)        {s.corr(o):+.3f}")
        print(f"  daily corr (both traded, n={both.sum()}) {s[both].corr(o[both]):+.3f}")
        print(f"  5-day-sum corr               {s5.corr(o5):+.3f}")
        print(f"  20-day-sum corr              {s.rolling(20).sum().corr(o.rolling(20).sum()):+.3f}")
        print(f"  signature net on SOLID's 10 worst days: ${s[o.nsmallest(10).index].sum():+,.0f}  (SOLID ${o.nsmallest(10).sum():+,.0f})")
        print(f"  signature net on SOLID's 10 best days:  ${s[o.nlargest(10).index].sum():+,.0f}  (SOLID ${o.nlargest(10).sum():+,.0f})")
        print(f"  signature net over the overlap ${s.sum():+,.0f} vs SOLID ${o.sum():+,.0f}")
    B.to_csv(r"C:\Users\mariu\Downloads\hedging_strategy\factory_front\oil_asia_card_daily.csv")


if __name__ == "__main__":
    main()
