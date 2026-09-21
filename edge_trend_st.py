#!/usr/bin/env python3
"""
SECOND-ENGINE SCREEN: SHORT-TERM trend on REAL futures (2026-07-30).

Context: ib_trend_phase1 (07-13) killed simple LONG-TERM Donchian trend (2nd half -0.55).
The 07-24 deep-research pointed at SHORT-TERM trend as the genuinely uncorrelated CTA factor
(corr 0.24-0.50 to SG CTA) with venue cost as the dominant swing. This screens the SHORT-TERM
ensemble the phase-1 run never tested, on IB real-futures economics.

PRE-COMMITTED GATE (set before running, per [[lead-with-sober-not-hype]]):
  equal-risk portfolio NET Sharpe >= 0.5 in BOTH halves AND positive over the recent 3y.
  (Exactly the axis phase-1 died on. Fail -> the class dies again, honestly.)

Cost model (IB real futures, from phase-1): NO swap; commission+spread ~= 1.0 bp per position
change (round-trip ~2bp, conservative retail-IB) + 4 rolls/yr x 1bp while positioned.
Data: Yahoo chart API (documented working source), 10y daily continuous futures.
Run: python edge_trend_st.py   (writes analysis_data/trend_st_screen.csv)
"""
import io, json, math, os, time, urllib.request
import statistics as st

UNIVERSE = {  # ~20 liquid real futures across classes
    "ES=F":"SP500", "NQ=F":"NAS100", "YM=F":"DOW", "RTY=F":"RUS2000",
    "GC=F":"GOLD", "SI=F":"SILVER", "HG=F":"COPPER", "CL=F":"WTI", "BZ=F":"BRENT", "NG=F":"NATGAS",
    "ZB=F":"T-BOND", "ZN=F":"T-NOTE10",
    "6E=F":"EUR", "6J=F":"JPY", "6B=F":"GBP", "6A=F":"AUD", "6C=F":"CAD",
    "ZC=F":"CORN", "ZW=F":"WHEAT", "ZS=F":"SOYBEAN",
}
COST_BP_PER_TURN = 1.0     # per position CHANGE (entry or exit side), bps of notional
ROLL_BP_YEAR     = 4.0     # 4 rolls/yr x ~1bp while positioned
VOL_TARGET       = 0.10    # per-market annualized vol target (position scaling)
RECENT_YEARS     = 3

def fetch(ticker):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=10y&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        j = json.loads(r.read().decode())
    res = j["chart"]["result"][0]
    ts = res["timestamp"]; q = res["indicators"]["quote"][0]
    out = [(t, c) for t, c in zip(ts, q["close"]) if c]
    return out

def ema_vol(rets, lam=0.94):
    v = st.pstdev(rets[:20]) if len(rets) >= 20 else 0.01
    out = []
    for r in rets:
        v = math.sqrt(lam*v*v + (1-lam)*r*r)
        out.append(max(v, 1e-6))
    return out

