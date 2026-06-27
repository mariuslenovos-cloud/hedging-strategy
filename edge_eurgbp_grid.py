#!/usr/bin/env python3
"""
The FAIR test of the thesis: GRID mechanism (fade + scale-in, NO stop, harvest on
reversion) on EURGBP -- the hardest-reverting cheap single leg (VR 0.67). The naive
z+stop reversion failed (bad payoff); the grid AVOIDS the stop -- it averages in and
waits for the reversion that EURGBP reliably delivers. Charges REAL spread per unit.
Reports net, PF, win, and MAX FLOATING DRAWDOWN (the grid's true risk) -- net of cost.

Caveat: bar-based (M5), so it's a SCREEN not a verdict -- but a no-stop scale-in is far
less path-sensitive than a stop/floor grid, so it's a fair go/no-go before any build.
"""
import numpy as np, pandas as pd
import MetaTrader5 as mt5

TF, NBARS = mt5.TIMEFRAME_M5, 60000
ROLL = 200
LADDER = [1.0, 2.0, 3.0, 4.0, 5.0]   # z levels to add a unit (fade further)
Z_FLOOR = 8.0                         # cointegration/regime-break floor (close at a loss; rare)
PT_GRID = [5, 10, 20, 40, 80]         # profit-target sweep (bps of leg notional) = GridStat's real harvest

def run_pt(sym, cost_frac, c, mu, sd, pt_frac):
    n = len(c); units = []; baskets = []; maxfloatdd = 0.0; floordd = 0.0
    for i in range(ROLL, n):
        if sd[i] <= 0 or np.isnan(mu[i]): continue
        z = (c[i] - mu[i]) / sd[i]
        want = sum(1 for lv in LADDER if abs(z) >= lv)
        if want > len(units):
            d = -1 if z > 0 else 1
            units.append((d, c[i]))
        if units:
            # basket float per unit-notional, minus cost already owed per open unit
            fl = sum(d * (c[i] - ep) / ep for d, ep in units) - cost_frac * len(units)
            maxfloatdd = min(maxfloatdd, fl)
            if fl >= pt_frac:                       # PT harvest (GridStat's real exit)
                baskets.append(fl - cost_frac * len(units)); units = []   # exit cost too
            elif abs(z) >= Z_FLOOR:                 # regime-break floor: cut at a loss
                baskets.append(fl - cost_frac * len(units)); units = []
    if not baskets: return None
    a = np.array(baskets)
    return dict(baskets=len(a), win=(a > 0).mean(),
                pf=(a[a > 0].sum() / -a[a < 0].sum()) if (a < 0).any() else np.inf,
                net_bps=a.sum() * 1e4, avg_bps=a.mean() * 1e4, maxFloatDD_bps=maxfloatdd * 1e4)

def run(sym, cost_frac):
    r = mt5.copy_rates_from_pos(sym, TF, 0, NBARS)
    if r is None or len(r) < 5000: return None
    c = pd.DataFrame(r)["close"].astype(float).values
    p = pd.Series(c)
    mu = p.rolling(ROLL).mean().values; sd = p.rolling(ROLL).std().values
    best = None
    for pt in PT_GRID:
        res = run_pt(sym, cost_frac, c, mu, sd, pt / 1e4)
        if res and (best is None or res["net_bps"] > best["net_bps"]):
            res["pt_bps"] = pt; best = res
    return best

def main():
    if not mt5.initialize(): raise SystemExit(f"init {mt5.last_error()}")
    costs = pd.read_csv("_universe_costs.csv").set_index("sym")["spread_bps"].to_dict()
    cand = ["GOLD", "EURGBP", "EURUSD", "USDJPY", "GBPJPY", "AUDJPY"]
    print(f"{'sym':<9}{'cost':>6}{'bestPT':>7}{'baskets':>9}{'win':>6}{'PF':>7}{'net_bps':>9}{'maxFloatDD':>12}")
    print("-" * 67)
    gold_pf = None
    for s in cand:
        res = run(s, costs.get(s, 5) / 1e4)
        if res is None: print(f"{s:<9} (no data)"); continue
        if s == "GOLD": gold_pf = res["pf"]
        flag = "  <== beats gold-grid" if (gold_pf and s != "GOLD" and res["pf"] > gold_pf and res["net_bps"] > 0) else \
               ("  <== net positive" if res["net_bps"] > 0 and res["pf"] > 1.2 else "")
        print(f"{s:<9}{costs.get(s,0):>6.2f}{res['pt_bps']:>7}{res['baskets']:>9}{res['win']:>6.0%}"
              f"{res['pf']:>7.2f}{res['net_bps']:>9.0f}{res['maxFloatDD_bps']:>12.0f}{flag}")
    print("\nPT-harvest grid (GridStat's real mechanism) net of REAL spread.")
    print("SANITY: GOLD must come out positive (it's the proven PF~3.9 substrate) or the sim is wrong.")
    print("EURGBP with PF >= gold AND lower maxFloatDD = the GridStat-beater thesis confirmed -> build & every-tick.")
    mt5.shutdown()

if __name__ == "__main__":
    main()
