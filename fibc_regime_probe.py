"""
fib C — WHY Feb-5? Test the hypothesis that the blow-up entries (buys 79/80)
opened during a VOLATILITY REGIME CHANGE (structural break), not a normal trend.

Uses every (time, price) event in the ledger as samples of the gold path,
builds a rolling realised-volatility + a daily-range proxy, and tags each
ENTRY with the vol regime it opened into. If the -$1,791 basket is a clear
vol outlier vs the profitable December baskets, the structural-break filter
is the fix (block/throttle entries when vol regime-changes), not a stop.
"""
import datetime as dt
from statistics import mean, pstdev

# reuse the ledger from the sweep file
import importlib.util, os
spec = importlib.util.spec_from_file_location(
    "sweep", os.path.join(os.path.dirname(__file__), "fibc_lot_sweep.py"))
sweep = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sweep)

evs = sweep.parse()
for e in evs:
    e["t"] = dt.datetime.strptime(e["dt"], "%Y.%m.%d %H:%M")

# --- per-day range proxy (max-min price across all events that day) ---
days = {}
for e in evs:
    d = e["t"].date()
    days.setdefault(d, []).append(e["price"])
day_range = {d: (max(p) - min(p)) for d, p in days.items()}

# trailing 5-day avg range (the "current volatility regime")
sorted_days = sorted(day_range)
roll = {}
for i, d in enumerate(sorted_days):
    window = [day_range[sorted_days[j]] for j in range(max(0, i - 4), i + 1)]
    roll[d] = mean(window)

# --- rolling realised vol over the last K events (std of price changes) ---
prices = [e["price"] for e in evs]
def trailing_vol(idx, k=12):
    lo = max(1, idx - k)
    chg = [abs(prices[j] - prices[j - 1]) for j in range(lo, idx + 1)]
    return mean(chg) if chg else 0.0

print("=" * 78)
print("VOLATILITY REGIME at each ENTRY (buy)  —  is Feb-5 an outlier?")
print("=" * 78)
print(f"{'entry':>5} {'date/time':>16} {'price':>8} {'dayRange':>9} {'5dRange':>8} {'trVol12':>8}  note")
print("-" * 78)
all_dayrange, all_trvol = [], []
rows = []
for i, e in enumerate(evs):
    if e["action"] != "buy":
        continue
    d = e["t"].date()
    dr = day_range[d]
    rr = roll[d]
    tv = trailing_vol(i)
    all_dayrange.append(rr)
    all_trvol.append(tv)
    note = ""
    if e["order"] in (79, 80):
        note = "<<< BLEW UP (-$1,791 floor dump)"
    rows.append((e["order"], e["t"].strftime("%m-%d %H:%M"), e["price"], dr, rr, tv, note))

# baseline = December entries (the calm, profitable period)
dec_roll = [r[4] for r in rows if r[1].startswith("12-")]
dec_tv = [r[5] for r in rows if r[1].startswith("12-")]
base_roll = mean(dec_roll)
base_tv = mean(dec_tv)

for (o, ts, px, dr, rr, tv, note) in rows:
    mult = rr / base_roll
    flag = note
    if not flag and mult >= 3.0:
        flag = f"vol {mult:.1f}x Dec baseline"
    print(f"{o:>5} {ts:>16} {px:>8.2f} {dr:>9.1f} {rr:>8.1f} {tv:>8.2f}  {flag}")

print("-" * 78)
print(f"December baseline: 5-day range ~{base_roll:.0f} pts, trailing-vol ~{base_tv:.1f}")
feb = [r for r in rows if r[1].startswith(("02-", "01-29", "01-30"))]
if feb:
    print(f"Late-Jan/Feb regime: 5-day range ~{mean([r[4] for r in feb]):.0f} pts "
          f"= {mean([r[4] for r in feb])/base_roll:.1f}x the Dec baseline")
print()
print("If the blow-up entries sit at multiples of the Dec baseline volatility,")
print("the Fib recovery grid + fixed -30% floor were calibrated for NORMAL vol;")
print("a regime change makes one day's move exceed the grid's recovery span AND")
print("trip the floor before mean-reversion -> the grid never gets to work.")
