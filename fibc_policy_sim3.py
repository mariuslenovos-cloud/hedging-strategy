"""
fibc_policy_sim3.py — POLICY PILOT v3 (2026-08-24): fib C's REAL payoff geometry on 5.25y paths.

v2's proxy charged release the full +0.8 ATR continuation run; real fib C banks the whole
book at +$40 and floors at -20% of balance — a ~15:1 payoff asymmetry the release policy is
built for. v3 walks each armed episode BAR BY BAR with the real exits:

  units: flat 0.02 lots (scale-1, the P-N0 zero-losing config; $1/point per unit... 0.02x100 = $2/point)
  book  = 4 units OPPOSITE the ride @ arm - 0.5 ATR (the drowned position that armed the rescue)
  ride  = fib ladder 1,1,2,3,5,8 units; leg 1 at arm; adds hourly while book mark < 0 (loss-gated), cap 6
  BANK  : whole-book mark >= +$40    (fib C RecoveryTargetUSD)
  FLOOR : whole-book mark <= -$600   (-20% of $3,000)
  TIME  : 24h cap -> mark at close (proxy detector's horizon)

Policies (release whole book at FIRST trigger; pre-committed in v2, unchanged):
  R1: (pull>=q66 & stale>=q66) or (pos<=0 & pull>=q66)
  R2: R1 AND velB <= median
  R3: velB <= q33 AND pull >= q66
  R4: R2 AND mark >= -$300   (release only while the loss is still small)
One walk per episode; policy = first trigger before the base exit.
"""
import csv, os
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
def load(path):
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            rows.append((datetime.strptime(r["time"], "%Y-%m-%d %H:%M"),
                         float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])))
    rows.sort(); return rows
def daily_atr(rows):
    days = {}
    for t, o, h, l, c in rows:
        d = t.date()
        if d not in days: days[d] = [h, l, c]
        else:
            days[d][0] = max(days[d][0], h); days[d][1] = min(days[d][1], l); days[d][2] = c
    dlist = sorted(days.items()); out, trs, prev_c, ab = {}, [], None, {}
    for d, (h, l, c) in dlist:
        tr = h - l if prev_c is None else max(h - l, abs(h - prev_c), abs(l - prev_c))
        trs.append(tr); prev_c = c
        if len(trs) >= 14: ab[d] = sum(trs[-14:]) / 14.0
    seq = [d for d, _ in dlist]
    for i in range(1, len(seq)):
        if seq[i - 1] in ab: out[seq[i]] = ab[seq[i - 1]]
    return out

rows = load(os.path.join(HERE, "analysis_data", "xauusd_m30_export.csv"))
patr = daily_atr(rows); n = len(rows)
BPH, LOOKBACK, TIMECAP, VELB = 2, 48, 48, 6
ARM_MULT = 0.5
UNIT = 2.0          # $ per gold point per unit (0.02 lots x 100)
FIBW = [1, 1, 2, 3, 5, 8]
W_BOOK = 4
TARGET, FLOOR = 40.0, -600.0
ADD_EVERY, MAX_LEGS = 2, 6

# thresholds carried from v2 (same detector/state definitions)
Q_PULL, Q_STALE, MED_VELB, Q33_VELB = 0.298, 7.0, 0.016, -0.064

