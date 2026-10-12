"""cot_iv_test.py -- the event-day class's last free pre-registered test (2026-10-12, research registry item cot_iv).
QUESTION (written before the run): does positioning crowding x implied-vol state, both known at a week's close, predict the
SIZE of the next 5 trading days' move in gold / crude -- i.e. could it have warned before an event day?
  crowding  = speculative (non-commercial) net long as % of open interest, percentile vs the trailing 156 weeks (3y)
  IV state  = GVZ (gold) / OVX (crude) close, percentile vs the trailing 252 days
  outcome   = |log return| over the next 5 trading days, and P(|5d move| > 2 x trailing 20d daily sd x sqrt5) = 'event week'
PRE-COMMITTED BAR: the top cell (crowding >= p80 AND IV >= p80) must show a median |5d move| >= 1.5x the unconditional median
AND an event-week rate >= 2x the base rate, in BOTH halves of the sample, with n >= 30 per half. Anything less = no early warning.
Also reported (not part of the bar): the signed next-5d return by crowding quintile (the 'crowded longs reverse' claim).
Data: CFTC legacy futures-only deacot<year>.zip (gold 088691, crude WTI 067651) + Yahoo GC=F, CL=F, ^GVZ, ^OVX daily."""
import io, os, sys, json, zipfile, glob
import numpy as np, pandas as pd
SRC = sys.argv[1]
def yahoo(n):
    r = json.load(open(os.path.join(SRC, n + ".json")))["chart"]["result"][0]
    s = pd.Series(r["indicators"]["quote"][0]["close"], index=pd.to_datetime(r["timestamp"], unit="s").normalize()).dropna()
    return s[~s.index.duplicated(keep="last")]
cot = []
for z in sorted(glob.glob(os.path.join(SRC, "deacot*.zip"))):
    with zipfile.ZipFile(z) as zf:
        df = pd.read_csv(zf.open(zf.namelist()[0]), low_memory=False)
    df.columns = [c.strip() for c in df.columns]
    cot.append(df)
