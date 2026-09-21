"""
oil_freeze_harvest_pilot.py -- FREEZE-HEDGE HARVEST pilot for OIL SOLID (2026-09-18).

USER'S ASK (live book pinned at -131.56 since 09-16): "when the hedge is in a significant
positive position it should cash in the profits, then determine if it needs to hedge again
if price moves further against the losing side, or wait if the losing side recovers."

WHAT IS ACTUALLY BEING PROPOSED: a different RELEASE TRIGGER for the freeze hedge.
The deployed rule is FreezeReleaseATR=1.5 (release on a 1.5xATR(D1) bounce off the adverse
extreme). THE PIN ALGEBRA: while frozen, book = L*(H-E)*contract -- a function of the HEDGE
PRICE H only, never of current price. So "banking the hedge profit" changes nothing at the
instant it happens; it converts the pin into a naked position from the release price, and a
later re-freeze at H2 moves the pin by L*(H2-H1)*contract. Every harvest cycle therefore costs
exactly the naked distance travelled + one spread. This pilot prices that.

FIRST-ORDER MODEL (delev_sim / oil_staterel_pilot pattern, per the sim-before-build rule):
  replay the SOLID LOCKED control run's real freeze episodes on M5 bars; hold everything else
  (the drowning legs, harvests, entries) at ACTUAL; re-price ONLY the hedge leg's exit, WITH the
  re-freeze ratchet the EA already implements (g_freezeAnchor: re-freeze only beyond the last
  adverse extreme). Score by total hedge contribution at a COMMON horizon (the actual release
  time) -- the drowning legs mark identically under every rule, so they cancel exactly.
KNOWN LIMITS (stated with the numbers, not after): first-order -- an earlier release unblocks new
entries (line 766 returns while frozen), which only the tester prices; FIFO leg matching; oil
swap not modelled per leg; rules still frozen at the horizon are marked to market there.
"""
import io, re, os
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
REPORT = r"C:\MT5 Pepperstone Runner\oil_solid_ctl.htm"
CONTRACT = 100.0
SPREAD = 0.028      # live SpotCrude spread in PRICE units (28 pts x point 0.001) -- measured 2026-09-18
DEEP_PCT = 5.0       # RescueOnDrawdownPct (SOLID lock)
MIN_PEAK_ATR = 0.25  # a peak-trail only arms once the hedge has made this much (anti-noise)

# ---------- price data + prior-day ATR(14) ----------
rows = []
with open(os.path.join(HERE, "analysis_data", "spotcrude_m5_export.csv")) as f:
    next(f)
    for ln in f:
        p = ln.strip().split(",")
        rows.append((datetime.strptime(p[0], "%Y-%m-%d %H:%M"),
                     float(p[1]), float(p[2]), float(p[3]), float(p[4])))
rows.sort()
days = {}
for t, o, h, l, c in rows:
    d = t.date()
    if d not in days:
        days[d] = [h, l, c]
    else:
        days[d][0] = max(days[d][0], h)
        days[d][1] = min(days[d][1], l)
        days[d][2] = c
dl = sorted(days.items())
ab, trs, pc = {}, [], None
for d, (h, l, c) in dl:
    tr = h - l if pc is None else max(h - l, abs(h - pc), abs(l - pc))
    trs.append(tr)
    pc = c
    if len(trs) >= 14:
        ab[d] = sum(trs[-14:]) / 14.0
seq = [d for d, _ in dl]
patr = {}
for i in range(1, len(seq)):
    if seq[i - 1] in ab:
        patr[seq[i]] = ab[seq[i - 1]]


def atr_on(t):
    d = t.date()
    for _ in range(40):
        if d in patr:
            return patr[d]
        d = d - timedelta(days=1)
    return 2.5


def bar_idx(t):
    lo, hi = 0, len(rows) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if rows[mid][0] <= t:
            lo = mid
        else:
            hi = mid - 1
    return lo


