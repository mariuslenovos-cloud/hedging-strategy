"""
statarb_stocks.py -- cointegration pairs scan over a broad STOCK universe, pulling
daily closes from the Yahoo chart API (free, fast) since MT5's stock download is slow.
Winners get mapped back to MT5 CFDs for execution.

Finds a PORTFOLIO of cointegrated pairs (sector clusters) -> diversified, market-neutral
stat-arb (the GridStat-equivalent structural edge). Reuses statarb_scan's ADF / half-life
/ z-score backtest.

Run: python statarb_stocks.py
"""
import sys, json, time, urllib.request, itertools
import numpy as np
import pandas as pd
import statarb_scan as S

try: sys.stdout.reconfigure(line_buffering=True)
except Exception: pass

# Sector groups (cointegration lives within a sector). Liquid US/CA names (Yahoo tickers).
GROUPS = {
    "us_banks":   ["JPM", "BAC", "WFC", "C", "USB", "PNC", "TFC"],
    "ca_banks":   ["RY", "TD", "BNS", "BMO", "CM"],
    "i_banks":    ["GS", "MS"],
    "big_tech":   ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA"],
    "oil_majors": ["XOM", "CVX", "COP", "OXY", "PSX", "VLO", "MPC"],
    "gold_miners":["NEM", "GOLD", "AEM", "KGC", "FNV", "WPM"],
    "telecom":    ["VZ", "T", "TMUS"],
    "retail":     ["WMT", "TGT", "COST", "HD", "LOW"],
    "beverage":   ["KO", "PEP"],
    "autos":      ["F", "GM"],
    "pharma":     ["PFE", "MRK", "JNJ", "BMY", "ABBV", "LLY"],
    "payments":   ["V", "MA"],
    "airlines":   ["DAL", "UAL", "AAL", "LUV"],
    "semis":      ["NVDA", "AMD", "INTC", "MU", "TXN", "QCOM"],
}


def yahoo_logclose(ticker, rng="3y"):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range={rng}&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            j = json.load(r)
        res = j["chart"]["result"][0]
        ts = res["timestamp"]; cl = res["indicators"]["quote"][0]["close"]
        s = pd.Series(cl, index=ts).dropna()
        s = s[s > 0]
        return np.log(s)
    except Exception as e:
        return None


def main():
    tickers = sorted({t for g in GROUPS.values() for t in g})
    data = {}
    print(f"Pulling {len(tickers)} tickers from Yahoo (daily, 3y):")
    for t in tickers:
        ls = yahoo_logclose(t)
        if ls is not None and len(ls) > 300:
            data[t] = ls
        else:
            print(f"  {t}: FAIL")
        time.sleep(0.15)
    print(f"  got {len(data)}/{len(tickers)}\n")

    results = []
    for grp, syms in GROUPS.items():
        syms = [s for s in syms if s in data]
        for s1, s2 in itertools.combinations(syms, 2):
            x, y = data[s1].align(data[s2], join="inner")
            if len(x) < 300: continue
            a, b = x.to_numpy(), y.to_numpy()
            A = np.column_stack([np.ones(len(b)), b]); coef, *_ = np.linalg.lstsq(A, a, rcond=None)
            spread = a - (A @ coef)
            adf = S.adf_stat(spread, 1); hl = S.half_life(spread); corr = np.corrcoef(a, b)[0, 1]
            bt = S.backtest_pair(a, b)
            results.append((grp, s1, s2, len(a), corr, adf, hl, bt))

    print(f"{'group':<12}{'A':<7}{'B':<7}{'n':>5}{'corr':>6}{'ADF':>7}{'half-life':>10} | z-score backtest (net of cost)")
    print("-" * 118)
    cands = []
    for grp, s1, s2, n, corr, adf, hl, bt in sorted(results, key=lambda r: r[5]):
        bs = "—"
        if bt: bs = f"n={bt['n']:<3} net={bt['net']:+.3f} avg={bt['avg']:+.4f} win={bt['win']*100:.0f}% PF={bt['pf']:.2f} Sh={bt['sharpe']:+.2f}"
        coint = adf < -2.86; tradeable = 2 < hl < 60
        good = coint and tradeable and bt and bt['pf'] > 1.5 and bt['n'] >= 8
        flag = "  <== CANDIDATE" if good else ("  coint" if coint else "")
        if good: cands.append((grp, s1, s2, adf, hl, bt))
        print(f"{grp:<12}{s1:<7}{s2:<7}{n:>5}{corr:>6.2f}{adf:>7.2f}{hl:>10.1f} | {bs}{flag}")

    print(f"\n{len(cands)} CANDIDATE pairs (cointegrated ADF<-2.86 + half-life 2-60d + PF>1.5 + >=8 trades):")
    for grp, s1, s2, adf, hl, bt in sorted(cands, key=lambda c: -c[5]['sharpe']):
        print(f"   {grp:<12} {s1}-{s2:<8} ADF={adf:.2f} HL={hl:.0f}d  net={bt['net']:+.3f} PF={bt['pf']:.2f} "
              f"Sh={bt['sharpe']:+.2f} trades={bt['n']} win={bt['win']*100:.0f}%")
    print("\nA PORTFOLIO of these (each market-neutral, ~uncorrelated) = the stat-arb book. "
          "Next: map to MT5 CFDs, lower-z/grid-on-spread for more trades, real per-bar cost, CPCV -> EA.")


if __name__ == "__main__":
    main()
