"""t2one_hour_watch.py -- forward watch for registry row t2one_hour_block (pre-registered 2026-10-14).
Counts the DEMO t2one fires since 2026-10-01 11:40 (live config) on the live population (SELL, tier>=2, 3 x risk <= $40),
split 04:00-11:59 server vs the rest. PASS = in-block n >= 60, in-block win >= 72%, out-of-block win at least 6pp lower.
Exit code 0 = PASS, 1 = not yet / fail (research_probe reads the printed verdict)."""
import sys, pandas as pd
P = r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\C54C4DDE98E7B1FB905AFE04A9333631\MQL5\Files\mm_fires_XAUUSD_PERIOD_M1_t2one.csv"
f = pd.read_csv(P); f["t"] = pd.to_datetime(f.signal_time, format="mixed")
f = f[(f.t >= "2026-10-01 11:40") & (f.dir == "SELL") & (f.tier >= 2) & (3 * f.risk_price <= 40) & f["r_tp1_0.5R"].notna()].drop_duplicates("t")
f["inb"] = f.t.dt.hour.between(4, 11); f["usd"] = f["r_tp1_0.5R"] * f.risk_price * 3; f["w"] = f["r_tp1_0.5R"] > 0
a, b = f[f.inb], f[~f.inb]
wa, wb = a.w.mean() * 100, b.w.mean() * 100
ok = len(a) >= 60 and wa >= 72 and wa - wb >= 6
print(f"t2one hour block 04-11: in {len(a)} fires {wa:.1f}% ${a.usd.sum():+.0f} | out {len(b)} fires {wb:.1f}% ${b.usd.sum():+.0f} -> "
      + ("PASS" if ok else ("FAIL" if len(a) >= 60 else f"ACCUMULATING ({len(a)}/60)")))
sys.exit(0 if ok else 1)
