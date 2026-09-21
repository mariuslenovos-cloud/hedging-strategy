"""
fibc_inflight.py — IN-FLIGHT separation study for the fib C adaptive-policy thesis (2026-08-24).

QUESTION: once a ride is ARMED and running, do features observable MID-EPISODE
separate eventual V-turns (whipsaw = the ride's disaster class) from continuations
(rescue completes), BEYOND the mechanical distance-to-barrier?

Context: the pre-arm version of this test (vturn_gate, 3,185 episodes, 11y) found NO
entry-time feature separates (x0.87-1.26). This is the never-run in-flight version —
the foundation of the "adapt as price action unfolds" rework direction.

Detector = the validated proxy (vturn_freq2 spec, reimplemented):
  ARM when price has run >= 0.5 x ATR(D1,14, shifted) against a 24h (288-bar) anchor.
  Ride direction = WITH the move. Race: +0.8 ATR continuation vs -0.8 ATR reversal
  (stop-first conservative within a bar), 288-bar time cap. Event-driven (no overlap).
ANCHOR CHECK: M5 V-turn rate must land ~20-24% (documented M5 cross-check: 23.5%).

Data: analysis_data/xauusd_m5_export.csv (PEP live feed, May-2025 -> Aug-2026).
"""
import csv, math, os
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(HERE, "analysis_data", "xauusd_m5_export.csv")

ARM_MULT, BAR_MULT, LOOKBACK, TIMECAP = 0.5, 0.8, 288, 288
CHECKPOINTS = [12, 36, 72, 144]   # 1h, 3h, 6h, 12h into the race

# ---------- load ----------
rows = []
with open(CSV, newline="") as f:
    for r in csv.DictReader(f):
        rows.append((datetime.strptime(r["time"], "%Y-%m-%d %H:%M"),
                     float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])))
rows.sort()
n = len(rows)
print(f"bars: {n}  {rows[0][0]} -> {rows[-1][0]}")

# ---------- daily ATR(14), shifted one day (no lookahead) ----------
days = {}
for t, o, h, l, c in rows:
    d = t.date()
    if d not in days: days[d] = [h, l, c]
    else:
        days[d][0] = max(days[d][0], h); days[d][1] = min(days[d][1], l); days[d][2] = c
dlist = sorted(days.items())
atr_by_day, trs, prev_c = {}, [], None
for d, (h, l, c) in dlist:
    tr = h - l if prev_c is None else max(h - l, abs(h - prev_c), abs(l - prev_c))
    trs.append(tr); prev_c = c
    if len(trs) >= 14:
        atr_by_day[d] = sum(trs[-14:]) / 14.0
# ATR available to bar t = ATR of the PREVIOUS day
day_seq = [d for d, _ in dlist]
prev_day_atr = {}
for i in range(1, len(day_seq)):
    if day_seq[i - 1] in atr_by_day:
        prev_day_atr[day_seq[i]] = atr_by_day[day_seq[i - 1]]

# ---------- episode scan (event-driven) ----------
episodes = []  # dict: arm_i, dir, arm_price, atr, outcome, end_i, samples[]
i = LOOKBACK
while i < n - 1:
    t, o, h, l, c = rows[i]
    atr = prev_day_atr.get(t.date())
    if atr is None or atr <= 0:
        i += 1; continue
    anchor = rows[i - LOOKBACK][4]
    move = c - anchor
    if abs(move) < ARM_MULT * atr:
        i += 1; continue
    # ARM: ride WITH the move
    rdir = 1 if move > 0 else -1
    arm_p = c
    cont_b = arm_p + rdir * BAR_MULT * atr
    rev_b = arm_p - rdir * BAR_MULT * atr
    outcome, end_i = "TIME", min(i + TIMECAP, n - 1)
    ext = arm_p            # post-arm extreme in ride dir
    ext_i = i
    vel_arm = (c - rows[i - 12][4]) / atr * rdir if i >= 12 else 0.0
    samples = []
    for j in range(i + 1, min(i + TIMECAP + 1, n)):
        tj, oj, hj, lj, cj = rows[j]
        # stop-first conservative
        if (rdir == 1 and lj <= rev_b) or (rdir == -1 and hj >= rev_b):
            outcome, end_i = "VTURN", j; break
        if (rdir == 1 and hj >= cont_b) or (rdir == -1 and lj <= cont_b):
            outcome, end_i = "CONT", j; break
        prog = (cj - arm_p) * rdir
        if prog > (ext - arm_p) * rdir:
            ext, ext_i = cj, j
        k = j - i
        if k in CHECKPOINTS:
            vel12 = (cj - rows[j - 12][4]) / atr * rdir
            vel3 = (cj - rows[j - 3][4]) / atr * rdir
            pull = ((ext - cj) * rdir) / atr                 # pullback from post-arm extreme
            stale = (j - ext_i)                               # bars since new extreme
            rng = (max(x[2] for x in rows[i:j + 1]) - min(x[3] for x in rows[i:j + 1])) / atr
            pos = prog / atr                                  # mechanical control variable
            samples.append(dict(k=k, pos=pos, vel3=vel3, vel12=vel12,
                                decel=vel12 - vel_arm, pull=pull, stale=stale,
                                rng=rng, t=tj))
    episodes.append(dict(arm_i=i, t=t, dir=rdir, atr=atr, outcome=outcome,
                         end_i=end_i, samples=samples))
    i = end_i + 1  # event-driven: no overlap

