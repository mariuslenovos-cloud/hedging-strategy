#!/usr/bin/env python3
"""
RELATIVE-VALUE / COINTEGRATION SCREEN  --  last class of the EA hunt (cost-first, market-NEUTRAL).

Trade the SPREAD between two STRUCTURALLY-linked instruments that mean-reverts by construction.
Market-neutral -> ~zero correlation to everything (the diversification prize) + no directional tail.

The project's earlier lesson (Session 19p): broad/arbitrary equity pairs FAIL out-of-sample (selection = luck);
only STRUCTURAL pairs persist -- same commodity (WTI-Brent) or physically-linked (crack spread = refiner vs
crude). The grid version died on 2-leg COST; this tests a SLOW, low-turnover z-reversion (few round-trips) net
of REAL 2-leg cost (cheap on IB stocks ~2bps/leg) -- which may clear the cost the oil-CFD grid couldn't.

DECISIVE metric = OUT-OF-SAMPLE Sharpe net of cost (fit beta on the 1st 60%, trade the last 40% unseen).
Includes ARBITRARY control pairs (banks/consumer) that SHOULD fail OOS -> confirms the structural distinction.

Run:  python rv_screen.py
"""
import sys, json, time, ssl
import urllib.request
from datetime import datetime
import numpy as np
import pandas as pd

# (legA, legB, label, kind, cost_bps_per_leg)   kind: STRUCT = physically linked, CTRL = arbitrary control
PAIRS = [
    ("CVX",  "VLO",  "integrated vs refiner",   "STRUCT", 2.0),
    ("PSX",  "VLO",  "refiner vs refiner",       "STRUCT", 2.0),
    ("MPC",  "VLO",  "refiner vs refiner",       "STRUCT", 2.0),
    ("COP",  "OXY",  "producer vs producer",     "STRUCT", 2.0),
    ("XOM",  "CVX",  "integrated vs integrated", "STRUCT", 2.0),
    ("CL=F", "BZ=F", "WTI vs Brent (futures)",   "STRUCT", 3.5),
    ("NEM",  "GOLD", "gold miner vs gold miner", "STRUCT", 2.0),
    ("JPM",  "BAC",  "bank vs bank (control)",   "CTRL",   2.0),
    ("KO",   "PEP",  "consumer vs consumer (ctrl)","CTRL", 2.0),
]
RANGE = "12y"; ZWIN = 60; ENTRY, EXIT, STOP = 2.0, 0.5, 4.0
_ctx = ssl.create_default_context(); _ctx.check_hostname = False; _ctx.verify_mode = ssl.CERT_NONE

def fetch(ticker):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range={RANGE}&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for a in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20, context=_ctx) as r:
                j = json.load(r)
            res = j["chart"]["result"][0]
            s = pd.Series(res["indicators"]["quote"][0]["close"],
                          index=pd.to_datetime(res["timestamp"], unit="s")).dropna()
            return s
        except Exception:
            if a == 2: return None
            time.sleep(1.2)

def pos_from_z(z):
    zv = z.values
    pos = np.zeros(len(zv)); state = 0
    for t in range(len(zv)):
        zt = zv[t]
        if np.isnan(zt): pos[t] = state; continue
        if state == 0:
            if zt > ENTRY: state = -1          # spread rich -> short spread
            elif zt < -ENTRY: state = 1        # spread cheap -> long spread
        elif state == 1:
            if zt >= -EXIT or zt <= -STOP: state = 0
        elif state == -1:
            if zt <= EXIT or zt >= STOP: state = 0
        pos[t] = state
    return pd.Series(pos, index=z.index)

def half_life(s):
    ds = s.diff().dropna(); sl = s.shift(1).dropna().reindex(ds.index)
    b = np.polyfit(sl.values, ds.values, 1)[0]
    return (-np.log(2) / b) if b < 0 else np.inf

def bt(la, lb, beta, cost_bps, win):
    s = (la - beta * lb)                       # log spread
    z = (s - s.rolling(win).mean()) / s.rolling(win).std()
    pos = pos_from_z(z)
    ret = pos.shift(1) * s.diff()
    cost = (cost_bps / 1e4) * (1 + abs(beta)) * pos.diff().abs().fillna(pos.abs())
    net = (ret - cost).dropna()
    if len(net) < 60 or net.std() == 0: return 0.0, 0
    sharpe = net.mean() / net.std() * np.sqrt(252)
    trades = int((pos.diff().abs() > 0).sum())
    return sharpe, trades

def main():
    print(f"RELATIVE-VALUE / COINTEGRATION SCREEN  |  {datetime.now():%Y-%m-%d %H:%M}  |  slow z-reversion, NET of 2-leg cost")
    print("DECISIVE = OUT-OF-SAMPLE Sharpe (beta fit on 1st 60%, traded on last 40% unseen)\n")
    print(f"{'pair':12} {'kind':7} {'half-life':>9} {'IS Sh':>6} {'OOS Sh':>7} {'OOStr':>6}  note")
    survivors = []
    for ta, tb, lbl, kind, cost in PAIRS:
        a, b = fetch(ta), fetch(tb)
        if a is None or b is None:
            print(f"{ta+'/'+tb:12} {kind:7}  fetch failed"); continue
        df = pd.concat([np.log(a), np.log(b)], axis=1, keys=["a", "b"]).dropna()
        if len(df) < 500:
            print(f"{ta+'/'+tb:12} {kind:7}  too short ({len(df)})"); continue
        n = len(df); cut = int(n * 0.6)
        isd, ood = df.iloc[:cut], df.iloc[cut:]
        beta = np.polyfit(isd["b"].values, isd["a"].values, 1)[0]   # hedge ratio from IS only
        hl = half_life((isd["a"] - beta * isd["b"]))
        is_sh, _ = bt(isd["a"], isd["b"], beta, cost, ZWIN)
        oos_sh, oos_tr = bt(ood["a"], ood["b"], beta, cost, ZWIN)
        ok = oos_sh > 0.5 and kind == "STRUCT"
        if ok: survivors.append((f"{ta}/{tb}", lbl, oos_sh))
        note = "PERSISTS" if ok else ("OOS-fail" if oos_sh <= 0.5 else "")
        time.sleep(0.3)
        print(f"{ta+'/'+tb:12} {kind:7} {hl:>8.0f}d {is_sh:>6.2f} {oos_sh:>7.2f} {oos_tr:>6}  {note}")
        time.sleep(0.2)
    print(f"\nSTRUCTURAL pairs that PERSIST OOS (net Sharpe > 0.5): {len(survivors)}")
    for p, lbl, sh in sorted(survivors, key=lambda x: -x[2]):
        print(f"   {p:10} OOS Sharpe {sh:.2f}   ({lbl})")
    print("\nREAD: structural (crack-spread / same-commodity) should hold OOS; arbitrary controls (banks/consumer)")
    print("should NOT -> confirms only STRUCTURAL cointegration persists. Survivors are MARKET-NEUTRAL, leverageable,")
    print("uncorrelated to the whole book. Caveat: Yahoo daily + static beta + slow z; real exec on IB stocks (cheap")
    print("2-leg) is the build; rolling-beta + a live demo decide. This is feasibility, not final P&L.")

if __name__ == "__main__":
    main()
