#!/usr/bin/env python3
"""
AUTOMATED FINGERPRINT-DB REFRESH (GOLD + OIL) via Python reproduction.
Keeps the fingerprint win-rates current WITHOUT a manual Strategy Tester run:
  1. pull fresh M5 bars from the live feed
  2. reproduce the shadow (Goldminer + session/ADX/angle gates + triple-barrier)
  3. rebuild the fingerprint DB to a *_research.csv (SAFE location, never the live gate)
  4. DIFF vs the current live gate DB -> ALERT on fingerprint flips / material win-rate shifts

Promotion to the live gate DB stays HUMAN-GLANCED: the Python iADX/iATR reproduction
is APPROXIMATE (documented parity gap), so we never auto-overwrite what the live EA
trades off. Fully-auto = rebuild + diff + alert; the one human touch = promote.

Read-only w.r.t. the live gate DBs. Schedulable: call from Task Scheduler / cron.
Run: python gridstat_shadow_refresh.py
"""
import os, io, csv, time
from datetime import datetime, timedelta
from collections import defaultdict
import numpy as np
import MetaTrader5 as mt5
from gridstat_signalscan import gm_val_series, gm_signals, wilder_adx, ema

LIVE_TERMINAL = r"C:\Program Files\Pepperstone MetaTrader 5\terminal64.exe"
COMMON  = r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\Common\Files"
OUTDIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "analysis_data")
os.makedirs(OUTDIR, exist_ok=True)

# per stream: feed symbol, grisk, gate threshold (gold=0.55 win-rate gate; oil trades filter-off so
# threshold is informational only), the LIVE reference DB in Common\Files.
STREAMS = {
    "GOLD": dict(sym="XAUUSD",    grisk=4, gate=0.55, live_db="gridstat_setups_gold.csv"),
    "OIL":  dict(sym="SpotCrude", grisk=4, gate=None, live_db="gridstat_setups_oil_mt5.csv"),
}
BARS = 60000   # ~10 months of M5

def pull(sym, tf, count):
    r = None
    for _ in range(6):
        r = mt5.copy_rates_from_pos(sym, tf, 0, count)
        if r is not None and len(r) > count*0.3:
            return r
        time.sleep(4)
    return r

def reproduce(sym, grisk):
    """-> list of dicts: setup_key, r_multiple, entry_time  (session+ADX+angle gated, no D1 filter = GridStat)."""
    mt5.symbol_select(sym, True); time.sleep(1)
    r  = pull(sym, mt5.TIMEFRAME_M5, BARS)
    d1 = pull(sym, mt5.TIMEFRAME_D1, 900)
    if r is None or d1 is None:
        return None, "feed unavailable"
    o,h,l,c,t = r['open'],r['high'],r['low'],r['close'],r['time']
    val = gm_val_series(o,h,l,c,grisk); sig = gm_signals(val, grisk)
    adx = np.array([x if x is not None else 0.0 for x in wilder_adx(h,l,c,14)])
    e20 = np.array([x if x is not None else np.nan for x in ema(list(c),20)])
    hours = ((t//3600)%24).astype(int); point = 0.01 if sym=="XAUUSD" else 0.001
    d1t = d1['time']
    d1tr = np.array([max(d1['high'][i]-d1['low'][i], abs(d1['high'][i]-d1['close'][i-1]),
                        abs(d1['low'][i]-d1['close'][i-1])) for i in range(1,len(d1))])
    def atrD1(ts):
        idx = int(np.searchsorted(d1t, ts)) - 1
        return None if idx < 14 else float(np.mean(d1tr[idx-14:idx]))
    tr = np.array([0.0]+[max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1])) for i in range(1,len(c))])
    def roll(a,n):
        out=np.full(len(a),np.nan); cs=np.cumsum(a); out[n:]=(cs[n:]-cs[:-n])/n; return out
    atr20, atr100 = roll(tr,20), roll(tr,100)
    def ang(i):
        if i<5 or np.isnan(e20[i]) or np.isnan(e20[i-5]): return 0.0
        return np.degrees(np.arctan((e20[i]-e20[i-5])/(5*point)))
    def sess(hr): return "ASIA" if hr<9 else "LDN" if hr<14 else "OVL" if hr<18 else "NY"
    rows=[]; N=len(c)
    for i in range(120, N-1):
        s = sig[i]
        if s not in ("BUY","SELL"): continue
        if hours[i] < 9 or hours[i] >= 23: continue          # session filter 9-23 (matches the EA; excludes ASIA)
        if adx[i] <= 25 or abs(ang(i)) <= 20: continue
        a = atrD1(t[i])
        if not a or a <= 0: continue
        isbuy=(s=="BUY"); entry=c[i]; up=entry+0.8*a; dn=entry-0.8*a; hit=None; rr=0.0; end=min(i+288,N)
        for j in range(i+1,end):
            if isbuy:
                if h[j]>=up: rr=1.0; hit=1; break
                if l[j]<=dn: rr=-1.0; hit=1; break
            else:
                if l[j]<=dn: rr=1.0; hit=1; break
                if h[j]>=up: rr=-1.0; hit=1; break
        if hit is None: rr=(c[end-1]-entry)/(0.8*a)*(1 if isbuy else -1)
        reg = "EXP" if (not np.isnan(atr20[i]) and not np.isnan(atr100[i]) and atr20[i]>1.3*atr100[i]) \
              else ("COMP" if (not np.isnan(atr20[i]) and atr20[i]<0.7*atr100[i]) else "NORM")
        rows.append(dict(setup_key=f"{s}|HR_{sess(hours[i])}|ATR_{reg}", r_multiple=rr,
                         entry_time=datetime.utcfromtimestamp(t[i]).strftime("%Y.%m.%d %H:%M")))
    return rows, f"{datetime.utcfromtimestamp(t[0]):%Y-%m} to {datetime.utcfromtimestamp(t[-1]):%Y-%m}"

