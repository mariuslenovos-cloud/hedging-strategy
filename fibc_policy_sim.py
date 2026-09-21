"""
fibc_policy_sim.py — POLICY PILOT SIM for the fib C adaptive rework (2026-08-24).

Counterfactuals TWO state-conditional action families (delev_sim pattern: first-order,
leg-level, signs verified on raw examples):
  SKIP family — refuse ride ADDS in bad in-flight states (leg 1 = arming hedge, never skipped)
    P1: pull >= q66 AND stale >= q66      (well off the post-arm extreme AND stale)
    P2: pos <= 0 AND pull >= q66          (ride under water AND well off extreme)
    P3: P1 OR P2
  RELEASE family — Rk: at the FIRST bad-state moment (P3 true), realize everything at market
    instead of riding to the episode's end.
Policies pre-committed before results. Thresholds = quantiles of Part A's add-state
distribution; Part B reuses them (no fitting on specimens).

PART A — scale: 5.25y PEP M30 proxy (1,454 episodes; stylized hourly adds, fib weights,
  exit at episode end barrier). Ride-leg economics only (no book side) — ORDERING evidence.
PART B — specimens: the demo twin's 3 REAL ride episodes with exact legs/times/P&L:
  EP1 Aug-4/5 rescue +$37.45 · EP2 Aug-5/7 rescue +$129.18 (contains bad-state adds that
  EARNED = the forfeit trap) · EP3 Aug-18/19 floor -$1,306.62 (the disaster to shrink).
  Release marks the WHOLE book (drowned legs + ride legs) at the trigger moment.

KNOWN LIMITS: first-order (skipped legs / early release would shift real exits and
book-target timing — only the tester prices that); Part A exits are proxy barriers.
"""
import csv, os
from datetime import datetime, timedelta

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
    dlist = sorted(days.items()); atr_by_day, trs, prev_c = {}, [], None
    for d, (h, l, c) in dlist:
        tr = h - l if prev_c is None else max(h - l, abs(h - prev_c), abs(l - prev_c))
        trs.append(tr); prev_c = c
        if len(trs) >= 14: atr_by_day[d] = sum(trs[-14:]) / 14.0
    seq = [d for d, _ in dlist]; out = {}
    for i in range(1, len(seq)):
        if seq[i - 1] in atr_by_day: out[seq[i]] = atr_by_day[seq[i - 1]]
    return out

# ================= PART A =================
rows = load(os.path.join(HERE, "analysis_data", "xauusd_m30_export.csv"))
patr = daily_atr(rows); n = len(rows)
BPH, LOOKBACK, TIMECAP = 2, 48, 48
ARM_MULT, BAR_MULT = 0.5, 0.8
ADD_EVERY, MAX_LEGS = 2, 6
FIBW = [1, 1, 2, 3, 5, 8]

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
    cont_b, rev_b = arm_p + rdir * BAR_MULT * atr, arm_p - rdir * BAR_MULT * atr
    outcome, end_i, exit_p = "TIME", min(i + TIMECAP, n - 1), rows[min(i + TIMECAP, n - 1)][4]
    ext, ext_i = arm_p, i
    adds = [dict(k=0, price=arm_p, pos=0.0, pull=0.0, stale=0.0, w=FIBW[0])]
    for j in range(i + 1, min(i + TIMECAP + 1, n)):
        tj, oj, hj, lj, cj = rows[j]
        if (rdir == 1 and lj <= rev_b) or (rdir == -1 and hj >= rev_b):
            outcome, end_i, exit_p = "VTURN", j, rev_b; break
        if (rdir == 1 and hj >= cont_b) or (rdir == -1 and lj <= cont_b):
            outcome, end_i, exit_p = "CONT", j, cont_b; break
        prog = (cj - arm_p) * rdir
        if prog > (ext - arm_p) * rdir: ext, ext_i = cj, j
        k = j - i
        if k % ADD_EVERY == 0:
            st = dict(k=k, price=cj, pos=prog / atr, pull=((ext - cj) * rdir) / atr,
                      stale=(j - ext_i) / BPH)
            if len(adds) < MAX_LEGS:
                st["w"] = FIBW[len(adds)]; adds.append(st)
            else:
                st["w"] = 0; adds.append(st)   # state checkpoint only (for release trigger)
    episodes.append(dict(t=t, dir=rdir, atr=atr, outcome=outcome, adds=adds, exit=exit_p))
    i = end_i + 1

