#!/usr/bin/env python3
"""
stage1_harness.py — Stage 1 of the factory front half.

One pass over raw M1 bars per instrument. For every cell in
    instrument x horizon x session
it asks the only Stage 1 question: DOES A RETURN SIGNATURE EXIST HERE,
AND IS ONE BAR'S MOVE LARGE ENOUGH TO PAY THE COST?

No signals, no entries, no exits. That is Stage 2. Cells that fail here
never get a Stage 2, which is where the throughput comes from.

Per cell:
  vr5, z_vr      Lo-MacKinlay variance ratio at q=5, heteroskedasticity-robust z
                 z < -2 mean reversion / z > +2 momentum
  ac1, t_ac      lag-1 autocorrelation of returns and its t-stat
  mom5, t_m5     corr(past-5-bar return, next-bar return) -- momentum signature
  mom20, t_m20   same with past-20-bar return
  sigma          one-bar return sd in price units
  sig_per_cost   sigma / round-turn cost C. <1 means a typical bar does not
                 cover cost; scalp targets at 3C are then >3 sigma away.
  tail1pct       share of total |return| carried by the top 1% of bars.
                 High = the cell's P&L is event-day driven (your pain window).
  verdict        MR / MOM / none, gated on |z_vr| or |t_ac| > 3.0 (about 50 cells
                 are tested at once; 3.0 keeps expected false positives below 0.2.
                 Loosen with --zcrit 2.5 to see 'look' candidates)
  pred_per_cost  |ac1| * sigma / C = the PREDICTABLE part of one bar per unit cost
                 (the card rule is gross >= 3C; Stage 1 demands >= 1C or the stat is unbuyable)
  feasible       verdict != none AND sig_per_cost >= 1.0 AND pred_per_cost >= 1.0
  explored       marked from EXPLORED below -- the map, not a judgement

Usage
-----
  python stage1_harness.py \
      --bars XAUUSD=gold_m1.csv XTIUSD=oil_m1.csv XAGUSD=silver_m1.csv \
      --cost XAUUSD=0.30 XTIUSD=0.05 XAGUSD=0.03 \
      --tz-shift 0 --out stage1_results.csv

Input CSVs: M1 bars with a timestamp column and a close (or mid) column.
Export from MT5: Tools > History Center, or any tick-to-M1 dump. Column
names are sniffed; override with --time-col / --price-col.
--tz-shift: hours to add to the file's timestamps to reach SAST (UTC+2).
Sessions are defined in SAST.

Run it on MID if you have it. Bid-only data manufactures mean reversion
at M1/M5 through bid-ask bounce.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------- #
# The search map's explored region. Keep this in sync with SEARCH_MAP.md.
# (instrument, horizon) -> note. A cell here is printed with [X] in the table.
# --------------------------------------------------------------------------- #
EXPLORED = {
    # GridStat trades M5 bars; its CONTEXT is D1 (EMA50 trend filter, ATR(D1) barriers/grid) and M5 ATR(20/100) regime -- no M15 anywhere.
    ("XAUUSD", "M1"):  "Gate 0 RUN + killed 09-05 (M1 mid VR z -2.7 real but $0.03/bar vs $0.25 cost); scalp-mode PT25/35 killed; outsized-bar fade t=0.83",
    ("XAUUSD", "M5"):  "GridStat GOLD HPIN12 (live) + fib C hedge (demo); Counter-Thrust, ADX<20 fade, VWAP-z, day-rank-as-gate all killed; DAYRANK sizing = candidate",
    ("XAUUSD", "H1"):  "TrendBreak (H1 Donchian) killed 08-17; GoldTrend H1 killed 06-20; SessionDrift 01-04 SAST sleeve (demo, time-of-day)",
    ("XAUUSD", "D1"):  "D1 momentum SCREENED 09-06: TSMOM/Donchian real at zero swap (Sharpe ~0.8) but swap-eaten (-6.6%/yr longs) + 47-52% DD at the 0.01-lot floor -> shelf ($10k+)",
    ("SpotCrude", "M5"): "GridStat OIL SOLID4 (live); regime-sells, crash-guard, freeze all locked; 7 cut-class levers killed",
    ("SpotCrude", "H1"): "GoldTrend-class H1 breakout on oil: TrendBreak generalisation never run; SessionDrift screen: oil time-of-day 2:1 edge/cost = killed 08-23",
    ("XAGUSD", "M5"):  "GridStat SILVER locked 06-12 (PF 2.60/8.7%DD, conc 4) -> live 07-14, PAUSED 07-20 (0.01-lot over-risk at $3k; venue = XM); event-day corr vs gold NOT measured",
}

HORIZONS = {"M1": 1, "M5": 5, "M15": 15, "H1": 60, "H4": 240, "D1": 1440}

# SAST hour buckets. Sessions only apply at horizons < H4.
SESSIONS = {
    "all":    range(0, 24),
    "asia":   range(0, 9),     # 00:00-08:59
    "london": range(9, 15),    # 09:00-14:59
    "ny":     range(15, 23),   # 15:00-22:59
}

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
    raise SystemExit(f"no {kind} column found in {list(cols)}; pass --{kind}-col")


def load_m1(path: Path, time_col, price_col, tz_shift):
    df = pd.read_csv(path, sep=None, engine="python")
    tcol = time_col or sniff_col(df.columns, TIME_CANDIDATES, "time")
    pcol = price_col or sniff_col(df.columns, PRICE_CANDIDATES, "price")
    ts = pd.to_datetime(df[tcol], errors="coerce")
    px = pd.to_numeric(df[pcol], errors="coerce")
    d = pd.DataFrame({"ts": ts, "px": px}).dropna()
    d = d[d.px > 0].sort_values("ts").drop_duplicates("ts")
    if tz_shift:
        d["ts"] = d["ts"] + pd.Timedelta(hours=tz_shift)
    d = d.set_index("ts")["px"]
    return d, pcol


def resample(m1: pd.Series, minutes: int) -> pd.Series:
    if minutes == 1:
        return m1
    if minutes >= 1440:
        return m1.resample("1D").last().dropna()
    return m1.resample(f"{minutes}min", label="left", closed="left").last().dropna()


# --------------------------------------------------------------------------- #
# statistics
# --------------------------------------------------------------------------- #
def gap_filtered_returns(px: pd.Series, minutes: int):
    """log returns with cross-gap returns dropped; returns (r, bar_start_ts)."""
    lp = np.log(px.to_numpy())
    r = np.diff(lp)
    dt = np.diff(px.index.to_numpy()).astype("timedelta64[s]").astype(float)
    keep = dt <= 5 * 60 * minutes if minutes < 1440 else dt <= 4 * 86400
    return r[keep], px.index.to_numpy()[:-1][keep]


def variance_ratio(r, q=5):
    n = len(r)
    if n < 10 * q:
        return np.nan, np.nan
    mu = r.mean()
    var1 = np.sum((r - mu) ** 2) / (n - 1)
    if var1 <= 0:
        return np.nan, np.nan
    cs = np.cumsum(np.insert(r, 0, 0.0))
    rq = cs[q:] - cs[:-q]
    m = q * (n - q + 1) * (1 - q / n)
    vr = np.sum((rq - q * mu) ** 2) / m / var1
    dev2 = (r - mu) ** 2
    denom = np.sum(dev2) ** 2
    theta = sum(((2 * (q - j) / q) ** 2) * (np.sum(dev2[j:] * dev2[:-j]) / denom)
                for j in range(1, q))
    return vr, (vr - 1) / np.sqrt(theta) if theta > 0 else np.nan


def corr_t(a, b):
    if len(a) < 30 or a.std() == 0 or b.std() == 0:
        return np.nan, np.nan
    c = float(np.corrcoef(a, b)[0, 1])
    return c, c * np.sqrt(len(a))


def past_k_signature(r, k):
    """corr(sum of past k returns, next return)."""
    if len(r) < k + 30:
        return np.nan, np.nan
    cs = np.cumsum(np.insert(r, 0, 0.0))
    past = cs[k:-1] - cs[:-k - 1]
    nxt = r[k:]
    return corr_t(past, nxt)


def tail_share(r, pct=0.01):
    a = np.abs(r)
    if len(a) < 100:
        return np.nan
    k = max(1, int(len(a) * pct))
    return float(np.sort(a)[-k:].sum() / a.sum())


def cell_stats(r, px_level, cost, zcrit, mom_pairs=None):
    vr, zvr = variance_ratio(r, 5)
    ac, tac = corr_t(r[:-1], r[1:])
    if mom_pairs is None:
        m5, t5 = past_k_signature(r, 5)
        m20, t20 = past_k_signature(r, 20)
    else:
        # 2026-09-06 fix: the past-k move must be the past k CLOCK bars of the full series with only the
        # TARGET bar session-masked. Masking before lagging concatenated Asia bars across days and
        # manufactured the SpotCrude 'Asia t_m20 -4.49' look (replay: t -0.5, net negative at cost).
        (p5, n5), (p20, n20) = mom_pairs
        m5, t5 = corr_t(p5, n5)
        m20, t20 = corr_t(p20, n20)
    sigma = r.std() * px_level
    spc = sigma / cost if cost > 0 else np.nan
    # predictable component of one bar = |lag-1 autocorr| * sigma. The card rule is gross >= 3*C; Stage 1
    # requires at least 1*C or the statistic is real but unbuyable (the 2026-09-05 gold Gate-0 kill: z -2.7, $0.03 vs $0.25).
    ppc = abs(ac) * sigma / cost if (cost > 0 and np.isfinite(ac)) else np.nan

    score = np.nanmax([abs(zvr), abs(tac)]) if np.isfinite(zvr) or np.isfinite(tac) else np.nan
    sign = np.sign(np.nansum([zvr, tac]))
    if not np.isfinite(score) or score < zcrit:
        verdict = "none"
    else:
        verdict = "MR" if sign < 0 else "MOM"
    # 2026-09-06: the past-5/20 momentum columns join the gate (the outside read's ask). A cell whose
    # lag-1 gate is silent but whose past-k signature clears zcrit gets verdict MOM-k / MR-k (sign of corr),
    # and its own predictability term |corr_k| * sigma / C (the regression of next bar on the past-k move).
    if verdict == "none":
        for k, (ck, tk) in ((20, (m20, t20)), (5, (m5, t5))):
            if np.isfinite(tk) and abs(tk) >= zcrit:
                verdict = ("MOM-%d" if ck > 0 else "MR-%d") % k
                score = abs(tk)
                ppc = abs(ck) * sigma / cost if cost > 0 else np.nan
                break
    feasible = (verdict != "none") and np.isfinite(spc) and spc >= 1.0 and np.isfinite(ppc) and ppc >= 1.0
    return dict(n=len(r), vr5=vr, z_vr=zvr, ac1=ac, t_ac=tac, mom5=m5, t_m5=t5,
                mom20=m20, t_m20=t20, sigma=sigma, sig_per_cost=spc, pred_per_cost=ppc,
                tail1pct=tail_share(r), verdict=verdict, feasible=feasible, score=score)


# --------------------------------------------------------------------------- #
# driver
# --------------------------------------------------------------------------- #
def parse_kv(items, cast=str):
    out = {}
    for it in items or []:
        k, v = it.split("=", 1)
        out[k.strip()] = cast(v.strip())
    return out


def run(args):
    bars = parse_kv(args.bars, Path)
    costs = parse_kv(args.cost, float)
    rows = []
    for sym, path in bars.items():
        if not path.exists():
            print(f"skip {sym}: {path} not found", file=sys.stderr)
            continue
        m1, pcol = load_m1(path, args.time_col, args.price_col, args.tz_shift)
        cost = costs.get(sym, 0.0)
        if cost <= 0:
            print(f"warn {sym}: no --cost given; sig_per_cost will be NaN", file=sys.stderr)
        if pcol.lower() != "mid":
            print(f"warn {sym}: price column '{pcol}' is not mid -- M1/M5 MR may be bid-ask bounce",
                  file=sys.stderr)
        level = float(m1.iloc[-1])
        print(f"{sym}: {len(m1):,} M1 bars  {m1.index[0]} -> {m1.index[-1]}", file=sys.stderr)

        for hname, mins in HORIZONS.items():
            px = resample(m1, mins)
            r_all, ts_all = gap_filtered_returns(px, mins)
            hours = pd.DatetimeIndex(ts_all).hour
            sessions = SESSIONS if mins < 240 else {"all": SESSIONS["all"]}
            cs_all = np.cumsum(np.insert(r_all, 0, 0.0))
            for sname, hrs in sessions.items():
                m = np.isin(hours, list(hrs))
                r = r_all[m]
                min_n = 60 if mins >= 240 else args.min_bars
                if len(r) < min_n:
                    continue
                pairs = []
                for k in (5, 20):
                    if len(r_all) > k + 30:
                        past = cs_all[k:-1] - cs_all[:-k - 1]
                        nxt = r_all[k:]
                        mk = m[k:]
                        pairs.append((past[mk], nxt[mk]))
                    else:
                        pairs.append((np.array([]), np.array([])))
                st = cell_stats(r, level, cost, args.zcrit, mom_pairs=tuple(pairs))
                st.update(instrument=sym, horizon=hname, session=sname,
                          explored=EXPLORED.get((sym, hname), ""))
                rows.append(st)

    if not rows:
        raise SystemExit("no cells computed")
    df = pd.DataFrame(rows)
    cols = ["instrument", "horizon", "session", "n", "vr5", "z_vr", "ac1", "t_ac",
            "mom5", "t_m5", "mom20", "t_m20", "sigma", "sig_per_cost", "pred_per_cost", "tail1pct",
            "verdict", "feasible", "score", "explored"]
    df = df[cols]
    df.to_csv(args.out, index=False)
    return df


def print_report(df: pd.DataFrame, zcrit: float):
    hz_order = {h: i for i, h in enumerate(HORIZONS)}
    ss_order = {s: i for i, s in enumerate(SESSIONS)}
    d = df.copy()
    d["_h"] = d.horizon.map(hz_order)
    d["_s"] = d.session.map(ss_order)
    d = d.sort_values(["instrument", "_h", "_s"])

    print()
    print(f"STAGE 1 — signature map   (verdict gate |stat| > {zcrit})")
    print(f"{'inst':<8}{'hz':<5}{'sess':<8}{'n':>8}{'VR5':>7}{'z_vr':>7}{'ac1':>8}{'t_ac':>7}"
          f"{'m5':>7}{'t_m5':>7}{'m20':>7}{'t_m20':>7}{'sig/C':>7}{'tail1%':>8}  verdict  feas  X")
    cur = None
    for _, r in d.iterrows():
        if r.instrument != cur:
            cur = r.instrument
            print("-" * 130)
        x = "X" if r.explored else " "
        print(f"{r.instrument:<8}{r.horizon:<5}{r.session:<8}{r.n:>8,}{r.vr5:>7.3f}{r.z_vr:>7.2f}"
              f"{r.ac1:>8.4f}{r.t_ac:>7.2f}{r.mom5:>7.3f}{r.t_m5:>7.2f}{r.mom20:>7.3f}{r.t_m20:>7.2f}"
              f"{r.sig_per_cost:>7.2f}{r.pred_per_cost:>7.2f}{r.tail1pct:>8.1%}  {r.verdict:<7}  {'yes' if r.feasible else '-':<4}  {x}")

    print()
    lead = df[df.feasible & (df.explored == "")].sort_values("score", ascending=False)
    print("UNEXPLORED + FEASIBLE cells, by signature strength — these get a hypothesis card:")
    if lead.empty:
        print("  none. Either the feed has no unexplored signature at these costs, or you need more history.")
    else:
        for _, r in lead.head(12).iterrows():
            print(f"  {r.instrument:<8}{r.horizon:<5}{r.session:<8} {r.verdict:<4} score {r.score:5.2f}"
                  f"  sig/C {r.sig_per_cost:4.2f}  tail1% {r.tail1pct:5.1%}")

    dead = df[(df.verdict != "none") & ~df.feasible]
    if not dead.empty:
        print()
        print("Signature present but UNBUYABLE: sig/C < 1 or the predictable part of a bar (|ac1|*sigma) < 1x C (card rule needs 3x):")
        for _, r in dead.iterrows():
            print(f"  {r.instrument:<8}{r.horizon:<5}{r.session:<8} {r.verdict:<4} sig/C {r.sig_per_cost:4.2f}  pred/C {r.pred_per_cost:4.2f}")
    print()
    print("X = explored cell per SEARCH_MAP.md. Bonferroni note: with this many cells, "
          "treat |stat| in 3.0-3.5 as 'look', >3.5 as 'card'. "
          "A cell that passes in one session and not the adjacent one is a look, not a card.")


def main():
    ap = argparse.ArgumentParser(description="Stage 1 signature harness")
    ap.add_argument("--bars", nargs="+", required=True, help="SYMBOL=path_to_m1.csv ...")
    ap.add_argument("--cost", nargs="+", help="SYMBOL=round_turn_cost_in_price_units ...")
    ap.add_argument("--time-col")
    ap.add_argument("--price-col")
    ap.add_argument("--tz-shift", type=float, default=0.0, help="hours to add to reach SAST")
    ap.add_argument("--min-bars", type=int, default=300,
                    help="min returns per intraday cell; H4/D1 use 60")
    ap.add_argument("--zcrit", type=float, default=3.0,
                    help="verdict gate on |z| or |t|; ~50 cells => 3.0 keeps expected false positives < 0.2")
    ap.add_argument("--out", default="stage1_results.csv")
    args = ap.parse_args()
    df = run(args)
    print_report(df, args.zcrit)
    print(f"written: {args.out}")


if __name__ == "__main__":
    main()
