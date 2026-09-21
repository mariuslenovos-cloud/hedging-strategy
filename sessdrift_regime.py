#!/usr/bin/env python3
"""
SESSIONDRIFT x REGIME — does the 01:00->04:00 accumulation drift survive a DOWN gold regime?

WHY (2026-09-02): SessionDrift bought into a -7.6%/8-day gold slide on the demo and lost
$18.56. That is the engine working as specified — it is a CLOCK strategy with no trend
filter, and its edge was measured over an 11-year gold BULL. The logged caveat has always
been "long-biased; its only bad year was flat/down gold (2022, -2%)". Gold is now in a
genuine DOWN regime, so the caveat is finally testable instead of theoretical.

THE QUESTION, stated so it can fail: is the window drift STRUCTURAL (present in both
regimes, so hold through) or is it BETA-DURING-HELD-HOURS (present only when gold rises,
so the engine is a leveraged long in disguise)?

METHOD: 5.25y of M30 gold (the same export the in-flight study used). For each day take the
return across the held window, and label the day's regime by the D1 5-day momentum sign
KNOWN BEFORE the window opens (close of 2 days prior vs 7 days prior -> no look-ahead).
Report both halves of the sample separately: an effect that only exists in one half is not
an effect. Costs charged at the measured round-trip spread.

Read-only research. No config is changed by this script.
"""
import io, csv, sys
from datetime import datetime, timedelta
from collections import defaultdict
import statistics as st

EXPORT = r"analysis_data\xauusd_m30_export.csv"
ENTRY_H, EXIT_H = 1, 4          # the locked window (server hours)
SPREAD_BP = 0.55                # measured round-trip on the 01->10 study; conservative here
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass


def load():
    bars = []
    for r in csv.DictReader(io.open(EXPORT, encoding="utf-8", errors="replace")):
        t = r.get("time") or r.get("Time") or r.get("datetime")
        c = r.get("close") or r.get("Close")
        if not t or not c:
            continue
        try:
            ts = datetime.fromisoformat(t.replace("/", "-"))
        except ValueError:
            try: ts = datetime.strptime(t, "%Y.%m.%d %H:%M")
            except ValueError: continue
        bars.append((ts, float(c)))
    bars.sort()
    return bars


def main():
    bars = load()
    if not bars:
        print("no bars parsed — check the export's column names"); return 1
    print(f"loaded {len(bars):,} M30 bars  {bars[0][0]:%Y-%m-%d} -> {bars[-1][0]:%Y-%m-%d}")

    # daily close series (for the regime label) + the window return per day
    by_day = defaultdict(dict)
    daily_close = {}
    for ts, c in bars:
        d = ts.date()
        by_day[d][(ts.hour, ts.minute)] = c
        daily_close[d] = c                      # last bar of the day wins

    days = sorted(by_day)
    dlist = sorted(daily_close)
    idx = {d: i for i, d in enumerate(dlist)}

    rows = []
    for d in days:
        h = by_day[d]
        entry = h.get((ENTRY_H, 0)) or h.get((ENTRY_H, 30))
        exit_ = h.get((EXIT_H, 0)) or h.get((EXIT_H, 30))
        if entry is None or exit_ is None:
            continue
        i = idx.get(d)
        if i is None or i < 8:
            continue
        # regime known BEFORE the window opens: momentum over days [-7,-2]
        c_recent, c_old = daily_close[dlist[i - 2]], daily_close[dlist[i - 7]]
        regime = "UP" if c_recent > c_old else "DOWN"
        ret_bp = (exit_ / entry - 1) * 10000 - SPREAD_BP
        rows.append((d, regime, ret_bp))

    if not rows:
        print("no window pairs found — check ENTRY_H/EXIT_H against the export's hours"); return 1

    half = len(rows) // 2
    def stats(sub):
        if not sub: return None
        v = [r[2] for r in sub]
        m = st.mean(v)
        sd = st.pstdev(v) or 1e-9
        t = m / (sd / (len(v) ** 0.5))
        return len(v), m, 100 * sum(1 for x in v if x > 0) / len(v), t, sum(v)

    print(f"\nwindow {ENTRY_H:02d}:00 -> {EXIT_H:02d}:00, net of {SPREAD_BP}bp round-trip, "
          f"{len(rows)} tradeable days\n")
    print(f"{'slice':22}{'n':>6}{'mean bp':>10}{'win%':>8}{'t':>7}{'total bp':>11}")
    for label, sub in (("ALL", rows),
                       ("regime UP", [r for r in rows if r[1] == "UP"]),
                       ("regime DOWN", [r for r in rows if r[1] == "DOWN"]),
                       ("--- 1st half ---", []),
                       ("  UP  (1st half)", [r for r in rows[:half] if r[1] == "UP"]),
                       ("  DOWN(1st half)", [r for r in rows[:half] if r[1] == "DOWN"]),
                       ("--- 2nd half ---", []),
                       ("  UP  (2nd half)", [r for r in rows[half:] if r[1] == "UP"]),
                       ("  DOWN(2nd half)", [r for r in rows[half:] if r[1] == "DOWN"])):
        if not sub:
            print(label); continue
        n, m, w, t, tot = stats(sub)
        print(f"{label:22}{n:>6}{m:>10.2f}{w:>8.1f}{t:>7.2f}{tot:>11.0f}")

    up = [r for r in rows if r[1] == "UP"]; dn = [r for r in rows if r[1] == "DOWN"]
    su, sd_ = stats(up), stats(dn)
    print("\n--- READ ---")
    if sd_ and sd_[1] > 0 and sd_[3] > 1.0:
        print("  DOWN-regime drift is POSITIVE and significant -> the edge is STRUCTURAL;")
        print("  buying into a downtrend is correct and no regime filter is warranted.")
    elif sd_ and sd_[1] <= 0:
        print("  DOWN-regime drift is NEGATIVE -> the window edge is at least partly")
        print("  BETA-DURING-HELD-HOURS. A regime filter becomes a legitimate candidate,")
        print("  but ONLY if the sign is stable across BOTH halves above — a one-half")
        print("  effect is the in-sample trap this project has been burned by repeatedly.")
    else:
        print("  DOWN-regime drift is positive but weak -> hold, keep measuring.")
    print("  NOTE: this is a bar-level proxy for the drift. It does not model the EA's")
    print("  risk-normed sizing or its stop/target bracket, so treat the SIGN and the")
    print("  HALVES as the finding, not the basis-point totals.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
