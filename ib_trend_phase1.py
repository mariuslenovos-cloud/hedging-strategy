#!/usr/bin/env python3
"""
IB TREND-ECONOMICS PHASE 1 (2026-07-13) -- the Session-20 platform-leap question:
does REAL FUTURES ECONOMICS lift the validated ~0.6-Sharpe 20-market trend
portfolio into deployable territory?

Method (same signal engine as edge_trend_portfolio.py -- Donchian 50/25,
equal-risk, daily):
  1. Data = Yahoo continuous futures, 10y daily. CAVEAT (logged): continuous
     contracts have roll gaps that appear as phantom daily returns (~4/yr per
     market. The RV sleeve died on roll artifacts; for DIRECTIONAL long-horizon
     trend they are second-order, but absolutes carry that noise -> judge the
     DELTA vs the same engine on the same data at CFD costs, plus robustness.)
  2. Costs, three scenarios on identical signals/data:
       a) FUTURES: round-trip = 2 x commission ($2.50/side incl fees, IB-ish
          conservative) + 1 x bid-ask spread (1 tick), as fraction of contract
          notional; PLUS roll drag = 4 rolls/yr x roll cost charged per held day.
          NO financing (futures carry is in the basis, not a broker fee).
       b) CFD-SPREAD-ONLY: the OLD baseline's optimistic cost (broker spread bps).
       c) CFD-FULL: spread + swap bps/day x days held (the honest retail cost
          that killed past trend attempts; swap ~1-9bps/day per XM data).
  3. Report per-scenario: portfolio Sharpe / ann return / maxDD + robustness
     (Donchian N in {20,40,55} x first-half vs second-half) + avg pairwise corr.

Win condition (pre-committed): FUTURES portfolio Sharpe >= 0.8 stable across the
robustness grid AND clearly above CFD-FULL. Anything less = trend stays "modest,
banked" and the IB build waits for a stronger tenant.
"""
import json, math, time, urllib.request
import numpy as np, pandas as pd

# ticker: (name, multiplier, tick_size, spread_ticks, cfd_spread_bps, cfd_swap_bps_day)
# cfd numbers from _universe_costs.csv / project notes where measured; else class-typical.
FUT = {
    "ES=F":  ("SP500",     50,    0.25,  1, 0.94, 2.5),
    "NQ=F":  ("NAS100",    20,    0.25,  1, 0.86, 2.5),
    "YM=F":  ("DOW",        5,    1.0,   1, 1.06, 2.5),
    "RTY=F": ("RUSSELL",   50,    0.10,  1, 1.5,  2.5),
    "GC=F":  ("GOLD",     100,    0.10,  1, 1.29, 1.5),
    "SI=F":  ("SILVER",  5000,    0.005, 1, 10.6, 1.5),
    "HG=F":  ("COPPER",  25000,   0.0005,1, 2.0,  1.5),
    "CL=F":  ("WTI",     1000,    0.01,  1, 6.61, 2.0),
    "BZ=F":  ("BRENT",   1000,    0.01,  2, 6.33, 2.0),
    "NG=F":  ("NATGAS",  10000,   0.001, 1, 65.9, 3.0),
    "ZC=F":  ("CORN",      50,    0.25,  1, 4.0,  2.0),
    "ZS=F":  ("SOYBEAN",   50,    0.25,  1, 4.0,  2.0),
    "ZW=F":  ("WHEAT",     50,    0.25,  2, 5.0,  2.0),
    "ZN=F":  ("NOTE10Y",  1000,   0.015625, 1, 1.0, 1.0),
    "ZB=F":  ("BOND30Y",  1000,   0.03125,  1, 1.5, 1.0),
    "6E=F":  ("EUR",     125000,  0.00005,  1, 1.75, 1.0),
    "6J=F":  ("JPY",     12500000,0.0000005,1, 1.55, 1.0),
    "6B=F":  ("GBP",     62500,   0.0001,   1, 1.8,  1.0),
    "6A=F":  ("AUD",     100000,  0.0001,   1, 2.0,  1.0),
    "BTC=F": ("BITCOIN",    5,    5.0,      2, 7.7,  4.15),
}
COMMISSION = 2.50      # $/contract/side, conservative IB all-in
ROLLS_PER_YEAR = 4

def yahoo_daily(ticker, rng="10y"):
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?range={rng}&interval=1d")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        j = json.loads(r.read().decode())
    res = j["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    df = pd.DataFrame({"t": pd.to_datetime(res["timestamp"], unit="s"),
                       "o": q["open"], "h": q["high"], "l": q["low"], "c": q["close"]})
    return df.dropna().reset_index(drop=True)

