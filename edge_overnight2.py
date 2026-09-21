#!/usr/bin/env python3
"""
SECOND-ENGINE CANDIDATE: the OVERNIGHT index premium, focused recency screen (2026-07-31).

Prior art: edge_yahoo/edge_overnight (06-23) found close->open drift NET of cost at Sharpe
0.80 (NIK225) / 0.55 (SP500) / 0.54 (NAS100) — shelved ONLY because CFDs can't capture the
cash gap. Real futures (MES/MNQ/Nikkei-mini) CAN: sell MOC-equivalent at open... i.e., hold
long ONLY overnight (buy near close, sell near open), ~1-1.5bp/day round trip on micros.
Structural basis: the equity risk premium concentrates overnight (NY Fed 'overnight drift';
earnings/news land off-hours; intraday is where the crowd trades).

This screen: 15y of cash-index daily OHLC (Yahoo), strategy = long every close->open, flat
intraday. Cost 1.5bp per night (round trip, micro-futures + slippage buffer).
PRE-COMMITTED GATE (before results): 2-4 index equal-weight portfolio NET Sharpe >= 0.5 in
the RECENT 3y AND positive in BOTH halves. (The axis every dead candidate died on.)
Run: python edge_overnight2.py     (writes analysis_data/overnight2.csv)
"""
import io, json, math, os, time, urllib.request
import statistics as st
from datetime import datetime, timezone

IDX = {"^GSPC":"SP500", "^NDX":"NAS100", "^N225":"NIK225", "^GDAXI":"DAX"}
COST_BP_NIGHT = 1.5
RECENT_Y = 3

def fetch(t):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(t)}?range=15y&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        j = json.loads(r.read().decode())
    res = j["chart"]["result"][0]
    ts = res["timestamp"]; q = res["indicators"]["quote"][0]
    rows = [(t_, o, c) for t_, o, c in zip(ts, q["open"], q["close"]) if o and c]
    return rows

import urllib.parse
def sharpe(rs):
    if len(rs) < 60: return 0.0
    s = st.pstdev(rs)
    return st.mean(rs)/s*math.sqrt(252) if s > 0 else 0.0

def main():
    print(f"OVERNIGHT PREMIUM SCREEN — long close->open only, cost {COST_BP_NIGHT}bp/night")
    port_by_day = {}
    table = []
    for tk, name in IDX.items():
        try:
            rows = fetch(tk); time.sleep(0.8)
        except Exception as e:
            print(f"{name}: FETCH FAIL {e}"); continue
        on = []   # (ts, overnight net), and intraday for reference
        idr = []
        for i in range(1, len(rows)):
            t_, o, c = rows[i]; _, _, cp = rows[i-1]
            if cp <= 0 or o <= 0: continue
            on.append((t_, (o/cp - 1) - COST_BP_NIGHT/1e4))
            idr.append(c/o - 1)
        rets = [r for _, r in on]
        n = len(rets); h = n//2
        rec = rets[-RECENT_Y*252:]
        # per-year for the recency story
        byyear = {}
        for t_, r in on:
            byyear.setdefault(datetime.fromtimestamp(t_, tz=timezone.utc).year, []).append(r)
        yrs = sorted(byyear)[-6:]
        ystr = " ".join(f"{y%100:02d}:{sharpe(byyear[y]):+.1f}" for y in yrs)
        print(f"{name:8} ON full {sharpe(rets):+.2f}  h1 {sharpe(rets[:h]):+.2f}  h2 {sharpe(rets[h:]):+.2f}  recent{RECENT_Y}y {sharpe(rec):+.2f}  (intraday ref {sharpe(idr):+.2f})   yearly[{ystr}]")
        table.append([name, f"{sharpe(rets):.2f}", f"{sharpe(rets[:h]):.2f}", f"{sharpe(rets[h:]):.2f}", f"{sharpe(rec):.2f}"])
        for t_, r in on:
            d = datetime.fromtimestamp(t_, tz=timezone.utc).date().isoformat()
            port_by_day.setdefault(d, []).append(r)
    days = sorted(d for d, v in port_by_day.items() if len(v) >= 2)
    port = [st.mean(port_by_day[d]) for d in days]
    n = len(port); h = n//2; rec = port[-RECENT_Y*252:]
    print("\n" + "="*60)
    print(f"PORTFOLIO ({len(table)} indices, {n} days):")
    print(f"  full {sharpe(port):+.2f}   1st half {sharpe(port[:h]):+.2f}   2nd half {sharpe(port[h:]):+.2f}   recent{RECENT_Y}y {sharpe(rec):+.2f}  (ann {252*st.mean(rec)*100:+.1f}%)")
    g = sharpe(port[:h]) > 0 and sharpe(port[h:]) > 0 and sharpe(rec) >= 0.5
    print(f"PRE-COMMITTED GATE (both halves > 0 AND recent-{RECENT_Y}y >= 0.5): {'PASS' if g else 'FAIL'}")
    os.makedirs("analysis_data", exist_ok=True)
    with io.open("analysis_data/overnight2.csv", "w", newline="\n") as f:
        f.write("index,full,h1,h2,recent3y\n")
        for r in table: f.write(",".join(r)+"\n")
        f.write(f"PORTFOLIO,{sharpe(port):.2f},{sharpe(port[:h]):.2f},{sharpe(port[h:]):.2f},{sharpe(rec):.2f},gate={'PASS' if g else 'FAIL'}\n")
    print("saved -> analysis_data/overnight2.csv")

if __name__ == "__main__":
    main()