episodes = []
i = LOOKBACK
while i < n - 1:
    t = rows[i][0]; c = rows[i][4]
    atr = patr.get(t.date())
    if atr is None or atr <= 0: i += 1; continue
    move = c - rows[i - LOOKBACK][4]
    if abs(move) < ARM_MULT * atr: i += 1; continue
    rdir = 1 if move > 0 else -1
    arm_p = c
    book_p = arm_p - rdir * 0.5 * atr
    legs = [(arm_p, FIBW[0])]
    ext, ext_i = arm_p, i
    outcome, end_j, end_mark = "TIME", min(i + TIMECAP, n - 1), None
    trig = {}   # policy -> (bar j, mark $) of first trigger
    for j in range(i + 1, min(i + TIMECAP + 1, n)):
        tj, oj, hj, lj, cj = rows[j]
        mark = (cj - book_p) * (-rdir) * W_BOOK * UNIT + sum((cj - p) * rdir * w * UNIT for p, w in legs)
        if mark >= TARGET: outcome, end_j, end_mark = "BANK", j, mark; break
        if mark <= FLOOR: outcome, end_j, end_mark = "FLOOR", j, mark; break
        prog = (cj - arm_p) * rdir
        if prog > (ext - arm_p) * rdir: ext, ext_i = cj, j
        k = j - i
        if k % ADD_EVERY == 0:
            pos = prog / atr; pull = ((ext - cj) * rdir) / atr
            stale = (j - ext_i) / BPH
            velB = (cj - rows[j - VELB][4]) / atr * rdir
            p3 = (pull >= Q_PULL and stale >= Q_STALE) or (pos <= 0 and pull >= Q_PULL)
            fired = {"R1": p3, "R2": p3 and velB <= MED_VELB,
                     "R3": velB <= Q33_VELB and pull >= Q_PULL}
            fired["R4"] = fired["R2"] and mark >= -300.0
            for pol, f in fired.items():
                if f and pol not in trig: trig[pol] = (j, mark)
            if len(legs) < MAX_LEGS and mark < 0:
                legs.append((cj, FIBW[len(legs)]))
    if end_mark is None:
        cj = rows[end_j][4]
        end_mark = (cj - book_p) * (-rdir) * W_BOOK * UNIT + sum((cj - p) * rdir * w * UNIT for p, w in legs)
    episodes.append(dict(t=t, atr=atr, outcome=outcome, end_j=end_j, pnl=end_mark, trig=trig))
    i = end_j + 1

N = len(episodes)
oc = {k: [e for e in episodes if e["outcome"] == k] for k in ("BANK", "FLOOR", "TIME")}
tot = sum(e["pnl"] for e in episodes)
print(f"episodes {N} over 5.25y  |  BANK {len(oc['BANK'])}  FLOOR {len(oc['FLOOR'])}  TIME {len(oc['TIME'])}")
print(f"BASE: total {tot:+,.0f} $  avg/ep {tot/N:+.1f}  "
      f"BANK$ {sum(e['pnl'] for e in oc['BANK']):+,.0f}  FLOOR$ {sum(e['pnl'] for e in oc['FLOOR']):+,.0f}  "
      f"TIME$ {sum(e['pnl'] for e in oc['TIME']):+,.0f}  worst {min(e['pnl'] for e in episodes):+,.0f}")
print(f"(reality check: floor rate {len(oc['FLOOR'])/N*100:.1f}% of episodes; fib C live ~1-in-5 ride class)")

mid_t = rows[n // 2][0]
for pol in ("R1", "R2", "R3", "R4"):
    tot_p = 0.0; cnt = {"BANK": 0.0, "FLOOR": 0.0, "TIME": 0.0}
    nrel = 0; hd = {"H1": 0.0, "H2": 0.0}; worst = 0.0
    floors_left = 0
    for e in episodes:
        tr = e["trig"].get(pol)
        if tr is not None and tr[0] <= e["end_j"]:
            p = tr[1]; nrel += 1
            if e["outcome"] == "FLOOR" and tr[0] < e["end_j"]: pass
        else:
            p = e["pnl"]
            if e["outcome"] == "FLOOR": floors_left += 1
        tot_p += p; cnt[e["outcome"]] += p
        hd["H1" if e["t"] < mid_t else "H2"] += p - e["pnl"]
        worst = min(worst, p)
    print(f"\n{pol}: total {tot_p:+,.0f} $ (delta {tot_p-tot:+,.0f})  released {nrel}/{N}  floors remaining {floors_left}/{len(oc['FLOOR'])}")
    print(f"   by base-outcome: BANK-class {cnt['BANK']:+,.0f}  FLOOR-class {cnt['FLOOR']:+,.0f}  TIME-class {cnt['TIME']:+,.0f}")
    print(f"   halves delta {hd['H1']:+,.0f}/{hd['H2']:+,.0f}   worst episode {worst:+,.0f}")

# distribution color: episode P&L percentiles base vs R4
import statistics
for pol in (None, "R4"):
    vals = []
    for e in episodes:
        tr = e["trig"].get(pol) if pol else None
        vals.append(tr[1] if tr and tr[0] <= e["end_j"] else e["pnl"])
    vals.sort()
    pc = lambda f: vals[int(len(vals) * f)]
    print(f"{'BASE' if pol is None else pol}: p5 {pc(0.05):+,.0f}  p25 {pc(0.25):+,.0f}  med {pc(0.5):+,.0f}  p75 {pc(0.75):+,.0f}  p95 {pc(0.95):+,.0f}")
