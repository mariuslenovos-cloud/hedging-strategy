#!/usr/bin/env python3
"""
FUNDING CARRY v2 — MULTI-SYMBOL ROTATION (the decisive utilization test, 2026-07-30).

v1 result: episodic carry PASSES on deployed capital (BTC 8-10%, ETH 8-10% net APR 2024+,
worst episode -0.34%) but BTC/ETH-only utilization is too low -> dedicated capital earns 1-2%.
v2 tests the practitioner design: scan ~12 liquid perps, always hold the RICHEST rich one
(trailing-7d annualized funding > ENTER%), rotate as leadership changes, exit to cash when
nothing is rich. Costs charged on every rotation (full 4-leg round trip).

PRE-COMMITTED GATE: net APR ON TOTAL DEDICATED CAPITAL (2024+, idle time included) >= 8%
with worst episode > -3%. That's the bar where a new venue + build beats just sizing the book.
Run: python edge_funding_carry2.py   (writes analysis_data/funding_carry2.csv)
"""
import io, json, math, os, time, urllib.request
from datetime import datetime

SYMS = ["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT","DOGEUSDT","BNBUSDT",
        "ADAUSDT","LINKUSDT","AVAXUSDT","LTCUSDT","DOTUSDT","SUIUSDT"]
RT_COST_BP = 40.0
ENTER_APR  = 12.0     # richness bar to deploy/rotate
EXIT_APR   = 5.0
SWITCH_EDGE= 8.0      # only rotate to another symbol if it beats current by this many APR pts (anti-churn)
TRAIL_N    = 21       # 7d x 3 payments

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

def fetch(sym):
    out, start = [], 1577836800000
    while True:
        j = get(f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={sym}&startTime={start}&limit=1000")
        if not isinstance(j, list) or not j: break
        out += [(int(x["fundingTime"]), float(x["fundingRate"])) for x in j]
        if len(j) < 1000: break
        start = out[-1][0] + 1
        time.sleep(0.25)
    return sorted(out)

def main():
    print(f"MULTI-SYMBOL FUNDING ROTATION — enter>{ENTER_APR}% APR, exit<{EXIT_APR}%, switch-edge {SWITCH_EDGE}pts, cost {RT_COST_BP}bp/rotation")
    hist = {}
    for s in SYMS:
        try:
            d = fetch(s)
            if len(d) >= TRAIL_N*4: hist[s] = dict(d); print(f"  {s:10} {len(d)} payments")
            else: print(f"  {s:10} thin — skipped")
        except Exception as e:
            print(f"  {s:10} fetch failed: {e}")
    # unified 8h timeline
    all_ts = sorted(set(t for d in hist.values() for t in d))
    # trailing APR per symbol per timestamp (walk each symbol's own series)
    series = {}
    for s, d in hist.items():
        ts_sorted = sorted(d)
        trail = {}
        for i in range(TRAIL_N, len(ts_sorted)):
            t = ts_sorted[i]
            trail[t] = sum(d[x] for x in ts_sorted[i-TRAIL_N:i]) / 7 * 365 * 100
        series[s] = trail
    held = None; pnl_bp_events = []   # (ts, pnl_contribution in fraction)
    episodes = []; cur = 0.0; cur_start = None; rotations = 0
    for t in all_ts:
        # richest symbol right now
        cands = [(series[s].get(t), s) for s in series if series[s].get(t) is not None]
        if not cands: continue
        best_apr, best_sym = max(cands)
        if held is None:
            if best_apr > ENTER_APR:
                held = best_sym; rotations += 1
                cur = -RT_COST_BP/1e4; cur_start = t
        else:
            fr = hist[held].get(t)
            if fr is not None: cur += fr
            held_apr = series[held].get(t, 0)
            if held_apr < EXIT_APR:
                episodes.append((cur_start, t, cur)); held = None; cur = 0.0
            elif best_sym != held and best_apr > held_apr + SWITCH_EDGE and best_apr > ENTER_APR:
                episodes.append((cur_start, t, cur))          # close current
                held = best_sym; rotations += 1
                cur = -RT_COST_BP/1e4; cur_start = t          # open new
    if held is not None: episodes.append((cur_start, all_ts[-1], cur))
    if not episodes: print("no episodes"); return
    span = (all_ts[-1]-all_ts[0])/86400e3
    t2024 = 1704067200000
    for label, eps, t_lo in (("FULL 2020-26", episodes, all_ts[0]),
                             ("2024+ (decayed era)", [e for e in episodes if e[0] >= t2024], t2024)):
        if not eps: print(f"{label}: none"); continue
        tot = sum(e[2] for e in eps)
        din = sum((b-a)/86400e3 for a,b,_ in eps)
        spn = (all_ts[-1]-t_lo)/86400e3
        w = min(e[2] for e in eps)
        print(f"\n{label}: {len(eps)} episodes | deployed {100*din/spn:.0f}% of days")
        print(f"  net APR on DEPLOYED: {100*tot*365/max(din,1):.1f}%")
        print(f"  net APR on TOTAL CAPITAL (idle incl.): {100*tot*365/spn:.1f}%")
        print(f"  worst episode: {100*w:.2f}%   rotations: {rotations}")
    g_eps = [e for e in episodes if e[0] >= t2024]
    tot = sum(e[2] for e in g_eps); spn = (all_ts[-1]-t2024)/86400e3
    on_cap = 100*tot*365/spn; worst = 100*min(e[2] for e in g_eps) if g_eps else -99
    print(f"\nPRE-COMMITTED GATE (2024+ on-capital >= 8% AND worst > -3%): {'PASS' if (on_cap>=8 and worst>-3) else 'FAIL'}")
    os.makedirs("analysis_data", exist_ok=True)
    with io.open("analysis_data/funding_carry2.csv","w",newline="\n") as f:
        f.write("start,end,net_frac\n")
        for a,b,p in episodes:
            f.write(f"{datetime.fromtimestamp(a/1e3):%Y-%m-%d},{datetime.fromtimestamp(b/1e3):%Y-%m-%d},{p:.5f}\n")
    print("saved -> analysis_data/funding_carry2.csv")

if __name__ == "__main__":
    main()
