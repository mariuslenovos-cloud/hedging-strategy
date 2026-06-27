"""
statarb_scan.py -- STATISTICAL ARBITRAGE / COINTEGRATION PAIRS SCANNER.

The GridStat-equivalent STRUCTURAL edge (not a forecast): trade the SPREAD between
two cointegrated assets, which mean-reverts BY CONSTRUCTION -> a far more reliable
"recovery" than a single instrument (fixes GridStat's blow-up tail), market-neutral
(uncorrelated to the directional book). The lineage of every quant pairs desk.

Method (Engle-Granger, no statsmodels needed):
  1. hedge ratio beta = OLS(logA on logB); spread = logA - (a + beta*logB)
  2. cointegration = ADF test on the spread (is the residual stationary?)
  3. half-life of mean-reversion from the spread's AR(1) coef (tradeable speed?)
  4. z-score reversion BACKTEST with a real cost estimate: enter |z|>=ZIN, exit |z|<=ZOUT
THE TEST: are there pairs with strong cointegration + tradeable half-life + a
cost-survivable z-score edge? Those become the EA.

Run: python statarb_scan.py
"""
import sys, itertools
import numpy as np
import pandas as pd
import MetaTrader5 as mt5

try: sys.stdout.reconfigure(line_buffering=True)
except Exception: pass

TF      = mt5.TIMEFRAME_H1 if False else mt5.TIMEFRAME_D1   # D1 = classic pairs horizon
NBARS   = 900           # ~3.5y daily
ZIN, ZOUT = 2.0, 0.5    # enter when |z|>=2, exit when |z|<=0.5
COST_BPS = 8.0          # round-trip cost estimate PER LEG in basis points (stocks/CFD ~ a few-10 bps); 2 legs charged

# Curated high-likelihood universe in economic GROUPS (cointegration lives within a group).
GROUPS = {
    "energy":   ["OILCash", "BRENTCash", "NGASCash"],
    "metals":   ["GOLD", "SILVER"],
    "ca_banks": ["BankofMontreal", "BankofNovaScotia", "CanadianImperialBank",
                 "RoyalBankCanada", "TorontoDominionBank"],
    "gold_miners": ["BarrickGold", "AgnicoEagleMines", "Kinross", "FrancoNevada", "WheatonPrecious"],
    "cannabis": ["AuroraCannabis", "Canopy", "Cronos", "TilrayBrands"],
    "ca_rail":  ["CanadianNationalRailway", "CanadianPacificRailway"],
    "ca_energy":["CanadianNaturalResources", "Suncor", "Cenovus", "ImperialOil"],
}


def get_logclose(sym, n):
    if not mt5.symbol_select(sym, True): return None
    r = mt5.copy_rates_from_pos(sym, TF, 0, n)
    if r is None or len(r) < 200: return None
    df = pd.DataFrame(r)[["time", "close"]]
    df = df[df["close"] > 0]
    return pd.Series(np.log(df["close"].to_numpy()), index=df["time"].to_numpy())


def adf_stat(x, lags=1):
    """Augmented Dickey-Fuller t-stat (constant, `lags` aug terms). More negative = more stationary.
    crit ~ -2.86 (5%), -3.43 (1%)."""
    x = np.asarray(x, float); dx = np.diff(x)
    n = len(dx)
    if n < lags + 10: return 0.0
    y = dx[lags:]
    X = [np.ones(n - lags), x[lags:-1] if lags > 0 else x[:-1][lags:]]
    X = [np.ones(n - lags), x[lags:n]]                 # const + level term x_{t-1}
    for k in range(1, lags + 1):
        X.append(dx[lags - k: n - k])
    X = np.column_stack(X)
    # OLS
    beta, res, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    dof = len(y) - X.shape[1]
    if dof <= 0: return 0.0
    s2 = (resid @ resid) / dof
    XtX_inv = np.linalg.pinv(X.T @ X)
    se = np.sqrt(s2 * XtX_inv[1, 1])
    return beta[1] / se if se > 0 else 0.0


def half_life(spread):
    s = np.asarray(spread, float); ds = np.diff(s); lag = s[:-1]
    b = np.polyfit(lag, ds, 1)[0]
    if b >= 0: return 1e9
    return -np.log(2) / np.log(1 + b)


