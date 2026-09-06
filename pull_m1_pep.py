"""Pull 12+ months of M1 bars (bid OHLC + per-bar spread) from the LIVE Pepperstone terminal,
build a MID close (bid close + spread/2) and save to analysis_data/<sym>_m1_export.csv.
Proof lines: login, bars, span, spread stats -- the Gate 0 run is only valid if these print."""
import sys, time, io
sys.path.insert(0, r"C:\Users\mariu\Downloads\hedging_strategy")
import MetaTrader5 as mt5, pandas as pd
from datetime import datetime, timedelta
import framework_check as fc
path, login = fc.TERMINALS["LIVE"] if hasattr(fc, "TERMINALS") else (r"C:\Program Files\Pepperstone MetaTrader 5\terminal64.exe", 51511633)
ai = fc.connect(path, login)
assert ai and ai.login == 51511633, f"login guard failed: {ai}"
print("LOGIN OK", ai.login, ai.server, flush=True)
end = datetime.now() + timedelta(days=1)
start = datetime(2025, 8, 20)
PAIRS = [tuple(a.split("=", 1)) for a in sys.argv[1:] if "=" in a] or [("XAUUSD", "xauusd_m1_export.csv"), ("SpotCrude", "spotcrude_m1_export.csv")]
for sym, out in PAIRS:   # usage: python pull_m1_pep.py XAGUSD=xagusd_m1_export.csv  (default = gold + oil)
    mt5.symbol_select(sym, True)
    info = mt5.symbol_info(sym); pt = info.point
    frames = []
    t0 = start
    while t0 < end:
        t1 = min(t0 + timedelta(days=14), end)
        rates = None
        for attempt in range(6):
            rates = mt5.copy_rates_range(sym, mt5.TIMEFRAME_M1, t0, t1)
            if rates is not None and len(rates) > 0: break
            time.sleep(2 + attempt)
        if rates is None or len(rates) == 0:
            print(f"  {sym} {t0:%Y-%m-%d}->{t1:%Y-%m-%d}: EMPTY after retries {mt5.last_error()}", flush=True)
        else:
            frames.append(pd.DataFrame(rates))
        t0 = t1
    d = pd.concat(frames).drop_duplicates("time").sort_values("time")
    d["time"] = pd.to_datetime(d["time"], unit="s")
    d["mid"] = d["close"] + d["spread"] * pt / 2.0
    d = d[["time", "open", "high", "low", "close", "spread", "mid", "tick_volume"]]
    d.to_csv(f"analysis_data/{out}", index=False)
    print(f"{sym}: {len(d):,} M1 bars  {d['time'].iloc[0]} -> {d['time'].iloc[-1]}  spread median={d['spread'].median()} p90={d['spread'].quantile(.9)} point={pt}  -> analysis_data/{out}", flush=True)
mt5.shutdown()