def trend_returns(df, N, NX, cost_per_change_frac, hold_drag_frac_per_day):
    h, l, c = df["h"].values, df["l"].values, df["c"].values
    n = len(c)
    hh = pd.Series(h).rolling(N).max().shift(1).values
    ll = pd.Series(l).rolling(N).min().shift(1).values
    xh = pd.Series(h).rolling(NX).max().shift(1).values
    xl = pd.Series(l).rolling(NX).min().shift(1).values
    atr = pd.Series(np.maximum(h - l, np.abs(pd.Series(c).diff()))).rolling(20).mean().values
    pos = np.zeros(n); p = 0
    for i in range(N, n):
        if p == 0:
            if c[i] > hh[i]: p = 1
            elif c[i] < ll[i]: p = -1
        elif p == 1 and c[i] < xl[i]: p = 0
        elif p == -1 and c[i] > xh[i]: p = 0
        pos[i] = p
    pct = np.zeros(n); pct[1:] = (c[1:] - c[:-1]) / c[:-1]
    rs = np.where(atr > 0, atr / c, np.nan)
    riskscale = np.nanmedian(rs) / rs
    riskscale = np.clip(np.nan_to_num(riskscale, nan=1.0), 0.2, 5.0)
    chg = np.abs(np.diff(np.concatenate([[0], pos])))
    ret = np.zeros(n)
    for i in range(1, n):
        ret[i] = (pos[i-1] * pct[i] * riskscale[i-1]
                  - chg[i] * cost_per_change_frac
                  - abs(pos[i-1]) * hold_drag_frac_per_day)
    return pd.Series(ret, index=df["t"]), int(chg.sum()), float(np.abs(pos).mean())

def portfolio_stats(R):
    port = R.mean(axis=1)                     # equal weight, already risk-scaled
    ann = port.mean() * 252
    vol = port.std() * math.sqrt(252)
    sh = ann / vol if vol > 0 else 0.0
    eq = port.cumsum(); maxdd = float(-(eq - eq.cummax()).min())
    corr = R.corr().values
    iu = np.triu_indices_from(corr, 1)
    return sh, ann, maxdd, float(np.nanmean(corr[iu]))

def run(N=50, NX=25, verbose=True):
    data = {}
    for tk in FUT:
        try:
            df = yahoo_daily(tk)
            if len(df) > 500: data[tk] = df
        except Exception as e:
            if verbose: print(f"  {tk}: fetch failed ({e})")
        time.sleep(0.4)
    if verbose: print(f"loaded {len(data)}/{len(FUT)} futures")
    scen = {"FUTURES": {}, "CFD-SPREAD": {}, "CFD-FULL": {}}
    meta = {}
    for tk, df in data.items():
        name, mult, tick, sprt, cfd_bps, swap_bps = FUT[tk]
        px = float(np.nanmedian(df["c"].values[-250:]))
        notional = px * mult
        fut_rt = (2 * COMMISSION + sprt * tick * mult) / notional          # round trip, frac
        roll_drag = fut_rt * ROLLS_PER_YEAR / 252.0                        # per held day
        cfd_rt = cfd_bps / 1e4
        swap_day = swap_bps / 1e4
        r_f, ntr, expo = trend_returns(df, N, NX, fut_rt, roll_drag)
        r_s, _, _     = trend_returns(df, N, NX, cfd_rt, 0.0)
        r_c, _, _     = trend_returns(df, N, NX, cfd_rt, swap_day)
        scen["FUTURES"][name] = r_f; scen["CFD-SPREAD"][name] = r_s; scen["CFD-FULL"][name] = r_c
        meta[name] = (fut_rt * 1e4, cfd_bps, swap_bps, ntr, expo)
    if verbose:
        print(f"\n{'market':10s} {'futRT bps':>9s} {'cfd bps':>8s} {'swap/d':>7s} {'trades':>7s} {'expo':>5s}")
        for nm, (f, cb, sb, ntr, ex) in sorted(meta.items()):
            print(f"{nm:10s} {f:9.2f} {cb:8.2f} {sb:7.2f} {ntr:7d} {ex:5.2f}")
    out = {}
    for sc, series in scen.items():
        R = pd.DataFrame(series).fillna(0.0)
        out[sc] = portfolio_stats(R)
    return out, scen

def main():
    print("=== PHASE 1: Donchian 50/25, 10y daily, 3 cost scenarios ===")
    out, scen = run(50, 25)
    print(f"\n{'scenario':12s} {'Sharpe':>7s} {'ann%':>7s} {'maxDD%':>7s} {'avgCorr':>8s}")
    for sc, (sh, ann, dd, corr) in out.items():
        print(f"{sc:12s} {sh:7.2f} {ann*100:7.1f} {dd*100:7.1f} {corr:8.3f}")
    print("\n=== ROBUSTNESS: Donchian N grid (futures scenario) ===")
    for N, NX in [(20, 10), (40, 20), (55, 28)]:
        o, _ = run(N, NX, verbose=False)
        sh, ann, dd, _ = o["FUTURES"]
        print(f"N={N:2d}/{NX:2d}: Sharpe {sh:5.2f}  ann {ann*100:5.1f}%  maxDD {dd*100:5.1f}%")
    print("\n=== FIRST vs SECOND HALF (futures, N=50/25) ===")
    _, scen50 = run(50, 25, verbose=False)
    R = pd.DataFrame(scen50["FUTURES"]).fillna(0.0)
    half = len(R) // 2
    for label, Rh in [("first half", R.iloc[:half]), ("second half", R.iloc[half:])]:
        sh, ann, dd, corr = portfolio_stats(Rh)
        print(f"{label:12s} Sharpe {sh:5.2f}  ann {ann*100:5.1f}%  maxDD {dd*100:5.1f}%")

if __name__ == "__main__":
    main()