# ---------- parse deals ----------
raw = None
for enc in ("utf-16", "utf-8", "cp1252"):
    try:
        raw = io.open(REPORT, encoding=enc, errors="strict").read()
        break
    except Exception:
        continue
text = re.sub(r"<[^>]+>", "|", raw)
text = re.sub(r"(\s*\|\s*)+", "|", text)
deals = []
pat = (r"\|(\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2})\|(\d+)\|[Ss]pot[Cc]rude\|(buy|sell)\|(in|out|in/out)"
       r"\|([\d.]+)\|([\d. ]+)\|(\d+)\|([-\d. ]+)\|([-\d. ]+)\|([-\d. ]+)\|([-\d. ]+)\|([^|]*)\|")
for m in re.finditer(pat, text):
    f = lambda s: float(s.replace(" ", ""))
    deals.append(dict(t=datetime.strptime(m.group(1), "%Y.%m.%d %H:%M:%S"),
                      dir=m.group(3), io=m.group(4), vol=f(m.group(5)), px=f(m.group(6)),
                      profit=f(m.group(10)), bal=f(m.group(11)), cmt=m.group(12).strip()))
deals.sort(key=lambda d: d["t"])
n_frz = sum(1 for d in deals if "_FRZ" in d["cmt"] and d["io"] == "in")
print("parsed %d deals   FRZ opens=%d" % (len(deals), n_frz))

# ---------- capture freeze episodes ----------
# NOTE: MT5 'out' deals do NOT carry the position's _FRZ comment (they get the closing order's).
# The release is therefore matched by OPPOSITE DIRECTION + EXACT VOLUME of the _FRZ leg (the EA
# closes the freeze legs with a single PositionClose); if no exact-volume match exists the leg was
# taken out by CloseEverything -> fall back to the first subsequent out deal on that side.
open_legs = []
episodes = []
for i, d in enumerate(deals):
    if d["io"] == "in":
        open_legs.append(dict(dir=d["dir"], vol=d["vol"], px=d["px"], frz=("_FRZ" in d["cmt"])))
        if "_FRZ" in d["cmt"]:
            lose = "buy" if d["dir"] == "sell" else "sell"
            legs = [(l["vol"], l["px"]) for l in open_legs if l["dir"] == lose and not l["frz"]]
            closer = "buy" if d["dir"] == "sell" else "sell"
            out = None
            for e2 in deals[i + 1:]:
                if e2["io"] == "out" and e2["dir"] == closer and abs(e2["vol"] - d["vol"]) < 1e-9:
                    out = (e2["t"], e2["px"], "exact"); break
            if out is None:
                for e2 in deals[i + 1:]:
                    if e2["io"] == "out" and e2["dir"] == closer:
                        out = (e2["t"], e2["px"], "fallback"); break
            if legs and out:
                episodes.append(dict(t0=d["t"], hdir=d["dir"], hvol=d["vol"], H=d["px"],
                                     bal=d["bal"] if d["bal"] > 0 else 3000.0,
                                     legs=legs, out=out, how=out[2]))
    else:
        need = d["vol"]
        opp = "buy" if d["dir"] == "sell" else "sell"
        for l in list(open_legs):
            if need <= 1e-9:
                break
            if l["dir"] != opp:
                continue
            take = min(need, l["vol"]); l["vol"] -= take; need -= take
            if l["vol"] <= 1e-9:
                open_legs.remove(l)
print("freeze episodes matched: %d (exact-volume %d / fallback %d)"
      % (len(episodes), sum(1 for e in episodes if e["how"] == "exact"),
         sum(1 for e in episodes if e["how"] == "fallback")))
print("")

