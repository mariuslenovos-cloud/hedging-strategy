#!/usr/bin/env python3
"""Cost-first foundation: enumerate the MT5 universe by REAL trading cost
(round-trip spread in bps + overnight swap). We only ever consider substrates
cheap enough that a grid/mean-reversion edge could survive on them."""
import MetaTrader5 as mt5
import pandas as pd

if not mt5.initialize():
    raise SystemExit(f"init failed {mt5.last_error()}")
ti = mt5.terminal_info()
print("MT5 ok | terminal:", ti.name, "| #symbols:", mt5.symbols_total())

rows = []
for s in mt5.symbols_get():
    si = mt5.symbol_info(s.name)
    if si is None:
        continue
    mid = (si.ask + si.bid) / 2 if (si.ask > 0 and si.bid > 0) else si.last
    if not mid or mid <= 0:
        continue
    spr_bps = (si.ask - si.bid) / mid * 1e4
    grp = s.path.split("\\")[0] if s.path else ""
    rows.append((s.name, grp, round(spr_bps, 2), si.swap_long, si.swap_short, si.swap_mode))

df = pd.DataFrame(rows, columns=["sym", "group", "spread_bps", "swap_long", "swap_short", "swap_mode"])
df = df.dropna(subset=["spread_bps"]).sort_values("spread_bps")
df.to_csv("_universe_costs.csv", index=False)
print("symbols with live quotes:", len(df))
print("\n--- groups ---")
print(df["group"].value_counts().head(25).to_string())
print("\n--- 30 CHEAPEST (round-trip spread, bps) ---")
print(df.head(30).to_string(index=False))
mt5.shutdown()
