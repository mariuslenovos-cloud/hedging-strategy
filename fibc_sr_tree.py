#!/usr/bin/env python3
"""
fibc_sr_tree.py -- ML PROGRAM item (3): the LEARNED STATE-RELEASE TRIGGER (2026-08-29).

SR6's release rule is hand-set: (pull>=0.30 ATR & stale>=7h) OR (pos<=0 & pull>=0.30), release only
while the book is cheap (MinMark -200). The in-flight study (fibc_inflight2) showed the state DOES
separate V-turns from continuations at p=0.000. Question: does a depth-2/3 tree, fitted on the
FIRST half of the 5.25y episode set and applied to the SECOND half, produce a release policy that
beats the hand rule on the same first-order proxy? (The tester decides the rest -- the parity wall
[[python-grid-sim-parity-wall]] means this proxy only ranks policies, it does not price fib C.)

Proxy (identical to the 08-24 pilot's units): an armed ride races +0.8 ATR (CONT, pays +0.8) vs
-0.8 ATR (VTURN, pays -0.8) within 24h; a release at bar j realizes pos_j (the current excursion in
ATR). TIME outcomes realize their final pos. Policies evaluated per episode on the SAME bars:
   NEVER      hold to outcome
   HAND       SR6's rule, with the cheapness bound (release only if pos >= -CHEAP)
   TREE(theta) release when P(VTURN | state) >= theta, same cheapness bound
Reported: mean payoff/episode, V-turn losses avoided, continuations forfeited, halves stability.
Usage: python fibc_sr_tree.py [csv] [bar_minutes]
"""
import csv, os, sys, warnings
from datetime import datetime
import numpy as np
warnings.filterwarnings("ignore")
from sklearn.tree import DecisionTreeClassifier, export_text

HERE = os.path.dirname(os.path.abspath(__file__))
CSV = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "analysis_data", "xauusd_m30_export.csv")
BAR_MIN = int(sys.argv[2]) if len(sys.argv) > 2 else 30
BPH = 60 // BAR_MIN; LOOKBACK = 24 * BPH; TIMECAP = 24 * BPH
VELA, VELB = 1 * BPH, 3 * BPH
ARM_MULT, BAR_MULT = 0.5, 0.8
CHEAP = 0.35          # release only while pos >= -CHEAP ATR (the MinMark analogue; -$200 on 0.02-0.06 lots ~ 0.3-0.5 ATR)
MIN_AGE_H = 1         # never release inside the first hour (the arm bar itself)
FEATS = ["pos", "velA", "velB", "decel", "pull", "stale", "age"]

# ------------------------------------------------------------------ data + episodes (per-bar states)
rows = []
with open(CSV, newline="") as f:
    for r in csv.DictReader(f):
        rows.append((datetime.strptime(r["time"], "%Y-%m-%d %H:%M"), float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])))
rows.sort(); n = len(rows)
days = {}
for t, o, h, l, c in rows:
    d = t.date()
    if d not in days: days[d] = [h, l, c]
    else: days[d][0] = max(days[d][0], h); days[d][1] = min(days[d][1], l); days[d][2] = c
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
    rdir = 1 if move > 0 else -1; arm_p = c
    cont_b, rev_b = arm_p + rdir * BAR_MULT * atr, arm_p - rdir * BAR_MULT * atr
    outcome, end_i = "TIME", min(i + TIMECAP, n - 1)
    ext, ext_i = arm_p, i
    vel_arm = (c - rows[i - VELA][4]) / atr * rdir
    states = []; final_pos = 0.0
    for j in range(i + 1, min(i + TIMECAP + 1, n)):
        tj, oj, hj, lj, cj = rows[j]
        if (rdir == 1 and lj <= rev_b) or (rdir == -1 and hj >= rev_b): outcome, end_i = "VTURN", j; break
        if (rdir == 1 and hj >= cont_b) or (rdir == -1 and lj <= cont_b): outcome, end_i = "CONT", j; break
        prog = (cj - arm_p) * rdir
        if prog > (ext - arm_p) * rdir: ext, ext_i = cj, j
        velA = (cj - rows[j - VELA][4]) / atr * rdir; velB_ = (cj - rows[j - VELB][4]) / atr * rdir
        states.append(dict(pos=prog / atr, velA=velA, velB=velB_, decel=velA - vel_arm,
                           pull=((ext - cj) * rdir) / atr, stale=(j - ext_i) / BPH, age=(j - i) / BPH))
        final_pos = prog / atr
    pay = 0.8 if outcome == "CONT" else (-0.8 if outcome == "VTURN" else final_pos)
    episodes.append(dict(t=t, outcome=outcome, states=states, pay=pay))
    i = end_i + 1

