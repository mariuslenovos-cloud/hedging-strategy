#!/usr/bin/env python3
"""
Landmine autopsy of the fib C SAFE MT4 ledger.
Q: do the trades that detonated (big losing closes) share a KNOWABLE-at-entry
signature -- specifically, was gold OVER-EXTENDED from its mean when the losing
leg was opened? If yes -> an entry filter can defuse the mine before it's planted.

Self-consistent: builds the daily price path from the broker's OWN ledger prices
(no external feed mismatch). Extension = (price - SMA20) / ATR20 of daily closes,
signed (+ = stretched above mean, - = stretched below).
"""
import numpy as np, pandas as pd

rows=[]
for ln in open("fibc_safe_ledger.txt"):
    p=ln.split()
    if len(p)<11: continue
    idx=int(p[0]); date=p[1]; tm=p[2]; typ=p[3]; ordn=int(p[4])
    lots=float(p[5]); price=float(p[6]); profit=float(p[9]); bal=float(p[10])
    rows.append(dict(idx=idx,dt=f"{date} {tm}",date=date,typ=typ,ordn=ordn,
                     lots=lots,price=price,profit=profit,bal=bal))
df=pd.DataFrame(rows)
df["ts"]=pd.to_datetime(df["dt"],format="%Y.%m.%d %H:%M")

# ---- daily close proxy from ledger prices (last trade price each day) ----
day=df.groupby("date").agg(close=("price","last")).reset_index()
day["close"]=day["close"].astype(float)
day["sma20"]=day["close"].rolling(20,min_periods=8).mean()
day["chg"]=day["close"].diff().abs()
day["atr20"]=day["chg"].rolling(20,min_periods=8).mean()
day["ext"]=(day["close"]-day["sma20"])/day["atr20"]      # signed extension in ATRs
ext_by_date=dict(zip(day["date"],day["ext"]))

# ---- map order# -> its OPEN row (entry context) ----
opens={}
for _,r in df.iterrows():
    if r["typ"] in ("buy","sell") and r["profit"]==0.0:
        opens[r["ordn"]]=r

def ext_at(date):  # extension on the entry's day (known at entry)
    return ext_by_date.get(date,np.nan)

# ---- every losing CLOSE >$100, traced back to its entry extension ----
print("="*84)
print("BIG LOSING CLOSES traced to the EXTENSION at the losing leg's ENTRY")
print("="*84)
print(f"{'closed':>16}{'ord':>5}{'dir':>5}{'entry$':>9}{'exit$':>9}{'loss$':>10}{'ext@entry':>11}")
losers=[]
for _,r in df.iterrows():
    if r["typ"]=="close" and r["profit"]<-100:
        o=opens.get(r["ordn"])
        if o is None: continue
        e=ext_at(o["date"])
        losers.append(e)
        print(f"{str(r['ts']):>16}{r['ordn']:>5}{o['typ']:>5}{o['price']:>9.0f}"
              f"{r['price']:>9.0f}{r['profit']:>10.0f}{e:>11.2f}")

# ---- distribution of extension across ALL opens (the baseline) ----
all_ext=[ext_at(o["date"]) for o in opens.values()]
all_ext=np.array([x for x in all_ext if not np.isnan(x)])
print("\n"+"="*84)
print("EXTENSION DISTRIBUTION across ALL basket-leg entries (the population)")
print("="*84)
for q in [5,25,50,75,90,95]:
    print(f"  {q:>3}th pctile: {np.percentile(all_ext,q):+.2f} ATR")
print(f"  |ext| mean over all opens: {np.abs(all_ext).mean():.2f} ATR")

los=np.array([x for x in losers if not np.isnan(x)])
print(f"\nLosing legs: |ext| mean = {np.abs(los).mean():.2f} ATR  vs all-opens {np.abs(all_ext).mean():.2f}")
# what % of all opens would an |ext|>=T filter block, and how many losers does it catch?
print("\nIf we BLOCK new entries when |ext| >= T (stretched too far from mean):")
print(f"{'T(ATR)':>7}{'%all-opens blocked':>20}{'losers caught':>15}")
for T in [1.5,2.0,2.5,3.0]:
    blocked=(np.abs(all_ext)>=T).mean()
    caught=(np.abs(los)>=T).mean()
    print(f"{T:>7.1f}{blocked:>19.0%}{caught:>15.0%}")
