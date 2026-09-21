"""
oil_staterel_pilot.py — SIDE-LEVEL STATE-RELEASE pilot for OIL SOLID (2026-08-24).

The user's ask: manage oil's floor-cut lumps (Aug-21: two shorts held 16 days -> -$514 of the
-$567 cut) the way FIBC SR6 manages fib C. The oil anatomy differs: the loss lives in STUBBORN
ORIGINAL legs while the freeze/harvest machinery banks profit AROUND them (+$938 that episode,
net +$354) — so a WHOLE-BOOK release would forfeit the harvests. The mappable version:
release only the DROWNING SIDE's legs when THAT side's state is dead AND its loss is still small.

First-order pilot (delev_sim pattern, per the user's own sim-before-build rule):
  replay the SOLID LOCKED control run (oil_solid_ctl.htm, Dec-01->Aug-19, $3,034/134tr);
  per side (buy/sell legs open simultaneously = one side-campaign), track from the side's first
  leg: favorable extreme, pull off it (xATR(D1,14)), stale hours; hourly checkpoints.
  RELEASE the side's open legs at the checkpoint close when (pre-committed cells):
    R-A  pull >= 0.5 ATR AND stale >= 48h AND side float >= -$250
    R-B  pull >= 1.0 ATR AND stale >= 72h AND side float >= -$250   (stricter)
    R-C  pull >= 0.3 ATR AND stale >= 24h AND side float >= -$250   (looser, fib-C-like)
  delta = (mark at release) - (actual realized close of those legs). >0 = saved.
  Everything else (harvests, later legs) held at actual = first-order; flagged.
KNOWN LIMITS: FIFO leg matching from the report deals; a real release changes later behavior
(freeze arming, new entries) — only the tester prices that; oil swap not modeled per-leg.
"""
import io, re, os
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
REPORT = r"C:\MT5 Pepperstone Runner\oil_solid_ctl.htm"
CONTRACT = 100.0   # $ per price unit per lot

# ---------- price data + daily ATR ----------
rows = []
with open(os.path.join(HERE, "analysis_data", "spotcrude_m5_export.csv")) as f:
    next(f)
    for ln in f:
        p = ln.strip().split(",")
        rows.append((datetime.strptime(p[0], "%Y-%m-%d %H:%M"), float(p[1]), float(p[2]), float(p[3]), float(p[4])))
rows.sort()
idx = {r[0]: k for k, r in enumerate(rows)}
def bar_at(t):
    lo, hi = 0, len(rows) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if rows[mid][0] <= t: lo = mid
        else: hi = mid - 1
    return lo
days = {}
for t, o, h, l, c in rows:
    d = t.date()
    if d not in days: days[d] = [h, l, c]
    else:
        days[d][0] = max(days[d][0], h); days[d][1] = min(days[d][1], l); days[d][2] = c
dl = sorted(days.items()); ab, trs, pc = {}, [], None
for d, (h, l, c) in dl:
    tr = h - l if pc is None else max(h - l, abs(h - pc), abs(l - pc))
    trs.append(tr); pc = c
    if len(trs) >= 14: ab[d] = sum(trs[-14:]) / 14.0
seq = [d for d, _ in dl]; patr = {}
for i in range(1, len(seq)):
    if seq[i-1] in ab: patr[seq[i]] = ab[seq[i-1]]

# ---------- parse deals ----------
raw = None
for enc in ("utf-16", "utf-8", "cp1252"):
    try: raw = io.open(REPORT, encoding=enc, errors="strict").read(); break
    except Exception: continue
text = re.sub(r"<[^>]+>", "|", raw); text = re.sub(r"(\s*\|\s*)+", "|", text)
deals = []
for m in re.finditer(r"\|(\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2})\|(\d+)\|[Ss]pot[Cc]rude\|(buy|sell)\|(in|out|in/out)\|([\d.]+)"
                     r"\|([\d. ]+)\|(\d+)\|([-\d. ]+)\|([-\d. ]+)\|([-\d. ]+)\|([-\d. ]+)\|([^|]*)\|", text):
    deals.append(dict(t=datetime.strptime(m.group(1), "%Y.%m.%d %H:%M:%S"),
                      typ=m.group(3), entry=m.group(4), vol=float(m.group(5)),
                      price=float(m.group(6).replace(" ", "")),
                      profit=float(m.group(10).replace(" ", "")) + float(m.group(9).replace(" ", "")),
                      comment=m.group(12).strip()))
print(f"deals parsed: {len(deals)}")

