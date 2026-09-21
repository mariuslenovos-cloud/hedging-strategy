"""
fibc_policy_sim2.py — POLICY PILOT v2 (2026-08-24): FULL-BOOK proxy + velocity-conditioned RELEASE.

v1 finding: ride-leg-only economics hide release's real value (the recovering BOOK side —
the Aug-19 specimen: release marks the whole book -$233 vs floored -$1,306). v2 models the
book in Part A: book = W_BOOK units OPPOSITE the ride, entered 0.5 ATR before arm (i.e. the
drowned position whose adverse move armed the ride). Episode P&L = book + ride legs.

Pre-committed policies (release at FIRST trigger; nothing else changes):
  R1: P3-bad state            (pull>=q66 & stale>=q66) OR (pos<=0 & pull>=q66)
  R2: P3-bad AND velB<=median (bad state AND the 3h ride-side velocity has died)
  R3: velB<=q33 AND pull>=q66 (deep deceleration + well off the extreme, no stale needed)
Sensitivity: W_BOOK in {2,4,8}. Halves + worst-episode + by-outcome always reported.

PROXY BIAS NOTE (favors the BASE, biases AGAINST release): proxy CONT episodes run rides to
the full +0.8 ATR barrier, but real fib C banks at the +$40 book target (earlier/smaller);
real VTURN realizes at the -20%%-of-balance floor (often worse than the -0.8 barrier).
Both real-world effects make release MORE attractive than this proxy shows.
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
    dlist = sorted(days.items()); out, trs, prev_c = {}, [], None
    ab = {}
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
BPH, LOOKBACK, TIMECAP = 2, 48, 48
ARM_MULT, BAR_MULT = 0.5, 0.8
ADD_EVERY, MAX_LEGS = 2, 6
FIBW = [1, 1, 2, 3, 5, 8]
VELB = 6   # 3h in M30 bars

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
    legs = [dict(k=0, price=arm_p, w=FIBW[0])]
    checks = []   # per-hour state checkpoints
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
                      stale=(j - ext_i) / BPH,
                      velB=(cj - rows[j - VELB][4]) / atr * rdir)
            checks.append(st)
            if len(legs) < MAX_LEGS:
                legs.append(dict(k=k, price=cj, w=FIBW[len(legs)]))
    episodes.append(dict(t=t, dir=rdir, atr=atr, outcome=outcome, exit=exit_p,
                         arm=arm_p, legs=legs, checks=checks))
    i = end_i + 1

allst = [s for e in episodes for s in e["checks"]]
q = lambda vals, f: sorted(vals)[int(len(vals) * f)]
Q_PULL = q([s["pull"] for s in allst], 2/3)
Q_STALE = q([s["stale"] for s in allst], 2/3)
MED_VELB = q([s["velB"] for s in allst], 1/2)
Q33_VELB = q([s["velB"] for s in allst], 1/3)
noc = {k: sum(1 for e in episodes if e["outcome"] == k) for k in ("VTURN", "CONT", "TIME")}
print(f"episodes {len(episodes)} (V {noc['VTURN']} / C {noc['CONT']} / T {noc['TIME']})")
print(f"thresholds: pull q66 {Q_PULL:.3f} | stale q66 {Q_STALE:.1f}h | velB med {MED_VELB:.3f} | velB q33 {Q33_VELB:.3f}")

def trigger(s, pol):
    p3 = (s["pull"] >= Q_PULL and s["stale"] >= Q_STALE) or (s["pos"] <= 0 and s["pull"] >= Q_PULL)
    if pol == "R1": return p3
    if pol == "R2": return p3 and s["velB"] <= MED_VELB
    if pol == "R3": return s["velB"] <= Q33_VELB and s["pull"] >= Q_PULL
    raise ValueError

def episode_pnl(e, W_BOOK, upto_k=None, at_price=None):
    """book + ride legs, wATR. upto_k/at_price -> release counterfactual."""
    x = e["exit"] if at_price is None else at_price
    book_p = e["arm"] - e["dir"] * 0.5 * e["atr"]          # book entered 0.5 ATR before arm
    pnl = (x - book_p) * (-e["dir"]) * W_BOOK / e["atr"]   # book is OPPOSITE the ride
    for lg in e["legs"]:
        if upto_k is not None and lg["k"] >= upto_k and lg["k"] > 0: continue
        pnl += lg["w"] * (x - lg["price"]) * e["dir"] / e["atr"]
    return pnl

mid_t = rows[n // 2][0]
for W_BOOK in (2, 4, 8):
    print(f"\n=========== W_BOOK = {W_BOOK} (ride max weight 20) ===========")
    base_tot = 0.0
    base_out = {k: 0.0 for k in noc}
    worst_b = 0.0
    for e in episodes:
        p = episode_pnl(e, W_BOOK); base_tot += p; base_out[e["outcome"]] += p
        worst_b = min(worst_b, p)
    print(f"BASE: total {base_tot:+.0f}  V {base_out['VTURN']:+.0f} / C {base_out['CONT']:+.0f} / T {base_out['TIME']:+.0f}  worst {worst_b:+.1f}")
    for pol in ("R1", "R2", "R3"):
        tot = 0.0; out = {k: 0.0 for k in noc}; nrel = 0
        hdelta = {"H1": 0.0, "H2": 0.0}; worst_p = 0.0
        for e in episodes:
            bp = episode_pnl(e, W_BOOK)
            st = next((s for s in e["checks"] if trigger(s, pol)), None)
            if st is None:
                p = bp
            else:
                nrel += 1
                p = episode_pnl(e, W_BOOK, upto_k=st["k"], at_price=st["price"])
            tot += p; out[e["outcome"]] += p
            hdelta["H1" if e["t"] < mid_t else "H2"] += p - bp
            worst_p = min(worst_p, p)
        print(f"{pol}: total {tot:+.0f} (delta {tot-base_tot:+.0f})  fired {nrel}/{len(episodes)}  "
              f"V {out['VTURN']:+.0f} ({out['VTURN']-base_out['VTURN']:+.0f}) / "
              f"C {out['CONT']:+.0f} ({out['CONT']-base_out['CONT']:+.0f}) / "
              f"T {out['TIME']:+.0f} ({out['TIME']-base_out['TIME']:+.0f})  "
              f"halves {hdelta['H1']:+.0f}/{hdelta['H2']:+.0f}  worst {worst_p:+.1f}")

# raw sign-check: one VTURN release, one CONT release (W_BOOK=4, R2)
print("\n--- raw examples (W_BOOK=4, R2) ---")
shown = {"VTURN": 0, "CONT": 0}
for e in episodes:
    if e["outcome"] in shown and shown[e["outcome"]] == 0:
        st = next((s for s in e["checks"] if trigger(s, "R2")), None)
        if st:
            shown[e["outcome"]] = 1
            bp = episode_pnl(e, 4); rp = episode_pnl(e, 4, upto_k=st["k"], at_price=st["price"])
            print(f"{e['outcome']} armed {e['t']} dir {e['dir']} arm {e['arm']:.1f} atr {e['atr']:.0f} exit {e['exit']:.1f}")
            print(f"   trigger @k={st['k']} px {st['price']:.1f} (pos {st['pos']:+.2f} pull {st['pull']:.2f} "
                  f"stale {st['stale']:.1f}h velB {st['velB']:+.2f})")
            print(f"   base episode {bp:+.2f} -> released {rp:+.2f}  (delta {rp-bp:+.2f})")
    if all(shown.values()): break
