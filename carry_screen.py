#!/usr/bin/env python3
"""
CARRY / SWAP-HARVESTING SCREEN  --  EA hunt (cost-first). Earn from HOLDING, not from price moving.

Two structurally-different carry edges, screened on REAL data:

(A) CRYPTO FUNDING-RATE CARRY (the market-NEUTRAL prize): on perpetual futures, longs pay shorts (or vice
    versa) a funding rate every 8h. Hold DELTA-NEUTRAL = long spot + short perp -> price exposure cancels,
    you bank the funding. ~zero correlation to everything = a true diversifier. Real funding history via ccxt.
    Net yield = avg funding (annualized) - setup cost (2 legs) - the regime risk that funding flips negative.

(B) FX CARRY (the classic, but directional): hold the positive-swap side of a pair, earn the broker's swap
    (already net of their shave). Real swap from MT5. NOT market-neutral -> you're exposed to the FX move
    (carry's fat left tail). Screen the yield AND carry/vol (does the yield pay for the risk).

Run:  python carry_screen.py
"""
import warnings; warnings.filterwarnings("ignore")
import numpy as np
from datetime import datetime

SETUP_COST_ANNUAL = 1.2   # crypto: ~2-leg entry+exit (~30bps) amortized over a ~6mo hold => ~1.2%/yr drag

def crypto_funding_carry():
    import ccxt
    print("="*78)
    print("(A) CRYPTO FUNDING-RATE CARRY  (delta-neutral: long spot + short perp -> market-NEUTRAL)")
    print("="*78)
    ex = ccxt.binanceusdm({"enableRateLimit": True})
    try:
        ex.load_markets()
    except Exception as e:
        print("  binanceusdm unreachable:", e); return
    perps = ["BTC/USDT:USDT","ETH/USDT:USDT","SOL/USDT:USDT","BNB/USDT:USDT","XRP/USDT:USDT",
             "DOGE/USDT:USDT","ADA/USDT:USDT","AVAX/USDT:USDT","LINK/USDT:USDT","LTC/USDT:USDT",
             "NEAR/USDT:USDT","SUI/USDT:USDT"]
    rows = []
    for s in perps:
        try:
            hist = ex.fetch_funding_rate_history(s, limit=1000)   # ~1000 x 8h ~ 333 days
            rates = np.array([h["fundingRate"] for h in hist if h.get("fundingRate") is not None], dtype=float)
            if len(rates) < 100: continue
            ann = rates.mean() * 3 * 365 * 100          # 3 fundings/day
            pos_pct = (rates > 0).mean() * 100
            recent = rates[-90:].mean() * 3 * 365 * 100  # last ~30 days
            net = ann - SETUP_COST_ANNUAL
            vol_of_funding = rates.std() * 3 * np.sqrt(365) * 100   # annualized vol of the funding yield
            rows.append(dict(s=s.split("/")[0], n=len(rates), ann=ann, recent=recent, pos=pos_pct, net=net))
        except Exception as e:
            print(f"  ! {s}: {type(e).__name__}")
    rows.sort(key=lambda x: -x["net"])
    print(f"{'coin':6} {'fundings':>9} {'avg ann%':>9} {'last30d%':>9} {'%posit':>7} {'NET ann%':>9}")
    for x in rows:
        print(f"{x['s']:6} {x['n']:>9} {x['ann']:>9.1f} {x['recent']:>9.1f} {x['pos']:>6.0f}% {x['net']:>9.1f}")
    if rows:
        eq = [x["net"] for x in rows if x["net"] > 0]
        basket = np.mean([x["net"] for x in rows])
        print(f"\n  equal-weight basket NET yield ~ {basket:.1f}% annual (market-neutral, delta-hedged)")
        print(f"  -> {len(eq)}/{len(rows)} coins net-positive after cost")
    print("  HONEST: market-NEUTRAL (the prize) + a REAL structural yield (longs pay shorts in a bull).")
    print("  RISKS: funding is regime-dependent (bull=high+, bear=low/negative -> compare avg vs last30d);")
    print("         short-perp leg needs margin buffer (liquidation risk); basis can wobble; exchange/custody risk.")
    print("  Yield looks modest now (calm regime) -> the test is the THROUGH-CYCLE average + a live demo.\n")

def fx_carry():
    import MetaTrader5 as mt5
    print("="*78)
    print("(B) FX CARRY  (hold the positive-swap side; DIRECTIONAL = exposed to the FX move)")
    print("="*78)
    if not mt5.initialize():
        print("  MT5 not connected."); return
    pairs = ["AUDJPY","NZDJPY","USDJPY","CADJPY","USDCHF","EURCHF","USDMXN","USDZAR","USDTRY",
             "EURUSD","GBPUSD","AUDUSD","GBPJPY","EURJPY"]
    rows = []
    for p in pairs:
        i = mt5.symbol_info(p); tk = mt5.symbol_info_tick(p)
        if not i or not tk or tk.bid <= 0: continue
        side = "LONG" if i.swap_long >= i.swap_short else "SHORT"
        sw = max(i.swap_long, i.swap_short)
        if sw <= 0: continue                         # no positive-carry side -> skip
        carry_ann = sw * i.point / tk.bid * 365 * 100
        rates = mt5.copy_rates_from_pos(p, mt5.TIMEFRAME_D1, 0, 365)
        vol_ann = 0.0
        if rates is not None and len(rates) > 60:
            c = np.array([r["close"] for r in rates], dtype=float)
            vol_ann = np.std(np.diff(c)/c[:-1]) * np.sqrt(252) * 100
        ctv = carry_ann / vol_ann if vol_ann > 0 else 0
        rows.append(dict(p=p, side=side, carry=carry_ann, vol=vol_ann, ctv=ctv))
    mt5.shutdown()
    rows.sort(key=lambda x: -x["ctv"])
    print(f"{'pair':8} {'side':5} {'carry ann%':>11} {'FX vol%':>8} {'carry/vol':>10}")
    for x in rows:
        print(f"{x['p']:8} {x['side']:5} {x['carry']:>11.1f} {x['vol']:>8.0f} {x['ctv']:>10.2f}")
    print("\n  HONEST: carry/vol is a crude carry-Sharpe -- the YIELD vs the directional RISK you take to hold it.")
    print("  The fat tail: high-yielders (TRY/MXN/ZAR) pay big swap but depreciate -> the steamroller.")
    print("  Retail swaps are SHAVED by the broker (these are already net of that). Diversified G10 carry")
    print("  basket (long the +carry/vol majors) is the survivable version; EM-FX carry is the tail risk.")

def main():
    print(f"CARRY SCREEN  |  {datetime.now():%Y-%m-%d %H:%M}\n")
    crypto_funding_carry()
    fx_carry()

if __name__ == "__main__":
    main()