# FIFO leg matching: 'in' opens a leg on its side ('buy' in = long leg; 'sell' in = short leg).
# 'out' rows close the OPPOSITE-type legs (a sell-out closes long legs).
legs = []           # dict(side, vol, open_t, open_p, close_t, close_p, profit)
open_legs = {"long": [], "short": []}
for d in deals:
    if d["entry"] == "in":
        side = "long" if d["typ"] == "buy" else "short"
        leg = dict(side=side, vol=d["vol"], open_t=d["t"], open_p=d["price"],
                   close_t=None, close_p=None, profit=None, comment=d.get("comment",""))
        open_legs[side].append(leg); legs.append(leg)
    elif d["entry"] in ("out", "in/out"):
        side = "long" if d["typ"] == "sell" else "short"   # sell-out closes longs
        remain = d["vol"]
        while remain > 1e-9 and open_legs[side]:
            leg = open_legs[side][0]
            take = min(leg["vol"], remain)
            if take >= leg["vol"] - 1e-9:
                leg["close_t"] = d["t"]; leg["close_p"] = d["price"]
                sgn = 1 if side == "long" else -1
                leg["profit"] = (d["price"] - leg["open_p"]) * sgn * leg["vol"] * CONTRACT
                open_legs[side].pop(0)
            else:
                # split: close part
                closed = dict(leg); closed["vol"] = take
                closed["close_t"] = d["t"]; closed["close_p"] = d["price"]
                sgn = 1 if side == "long" else -1
                closed["profit"] = (d["price"] - leg["open_p"]) * sgn * take * CONTRACT
                legs.append(closed)
                leg["vol"] -= take
            remain -= take
closed_legs = [l for l in legs if l["close_t"] is not None]
print(f"matched legs: {len(closed_legs)}  (unclosed at test end: {len(open_legs['long'])+len(open_legs['short'])})")

# ---------- PER-LEG state-release (oil's unit: baskets are single positions) ----------
# exclude freeze/rescue legs (FRZ/B..R rescue comments) — they belong to the freeze machinery.
elig = [l for l in closed_legs if "FRZ" not in l.get("comment","").upper()]
print(f"eligible legs (non-FRZ): {len(elig)} of {len(closed_legs)}")

CELLS = {"R-A": (0.5, 48.0, -200.0), "R-B": (1.0, 72.0, -200.0), "R-C": (0.3, 24.0, -200.0)}

for name, (PULL, STALE, MINMARK) in CELLS.items():
    tot = saves = forf = 0.0; nfire = 0
    details = []
    for l in elig:
        k0 = bar_at(l["open_t"]); kend = bar_at(l["close_t"])
        if kend <= k0 + 12: continue
        sgn = 1 if l["side"] == "long" else -1
        ext, ext_k = rows[k0][4], k0
        for k in range(k0 + 12, kend, 12):
            for kk in range(ext_k + 1, k + 1):
                if (rows[kk][4] - ext) * sgn > 0: ext, ext_k = rows[kk][4], kk
            px = rows[k][4]; t = rows[k][0]
            atr = patr.get(t.date())
            if not atr: continue
            pull = (ext - px) * sgn / atr
            stale = (k - ext_k) * 5 / 60.0
            mark = (px - l["open_p"]) * sgn * l["vol"] * CONTRACT
            if pull >= PULL and stale >= STALE and mark >= MINMARK and mark < 0:
                delta = mark - l["profit"]
                tot += delta; nfire += 1
                if delta > 0: saves += delta
                else: forf += -delta
                details.append((t, l["side"], l["vol"], l["open_p"], mark, l["profit"], delta))
                break
    print(f"\n== {name}  (pull>={PULL} ATR, stale>={STALE}h, leg-mark>={MINMARK}) ==")
    print(f"  fired on {nfire}/{len(elig)} legs   TOTAL DELTA {tot:+.0f}   (saves {saves:.0f} / forfeits {forf:.0f})")
    for t, side, vol, op, mark, act, delta in sorted(details, key=lambda x: x[6])[:5]:
        print(f"    forfeit: {t:%Y-%m-%d %H:%M} {side} {vol}@{op}  rel {mark:+.0f} vs actual {act:+.0f}  delta {delta:+.0f}")
    for t, side, vol, op, mark, act, delta in sorted(details, key=lambda x: -x[6])[:5]:
        print(f"    save   : {t:%Y-%m-%d %H:%M} {side} {vol}@{op}  rel {mark:+.0f} vs actual {act:+.0f}  delta {delta:+.0f}")
