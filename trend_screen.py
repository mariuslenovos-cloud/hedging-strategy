#!/usr/bin/env python3
"""
TREND SCREEN  --  EA #3 hunt, step 1 (venue-AGNOSTIC, validate the edge before any execution code).

The factory's kill-test for a multi-market trend/momentum edge -- the OPPOSITE species to the
GridStat/fib C reversion harvesters (low win-rate, big winners, negatively correlated by construction).

Method (standard CTA, daily bars):
  - free daily OHLC from the Yahoo chart API (no key) for ~25 liquid markets across 5 asset classes
  - signal = Donchian(N) breakout entry + ATR chandelier trailing stop (let winners run, no fixed TP)
  - position = VOL-TARGETED to ~15% annual per market  => the 25 markets are EQUAL-RISK => a fair portfolio
  - COST modeled from line one: round-trip transaction cost (bps) charged on turnover.
    NOTE: this is a FUTURES-target screen -> no overnight swap (futures carry is in the price). That is the
    whole point: our past trend attempts died on MT5 CFD SWAP (crypto -2659; CFD spread+swap on multi-day
    holds). On real futures that cost ~vanishes. A cost-STRESS multiplier tests sensitivity.

What it decides (the discipline):
  - per market: Sharpe / maxDD / Recovery / trades, NET of cost
  - ROBUSTNESS (kills regime-fragile single spikes): positive across a Donchian-N x chandelier grid AND in
    BOTH halves of history. A market only counts if it's robust, not if one lucky cell prints.
  - PORTFOLIO: equal-risk combine the survivors -> portfolio Sharpe + avg pairwise correlation (~0 = the prize)
  - the SURVIVING UNIVERSE, grouped by asset class, points at the venue (futures->IB, crypto->exchange, FX->ECN).

Run:  python trend_screen.py            (base grid)
      python trend_screen.py 2.0        (cost-stress x2.0)
"""
import sys, json, time, ssl
import urllib.request
from datetime import datetime
import numpy as np
import pandas as pd

_args = [a.lower() for a in sys.argv[1:]]
CRYPTO = "crypto" in _args                  # python trend_screen.py crypto [cost_mult]
_nums = [a for a in sys.argv[1:] if a.replace('.', '', 1).isdigit()]
COST_MULT = float(_nums[0]) if _nums else 1.0
TARGET_VOL = 0.15           # annual vol target per market (equal-risk)
MAXLEV     = 3.0            # leverage cap on the vol-target
RANGE      = "15y"
PPY = 365 if CRYPTO else 252   # crypto trades 7d/wk -> annualize on 365

# name, yahoo ticker, asset class, round-trip cost in bps (futures-realistic: spread+commission, NO swap)
UNIVERSE = [
    ("EURUSD", "EURUSD=X", "FX",        1.5),
    ("GBPUSD", "GBPUSD=X", "FX",        2.0),
    ("USDJPY", "USDJPY=X", "FX",        1.5),
    ("AUDUSD", "AUDUSD=X", "FX",        2.0),
    ("USDCAD", "USDCAD=X", "FX",        2.0),
    ("USDCHF", "USDCHF=X", "FX",        3.0),
    ("NZDUSD", "NZDUSD=X", "FX",        3.0),
    ("SP500",  "ES=F",     "IndexFut",  1.5),
    ("Nasdaq", "NQ=F",     "IndexFut",  1.5),
    ("Dow",    "YM=F",     "IndexFut",  2.0),
    ("DAX",    "^GDAXI",   "IndexFut",  2.5),
    ("Nikkei", "^N225",    "IndexFut",  3.0),
    ("Gold",   "GC=F",     "Commodity", 3.0),
    ("Silver", "SI=F",     "Commodity", 5.0),
    ("WTI",    "CL=F",     "Commodity", 4.0),
    ("NatGas", "NG=F",     "Commodity", 8.0),
    ("Copper", "HG=F",     "Commodity", 5.0),
    ("Corn",   "ZC=F",     "Commodity", 5.0),
    ("Soybean","ZS=F",     "Commodity", 5.0),
    ("Wheat",  "ZW=F",     "Commodity", 6.0),
    ("UST10y", "ZN=F",     "Rates",     1.5),
    ("UST30y", "ZB=F",     "Rates",     2.0),
    ("UST5y",  "ZF=F",     "Rates",     1.5),
    ("Bitcoin","BTC-USD",  "Crypto",    6.0),
    ("Ether",  "ETH-USD",  "Crypto",    8.0),
]

