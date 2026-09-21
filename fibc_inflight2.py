"""
fibc_inflight2.py — IN-FLIGHT separation at SCALE (5.25y PEP M30, 2026-08-24).
Same detector as fibc_inflight.py (validated proxy: arm 0.5xATR run vs 24h anchor,
race +/-0.8xATR / 24h, event-driven, stop-first). Time-equivalent features, permutation null.
Usage: python fibc_inflight2.py [csv] [bar_minutes]
"""
import csv, os, sys, random
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
CSV = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "analysis_data", "xauusd_m30_export.csv")
BAR_MIN = int(sys.argv[2]) if len(sys.argv) > 2 else 30

BPH = 60 // BAR_MIN                       # bars per hour
LOOKBACK = 24 * BPH                       # 24h anchor
TIMECAP = 24 * BPH
CHECKPOINTS = [1 * BPH, 3 * BPH, 6 * BPH, 12 * BPH]
VELA, VELB = 1 * BPH, 3 * BPH             # 1h and 3h velocity windows
ARM_MULT, BAR_MULT = 0.5, 0.8
random.seed(42)

rows = []
with open(CSV, newline="") as f:
    for r in csv.DictReader(f):
        rows.append((datetime.strptime(r["time"], "%Y-%m-%d %H:%M"),
                     float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])))
rows.sort(); n = len(rows)
print(f"bars: {n} ({BAR_MIN}m)  {rows[0][0]} -> {rows[-1][0]}")

# daily ATR(14) shifted
days = {}
for t, o, h, l, c in rows:
    d = t.date()
    if d not in days: days[d] = [h, l, c]
    else:
        days[d][0] = max(days[d][0], h); days[d][1] = min(days[d][1], l); days[d][2] = c
dlist = sorted(days.items()); atr_by_day, trs, prev_c = {}, [], None
for d, (h, l, c) in dlist:
    tr = h - l if prev_c is None else max(h - l, abs(h - prev_c), abs(l - prev_c))
    trs.append(tr); prev_c = c
    if len(trs) >= 14: atr_by_day[d] = sum(trs[-14:]) / 14.0
day_seq = [d for d, _ in dlist]; prev_day_atr = {}
for i in range(1, len(day_seq)):
    if day_seq[i - 1] in atr_by_day: prev_day_atr[day_seq[i]] = atr_by_day[day_seq[i - 1]]

episodes = []
i = max(LOOKBACK, VELB)
while i < n - 1:
    t, o, h, l, c = rows[i]
    atr = prev_day_atr.get(t.date())
    if atr is None or atr <= 0: i += 1; continue
    move = c - rows[i - LOOKBACK][4]
    if abs(move) < ARM_MULT * atr: i += 1; continue
    rdir = 1 if move > 0 else -1
    arm_p = c
    cont_b, rev_b = arm_p + rdir * BAR_MULT * atr, arm_p - rdir * BAR_MULT * atr
    outcome, end_i = "TIME", min(i + TIMECAP, n - 1)
    ext, ext_i = arm_p, i
    vel_arm = (c - rows[i - VELA][4]) / atr * rdir
    samples = []
    for j in range(i + 1, min(i + TIMECAP + 1, n)):
        tj, oj, hj, lj, cj = rows[j]
        if (rdir == 1 and lj <= rev_b) or (rdir == -1 and hj >= rev_b):
            outcome, end_i = "VTURN", j; break
        if (rdir == 1 and hj >= cont_b) or (rdir == -1 and lj <= cont_b):
            outcome, end_i = "CONT", j; break
        prog = (cj - arm_p) * rdir
        if prog > (ext - arm_p) * rdir: ext, ext_i = cj, j
        k = j - i
        if k in CHECKPOINTS:
            velA = (cj - rows[j - VELA][4]) / atr * rdir
            velB_ = (cj - rows[j - VELB][4]) / atr * rdir
            samples.append(dict(k=k, pos=prog / atr, velA=velA, velB=velB_,
                                decel=velA - vel_arm,
                                pull=((ext - cj) * rdir) / atr,
                                stale=(j - ext_i) / BPH,          # hours since new extreme
                                t=tj))
    episodes.append(dict(t=t, outcome=outcome, samples=samples))
    i = end_i + 1

