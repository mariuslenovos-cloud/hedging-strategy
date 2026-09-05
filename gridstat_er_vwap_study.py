"""Do the REVSCALP regime features (M5 Efficiency Ratio, session-VWAP z) predict GridStat gold's OWN
triple-barrier outcome? Join at fire time to the PEP M5 export; buckets + halves + within-cell control."""
import pandas as pd, numpy as np, io, csv, sys
F = r"C:/Users/mariu/AppData/Roaming/MetaQuotes/Terminal/Common/Files/gridstat_setups_gold_research_allfires.csv"
raw = io.open(F, encoding="utf-8", errors="replace").read().splitlines()
hdr = raw[0].split(","); n = len(hdr)
rows = []
for line in raw[1:]:
    p = line.split(",")
    if len(p) > n: p = p[:n-1] + [",".join(p[n-1:])]   # skip_reason overflow (unquoted comma)
    if len(p) == n: rows.append(p)
a = pd.DataFrame(rows, columns=hdr)
tcol = [c for c in a.columns if "time" in c.lower()][0]
a["t"] = pd.to_datetime(a[tcol], errors="coerce"); a = a.dropna(subset=["t"])
a["r"] = pd.to_numeric(a["r_multiple"], errors="coerce"); a = a.dropna(subset=["r"])
a["skip"] = a["skip_reason"].fillna("").str.strip() if "skip_reason" in a else ""
a["gate"] = a["skip"].eq("PASS")
print("fires", len(a), "gate-quality", a.gate.sum(), "span", a.t.min(), "->", a.t.max())
m = pd.read_csv("analysis_data/xauusd_m5_export.csv", parse_dates=["time"]).set_index("time")
m["er"] = (m.close - m.close.shift(10)).abs() / m.close.diff().abs().rolling(10).sum()
tp = (m.high + m.low + m.close) / 3; day = m.index.date
m["vwap"] = (tp * m.tick_volume).groupby(day).cumsum() / m.tick_volume.groupby(day).cumsum()
m["dev"] = m.close - m.vwap; m["z"] = m.dev / m.dev.rolling(24).std()
ctx = m[["er", "z"]].shift(1)                      # completed bar before the fire
j = ctx.reindex(a.t, method="ffill"); a["er"] = j.er.values; a["z"] = j.z.values
a["dir"] = a["direction"].str.upper().str[:1] if "direction" in a else a["setup_key"].str[:1]
a["zs"] = np.where(a.dir == "B", -a.z, a.z)         # stretch AGAINST the fire's direction (>0 = fading a stretch)
a = a.dropna(subset=["er", "z"])
a["half"] = (a.t > a.t.quantile(0.5)).map({False: "H1", True: "H2"})
def table(df, col, name, q=3):
    df = df.copy(); df["b"] = pd.qcut(df[col], q, labels=[f"{name}_lo", f"{name}_mid", f"{name}_hi"])
    g = df.groupby("b", observed=True)
    out = g.r.agg(n="size", win=lambda x: (x > 0).mean(), meanR="mean")
    out["H1"] = df[df.half == "H1"].groupby("b", observed=True).r.mean(); out["H2"] = df[df.half == "H2"].groupby("b", observed=True).r.mean()
    return out.round(3)
for label, df in (("ALL FIRES", a), ("GATE-QUALITY (what the EA trades)", a[a.gate])):
    print(f"\n== {label}  n={len(df)}  meanR={df.r.mean():+.3f}")
    print(table(df, "er", "ER")); print(table(df, "zs", "VWAPz"))
    print("  spec's chop regime ER<0.30 :", f"n={(df.er<0.30).sum()} meanR={df[df.er<0.30].r.mean():+.3f}   directional ER>0.45: n={(df.er>0.45).sum()} meanR={df[df.er>0.45].r.mean():+.3f}")
g = a[a.gate]
print("\n== WITHIN-CELL control (gate-quality, top fingerprints): ER lo/hi tercile meanR")
for k, c in g.groupby("setup_key"):
    if len(c) < 40: continue
    lo, hi = c[c.er <= c.er.quantile(1/3)], c[c.er >= c.er.quantile(2/3)]
    print(f"  {k:<26} n={len(c):3d}  ERlo {lo.r.mean():+.3f} (n{len(lo)})  ERhi {hi.r.mean():+.3f} (n{len(hi)})   | VWAPz lo {c[c.zs<=c.zs.quantile(1/3)].r.mean():+.3f}  hi {c[c.zs>=c.zs.quantile(2/3)].r.mean():+.3f}")