# Broad crypto universe (exchange SPOT -> cost = round-trip TAKER fee only, NO funding/swap;
# this is the venue-unlock vs MT5 where crypto-trend died on -2659 swap). Tiered by liquidity.
CRYPTO_UNIVERSE = [
    ("BTC",   "BTC-USD",  "Crypto",  8.0),
    ("ETH",   "ETH-USD",  "Crypto",  8.0),
    ("BNB",   "BNB-USD",  "Crypto", 12.0),
    ("XRP",   "XRP-USD",  "Crypto", 12.0),
    ("SOL",   "SOL-USD",  "Crypto", 12.0),
    ("ADA",   "ADA-USD",  "Crypto", 12.0),
    ("DOGE",  "DOGE-USD", "Crypto", 12.0),
    ("AVAX",  "AVAX-USD", "Crypto", 14.0),
    ("LINK",  "LINK-USD", "Crypto", 14.0),
    ("LTC",   "LTC-USD",  "Crypto", 12.0),
    ("DOT",   "DOT-USD",  "Crypto", 14.0),
    ("BCH",   "BCH-USD",  "Crypto", 12.0),
    ("XLM",   "XLM-USD",  "Crypto", 16.0),
    ("ETC",   "ETC-USD",  "Crypto", 16.0),
    ("ATOM",  "ATOM-USD", "Crypto", 16.0),
    ("TRX",   "TRX-USD",  "Crypto", 14.0),
    ("NEAR",  "NEAR-USD", "Crypto", 16.0),
    ("FIL",   "FIL-USD",  "Crypto", 16.0),
]

GRID_N     = [20, 40, 55]
GRID_CHAND = [2.0, 3.0, 4.0]
BASE_N, BASE_CHAND = 40, 3.0
ATR_P = 20

_ctx = ssl.create_default_context(); _ctx.check_hostname = False; _ctx.verify_mode = ssl.CERT_NONE

def fetch_daily(ticker):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range={RANGE}&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20, context=_ctx) as r:
                j = json.load(r)
            res = j["chart"]["result"][0]
            ts = res["timestamp"]; q = res["indicators"]["quote"][0]
            df = pd.DataFrame({"o": q["open"], "h": q["high"], "l": q["low"], "c": q["close"]},
                              index=pd.to_datetime(ts, unit="s"))
            return df.dropna()
        except Exception as e:
            if attempt == 2: print(f"  ! {ticker}: {type(e).__name__} {e}"); return None
            time.sleep(1.5)