def backtest_pair(a, b):
    """z-score reversion on spread = a - (alpha+beta*b). Returns dict of stats (net of cost)."""
    n = len(a)
    A = np.column_stack([np.ones(n), b])
    coef, *_ = np.linalg.lstsq(A, a, rcond=None)
    alpha, beta = coef
    spread = a - (alpha + beta * b)
    mu, sd = spread.mean(), spread.std()
    if sd <= 0: return None
    z = (spread - mu) / sd
    cost = 2 * COST_BPS / 1e4          # round-trip, both legs (in spread log-return units approx)
    pos = 0; entry_spr = 0.0; trades = []
    for i in range(1, n):
        if pos == 0:
            if z[i] >= ZIN: pos = -1; entry_spr = spread[i]     # short spread
            elif z[i] <= -ZIN: pos = +1; entry_spr = spread[i]  # long spread
        else:
            if (pos == -1 and z[i] <= ZOUT) or (pos == +1 and z[i] >= -ZOUT) or i == n - 1:
                pnl = pos * (spread[i] - entry_spr) - cost      # spread pnl in log units, minus cost
                trades.append(pnl); pos = 0
    if len(trades) < 5: return None
    t = np.array(trades)
    gp = t[t > 0].sum(); gl = -t[t < 0].sum()
    return dict(n=len(t), net=t.sum(), avg=t.mean(), win=(t > 0).mean(),
                pf=(gp / gl if gl > 0 else 9.99), sharpe=(t.mean() / t.std() if t.std() > 0 else 0))


def main():
    if not mt5.initialize(): print("init fail", mt5.last_error()); return
    # pull all unique symbols
    universe = sorted({s for g in GROUPS.values() for s in g})
    data = {}
    for s in universe:
        ls = get_logclose(s, NBARS)
        if ls is not None: data[s] = ls
        print(f"  {s:<26} {'ok '+str(len(ls)) if ls is not None else 'NO DATA'}")
    mt5.shutdown()

    results = []
    for grp, syms in GROUPS.items():
        syms = [s for s in syms if s in data]
        for s1, s2 in itertools.combinations(syms, 2):
            x, y = data[s1].align(data[s2], join="inner")
            if len(x) < 250: continue
            a, b = x.to_numpy(), y.to_numpy()
            # hedge ratio + spread
            A = np.column_stack([np.ones(len(b)), b]); coef, *_ = np.linalg.lstsq(A, a, rcond=None)
            spread = a - (A @ coef)
            adf = adf_stat(spread, lags=1)
            hl = half_life(spread)
            corr = np.corrcoef(a, b)[0, 1]
            bt = backtest_pair(a, b)
            results.append((grp, s1, s2, len(a), corr, adf, hl, bt))

    # rank by ADF (most stationary) among economically-correlated, tradeable-half-life pairs
    print(f"\n{'group':<11}{'pairA':<22}{'pairB':<22}{'n':>5}{'corr':>6}{'ADF':>7}{'half-life':>10} | backtest(net of cost)")
    print("-" * 120)
    def keyf(r): return r[5]  # adf
    for grp, s1, s2, n, corr, adf, hl, bt in sorted(results, key=keyf):
        btstr = "—"
        if bt: btstr = f"n={bt['n']:<3} net={bt['net']:+.3f} avg={bt['avg']:+.4f} win={bt['win']*100:.0f}% PF={bt['pf']:.2f} Sh={bt['sharpe']:+.2f}"
        flag = ""
        coint = adf < -2.86
        tradeable = 2 < hl < 60
        if coint and tradeable and bt and bt['pf'] > 1.3: flag = "  <== CANDIDATE"
        print(f"{grp:<11}{s1:<22}{s2:<22}{n:>5}{corr:>6.2f}{adf:>7.2f}{hl:>10.1f} | {btstr}{flag}")
    print("\nADF < -2.86 = cointegrated (5%); half-life 2-60 bars = tradeable speed; PF>1.3 net = worth an EA.")
    print("(D1 bars; cost = 2 legs x 8bps round-trip. Candidates -> deeper backtest + real per-bar spread + CPCV -> EA.)")


if __name__ == "__main__":
    main()
