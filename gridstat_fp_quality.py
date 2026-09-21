#!/usr/bin/env python3
"""
FINGERPRINT QUALITY REPORT -- the DB-refresh gate (2026-07-29, user directive:
"identify solid repeatable patterns with frequent triggers").

Reads a freshly-shadowed research DB (full window INCLUDING the crash regime) and buckets
every fingerprint by three tests:
  SOLID      -- same-sign expectancy in BOTH regimes (uptrend segment AND crash segment).
                A fingerprint that only won while oil rose is a regime artifact (the exact
                failure of the June DB: its stats were 100% uptrend).
  REPEATABLE -- statistically real: uniqueness-weighted win rate, Wilson 95% lower bound,
                t-stat on R. Kills lucky streaks.
  FREQUENT   -- >= MIN_PER_MONTH signals/month (no US30-style 5-trade phantoms).

Buckets:
  ALL-WEATHER  -> gate/size candidates (trade these)
  REGIME-ONLY  -> works in ONE regime -> candidate for regime-CONDITIONAL use
                  (e.g. crash-state sells), never unconditional
  THIN         -> too few triggers -- accumulate, don't trade on it
  DEAD         -> negative/no edge -> zero

Usage:  python gridstat_fp_quality.py [research_csv] [crash_start YYYY-MM-DD]
Defaults: gridstat_setups_oil_research.csv, crash split 2026-04-29 (oil 111->70 begins).
Read-only. Output: console report + analysis_data/fp_quality_<date>.csv
"""
import csv, io, math, os, sys
from collections import defaultdict
from datetime import datetime

CF = r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\Common\Files"
CSV_NAME    = sys.argv[1] if len(sys.argv) > 1 else "gridstat_setups_oil_research.csv"
CRASH_START = sys.argv[2] if len(sys.argv) > 2 else "2026-04-29"
MIN_PER_MONTH = 1.5      # FREQUENT: at least ~1.5 triggers/month
MIN_N         = 12       # and an absolute floor
WILSON_MIN    = 0.50     # REPEATABLE: 95% lower bound on win rate must clear coin-flip
T_MIN         = 1.3      # and a minimally-real t-stat on R

def wilson_lb(w, n, z=1.96):
    if n == 0: return 0.0
    p = w / n
    d = 1 + z*z/n
    c = p + z*z/(2*n)
    e = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n))
    return (c - e) / d

def load(path):
    rows = list(csv.reader(io.open(path, encoding="utf-8", errors="replace")))
    hdr = [h.strip() for h in rows[0]]; ix = {h: i for i, h in enumerate(hdr)}
    out = []
    for r in rows[1:]:
        if len(r) < len(hdr): continue
        try:
            out.append(dict(key=r[ix["setup_key"]].strip(),
                            t=datetime.strptime(r[ix["entry_time"]].strip()[:16], "%Y.%m.%d %H:%M"),
                            r=float(r[ix["r_multiple"]])))
        except (ValueError, KeyError):
            continue
    return out

def seg_stats(rs):
    n = len(rs)
    if n == 0: return 0, 0.0, 0.0
    wins = sum(1 for x in rs if x > 0)
    mean = sum(rs)/n
    return n, wins/n, mean

def main():
    path = os.path.join(CF, CSV_NAME)
    if not os.path.exists(path):
        print(f"NOT FOUND: {path}\nRun the shadow first (see the recipe)."); return
    rows = load(path)
    if not rows:
        print("no parsable rows"); return
    t0, t1 = min(r["t"] for r in rows), max(r["t"] for r in rows)
    months = max((t1 - t0).days / 30.4, 0.1)
    crash = datetime.strptime(CRASH_START, "%Y-%m-%d")
    print(f"DB: {CSV_NAME}  |  {len(rows)} signals  {t0:%Y-%m-%d} -> {t1:%Y-%m-%d} ({months:.1f} mo)")
    print(f"regime split at {CRASH_START} (before = uptrend segment, after = crash/mixed segment)")
    if t1 < crash:
        print("⚠ WARNING: the DB ENDS BEFORE the crash split -- it contains only the uptrend."
              "\n  This is the exact staleness being fixed; extend the shadow window to today.")
    byfp = defaultdict(list)
    for r in rows: byfp[r["key"]].append(r)

    hdr = f"{'fingerprint':30}{'n':>5}{'/mo':>6}{'win%':>6}{'wLB':>6}{'avgR':>7}{'t':>6}{'upR':>7}{'crR':>7}  bucket"
    print("\n" + hdr + "\n" + "-"*len(hdr))
    out = []
    for fp, rs in sorted(byfp.items(), key=lambda kv: -sum(x["r"] for x in kv[1])):
        rvals = [x["r"] for x in rs]
        n = len(rvals); per_mo = n / months
        wins = sum(1 for x in rvals if x > 0)
        wr = wins / n
        wlb = wilson_lb(wins, n)
        mean = sum(rvals)/n
        sd = math.sqrt(sum((x-mean)**2 for x in rvals)/max(n-1,1)) or 1e-9
        tstat = mean / (sd/math.sqrt(n))
        upn, upwr, upR = seg_stats([x["r"] for x in rs if x["t"] <  crash])
        crn, crwr, crR = seg_stats([x["r"] for x in rs if x["t"] >= crash])
        frequent   = per_mo >= MIN_PER_MONTH and n >= MIN_N
        repeatable = wlb >= WILSON_MIN and tstat >= T_MIN and mean > 0
        both_seg   = upn >= 4 and crn >= 4
        solid      = both_seg and upR > 0 and crR > 0
        one_regime = both_seg and (upR > 0) != (crR > 0)
        if not frequent:                 bucket = "THIN"
        elif solid and repeatable:       bucket = "ALL-WEATHER **"
        elif one_regime and repeatable:  bucket = f"REGIME-ONLY({'UP' if upR>0 else 'CRASH'})"
        elif mean <= 0:                  bucket = "DEAD -> zero"
        else:                            bucket = "weak/unstable"
        print(f"{fp:30}{n:>5}{per_mo:>6.1f}{100*wr:>5.0f}%{wlb:>6.2f}{mean:>+7.2f}{tstat:>6.1f}{upR:>+7.2f}{crR:>+7.2f}  {bucket}")
        out.append([fp, n, f"{per_mo:.2f}", f"{wr:.3f}", f"{wlb:.3f}", f"{mean:.4f}",
                    f"{tstat:.2f}", upn, f"{upR:.4f}", crn, f"{crR:.4f}", bucket])
    os.makedirs("analysis_data", exist_ok=True)
    dest = os.path.join("analysis_data", f"fp_quality_{datetime.now():%Y%m%d}.csv")
    with io.open(dest, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["fingerprint","n","per_month","win_rate","wilson_lb","avg_r","t_stat",
                    "up_n","up_avg_r","crash_n","crash_avg_r","bucket"])
        w.writerows(out)
    print(f"\nsaved -> {dest}")
    print("\nREAD: trade ALL-WEATHER unconditionally; REGIME-ONLY only behind the matching regime")
    print("state (e.g. CRASH-only sells behind g_crashDown); THIN accumulates; DEAD zeroes.")
    print("Next: rebuild gate/sizing from ALL-WEATHER survivors -> promote via gridstat_db_version.py.")

if __name__ == "__main__":
    main()