def atr(df, p=ATR_P):
    h, l, c = df["h"], df["l"], df["c"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(p).mean()

def positions(df, N, chand, a):
    """Donchian(N) breakout entry + ATR chandelier trail. Returns signed pos in {-1,0,1}."""
    h, l, c = df["h"].values, df["l"].values, df["c"].values
    av = a.values
    dh = df["h"].rolling(N).max().shift(1).values
    dl = df["l"].rolling(N).min().shift(1).values
    n = len(c); pos = np.zeros(n); state = 0; ext = 0.0
    for t in range(n):
        if not (np.isnan(dh[t]) or np.isnan(av[t])):
            if state == 0:
                if c[t] > dh[t]:   state = 1; ext = h[t]
                elif c[t] < dl[t]: state = -1; ext = l[t]
            elif state == 1:
                ext = max(ext, h[t])
                if c[t] < ext - chand * av[t]: state = 0
            else:
                ext = min(ext, l[t])
                if c[t] > ext + chand * av[t]: state = 0
        pos[t] = state
    return pd.Series(pos, index=df.index)

def strat_returns(df, N, chand, cost_bps):
    a = atr(df)
    r = df["c"].pct_change()
    dvol = r.rolling(30).std()
    lev = (TARGET_VOL / np.sqrt(PPY) / dvol).clip(upper=MAXLEV).replace([np.inf, -np.inf], 0).fillna(0)
    sig = positions(df, N, chand, a)
    p = (sig * lev)
    sr = p.shift(1) * r
    turn = p.diff().abs().fillna(p.abs())
    sr = sr - (cost_bps * COST_MULT / 10000.0) * turn
    return sr.dropna(), sig

def stats(sr):
    if len(sr) < 50: return dict(n=len(sr), sharpe=0, ann=0, vol=0, dd=0, rec=0)
    ann = sr.mean() * PPY; vol = sr.std() * np.sqrt(PPY)
    sharpe = ann / vol if vol > 0 else 0
    eq = (1 + sr).cumprod(); dd = (eq / eq.cummax() - 1).min()
    rec = (ann / abs(dd)) if dd < 0 else 0
    return dict(n=len(sr), sharpe=sharpe, ann=ann, vol=vol, dd=dd, rec=rec)

def main():
    print(f"TREND SCREEN  |  {datetime.now():%Y-%m-%d %H:%M}  |  {'CRYPTO' if CRYPTO else 'MULTI-ASSET'}  |  cost x{COST_MULT}  |  target_vol {TARGET_VOL:.0%}  |  PPY {PPY}")
    print("fetching daily data (free Yahoo) ...")
    data = {}
    for name, tk, cls, cost in (CRYPTO_UNIVERSE if CRYPTO else UNIVERSE):
        df = fetch_daily(tk)
        if df is not None and len(df) > 400:
            data[name] = (df, cls, cost)
            print(f"  {name:8} {cls:10} {len(df):>5} bars  {df.index[0].date()}..{df.index[-1].date()}")
        time.sleep(0.4)
    print(f"\nloaded {len(data)}/{len(UNIVERSE)} markets\n")

    rows = []; port_returns = {}
    for name, (df, cls, cost) in data.items():
        # base config
        sr, sig = strat_returns(df, BASE_N, BASE_CHAND, cost)
        s = stats(sr)
        # robustness grid
        cells = []
        for N in GRID_N:
            for ch in GRID_CHAND:
                cs = stats(strat_returns(df, N, ch, cost)[0])
                cells.append(cs["sharpe"])
        cells = np.array(cells)
        pos_cells = int((cells > 0.2).sum())          # how many of 9 grid cells beat Sharpe 0.2
        # half stability
        half = len(sr) // 2
        sh1 = stats(sr.iloc[:half])["sharpe"]; sh2 = stats(sr.iloc[half:])["sharpe"]
        robust = pos_cells >= 6 and sh1 > 0 and sh2 > 0   # most cells + BOTH halves positive
        trades = int((sig.diff().abs() > 0).sum())
        rows.append(dict(name=name, cls=cls, sharpe=s["sharpe"], dd=s["dd"], rec=s["rec"],
                         ann=s["ann"], trades=trades, gridpos=pos_cells, sh1=sh1, sh2=sh2, robust=robust))
        port_returns[name] = sr

    rows.sort(key=lambda x: -x["sharpe"])
    print("PER-MARKET (base N=40 chand=3, NET of cost)   [robust = >=6/9 grid cells + BOTH halves positive]")
    print(f"{'market':9} {'class':10} {'Sharpe':>7} {'maxDD':>7} {'Recov':>6} {'ann%':>6} {'grid':>5} {'h1':>5} {'h2':>5} robust")
    for x in rows:
        flag = "YES" if x["robust"] else ""
        print(f"{x['name']:9} {x['cls']:10} {x['sharpe']:>7.2f} {x['dd']*100:>6.0f}% {x['rec']:>6.2f} "
              f"{x['ann']*100:>5.0f}% {x['gridpos']:>3}/9 {x['sh1']:>5.2f} {x['sh2']:>5.2f}  {flag}")

    # ---- portfolio of ROBUST survivors (equal-risk = equal weight, already vol-targeted) ----
    survivors = [x["name"] for x in rows if x["robust"]]
    print(f"\nROBUST survivors: {len(survivors)} -> {survivors}")
    if len(survivors) >= 2:
        P = pd.DataFrame({n: port_returns[n] for n in survivors}).dropna(how="all")
        port = P.mean(axis=1)   # equal-risk equal-weight
        ps = stats(port.dropna())
        # avg pairwise correlation
        corr = P.corr()
        iu = np.triu_indices_from(corr.values, k=1)
        avg_corr = np.nanmean(corr.values[iu])
        print(f"\nEQUAL-RISK PORTFOLIO of survivors:")
        print(f"  Sharpe {ps['sharpe']:.2f}  |  ann {ps['ann']*100:.0f}%  |  vol {ps['vol']*100:.0f}%  |  maxDD {ps['dd']*100:.0f}%  |  Recovery {ps['rec']:.2f}")
        print(f"  avg pairwise correlation {avg_corr:+.2f}   (near 0 = the diversification prize)")
        ph = port.dropna(); half = len(ph) // 2
        s1 = stats(ph.iloc[:half])['sharpe']; s2 = stats(ph.iloc[half:])['sharpe']
        rec2 = stats(ph.iloc[-2 * PPY:])['sharpe'] if len(ph) > 2 * PPY else float('nan')
        print(f"  ERA DECAY CHECK -> portfolio Sharpe: 1st-half {s1:.2f} | 2nd-half {s2:.2f} | last-2yr {rec2:.2f}   (forward expectation = the recent number, NOT the full-period)")
        # diversification ratio vs the average single-market vol
        print(f"  diversification: portfolio vol {ps['vol']*100:.0f}% vs avg single-market ~{TARGET_VOL*100:.0f}% target")

    # ---- asset-class summary -> the venue signal ----
    print("\nBY ASSET CLASS (avg Sharpe of robust survivors -> points at the venue):")
    by = {}
    for x in rows:
        by.setdefault(x["cls"], []).append(x)
    for cls, xs in sorted(by.items(), key=lambda kv: -np.mean([r["sharpe"] for r in kv[1] if r["robust"]] or [0])):
        rob = [r for r in xs if r["robust"]]
        avg = np.mean([r["sharpe"] for r in rob]) if rob else 0
        print(f"  {cls:10} robust {len(rob)}/{len(xs)}   avg Sharpe {avg:>5.2f}   {[r['name'] for r in rob]}")
    print("\nVENUE READ: where the survivors cluster picks the venue --")
    print("  IndexFut/Commodity/Rates dominate -> Interactive Brokers (real futures: no swap, tight, broad).")
    print("  Crypto strong               -> add a ccxt exchange sleeve (only if it survives its funding cost).")
    print("  FX dominates                -> an ECN (cTrader/FIX) for raw spreads.")
    print("\n(Caveat: Yahoo =F are continuous futures with roll artifacts -> screen finds WHERE trend lives,")
    print(" not exact P&L. Survivors get a clean per-instrument backtest on the chosen venue's real data next.)")

if __name__ == "__main__":
    main()
