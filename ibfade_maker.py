#!/usr/bin/env python3
"""
IB FADE-AS-MAKER STUDY (2026-07-13) -- the lead IB-platform tenant audition.

FX rollover-fade is fully validated at MID (+0.54R, CPCV/holdout/cost-stress)
and dead as a spread-TAKER on two retail venue tiers (XM PF 0.37, Razor 0.61).
Question: does POSTING the fade as a LIMIT order (IDEALPRO-style maker) survive
a SKEPTICAL fill model?

Skeptic assumptions (each biases AGAINST the edge):
  * A limit at the signal price fills ONLY if price subsequently trades THROUGH
    it by `penetration` x current spread (touch != fill; queue position unknown).
    Scenarios: 0.0 (touch, optimistic bound), 0.5, 1.0 (deep skeptic).
  * Within-bar ordering: ADVERSE barrier checked before favorable (worst case).
  * Exit is a MARKET order (cross half-spread) -- maker on entry only.
  * IDEALPRO commission 0.2bp per side, $2 minimum, both sides, on 100k notional.
  * Fill window = 12 bars (1h); unfilled = missed trade (measured separately ->
    the adverse-selection mirror: are the misses the winners?).

Events: CUSUM(K=3 x rolling vol(100)) on M5 log-closes, deployable tree rule
(server hours 22/23 fade-up=SELL, hour 0 fade-down=BUY), barriers +/-4 x vol,
96-bar time exit -- identical parameters to afml_engine/fxfade_tree.

Verdict gate (pre-committed): net avg R >= +0.15 at penetration 0.5 with a fill
rate >= 40%, and filled-event edge not collapsing vs the mid-price +0.54R
reference -> IB OMS build gets its green light. Else the platform waits.
"""
import math
import numpy as np
import MetaTrader5 as mt5

SYMBOLS = ["EURUSD","USDJPY","GBPUSD","USDCHF","AUDUSD","NZDUSD","USDCAD",
           "EURJPY","GBPJPY","EURGBP","AUDJPY"]
NBARS, VOLW, CUSUM_K, MOMW = 100_000, 100, 3.0, 20
BARR, MAXH, FILLW = 4.0, 96, 12
COMM_BP, COMM_MIN, NOTIONAL = 0.2, 2.0, 100_000.0

def load(sym):
    r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, NBARS)
    if r is None or len(r) < 5000: return None
    return r