N = len(episodes)
oc = {k: sum(1 for e in episodes if e["outcome"] == k) for k in ("VTURN", "CONT", "TIME")}
dec = oc["VTURN"] + oc["CONT"]
print(f"\nepisodes: {N}   CONT {oc['CONT']}  VTURN {oc['VTURN']}  TIME {oc['TIME']}")
print(f"ANCHOR CHECK — V-turn rate (decisive): {oc['VTURN']/dec*100:.1f}%  (documented M5: ~23.5%)")

# raw example sanity print
for e in episodes[:2]:
    print(f"  ex: arm {e['t']} dir {e['dir']} atr {e['atr']:.1f} -> {e['outcome']} after {e['end_i']-e['arm_i']} bars, {len(e['samples'])} checkpoints")

# ---------- analysis ----------
mid_t = rows[n // 2][0]

def tercile_split(vals):
    s = sorted(vals)
    return s[len(s) // 3], s[2 * len(s) // 3]

FEATURES = ["vel3", "vel12", "decel", "pull", "stale", "rng"]

def report(title, pts):
    """pts = list of (features-dict, is_vturn). Bucket each feature by tercile."""
    if len(pts) < 30:
        print(f"  {title}: n={len(pts)} too thin, skipped"); return
    base = sum(v for _, v in pts) / len(pts)
    print(f"  {title}: n={len(pts)}  base P(VTURN)={base:.2f}")
    for f in FEATURES:
        vals = [p[f] for p, _ in pts]
        q1, q2 = tercile_split(vals)
        buckets = [[], [], []]
        for p, v in pts:
            b = 0 if p[f] <= q1 else (1 if p[f] <= q2 else 2)
            buckets[b].append(v)
        rates = [sum(b) / len(b) if b else float("nan") for b in buckets]
        spread = max(rates) - min(rates)
        flag = " <== separates" if spread >= 0.15 and min(len(b) for b in buckets) >= 15 else ""
        print(f"    {f:6}: T1 {rates[0]:.2f} (n{len(buckets[0])}) | T2 {rates[1]:.2f} (n{len(buckets[1])}) | T3 {rates[2]:.2f} (n{len(buckets[2])}){flag}")

for k in CHECKPOINTS:
    # one sample per episode per checkpoint; only episodes still OPEN at k that later resolved decisively
    pts = []
    for e in episodes:
        if e["outcome"] == "TIME": continue
        s = next((x for x in e["samples"] if x["k"] == k), None)
        if s: pts.append((s, 1 if e["outcome"] == "VTURN" else 0))
    print(f"\n== checkpoint {k} bars ({k*5//60}h into race) ==")
    report("ALL", pts)
    # THE CONTROL: within position-terciles (mechanical distance held ~constant)
    if len(pts) >= 60:
        posv = [p["pos"] for p, _ in pts]
        q1, q2 = tercile_split(posv)
        for bi, (lo, hi, nm) in enumerate([(-9, q1, "pos-LOW (losing ground)"),
                                           (q1, q2, "pos-MID"), (q2, 9, "pos-HIGH (winning)")]):
            sub = [(p, v) for p, v in pts if lo < p["pos"] <= hi]
            report(f"CTRL {nm}", sub)
    # halves stability on the strongest feature candidates
    h1 = [(p, v) for p, v in pts if p["t"] < mid_t]
    h2 = [(p, v) for p, v in pts if p["t"] >= mid_t]
    print(f"  halves: n1={len(h1)} n2={len(h2)}")
    report("HALF-1", h1); report("HALF-2", h2)