N = len(episodes); mid_t = rows[n // 2][0]
oc = {k: sum(1 for e in episodes if e["outcome"] == k) for k in ("VTURN", "CONT", "TIME")}
print(f"bars {n} ({BAR_MIN}m) {rows[0][0]:%Y-%m-%d} -> {rows[-1][0]:%Y-%m-%d} | episodes {N}: CONT {oc['CONT']} VTURN {oc['VTURN']} TIME {oc['TIME']}"
      f" | V-turn rate {oc['VTURN']/N*100:.1f}% (anchor 20.7-27.4%)")

# ------------------------------------------------------------------ policies
def hand_rule(s):
    return ((s["pull"] >= 0.30 and s["stale"] >= 7) or (s["pos"] <= 0 and s["pull"] >= 0.30))

def run_policy(eps, decide):
    """decide(state)->bool release. Returns per-episode payoffs + counts."""
    pays, saved, forf, rel = [], 0.0, 0.0, 0
    for e in eps:
        pay = e["pay"]; done = False
        for s in e["states"]:
            if s["age"] < MIN_AGE_H: continue
            if s["pos"] < -CHEAP: continue          # not cheap -> the floor/ride handles it
            if decide(s):
                pays.append(s["pos"]); rel += 1; done = True
                if e["outcome"] == "VTURN": saved += s["pos"] - pay
                else: forf += s["pos"] - pay
                break
        if not done: pays.append(pay)
    return np.mean(pays), rel, saved, forf

train = [e for e in episodes if e["t"] < mid_t]; test = [e for e in episodes if e["t"] >= mid_t]
print(f"train {len(train)} eps | test {len(test)} eps (forward half)")

# per-bar training set: label = episode outcome VTURN (exclude TIME), one row per state bar
def rows_of(eps):
    X, y = [], []
    for e in eps:
        if e["outcome"] == "TIME": continue
        for s in e["states"]:
            if s["age"] < MIN_AGE_H: continue
            X.append([s[f] for f in FEATS]); y.append(1 if e["outcome"] == "VTURN" else 0)
    return np.array(X), np.array(y)
Xtr, ytr = rows_of(train)
print(f"train state-bars {len(ytr)} (P(VTURN) {ytr.mean():.3f})")

print(f"\n{'policy':28s}{'train pay':>10s}{'test pay':>10s}{'rel%':>7s}{'saved':>8s}{'forfeit':>9s}")
def report(name, decide):
    ptr, rtr, str_, ftr = run_policy(train, decide); pte, rte, ste, fte = run_policy(test, decide)
    print(f"{name:28s}{ptr:10.4f}{pte:10.4f}{100*rte/len(test):7.1f}{ste:8.1f}{fte:9.1f}")
    return pte
base_te = report("NEVER (hold to outcome)", lambda s: False)
hand_te = report("HAND = SR6 rule", hand_rule)

trees = {}
for depth in (2, 3):
    clf = DecisionTreeClassifier(max_depth=depth, min_samples_leaf=200, random_state=0).fit(Xtr, ytr)
    trees[depth] = clf
    for theta in (0.45, 0.55, 0.65, 0.75):
        report(f"TREE d{depth} theta {theta:.2f}", lambda s, c=clf, th=theta: c.predict_proba(np.array([[s[f] for f in FEATS]]))[0, 1] >= th)

print("\n=== depth-2 tree (train half) — the hand-codable form ===")
print(export_text(trees[2], feature_names=FEATS, decimals=2, show_weights=True))
print("=== depth-3 tree (train half) ===")
print(export_text(trees[3], feature_names=FEATS, decimals=2, show_weights=True))
print(f"\nREAD: test-half payoff per episode: NEVER {base_te:+.4f} | HAND {hand_te:+.4f}. A tree row must beat HAND on the TEST half, "
      f"with saved > forfeit, to earn the EA lever. Proxy units = ATR(D1); asymmetric fib C payoff not modelled (tester decides).")