# ---------- the replay ----------
def run(ep, rule):
    """Total hedge-side $ from the FRZ open to the episode's common horizon, incl. re-freeze ratchet."""
    sgn = -1.0 if ep["hdir"] == "sell" else 1.0       # hedge P&L = sgn*(P-H)*lots*contract
    down = (ep["hdir"] == "sell")                      # frozen LONGS -> adverse = price falling
    lots = ep["hvol"]
    legs = ep["legs"]
    i0, i1 = bar_idx(ep["t0"]), bar_idx(ep["out"][0])
    atr = atr_on(ep["t0"])
    half_spread_cost = SPREAD * lots * CONTRACT / 2.0
    H = ep["H"]; extreme = H; peak = 0.0; anchor = None
    realized = 0.0; cycles = 0; frozen = True
    for k in range(i0, i1 + 1):
        t, o, hi, lo, c = rows[k]
        if frozen:
            extreme = min(extreme, lo) if down else max(extreme, hi)
            hp_ext = sgn * (extreme - H) * lots * CONTRACT
            peak = max(peak, hp_ext)
            hp_now = sgn * (c - H) * lots * CONTRACT
            rel, rp = False, c
            if rule[0] == "atr":
                trig = extreme + rule[1] * atr if down else extreme - rule[1] * atr
                if (c >= trig) if down else (c <= trig):
                    rel, rp = True, trig
            elif rule[0] == "trail":
                if peak >= MIN_PEAK_ATR * atr * lots * CONTRACT and hp_now <= peak * (1.0 - rule[1]):
                    rel, rp = True, c
            elif rule[0] == "thresh":
                if hp_ext >= rule[1] * atr * lots * CONTRACT:
                    rel = True
                    rp = H - rule[1] * atr if down else H + rule[1] * atr
            if rel:
                realized += sgn * (rp - H) * lots * CONTRACT - half_spread_cost
                anchor = extreme
                frozen = False
                cycles += 1
        else:
            newext = (lo < anchor) if down else (hi > anchor)
            if newext:
                p2 = lo if down else hi
                bookf = sum(((p2 - e) if down else (e - p2)) * v * CONTRACT for v, e in legs)
                if bookf <= -DEEP_PCT / 100.0 * ep["bal"]:
                    H = p2; extreme = p2; peak = 0.0; frozen = True
                    realized -= half_spread_cost
                else:
                    anchor = p2
    mark = sgn * (rows[i1][4] - H) * lots * CONTRACT if frozen else 0.0
    return realized + mark, cycles


RULES = [("ACTUAL  deployed: release on 1.5xATR bounce", ("atr", 1.5)),
         ("A1.0    release on 1.0xATR bounce",            ("atr", 1.0)),
         ("A0.5    release on 0.5xATR bounce",            ("atr", 0.5)),
         ("A0.25   release on 0.25xATR bounce",           ("atr", 0.25)),
         ("T60     hedge peak-trail, give back 60%",      ("trail", 0.60)),
         ("T40     hedge peak-trail, give back 40%",      ("trail", 0.40)),
         ("T25     hedge peak-trail, give back 25%",      ("trail", 0.25)),
         ("P0.5    USER LITERAL: bank at +0.5xATR profit (no turn)", ("thresh", 0.5)),
         ("P1.0    USER LITERAL: bank at +1.0xATR profit (no turn)", ("thresh", 1.0))]

base = None
print("%-58s %10s %11s %7s %10s" % ("rule", "total $", "vs actual", "cycles", "worst ep"))
print("-" * 100)
for name, rule in RULES:
    per, cyc = [], 0
    for ep in episodes:
        v, c = run(ep, rule)
        per.append(v)
        cyc += c
    tot = sum(per)
    if base is None:
        base = dict(tot=tot, per=per[:])
    delta = tot - base["tot"]
    worst = min(p - b for p, b in zip(per, base["per"]))
    print("%-58s %10.2f %+11.2f %7d %+10.2f" % (name, tot, delta, cyc, worst))

act = sum((-1.0 if e["hdir"] == "sell" else 1.0) * (e["out"][1] - e["H"]) * e["hvol"] * CONTRACT
          for e in episodes)
print("\nCONTROL CELL: real hedge P&L in the report = %+.2f ; replay of the deployed rule = %+.2f  (gap %+.2f)"
      % (act, base["tot"], base["tot"] - act))
print("episodes=%d   spread charged per half-cycle = $%.2f/lot" % (len(episodes), SPREAD * CONTRACT / 2))