N = len(episodes)
oc = {k: sum(1 for e in episodes if e["outcome"] == k) for k in ("VTURN", "CONT", "TIME")}
print(f"episodes: {N}  CONT {oc['CONT']}  VTURN {oc['VTURN']}  TIME {oc['TIME']}")
print(f"ANCHOR: V-turn rate (of ALL armed) = {oc['VTURN']/N*100:.1f}%  (11y M30 documented: 20.7%, CI 19.4-22.2)")

mid_t = rows[n // 2][0]
FEATURES = ["velA", "velB", "decel", "pull", "stale"]

def terciles(vals):
    s = sorted(vals); return s[len(s)//3], s[2*len(s)//3]

def spread_of(pts, f):
    vals = [p[f] for p, _ in pts]
    q1, q2 = terciles(vals)
    b = [[], [], []]
    for p, v in pts:
        b[0 if p[f] <= q1 else (1 if p[f] <= q2 else 2)].append(v)
    rates = [sum(x)/len(x) if x else float("nan") for x in b]
    return rates, [len(x) for x in b]

def perm_p(pts, f, obs_spread, iters=300):
    labels = [v for _, v in pts]
    feats = [p for p, _ in pts]
    ge = 0
    for _ in range(iters):
        random.shuffle(labels)
        rates, _ = spread_of(list(zip(feats, labels)), f)
        if max(rates) - min(rates) >= obs_spread: ge += 1
    return ge / iters

for k in CHECKPOINTS:
    pts = []
    for e in episodes:
        if e["outcome"] == "TIME": continue
        s = next((x for x in e["samples"] if x["k"] == k), None)
        if s: pts.append((s, 1 if e["outcome"] == "VTURN" else 0))
    base = sum(v for _, v in pts) / len(pts) if pts else 0
    print(f"\n== {k//BPH}h into race ==  n={len(pts)}  base P(VTURN)={base:.2f}")
    for f in FEATURES:
        rates, ns = spread_of(pts, f)
        sp = max(rates) - min(rates)
        p = perm_p(pts, f, sp) if sp >= 0.10 else None
        ptxt = f"  perm p={p:.3f}" if p is not None else ""
        print(f"  {f:5}: T1 {rates[0]:.2f} | T2 {rates[1]:.2f} | T3 {rates[2]:.2f}  (n~{ns[0]}){ptxt}")
    # position control + halves for the two headline features
    posv = [p["pos"] for p, _ in pts]
    if len(pts) >= 150:
        q1, q2 = terciles(posv)
        for lo, hi, nm in [(-9, q1, "posLOW"), (q1, q2, "posMID"), (q2, 9, "posHIGH")]:
            sub = [(p, v) for p, v in pts if lo < p["pos"] <= hi]
            if len(sub) < 45: continue
            line = f"  CTRL {nm:7} (n={len(sub)}, base {sum(v for _,v in sub)/len(sub):.2f}): "
            for f in ("velA", "pull", "stale"):
                r, _ = spread_of(sub, f)
                line += f"{f} {r[0]:.2f}/{r[1]:.2f}/{r[2]:.2f}  "
            print(line)
        for nm, sub in [("H1", [(p, v) for p, v in pts if p["t"] < mid_t]),
                        ("H2", [(p, v) for p, v in pts if p["t"] >= mid_t])]:
            line = f"  {nm} (n={len(sub)}): "
            for f in ("velA", "velB", "pull", "stale"):
                r, _ = spread_of(sub, f)
                line += f"{f} {r[0]:.2f}/{r[1]:.2f}/{r[2]:.2f}  "
            print(line)
