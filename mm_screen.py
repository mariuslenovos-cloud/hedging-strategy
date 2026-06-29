#!/usr/bin/env python3
"""
MARKET-MAKING FEASIBILITY MAP  --  EA #4 hunt, step 1 (cost-first; "is it even plausible" BEFORE any build).

Market-making = post resting LIMIT orders, EARN the spread (+ any maker rebate), get filled by takers.
P&L per round-trip ~= spread_captured  -  2*maker_fee  -  adverse_selection.
  - spread_captured  = best-ask - best-bid (you make both sides)
  - maker_fee        = what the venue charges (or pays, if negative = rebate) per maker fill
  - adverse_selection= price drifts against your inventory between fills (proxy: short-horizon volatility)

This is a MICROSTRUCTURE edge -> it CANNOT be validated on daily data. This step only maps WHERE the spread is
wide enough vs the fee+noise to be plausible. Survivors -> a maker-fill SIMULATION on tick/L2 data -> a live demo
(fills are the only truth). The crypto exchange is the realistic retail MM venue (you can post maker orders;
fees are public; some venues pay maker REBATES) -- unlike MT5's B-book where you can't be the maker.

Pulls LIVE data via ccxt (public endpoints, no key): order book (real spread) + 1-min OHLCV (short-horizon vol)
+ the exchange's real maker fee.

Run:  python mm_screen.py            (binance)
      python mm_screen.py kraken
"""
import sys, time
import numpy as np

EXCH = sys.argv[1] if len(sys.argv) > 1 else "binance"
PAIRS = [
    "BTC/USDT","ETH/USDT","BNB/USDT","SOL/USDT","XRP/USDT","DOGE/USDT","ADA/USDT",
    "AVAX/USDT","LINK/USDT","LTC/USDT","TRX/USDT","NEAR/USDT","ATOM/USDT","FIL/USDT",
    "ALGO/USDT","GALA/USDT","SAND/USDT","INJ/USDT","SUI/USDT","APT/USDT",
]

def main():
    import ccxt
    ex = getattr(ccxt, EXCH)({"enableRateLimit": True})
    try:
        mk = ex.load_markets()
    except Exception as e:
        print(f"{EXCH}: load_markets failed ({e}). Try: python mm_screen.py kraken"); return
    print(f"MARKET-MAKING FEASIBILITY MAP  |  {EXCH}  |  live order book + 1m vol + real maker fee\n")

    rows = []
    for p in PAIRS:
        if p not in mk:
            # some venues use different quote (USD vs USDT)
            alt = p.replace("/USDT", "/USD")
            p2 = alt if alt in mk else None
            if p2 is None:
                continue
            p = p2
        try:
            ob = ex.fetch_order_book(p, limit=5)
            bid, ask = ob["bids"][0][0], ob["asks"][0][0]
            mid = 0.5 * (bid + ask)
            spread_bps = (ask - bid) / mid * 1e4
            oh = ex.fetch_ohlcv(p, "1m", limit=500)
            closes = np.array([c[4] for c in oh], dtype=float)
            r = np.diff(closes) / closes[:-1]
            vol1m_bps = np.std(r) * 1e4                       # per-minute move = adverse-selection scale
            maker_bps = mk[p].get("maker", 0.001) * 1e4       # venue maker fee (bps); negative = rebate
            net_rt = spread_bps - 2 * maker_bps               # net capture per round-trip at this fee
            be_fee = spread_bps / 2.0                          # maker fee you'd need to break even on capture alone
            rows.append(dict(p=p, spread=spread_bps, vol1m=vol1m_bps, maker=maker_bps,
                             net=net_rt, be=be_fee, ratio=(net_rt / vol1m_bps if vol1m_bps > 0 else 0)))
        except Exception as e:
            print(f"  ! {p}: {type(e).__name__}")
        time.sleep(0.15)

    if not rows:
        print("no data pulled (venue geo-blocked? try kraken/bybit)"); return
    maker0 = rows[0]["maker"]
    rows.sort(key=lambda x: -x["spread"])
    print(f"venue maker fee = {maker0:.1f} bps/side  ->  round-trip fee to beat = {2*maker0:.1f} bps\n")
    print(f"{'pair':12} {'spread':>8} {'1m vol':>8} {'net@fee':>9} {'cap/adv':>8}  {'breakeven fee':>13}")
    print(f"{'':12} {'(bps)':>8} {'(bps)':>8} {'(bps)':>9} {'ratio':>8}  {'needed (bps)':>13}")
    for x in rows:
        flag = "  <- net>0" if x["net"] > 0 else ""
        print(f"{x['p']:12} {x['spread']:>8.1f} {x['vol1m']:>8.1f} {x['net']:>9.1f} {x['ratio']:>8.2f}  {x['be']:>11.1f}{flag}")

    pos = [x for x in rows if x["net"] > 0]
    print(f"\nnet-positive at the venue's standard maker fee: {len(pos)}/{len(rows)}")
    print("READ:")
    print("  - On a standard fee-charging SPOT venue the maker fee usually DWARFS the spread on liquid pairs")
    print("    (spread ~1-3 bps vs round-trip fee ~20 bps) -> retail spot MM is FEE-WALLED there.")
    print("  - MM needs EITHER a maker-REBATE venue (negative maker fee) OR a pair whose spread is wide")
    print("    enough to clear the fee AND exceed the 1-min adverse move (cap/adv ratio > ~1).")
    print("  - 'breakeven fee needed' tells you the maker fee a venue must offer for each pair to even start.")
    print("\nNEXT IF any pair looks plausible: maker-fill SIM on L2/tick data (model fill prob + adverse selection),")
    print("then a live demo on a rebate venue. This map is feasibility only -- not P&L.")

if __name__ == "__main__":
    main()