cot = pd.concat(cot)
code = "CFTC Contract Market Code" if "CFTC Contract Market Code" in cot.columns else [c for c in cot.columns if "Contract_Market_Code" in c or "Market Code" in c][0]
datec = [c for c in cot.columns if "As of Date in Form YYYY-MM-DD" in c or c == "As of Date in Form YYYY-MM-DD"][0]
L = [c for c in cot.columns if c.startswith("Noncommercial Positions-Long")][0]; S_ = [c for c in cot.columns if c.startswith("Noncommercial Positions-Short")][0]
OI = [c for c in cot.columns if c.startswith("Open Interest")][0]
out = []
for name, cc, px, iv in [("GOLD", "088691", "GCF", "GVZ"), ("CRUDE", "067651", "CLF", "OVX")]:
    c = cot[cot[code].astype(str).str.strip().str.zfill(6) == cc].copy()
    c["d"] = pd.to_datetime(c[datec]); c = c.sort_values("d").drop_duplicates("d")
    c["net"] = (c[L].astype(float) - c[S_].astype(float)) / c[OI].astype(float) * 100
    c["crowd"] = c["net"].rolling(156, min_periods=104).apply(lambda w: (w[:-1] < w[-1]).mean() * 100, raw=True)
    P = yahoo(px); V = yahoo(iv)
    ivp = V.rolling(252, min_periods=200).apply(lambda w: (w[:-1] < w[-1]).mean() * 100, raw=True)
    lr = np.log(P).diff(); sd20 = lr.rolling(20).std()
    rows = []
    for _, r in c.iterrows():
        # COT is as of Tuesday, released Friday -> act on the FIRST trading day after the following Friday (no look-ahead)
        rel = r["d"] + pd.Timedelta(days=3)
        idx = P.index[P.index > rel]
        if len(idx) < 6: continue
        t0 = idx[0]; i0 = P.index.get_loc(t0)
        if i0 + 5 >= len(P): continue
        prev = P.index[i0 - 1]
        ivv = ivp.get(prev, np.nan)
        if np.isnan(r["crowd"]) or np.isnan(ivv) or np.isnan(sd20.iloc[i0 - 1]): continue
        m5 = np.log(P.iloc[i0 + 4] / P.iloc[i0 - 1])
        rows.append(dict(t=t0, crowd=r["crowd"], ivp=ivv, net=r["net"], m5=m5, a5=abs(m5), thr=2 * sd20.iloc[i0 - 1] * np.sqrt(5)))
    D = pd.DataFrame(rows); D["event"] = D.a5 > D.thr
    mid = D.t.iloc[len(D) // 2]
    def cell(x):
        return dict(n=len(x), med=np.median(x.a5) * 100 if len(x) else np.nan, ev=x.event.mean() * 100 if len(x) else np.nan)
    base = cell(D); top = D[(D.crowd >= 80) & (D.ivp >= 80)]; low = D[(D.crowd <= 20) & (D.ivp >= 80)]
    print(f"\n== {name} ({cc} / {iv})  weeks {len(D)}  {D.t.iloc[0]:%Y-%m-%d} -> {D.t.iloc[-1]:%Y-%m-%d}  split {mid:%Y-%m-%d}")
    print(f"  base: n {base['n']}  median |5d| {base['med']:.2f}%  event-week rate {base['ev']:.1f}%")
    print(f"  {'cell':<34}{'n':>5}{'med|5d|%':>10}{'xbase':>7}{'event%':>8}{'xbase':>7}")
    for lab, X in [("crowd>=80 & IV>=80 (THE BAR)", top), ("crowd<=20 & IV>=80", low), ("IV>=80 any crowd", D[D.ivp >= 80]),
                   ("IV<=20 any crowd", D[D.ivp <= 20]), ("crowd>=80 any IV", D[D.crowd >= 80]), ("crowd<=20 any IV", D[D.crowd <= 20])]:
        q = cell(X); print(f"  {lab:<34}{q['n']:>5}{q['med']:>10.2f}{q['med']/base['med']:>7.2f}{q['ev']:>8.1f}{(q['ev']/base['ev'] if base['ev'] else np.nan):>7.2f}")
    verdict = []
    for half, H in [("H1", D[D.t < mid]), ("H2", D[D.t >= mid])]:
        b = cell(H); t_ = cell(H[(H.crowd >= 80) & (H.ivp >= 80)])
        ok = t_["n"] >= 30 and t_["med"] >= 1.5 * b["med"] and t_["ev"] >= 2 * b["ev"]
        verdict.append(ok)
        print(f"  {half}: base med {b['med']:.2f}% ev {b['ev']:.1f}% | top n {t_['n']} med {t_['med']:.2f}% ev {t_['ev']:.1f}% -> {'PASS' if ok else 'FAIL'}")
    print(f"  VERDICT ({name}): {'EARLY WARNING' if all(verdict) else 'NO EARLY WARNING'}")
    D["cq"] = pd.qcut(D.crowd, 5, labels=["Q1 short-crowded", "Q2", "Q3", "Q4", "Q5 long-crowded"], duplicates="drop")
    g = D.groupby("cq", observed=True).agg(n=("m5", "size"), signed=("m5", lambda s: s.mean() * 100), up=("m5", lambda s: (s > 0).mean() * 100))
    print("  signed next-5d return by crowding quintile (contrarian claim):"); print("  " + g.round(2).to_string().replace("\n", "\n  "))
    # the live event days, read back
    ev_days = {"GOLD": ["2026-08-05", "2026-08-19", "2026-09-03"], "CRUDE": ["2026-07-27", "2026-07-28", "2026-09-21"]}[name]
    for e in ev_days:
        e = pd.Timestamp(e); prior = D[D.t <= e].tail(1)
        if len(prior): r_ = prior.iloc[0]; print(f"  live event {e:%Y-%m-%d}: week of {r_.t:%m-%d} crowd p{r_.crowd:.0f} IV p{r_.ivp:.0f} -> {'TOP CELL' if (r_.crowd>=80 and r_.ivp>=80) else 'not flagged'}")