states = [a for e in episodes for a in e["adds"][1:]]
pulls = sorted(a["pull"] for a in states); stales = sorted(a["stale"] for a in states)
Q_PULL = pulls[2 * len(pulls) // 3]; Q_STALE = stales[2 * len(stales) // 3]
noc = {k: sum(1 for e in episodes if e["outcome"] == k) for k in ("VTURN", "CONT", "TIME")}
print(f"PART A — episodes {len(episodes)} (V {noc['VTURN']} / C {noc['CONT']} / T {noc['TIME']}), add-states {len(states)}")
print(f"pre-committed thresholds: pull q66 = {Q_PULL:.3f} ATR, stale q66 = {Q_STALE:.2f} h")

def bad(a, pol):
    p1 = a["pull"] >= Q_PULL and a["stale"] >= Q_STALE
    p2 = a["pos"] <= 0 and a["pull"] >= Q_PULL
    return {"P1": p1, "P2": p2, "P3": p1 or p2}[pol]

def leg_pnl(e, a, exit_p=None):
    x = e["exit"] if exit_p is None else exit_p
    return a["w"] * (x - a["price"]) * e["dir"] / e["atr"]

mid_t = rows[n // 2][0]

# --- SKIP family ---
for pol in ("P1", "P2", "P3"):
    tot_b = tot_p = saves = forf = 0.0; nskip = nadds = 0
    by_out = {k: [0.0, 0.0] for k in ("VTURN", "CONT", "TIME")}
    hdelta = {"H1": 0.0, "H2": 0.0}; worst_b = worst_p = 0.0
    for e in episodes:
        eb = ep = 0.0
        for idx, a in enumerate(e["adds"]):
            if a["w"] == 0: continue
            pnl = leg_pnl(e, a); eb += pnl
            if idx > 0: nadds += 1
            if idx > 0 and bad(a, pol):
                nskip += 1
                if pnl < 0: saves += -pnl
                else: forf += pnl
            else:
                ep += pnl
        tot_b += eb; tot_p += ep
        by_out[e["outcome"]][0] += eb; by_out[e["outcome"]][1] += ep
        hdelta["H1" if e["t"] < mid_t else "H2"] += ep - eb
        worst_b = min(worst_b, eb); worst_p = min(worst_p, ep)
    print(f"\nSKIP {pol}: skipped {nskip}/{nadds} adds ({nskip/max(nadds,1)*100:.0f}%)")
    print(f"  ride P&L (wATR): base {tot_b:+.0f} -> {tot_p:+.0f}  (delta {tot_p-tot_b:+.0f} = saves {saves:.0f} - forfeits {forf:.0f})")
    for k in ("VTURN", "CONT", "TIME"):
        b, p = by_out[k]
        print(f"    {k:5}: {b:+8.0f} -> {p:+8.0f}  (delta {p-b:+.0f})")
    print(f"  halves delta: H1 {hdelta['H1']:+.0f} | H2 {hdelta['H2']:+.0f}   worst episode: {worst_b:+.1f} -> {worst_p:+.1f}")

# --- RELEASE family (ride legs realized at first bad-state moment) ---
tot_b = tot_p = 0.0
by_out = {k: [0.0, 0.0] for k in ("VTURN", "CONT", "TIME")}
hdelta = {"H1": 0.0, "H2": 0.0}; worst_b = worst_p = 0.0; nrel = 0
for e in episodes:
    eb = sum(leg_pnl(e, a) for a in e["adds"] if a["w"] > 0)
    rel_k = next((a["k"] for a in e["adds"][1:] if bad(a, "P3")), None)
    if rel_k is None:
        ep = eb
    else:
        nrel += 1
        rel_price = next(a["price"] for a in e["adds"] if a["k"] == rel_k)
        ep = sum(leg_pnl(e, a, rel_price) for a in e["adds"] if a["w"] > 0 and a["k"] < rel_k)
    tot_b += eb; tot_p += ep
    by_out[e["outcome"]][0] += eb; by_out[e["outcome"]][1] += ep
    hdelta["H1" if e["t"] < mid_t else "H2"] += ep - eb
    worst_b = min(worst_b, eb); worst_p = min(worst_p, ep)
print(f"\nRELEASE R(P3): fired in {nrel}/{len(episodes)} episodes")
print(f"  ride P&L (wATR): base {tot_b:+.0f} -> {tot_p:+.0f}  (delta {tot_p-tot_b:+.0f})")
for k in ("VTURN", "CONT", "TIME"):
    b, p = by_out[k]
    print(f"    {k:5}: {b:+8.0f} -> {p:+8.0f}  (delta {p-b:+.0f})")
print(f"  halves delta: H1 {hdelta['H1']:+.0f} | H2 {hdelta['H2']:+.0f}   worst episode: {worst_b:+.1f} -> {worst_p:+.1f}")

# raw sign-check examples
print("\n--- raw examples (sign check) ---")
shown = {"VTURN": 0, "CONT": 0}
for e in episodes:
    if e["outcome"] in shown and shown[e["outcome"]] == 0:
        if any(a["w"] > 0 and bad(a, "P3") for a in e["adds"][1:]):
            shown[e["outcome"]] = 1
            print(f"{e['outcome']} armed {e['t']} dir {e['dir']} arm {e['adds'][0]['price']:.1f} exit {e['exit']:.1f} atr {e['atr']:.0f}")
            for a in e["adds"][1:]:
                if a["w"] == 0: continue
                print(f"   add@{a['price']:.1f} w{a['w']} pos {a['pos']:+.2f} pull {a['pull']:.2f} stale {a['stale']:.1f}h "
                      f"pnl {leg_pnl(e,a):+.2f} {'SKIP' if bad(a,'P3') else 'keep'}")
    if all(shown.values()): break

# ================= PART B — demo specimen replay =================
print("\n================= PART B — demo specimen replay (real $, real legs) =================")
m5 = load(os.path.join(HERE, "analysis_data", "xauusd_m5_export.csv"))
m5atr = daily_atr(m5)

def m5_at(t):
    lo, hi = 0, len(m5) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if m5[mid][0] <= t: lo = mid
        else: hi = mid - 1
    return lo

# each specimen: name, ride_dir, book legs [(price, lots, dir)], ride legs [(time, price, lots, actual_pnl$)], actual_net
SPECS = [
    dict(name="EP1 Aug-4/5 rescue  (actual net +$37.45)", rdir=+1,
         book=[(4064.25, 0.03, -1), (4076.66, 0.03, -1)],
         ride=[("2026-08-05 03:30", 4079.79, 0.03, +250.89),
               ("2026-08-05 05:25", 4076.86, 0.04, +346.48)],
         net=+37.45, end="2026-08-05 10:48"),
    dict(name="EP2 Aug-5/7 rescue  (actual net +$129.18)", rdir=+1,
         book=[(4183.57, 0.03, -1)],
         ride=[("2026-08-05 22:30", 4244.80, 0.03, +59.73),
               ("2026-08-06 04:05", 4252.89, 0.03, +35.46),
               ("2026-08-06 10:40", 4262.09, 0.03, +7.86),
               ("2026-08-06 12:20", 4264.32, 0.03, +1.17),
               ("2026-08-06 17:35", 4268.17, 0.03, -10.41),
               ("2026-08-06 18:45", 4270.02, 0.03, -15.96),
               ("2026-08-06 22:20", 4241.63, 0.03, +69.78),
               ("2026-08-07 00:05", 4248.46, 0.03, +49.80),
               ("2026-08-07 00:55", 4247.39, 0.03, +52.41),
               ("2026-08-07 03:50", 4242.03, 0.03, +68.34),
               ("2026-08-07 06:40", 4246.60, 0.03, +54.63)],
         net=+129.18, end="2026-08-07 08:58"),
    dict(name="EP3 Aug-18/19 FLOOR (actual net -$1,306.62)", rdir=-1,
         book=[(4416.49, 0.04, +1), (4395.04, 0.04, +1)],
         ride=[("2026-08-18 19:40", 4383.13, 0.04, -323.96),
               ("2026-08-18 22:20", 4364.48, 0.06, -599.10),
               ("2026-08-19 08:20", 4352.69, 0.04, -446.68),
               ("2026-08-19 16:45", 4363.52, 0.04, -403.88)],
         net=-1306.62, end="2026-08-19 18:17"),
]

for S in SPECS:
    t0 = datetime.strptime(S["ride"][0][0], "%Y-%m-%d %H:%M")
    tend = datetime.strptime(S["end"], "%Y-%m-%d %H:%M")
    k0 = m5_at(t0); p0 = S["ride"][0][1]; rdir = S["rdir"]
    atr = m5atr[t0.date()]
    print(f"\n{S['name']}   ride={'BUYS' if rdir==1 else 'SELLS'}  ATR(D1)={atr:.1f}")
    delta = {"P1": 0.0, "P2": 0.0, "P3": 0.0}
    ext, ext_k = p0, k0
    legs_states = []
    for li, (ts, price, lots, pnl) in enumerate(S["ride"]):
        t = datetime.strptime(ts, "%Y-%m-%d %H:%M"); k = m5_at(t)
        for kk in range(ext_k + 1, k + 1):
            if (m5[kk][4] - ext) * rdir > 0: ext, ext_k = m5[kk][4], kk
        c = m5[k][4]
        pos = (c - p0) * rdir / atr; pull = (ext - c) * rdir / atr
        stale = (k - ext_k) * 5 / 60.0
        p1 = pull >= Q_PULL and stale >= Q_STALE
        p2 = pos <= 0 and pull >= Q_PULL
        dec = {"P1": p1 and li > 0, "P2": p2 and li > 0, "P3": (p1 or p2) and li > 0}
        for pol in delta:
            if dec[pol]: delta[pol] -= pnl
        legs_states.append((t, dec))
        tag = "+".join(p for p in ("P1", "P2", "P3") if dec[p]) or "keep"
        print(f"   leg{li+1} {ts} @{price:<8} {lots}  pos {pos:+.2f}  pull {pull:.2f}  stale {stale:4.1f}h  pnl {pnl:+8.2f}  [{tag}]")
    for pol in ("P1", "P2", "P3"):
        print(f"   SKIP {pol}: net {S['net']:+8.2f} -> {S['net']+delta[pol]:+8.2f}  (delta {delta[pol]:+.2f})")
    # RELEASE: scan M5 states every bar from arm to end; first P3-bad moment -> mark whole book
    kend = m5_at(tend)
    ext, ext_k = p0, k0
    rel = None
    for kk in range(k0 + 1, kend):
        c = m5[kk][4]
        if (c - ext) * rdir > 0: ext, ext_k = c, kk
        pos = (c - p0) * rdir / atr; pull = (ext - c) * rdir / atr
        stale = (kk - ext_k) * 5 / 60.0
        if (pull >= Q_PULL and stale >= Q_STALE) or (pos <= 0 and pull >= Q_PULL):
            rel = kk; break
    if rel is None:
        print("   RELEASE: never triggered -> unchanged")
    else:
        c = m5[rel][4]; trel = m5[rel][0]
        mtm = 0.0
        for price, lots, d in S["book"]:
            mtm += (c - price) * d * lots * 100
        for li, (ts, price, lots, pnl) in enumerate(S["ride"]):
            if datetime.strptime(ts, "%Y-%m-%d %H:%M") <= trel:
                mtm += (c - price) * rdir * lots * 100
        print(f"   RELEASE @ {trel} px {c:.2f}: whole-book mark {mtm:+.2f}  vs actual {S['net']:+.2f}  (delta {mtm-S['net']:+.2f})")
