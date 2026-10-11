"""opec_split.py -- OPEC+ meeting proximity x oil engine P&L (2026-10-11, roadmap item 2b/2c).
Question: is there a SIZING / no-new-basket rule worth having around the eight-country OPEC+ meetings?
Buckets by calendar distance to the nearest meeting (meetings fall on Sundays -> 'post' = the following week).
Sources: tester deals of the deployed oil cell at $10k (retest_o10k_kp1.htm) + the live episode ledger (LIVE/DEON oil).
Meeting dates: 2025 confirmed from opec.org releases (May-3, May-31, Jul-5, Aug-3, Sep-7, Nov-2, Nov-30; Oct-5 per the
Sep release); 2026 confirmed Jan-4, Feb-1, Mar-1, Apr-5; May-3 .. Oct-4 ASSUMED first-Sunday cadence (grade B)."""
import os, sys, pandas as pd, numpy as np
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, os.path.join(HERE, "factory_front"))
import cell_d_allocation as CD
MEET = pd.to_datetime(["2025-11-30", "2026-01-04", "2026-02-01", "2026-03-01", "2026-04-05",     # confirmed
                       "2026-05-03", "2026-06-07", "2026-07-05", "2026-08-02", "2026-09-06", "2026-10-04"])  # assumed cadence
def bucket(ts):
    d = min(((ts.normalize() - m).days for m in MEET), key=abs)
    return "pre_1-7d" if -7 <= d <= -1 else "pre_8-14d" if -14 <= d <= -8 else "post_1-5d" if 1 <= d <= 5 else "post_6-10d" if 6 <= d <= 10 else "far"
def table(p, label):
    b = pd.Series([bucket(t) for t in p.index], index=p.index)
    g = p.groupby(b).agg(["sum", "count", "mean"]); g["per_day"] = g["sum"] / g["count"]
    print(f"\n{label}: daily P&L by proximity to the nearest OPEC+ meeting")
    print(g.round(1).to_string())
rp = r"C:\MT5 Pepperstone Runner\retest_o10k_kp1.htm"
d = CD.deals(rp); out = d[d.dir != "in"]
p = out.groupby(out.time.dt.date).net.sum(); p.index = pd.to_datetime(p.index)
table(p, "TESTER oil KP1 @ $10k, Dec-01 -> Oct-10 (realized, by CLOSE day)")
# entries: where do the baskets that LOSE get opened?
ins = d[d.dir == "in"].copy(); ins["b"] = [bucket(t) for t in ins.time]
# attribute each position's final P&L to its open day via position id is not in the parsed frame; use close-day of losing days instead
L = p[p < 0]; print(f"\nlosing CLOSE days: {len(L)} of {len(p)}, by bucket:"); print(pd.Series([bucket(t) for t in L.index]).value_counts().to_string())
print(f"worst 8 days:\n{p.nsmallest(8).round(0).to_string()}")
led = pd.read_csv(os.path.join(HERE, "analysis_data", "episode_ledger.csv"), parse_dates=["closed", "started"])
oil = led[led.stream.str.contains("oil", case=False) & led.account.isin(["LIVE", "DEON"]) & (led.closed >= "2026-09-01")]
if len(oil):
    oil = oil.assign(b_open=[bucket(t) for t in oil.started], b_close=[bucket(t) for t in oil.closed])
    print("\nLIVE+DEON oil episodes since 09-01 (ledger realized_net), by OPEN bucket:")
    print(oil.groupby("b_open").realized_net.agg(["sum", "count"]).round(1).to_string())