def winrates(rows_or_path, from_file=False):
    agg = defaultdict(list)
    if from_file:
        if not os.path.exists(rows_or_path): return {}
        rr = list(csv.reader(io.open(rows_or_path, encoding="utf-8", errors="replace")))
        ix = {hh.strip(): k for k, hh in enumerate(rr[0])}
        kc, rc = ix.get("setup_key",0), ix.get("r_multiple")
        for r in rr[1:]:
            if rc is None or len(r)<=rc: continue
            try: agg[r[kc].strip()].append(float(r[rc]))
            except ValueError: pass
    else:
        for r in rows_or_path: agg[r["setup_key"]].append(r["r_multiple"])
    return {k: (len(v), sum(1 for x in v if x>0)/len(v)) for k,v in agg.items()}

def main():
    for _ in range(6):
        mt5.shutdown()
        if mt5.initialize(path=LIVE_TERMINAL): break
        time.sleep(1)
    print(f"SHADOW-DB REFRESH (reproduction) | {datetime.now():%Y-%m-%d %H:%M}\n")
    alerts_total = 0
    for label, cfg in STREAMS.items():
        rows, meta = reproduce(cfg["sym"], cfg["grisk"])
        if rows is None:
            print(f"===== {label}: {meta} (skipped)\n"); continue
        # write research DB (safe location)
        out = os.path.join(OUTDIR, f"gridstat_setups_{label.lower()}_research.csv")
        with io.open(out, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f); w.writerow(["setup_key","r_multiple","entry_time"])
            for r in rows: w.writerow([r["setup_key"], f"{r['r_multiple']:.3f}", r["entry_time"]])
        fresh = winrates(rows)
        live  = winrates(os.path.join(COMMON, cfg["live_db"]), from_file=True)
        gate  = cfg["gate"]
        print(f"===== {label} ({cfg['sym']}, grisk {cfg['grisk']}) | {len(rows)} signals {meta}")
        print(f"   research DB -> {out}")
        print(f"   {'fingerprint':30}{'fresh_n':>8}{'freshWR':>8}{'liveWR':>7}{'dWR':>6}  alert")
        keys = sorted(set(fresh) | set(live), key=lambda k: -(fresh.get(k,(0,0))[0]))
        onboard, drop = [], []                         # actionable candidates (gate streams only)
        MINN = 15                                       # min fresh samples to be a candidate
        for k in keys:
            fn, fw = fresh.get(k, (0, None))
            ln, lw = live.get(k, (0, None))
            fw_s = f"{100*fw:.0f}%" if fw is not None else "  -"
            lw_s = f"{100*lw:.0f}%" if lw is not None else "  -"
            alert = ""
            if fw is not None and lw is not None:
                d = fw - lw
                dw_s = f"{100*d:+.0f}"
                if gate is not None and (fw >= gate) != (lw >= gate):
                    alert = f"** FLIP across {gate:.2f} gate"; alerts_total += 1
                    if fn >= MINN:
                        (onboard if fw >= gate else drop).append((k, fn, fw, lw))
                elif abs(d) >= 0.10 and fn >= 10:
                    alert = f"shift {100*d:+.0f}pp"; alerts_total += 1
            elif fw is not None and lw is None:
                dw_s = "NEW"
                alert = "** NEW fingerprint (not in live DB)"; alerts_total += 1
                if gate is not None and fw >= gate and fn >= MINN:
                    onboard.append((k, fn, fw, None))
            else:
                dw_s = "gone"
            if fn >= 5 or ln >= 5:
                print(f"   {k:30}{fn:>8}{fw_s:>8}{lw_s:>7}{dw_s:>6}  {alert}")
        if gate is not None and (onboard or drop):
            print(f"   -- CANDIDATES (fresh n>={MINN}; confirm via EA-shadow before promoting) --")
            for k, n, w, lw in onboard:
                origin = "NEW fingerprint" if lw is None else f"flipped up from {100*lw:.0f}%"
                print(f"      ONBOARD  {k:28} fresh {100*w:.0f}% / n{n}  ({origin} -> now clears {gate:.2f})")
            for k, n, w, lw in drop:
                print(f"      DROP     {k:28} fresh {100*w:.0f}% / n{n}  (was {100*lw:.0f}% live -> now below {gate:.2f})")
        print()
    mt5.shutdown()
    print(f"{'>>> '+str(alerts_total)+' ALERT(S): review the research DB + promote to the live gate if warranted' if alerts_total else '>>> no material fingerprint changes — live gate DB still current'}.")
    print("PROMOTE (human-glanced) = copy analysis_data/gridstat_setups_<stream>_research.csv -> Common\\Files\\<live_db> after eyeballing the diff.")

if __name__ == "__main__":
    main()
