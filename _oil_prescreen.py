import MetaTrader5 as mt5
for _ in range(3):
    if mt5.initialize(): break
LOT=0.02; HARVEST=80.0   # fib C base lot + basket-trail arm ($80 float)
print(f"{'sym':>8}{'price':>10}{'spread_pt':>10}{'spread_$/leg':>13}{'spread_bps':>11}"
      f"{'ATRm5_bps':>10}{'spr/ATR':>8}{'$/M5bar':>9}{'bars_80':>9}{'spr%harvest':>12}")
res={}
for sym in ["GOLD","OILCash"]:
    if mt5.symbol_info(sym) is None: mt5.symbol_select(sym,True)
    info=mt5.symbol_info(sym); tk=mt5.symbol_info_tick(sym)
    price=tk.bid; spread_price=tk.ask-tk.bid; spread_pt=spread_price/info.point
    vpp=info.trade_tick_value/info.trade_tick_size              # $ per 1.0 price move per 1 lot
    spread_usd=spread_price*vpp*LOT                             # round-trip spread cost per 0.02-lot leg
    spread_bps=spread_price/price*1e4
    r=mt5.copy_rates_from_pos(sym,mt5.TIMEFRAME_M5,0,300)
    trs=[max(r[i]['high']-r[i]['low'],abs(r[i]['high']-r[i-1]['close']),abs(r[i]['low']-r[i-1]['close'])) for i in range(1,len(r))]
    atr=sum(trs[-14:])/14; atr_bps=atr/price*1e4; atr_usd=atr*vpp*LOT
    spr_atr=spread_price/atr
    bars=HARVEST/atr_usd                                         # ~bars for one 0.02 leg to float +$80
    spr_pct=spread_usd/HARVEST*100                               # one leg's spread as % of an $80 harvest
    res[sym]=dict(spread_bps=spread_bps,spr_atr=spr_atr,spr_pct=spr_pct,spread_usd=spread_usd,bars=bars,atr_usd=atr_usd)
    print(f"{sym:>8}{price:>10.2f}{spread_pt:>10.1f}{spread_usd:>13.3f}{spread_bps:>11.2f}"
          f"{atr_bps:>10.1f}{spr_atr:>8.2f}{atr_usd:>9.3f}{bars:>9.0f}{spr_pct:>11.1f}%")
g,o=res["GOLD"],res["OILCash"]
print(f"\n--- OIL vs GOLD cost headwind for fib C ---")
print(f"spread (bps):           oil {o['spread_bps']:.2f}  vs gold {g['spread_bps']:.2f}   = {o['spread_bps']/g['spread_bps']:.1f}x wider")
print(f"spread / ATR(M5):       oil {o['spr_atr']:.2f}  vs gold {g['spr_atr']:.2f}   = {o['spr_atr']/g['spr_atr']:.1f}x of a bar")
print(f"spread % of $80 harvest:oil {o['spr_pct']:.1f}% vs gold {g['spr_pct']:.1f}%  = {o['spr_pct']/g['spr_pct']:.1f}x the tax/leg")
print(f"(a fib C basket is multi-leg + has a TINY 50-pt quick-harvest too -> multiply the per-leg tax)")
mt5.shutdown()
