#!/usr/bin/env python3
"""
COST-FIRST structural-spread screen. Target: a market-neutral grid/reversion edge
on a CHEAP cointegrated pair that survives REAL 2-leg cost (the oil spread-grid
died on ~13bps; the US-index pairs cost ~2bps). Bar to beat = GridStat gold net.

For each candidate pair (within cheap groups), with REAL per-leg cost from MT5:
  beta = OLS(logA, logB);  spread = logA - (a + b*logB)
  -> ADF (cointegration), half-life (mean-reversion speed),
  -> rolling-z reversion backtest NET of real round-trip 2-leg cost.
Ranks by NET Sharpe. Only structural survivors get proposed for a build.
"""
import itertools, numpy as np, pandas as pd
import MetaTrader5 as mt5

TF      = mt5.TIMEFRAME_H1
NBARS   = 12000
Z_IN, Z_OUT, Z_STOP = 2.0, 0.5, 4.0
ROLL    = 200          # rolling window for beta + z
# candidates: the cheapest structurally-linked groups (from _universe_costs.csv)
GROUPS = {
    "US-index": ["US100Cash", "US500Cash", "US30Cash"],
    "FX-USD":   ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDCAD"],
    "FX-JPY":   ["USDJPY", "EURJPY", "GBPJPY", "AUDJPY"],
    "energy":   ["OILCash", "BRENTCash"],     # the known-but-expensive control
}

def adf_t(x):
    """Engle-Granger style ADF t-stat on residual (no statsmodels)."""
    x = np.asarray(x, float); dx = np.diff(x); xl = x[:-1]
    xl1 = xl - xl.mean()
    b = (xl1 @ dx) / (xl1 @ xl1)
    resid = dx - b * xl1
    se = np.sqrt((resid @ resid) / (len(dx) - 1) / (xl1 @ xl1))
    return b / se if se > 0 else 0.0

def halflife(spread):
    s = np.asarray(spread, float); ds = np.diff(s); sl = s[:-1]
    sl1 = sl - sl.mean()
    b = (sl1 @ ds) / (sl1 @ sl1)
    return (-np.log(2) / b) if b < 0 else np.inf

def get(sym):
    r = mt5.copy_rates_from_pos(sym, TF, 0, NBARS)
    if r is None or len(r) < ROLL * 3:
        return None
    d = pd.DataFrame(r); d["t"] = pd.to_datetime(d["time"], unit="s")
    return d.set_index("t")["close"].astype(float)

def backtest(la, lb, cost_rt):
    """rolling-beta z-reversion on the spread, charge cost_rt (fraction) per leg per round-trip."""
    df = pd.concat([la, lb], axis=1, keys=["a", "b"]).dropna()
    if len(df) < ROLL * 3: return None
    a, b = df["a"].values, df["b"].values
    n = len(a); pos = 0; entry_s = 0.0; pnl = []; trades = 0
    # rolling beta + rolling z of spread
    beta = np.full(n, np.nan); spread = np.full(n, np.nan)
    for i in range(ROLL, n):
        x = b[i-ROLL:i]; y = a[i-ROLL:i]
        bb = np.cov(x, y)[0, 1] / np.var(x) if np.var(x) > 0 else 0
        beta[i] = bb; spread[i] = a[i] - bb * b[i]
    sp = pd.Series(spread)
    mu = sp.rolling(ROLL).mean(); sd = sp.rolling(ROLL).std()
    z = (sp - mu) / sd
    for i in range(ROLL * 2, n):
        zi = z.iloc[i]
        if np.isnan(zi): continue
        if pos == 0:
            if zi >= Z_IN:   pos = -1; entry_s = spread[i]; trades += 1
            elif zi <= -Z_IN: pos = 1; entry_s = spread[i]; trades += 1
        else:
            exit = (pos == 1 and (zi >= -Z_OUT or zi <= -Z_STOP)) or \
                   (pos == -1 and (zi <= Z_OUT or zi >= Z_STOP))
            if exit:
                # spread is in log units; pnl ~ pos*(exit-entry) on leg-A notional, minus 2-leg cost
                gross = pos * (spread[i] - entry_s)
                pnl.append(gross - 2 * cost_rt)   # cross both legs in+out ~ 2*round-trip-leg
                pos = 0
    if not pnl: return None
    pnl = np.array(pnl)
    sharpe = pnl.mean() / pnl.std() * np.sqrt(len(pnl)) if pnl.std() > 0 else 0
    wins = (pnl > 0).mean()
    pf = pnl[pnl > 0].sum() / -pnl[pnl < 0].sum() if (pnl < 0).any() else np.inf
    return dict(trades=len(pnl), win=wins, pf=pf, net=pnl.sum(), sharpe=sharpe,
                avg=pnl.mean())

def main():
    if not mt5.initialize(): raise SystemExit(f"init failed {mt5.last_error()}")
    costs = pd.read_csv("_universe_costs.csv").set_index("sym")["spread_bps"].to_dict()
    price = {}
    for g, syms in GROUPS.items():
        for s in syms:
            if s not in price:
                p = get(s);
                if p is not None: price[s] = p
    print(f"loaded {len(price)} series\n")
    print(f"{'pair':<24}{'cost2leg_bps':>13}{'ADF':>7}{'halflife':>9}{'trades':>7}{'win':>6}{'PF':>6}{'netSharpe':>10}")
    print("-"*82)
    results = []
    for g, syms in GROUPS.items():
        for x, y in itertools.combinations([s for s in syms if s in price], 2):
            la, lb = np.log(price[x]), np.log(price[y])
            df = pd.concat([la, lb], axis=1).dropna()
            if len(df) < ROLL*3: continue
            beta = np.polyfit(df.iloc[:,1], df.iloc[:,0], 1)[0]
            resid = df.iloc[:,0] - beta*df.iloc[:,1]
            adf = adf_t(resid.values); hl = halflife(resid.values)
            c2 = (costs.get(x,99)+costs.get(y,99))            # 2-leg round-trip bps
            bt = backtest(la, lb, c2/1e4)
            if bt is None: continue
            results.append((f"{x}/{y}", c2, adf, hl, bt))
            print(f"{x+'/'+y:<24}{c2:>13.1f}{adf:>7.2f}{hl:>9.0f}{bt['trades']:>7}"
                  f"{bt['win']:>6.0%}{bt['pf']:>6.2f}{bt['sharpe']:>10.2f}")
    print("\nGridStat gold bar to beat: PF 3.92 / 20% DD (net of cost, single-leg).")
    print("Cointegrated (ADF<-2.9) + netSharpe>1 + PF>1.5 = a real candidate to build & validate.")
    mt5.shutdown()

if __name__ == "__main__":
    main()
