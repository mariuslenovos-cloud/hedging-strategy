"""tom_replay.py -- TURN-OF-MONTH index long, replayed on daily index closes with REAL CFD costs (2026-10-11).
Mechanism (Etula et al.): mutual-fund month-end cash needs -> equity index returns concentrate in the last 3 and
first 3 trading days of each month. Pre-registered: hold from the CLOSE of trading day L-3 (L = last trading day of
the month) to the CLOSE of trading day +3 of the next month; flat otherwise. Cost per round trip = 2 x spread_bp +
financing_bp x calendar nights held. Judged per decade and in halves; 'died after 1990' (Maberly & Waggoner) is the
conflict to resolve. Data: analysis_data/index_d1_<sym>.csv (Yahoo daily, pulled 2026-10-11).
usage: python factory_front/tom_replay.py [--spread 0.56] [--fin 1.9] [--pre 3] [--post 3]
"""
import argparse, os, sys, numpy as np, pandas as pd
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ap = argparse.ArgumentParser(); ap.add_argument("--spread", type=float, default=0.56); ap.add_argument("--fin", type=float, default=1.9)
ap.add_argument("--pre", type=int, default=3); ap.add_argument("--post", type=int, default=3); a = ap.parse_args()


def tom_mask(idx, pre, post):
    """True on the days whose close-to-close return the strategy HOLDS: L-(pre-1) .. L .. +post"""
    df = pd.DataFrame(index=idx); df["ym"] = idx.to_period("M")
    pos = df.groupby("ym").cumcount(); cnt = df.groupby("ym")["ym"].transform("size")
    from_end = cnt - 1 - pos            # 0 on the last trading day
    hold = (from_end <= pre - 1) | (pos <= post - 1)
    return hold.values


def run(sym):
    d = pd.read_csv(os.path.join(HERE, "analysis_data", f"index_d1_{sym}.csv"), parse_dates=["date"]).set_index("date")
    r = d.close.pct_change().fillna(0.0)
    hold = tom_mask(d.index, a.pre, a.post)
    # entry = close of the day BEFORE the first held day; cost charged on the first held day (spread) + nights
    held = pd.Series(hold, index=d.index)
    enter = held & ~held.shift(1, fill_value=False); exit_ = held & ~held.shift(-1, fill_value=False)
    nights = pd.Series(0.0, index=d.index)
    nights[held] = (d.index.to_series().diff().dt.days.fillna(1))[held]        # calendar nights carried into each held day
    nights[enter] = 0.0                                                          # entered at the prior close: first held day's nights are real too -> keep; (conservative: count all)
    nights[held] = (d.index.to_series().diff().dt.days.fillna(1))[held]
    cost = (enter.astype(float) * 2 * a.spread + nights * a.fin) * 1e-4
    strat = r.where(held, 0.0) - cost
    rest = r.where(~held, 0.0)
    out = []
    for name, lo, hi in [("1980-89", "1980", "1989"), ("1990-99", "1990", "1999"), ("2000-09", "2000", "2009"), ("2010-19", "2010", "2019"),
                         ("2020-26", "2020", "2026"), ("pre-1990", "1980", "1989"), ("1990-2026", "1990", "2026"), ("2015-2026", "2015", "2026"), ("ALL", "1980", "2026")]:
        s = strat[lo:hi]; o = rest[lo:hi]; bh = r[lo:hi]; h = held[lo:hi]
        if len(s) < 250: continue
        yrs = len(s) / 252
        tom_d = r[lo:hi][h]; rest_d = r[lo:hi][~h]
        t = (tom_d.mean() - rest_d.mean()) / np.sqrt(tom_d.var() / len(tom_d) + rest_d.var() / len(rest_d))
        eq = (1 + s).cumprod(); dd = (eq / eq.cummax() - 1).min()
        eqb = (1 + bh).cumprod(); ddb = (eqb / eqb.cummax() - 1).min()
        out.append(dict(period=name, yrs=round(yrs, 1), tom_ann=100 * (eq.iloc[-1] ** (1 / yrs) - 1), bh_ann=100 * (eqb.iloc[-1] ** (1 / yrs) - 1),
                        rest_ann=100 * ((1 + o).cumprod().iloc[-1] ** (1 / yrs) - 1), tom_bp_d=1e4 * tom_d.mean(), rest_bp_d=1e4 * rest_d.mean(), t=t,
                        sharpe=s.mean() / s.std() * np.sqrt(252) if s.std() > 0 else 0, bh_sharpe=bh.mean() / bh.std() * np.sqrt(252),
                        maxdd=100 * dd, bh_dd=100 * ddb, days_in=100 * h.mean()))
    return pd.DataFrame(out).set_index("period")


pd.set_option("display.width", 200)
print(f"TURN-OF-MONTH LONG: hold close(L-{a.pre}) -> close(+{a.post}); cost {a.spread}bp/side spread + {a.fin}bp/night financing")
for sym in ("gspc", "ndx", "gdaxi", "ixic"):
    p = os.path.join(HERE, "analysis_data", f"index_d1_{sym}.csv")
    if not os.path.exists(p): continue
    print(f"\n== {sym.upper()} ==")
    print(run(sym).round(2).to_string())