def events_for(r):
    c = r['close']; n = len(c)
    lr = np.zeros(n); lr[1:] = np.diff(np.log(c))
    vol = np.full(n, np.nan)
    s = np.lib.stride_tricks.sliding_window_view(lr, VOLW)
    vol[VOLW-1:] = s.std(axis=1)
    hours = ((r['time'] // 3600) % 24).astype(int)
    ev = []
    up = dn = 0.0
    for i in range(VOLW, n - MAXH - FILLW - 1):
        v = vol[i]
        if not v > 0: continue
        up = max(0.0, up + lr[i]); dn = min(0.0, dn + lr[i])
        breach = None
        if up >= CUSUM_K * v: breach, up = +1, 0.0
        elif dn <= -CUSUM_K * v: breach, dn = -1, 0.0
        if breach is None: continue
        mom = c[i] - c[i - MOMW]
        side = -1 if mom > 0 else +1          # fade: momentum up -> SELL(-1)
        h = hours[i]
        if (h in (22, 23) and side == -1) or (h == 0 and side == +1):
            ev.append((i, side, v))
    return ev

def sim(sym, r, ev, penetration):
    """returns list of dicts per event: filled?, netR maker, netR market, midR"""
    c, hi, lo, sp = r['close'], r['high'], r['low'], r['spread']
    pt = mt5.symbol_info(sym).point
    out = []
    comm_frac = max(COMM_BP / 1e4, COMM_MIN / NOTIONAL)          # per side
    for (i, side, v) in ev:
        p0 = c[i]
        spread = sp[i] * pt
        half = spread / 2.0
        Rdist = BARR * v * p0                                     # 1R in price
        commR = 2 * comm_frac * p0 / Rdist                        # both sides, in R
        # --- mid-price outcome (reference, no cost), barriers from p0
        def outcome(entry, j0):
            tp = entry + side * Rdist
            slp = entry - side * Rdist
            for j in range(j0, i + MAXH):
                if side > 0:
                    if lo[j] <= slp: return -1.0, j               # adverse first
                    if hi[j] >= tp:  return +1.0, j
                else:
                    if hi[j] >= slp: return -1.0, j
                    if lo[j] <= tp:  return +1.0, j
            j = min(i + MAXH, len(c) - 1)
            return side * (c[j] - entry) / Rdist, j
        midR, _ = outcome(p0, i + 1)
        # --- MARKET taker: enter at p0 +/- half-spread, exit crosses half-spread
        mkt_entry = p0 + side * half
        mR, _ = outcome(mkt_entry, i + 1)
        mktR = mR - (half / Rdist) - commR                        # exit half-spread + comm
        # --- MAKER: limit at p0, fill iff penetration-through within FILLW bars
        limit = p0
        need = limit - side * penetration * spread                # price must reach this
        fj = None
        for j in range(i + 1, i + 1 + FILLW):
            if side > 0 and lo[j] <= need: fj = j; break
            if side < 0 and hi[j] >= need: fj = j; break
        if fj is None:
            out.append(dict(filled=False, midR=midR, mktR=mktR, makR=np.nan))
            continue
        kR, _ = outcome(limit, fj)                                # barriers from limit
        makR = kR - (half / Rdist) - commR                        # exit crosses + comm
        out.append(dict(filled=True, midR=midR, mktR=mktR, makR=makR))
    return out

def main():
    if not mt5.initialize(path=r"C:\Program Files\XM Global MT5\terminal64.exe"):
        raise SystemExit(f"mt5 init: {mt5.last_error()}")
    data = {}
    for s in SYMBOLS:
        mt5.symbol_select(s, True)
        r = load(s)
        if r is not None: data[s] = (r, events_for(r))
    print(f"symbols loaded: {len(data)} | events: {sum(len(e) for _, e in data.values())}")
    for pen in (0.0, 0.5, 1.0):
        rows = []
        for s, (r, ev) in data.items():
            rows += [(s, d) for d in sim(s, r, ev, pen)]
        filled  = [d for _, d in rows if d['filled']]
        missed  = [d for _, d in rows if not d['filled']]
        fr = len(filled) / len(rows) if rows else 0
        mak = np.array([d['makR'] for d in filled])
        mid_f = np.array([d['midR'] for d in filled])
        mid_m = np.array([d['midR'] for d in missed]) if missed else np.array([0.0])
        mkt = np.array([d['mktR'] for _, d in rows])
        print(f"\n=== penetration {pen:.1f} x spread ===")
        print(f"fill rate {fr*100:5.1f}%  ({len(filled)}/{len(rows)})")
        print(f"MAKER  net avgR {mak.mean():+.3f}  win% {(mak>0).mean()*100:4.1f}  totR {mak.sum():+8.0f}")
        print(f"TAKER  net avgR {mkt.mean():+.3f}   (the dead retail baseline)")
        print(f"adverse selection: mid-price R of FILLED {mid_f.mean():+.3f} vs MISSED {mid_m.mean():+.3f}")
        # per-symbol at this penetration
        sym_stats = {}
        for s, d in rows:
            if d['filled']: sym_stats.setdefault(s, []).append(d['makR'])
        pos = sum(1 for s, v in sym_stats.items() if np.mean(v) > 0)
        print(f"symbols positive (maker): {pos}/{len(sym_stats)}  " +
              " ".join(f"{s}:{np.mean(v):+.2f}" for s, v in sorted(sym_stats.items())))
    mt5.shutdown()

if __name__ == "__main__":
    main()