def strat_positions(closes, mode):
    """daily target position in {-1,0,+1} BEFORE vol scaling; signal on CLOSED data (shifted by caller)"""
    n = len(closes); pos = [0.0]*n
    if mode == "tsmom20":
        for i in range(21, n): pos[i] = 1.0 if closes[i-1] > closes[i-21] else -1.0
    elif mode == "tsmom60":
        for i in range(61, n): pos[i] = 1.0 if closes[i-1] > closes[i-61] else -1.0
    elif mode.startswith("donch"):
        N = int(mode[5:]); X = max(N//2, 3)   # enter on N-day breakout, exit on X-day reverse extreme
        cur = 0.0
        for i in range(N+1, n):
            hiN = max(closes[i-N-1:i-1]); loN = min(closes[i-N-1:i-1])
            hiX = max(closes[i-X-1:i-1]); loX = min(closes[i-X-1:i-1])
            c = closes[i-1]
            if cur == 0:
                if c > hiN: cur = 1.0
                elif c < loN: cur = -1.0
            elif cur > 0 and c < loX: cur = 0.0
            elif cur < 0 and c > hiX: cur = 0.0
            pos[i] = cur
    return pos

def net_returns(closes, pos):
    """vol-targeted daily net returns with turnover + roll costs"""
    rets = [closes[i]/closes[i-1]-1 for i in range(1, len(closes))]
    vols = ema_vol(rets)
    daily_roll = ROLL_BP_YEAR/1e4/252
    out = []; prev_w = 0.0
    for i in range(1, len(closes)):
        scale = min(VOL_TARGET/(vols[i-1]*math.sqrt(252)), 3.0)
        w = pos[i]*scale
        cost = abs(w-prev_w)*COST_BP_PER_TURN/1e4 + abs(w)*daily_roll
        out.append(w*rets[i-1] - cost)
        prev_w = w
    return out

def sharpe(rs):
    if len(rs) < 60: return 0.0
    m = st.mean(rs); s = st.pstdev(rs)
    return (m/s*math.sqrt(252)) if s > 0 else 0.0

def main():
    strats = ["tsmom20", "tsmom60", "donch10", "donch20"]
    series = {}   # name -> (timestamps, ensemble net returns)
    rows = []
    print(f"{'market':10}" + "".join(f"{s:>10}" for s in strats) + f"{'ENSEMBLE':>10}")
    for tk, name in UNIVERSE.items():
        try:
            data = fetch(tk); time.sleep(0.6)
        except Exception as e:
            print(f"{name:10}  FETCH FAIL {e}"); continue
        ts = [t for t, _ in data]; closes = [c for _, c in data]
        if len(closes) < 800: print(f"{name:10}  thin ({len(closes)})"); continue
        per = []
        nets_by_strat = []
        for sname in strats:
            nr = net_returns(closes, strat_positions(closes, sname))
            nets_by_strat.append(nr); per.append(sharpe(nr))
        ens = [st.mean(x) for x in zip(*nets_by_strat)]
        series[name] = (ts[1:], ens)
        rows.append([name] + [f"{x:.2f}" for x in per] + [f"{sharpe(ens):.2f}"])
        print(f"{name:10}" + "".join(f"{x:>10.2f}" for x in per) + f"{sharpe(ens):>10.2f}")

    # equal-risk portfolio on aligned dates
    from collections import defaultdict
    byday = defaultdict(list)
    for name, (ts, ens) in series.items():
        for t, r in zip(ts, ens): byday[t].append(r)
    days = sorted(d for d, v in byday.items() if len(v) >= 10)
    port = [st.mean(byday[d]) for d in days]
    n = len(port); h = n//2
    recent = port[-RECENT_YEARS*252:]
    # avg pairwise correlation (coarse, on overlapping days)
    print("\n" + "="*64)
    print(f"PORTFOLIO ({len(series)} markets, {n} days):")
    print(f"  full Sharpe   : {sharpe(port):.2f}")
    print(f"  1st half      : {sharpe(port[:h]):.2f}")
    print(f"  2nd half      : {sharpe(port[h:]):.2f}")
    print(f"  recent {RECENT_YEARS}y     : {sharpe(recent):.2f}  (ann ret {252*st.mean(recent)*100:.1f}%)")
    g = (sharpe(port[:h]) >= 0.5 and sharpe(port[h:]) >= 0.5 and st.mean(recent) > 0)
    print(f"\nPRE-COMMITTED GATE (>=0.5 BOTH halves AND recent-{RECENT_YEARS}y positive): {'PASS' if g else 'FAIL'}")
    os.makedirs("analysis_data", exist_ok=True)
    with io.open("analysis_data/trend_st_screen.csv", "w", newline="\n") as f:
        f.write("market," + ",".join(strats) + ",ensemble\n")
        for r in rows: f.write(",".join(r) + "\n")
        f.write(f"\nPORTFOLIO,full={sharpe(port):.2f},h1={sharpe(port[:h]):.2f},h2={sharpe(port[h:]):.2f},recent{RECENT_YEARS}y={sharpe(recent):.2f},gate={'PASS' if g else 'FAIL'}\n")
    print("saved -> analysis_data/trend_st_screen.csv")

if __name__ == "__main__":
    main()
