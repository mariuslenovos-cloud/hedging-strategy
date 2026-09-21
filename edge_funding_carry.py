#!/usr/bin/env python3
"""
SECOND-ENGINE CANDIDATE SCREEN: CONDITIONAL crypto funding-rate carry (2026-07-30).

Thesis: the ALWAYS-ON cash-and-carry (long spot + short perp, collect funding) decayed
(~4% APY by mid-2025, negative Sharpe 2025 per research). But funding is EPISODIC — spikes
>15-40% annualized during leverage frenzies (BIS/CEPR: structural limits-to-arbitrage).
A CONDITIONAL harvester that only deploys during rich-funding episodes may retain real yield.

This screens with REAL funding-rate history (Binance public API, Bybit fallback — no account
needed): BTC + ETH perps, full available history (2020->now).
Strategy: enter delta-neutral when trailing 7d funding annualizes > ENTER%; exit when < EXIT%.
Costs: 4 legs (spot+perp in, spot+perp out) at taker ~= 40bp round trip TOTAL (conservative
retail: 7.5bp spot taker x2 + 5bp perp taker x2 + slippage buffer).
PRE-COMMITTED GATE: net annualized yield ON DEPLOYED CAPITAL >= 8% during 2024-2026 (the
decayed era, not the glory years) with worst episode > -3%. Below that it can't beat just
sizing up the proven book, and dies honestly.
Run: python edge_funding_carry.py    (writes analysis_data/funding_carry_screen.csv)
"""
import io, json, math, os, time, urllib.request
from datetime import datetime, timezone

SYMS = ["BTCUSDT", "ETHUSDT"]
RT_COST_BP = 40.0          # full round-trip, all 4 legs, conservative taker
ENTER_APRS = [10.0, 15.0, 25.0]   # trailing-7d annualized funding to ENTER (%)
EXIT_APR   = 5.0                  # drop below -> exit
TRAIL_D    = 7

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

def fetch_binance(sym):
    out, start = [], 1577836800000  # 2020-01-01
    while True:
        j = get(f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={sym}&startTime={start}&limit=1000")
        if not isinstance(j, list) or not j: break
        out += [(int(x["fundingTime"]), float(x["fundingRate"])) for x in j]
        if len(j) < 1000: break
        start = out[-1][0] + 1
        time.sleep(0.3)
    return out

def fetch_bybit(sym):
    out, end = [], int(time.time()*1000)
    for _ in range(80):
        j = get(f"https://api.bybit.com/v5/market/funding/history?category=linear&symbol={sym}&limit=200&endTime={end}")
        rows = j.get("result", {}).get("list", [])
        if not rows: break
        batch = sorted((int(x["fundingRateTimestamp"]), float(x["fundingRate"])) for x in rows)
        out = batch + out
        end = batch[0][0] - 1
        time.sleep(0.3)
    return out

def screen(sym):
    try:
        data = fetch_binance(sym); src = "binance"
    except Exception as e:
        print(f"  binance failed ({e}); trying bybit"); data = fetch_bybit(sym); src = "bybit"
    if len(data) < 1000:
        print(f"  {sym}: insufficient data ({len(data)})"); return []
    data.sort()
    t0, t1 = datetime.fromtimestamp(data[0][0]/1e3), datetime.fromtimestamp(data[-1][0]/1e3)
    per_day = 3  # 8h funding
    print(f"  {sym} [{src}]: {len(data)} payments {t0:%Y-%m}->{t1:%Y-%m}")
    rows = []
    for enter_apr in ENTER_APRS:
        n_tr = TRAIL_D * per_day
        in_pos = False
        episodes = []; cur = 0.0; cur_start = None
        yearly = {}
        for i in range(n_tr, len(data)):
            ts, fr = data[i]
            trail_apr = sum(f for _, f in data[i-n_tr:i]) / TRAIL_D * 365 * 100
            yr = datetime.fromtimestamp(ts/1e3).year
            if not in_pos and trail_apr > enter_apr:
                in_pos = True; cur = -RT_COST_BP/1e4; cur_start = ts   # pay full RT cost up front
            elif in_pos:
                cur += fr                                             # collect (or pay) each funding
                yearly.setdefault(yr, 0.0); yearly[yr] += fr
                if trail_apr < EXIT_APR:
                    episodes.append((cur_start, ts, cur)); in_pos = False; cur = 0.0
        if in_pos: episodes.append((cur_start, data[-1][0], cur))
        if not episodes:
            rows.append([sym, enter_apr, 0, 0, 0, 0, 0, 0]); continue
        total = sum(e[2] for e in episodes)
        days_in = sum((b-a)/86400e3 for a, b, _ in episodes)
        span_days = (data[-1][0]-data[0][0])/86400e3
        # recent era only (2024+)
        rec = [e for e in episodes if e[0] >= 1704067200000]
        rec_total = sum(e[2] for e in rec)
        rec_days_in = sum((b-a)/86400e3 for a, b, _ in rec) or 1
        rec_span = (data[-1][0]-1704067200000)/86400e3
        worst = min(e[2] for e in episodes)
        r = [sym, enter_apr, len(episodes), f"{100*days_in/span_days:.0f}%",
             f"{100*total*365/max(days_in,1):.1f}%", f"{100*rec_total*365/rec_days_in:.1f}%",
             f"{100*rec_total*365/max(rec_span,1):.1f}%", f"{100*worst:.2f}%"]
        rows.append(r)
        print(f"    enter>{enter_apr:>4.0f}%: {len(episodes):>3} episodes, deployed {r[3]:>4}, "
              f"net APR-on-deployed {r[4]:>7} (2024+: {r[5]:>7}), on-capital-2024+ {r[6]:>7}, worst ep {r[7]}")
    return rows

def main():
    print("CONDITIONAL FUNDING CARRY — real exchange data, cost", RT_COST_BP, "bp RT, exit <", EXIT_APR, "% APR")
    allrows = []
    for s in SYMS: allrows += screen(s)
    os.makedirs("analysis_data", exist_ok=True)
    with io.open("analysis_data/funding_carry_screen.csv", "w", newline="\n") as f:
        f.write("symbol,enter_apr,episodes,pct_deployed,net_apr_on_deployed_full,net_apr_on_deployed_2024plus,net_apr_on_capital_2024plus,worst_episode\n")
        for r in allrows: f.write(",".join(str(x) for x in r) + "\n")
    print("\nGATE: net APR-on-deployed (2024+) >= 8% AND worst episode > -3% -> candidate lives; else dies.")
    print("saved -> analysis_data/funding_carry_screen.csv")

if __name__ == "__main__":
    main()
