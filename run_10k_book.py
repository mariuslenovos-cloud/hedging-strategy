"""run_10k_book.py -- THE $10k BOOK, priced on the runner (2026-10-11, user brief: "make sure a 10k account brings in a lot of money").
Runs every validated engine AS IT WOULD BE ATTACHED on a $10,000 deposit, Dec-01-2025 -> today, then composes
the daily realized P&L into one book: net / realized DD / RF / $ per trading day / worst day / pain windows.
Generated ticks before 08-28 (the runner has no deeper tick store since 10-07) -> absolutes are a PAIRED RANKING;
the known runner-vs-100%-tick ratio on gold HPIN12 (runner $6,759 vs GUI $5,952 at $3k) is printed as the haircut.
usage: python run_10k_book.py [run|compose] [CELL ...]
"""
import io, os, sys, itertools
from datetime import datetime
from collections import OrderedDict
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "factory_front"))
import rolling_retest as rr
import cell_d_allocation as CD
import pandas as pd, numpy as np

DEPOSIT = 10000
ZBASE = OrderedDict(TriggerMode="2", ZLookback="24", EntryZ="2.25", UseSessionFilter="true", SessionStartHour="18", SessionEndHour="23",
                    UseDailyTrendFilter="true", AlignEmaPeriod="200", StagedCutCooldownMin="0", UseSignalLog="false")
CELLS = OrderedDict([
    # name          expert                       symbol       setlines (None = zero-input cell verbatim)
    ("g10k_half",  ("GOLD HPIN12",              "XAUUSD",   None)),                       # live HALF geometry; compounding x2 at $10k -> 0.02 from day one
    ("g10k_full",  ("GOLD HPIN12 FULL",         "XAUUSD",   None)),                       # FULL geometry (0.02/PT100/RBT40); compounding x2 -> 0.04 at $10k
    ("o10k_kp1",   ("OIL FRZRT15KP1",           "SpotCrude", None)),                      # deployed oil, risk-norm 2.5% of balance
    ("z10k_lot02", ("Marius ZGrid MT5 v1.0",    "XAUUSD",   dict(ZBASE, LotSize="0.02", ProfitTargetUSD="100.0", RescueBookTargetUSD="40.0"))),   # the demo preset as loaded (compounding x2 at $10k -> 0.04)
    ("z10k_lot05", ("Marius ZGrid MT5 v1.0",    "XAUUSD",   dict(ZBASE, LotSize="0.05", ProfitTargetUSD="250.0", RescueBookTargetUSD="100.0", UseCompounding="false"))),  # the roadmap's 0.05, covariant $-levers, no compounding -> REJECTED (eqDD 30%)
    # --- the SAFE-SIZE levers (2026-10-11, user: "do we increase position size safely?") ---
    ("g10k_full_c3", ("GOLD HPIN12 FULL C3",      "XAUUSD",   None)),                       # MaxCompoundScale 3: lots 0.06 above $9k, %-floors + $100 target unchanged
    ("z10k_lot03", ("Marius ZGrid MT5 v1.0",    "XAUUSD",   dict(ZBASE, LotSize="0.03", ProfitTargetUSD="150.0", RescueBookTargetUSD="60.0"))),   # compounding x2 -> 0.06 at the SAME $25-per-0.01 target as the good lot02 cell
    ("z10k_lot04", ("Marius ZGrid MT5 v1.0",    "XAUUSD",   dict(ZBASE, LotSize="0.04", ProfitTargetUSD="200.0", RescueBookTargetUSD="80.0"))),   # -> 0.08 effective, same geometry
    ("o10k_r20",   ("OIL KP1 R20",              "SpotCrude", None)),                      # oil risk 2.0% (Pass-61 validated at $3k)
    ("o10k_r15",   ("OIL KP1 R15",              "SpotCrude", None)),                      # oil risk 1.5%
])
GROUPS = dict(gold=["g10k_half", "g10k_full", "g10k_full_c3"], zg=["z10k_lot02", "z10k_lot03", "z10k_lot04", "z10k_lot05"], oil=["o10k_kp1", "o10k_r20", "o10k_r15"])
OUT = os.path.join(HERE, "analysis_data", f"book_10k_{datetime.now():%Y%m%d}.txt")


def report(name):
    return next((p for p in rr.report_paths(f"retest_{name}") if os.path.exists(p)), None)


def run(names):
    rr.WINDOW_DAYS = (datetime.now() - datetime(2025, 12, 1)).days + 1
    if rr.runner_busy():
        print("!! runner already running -- abort"); sys.exit(2)
    for n in names:
        exp, sym, setl = CELLS[n]
        for attempt in range(8):   # XAUUSD tick pre-download is cancelled on most launches (Bug Log 10-08); 45-s pauses between outer tries
            rr.run_job(n, dict(expert=exp, symbol=sym, deposit=DEPOSIT,
                               setlines=[f"{k}={v}" for k, v in setl.items()] if setl else None))
            rp = report(n); nd = len(CD.deals(rp)) if rp else 0
            print(f"  [{n}] outer attempt {attempt+1}: deals {nd}", flush=True)
            if nd > 0: break
            import time; time.sleep(45)


def summary(path):
    import run_frz_ab as F
    return F.parse(path)


def compose(names):
    lines = [f"THE $10k BOOK -- runner paired bench, 2025-12-01 -> {datetime.now():%Y-%m-%d}, deposit {DEPOSIT}, Model 4 (generated ticks before 08-28)"]
    series, lots = {}, {}
    hdr = f"{'cell':<12}{'net':>10}{'PF':>6}{'RF':>6}{'eqDD%':>7}{'tr':>5}{'qual':>5}{'$/tday':>8}{'realDD':>8}{'worst d':>8}{'lots':>12}"
    lines.append(hdr); lines.append("-" * len(hdr))
    for n in names:
        rp = report(n)
        if not rp: lines.append(f"{n:<12} NO REPORT"); continue
        s = summary(rp); d = CD.deals(rp); d = d[d.dir != "in"]
        p = d.groupby(d.time.dt.date).net.sum(); p.index = pd.to_datetime(p.index)
        st = CD.stats(p); series[n] = p
        lotset = sorted(set(round(x, 2) for x in d.lots)); lots[n] = f"{min(lotset)}-{max(lotset)}" if lotset else "-"
        lines.append(f"{n:<12}{st['net']:>10,.0f}{s['pf'] or 0:>6.2f}{s['rf'] or 0:>6.2f}{s['eqdd'] or 0:>7.1f}{s['trades'] or 0:>5}{s['quality'] or 0:>5}"
                     f"{st['net']/max(len(p),1):>8,.0f}{st['maxdd']:>8,.0f}{st['worst']:>8,.0f}{lots[n]:>12}")
    if not series: print("\n".join(lines)); return
    lo = min(s.index[0] for s in series.values()); hi = max(s.index[-1] for s in series.values())
    idx = pd.bdate_range(lo, hi); P = pd.DataFrame({k: v.reindex(idx).fillna(0.0) for k, v in series.items()})
    tdays = len(idx)
    lines.append(f"\nwindow {lo.date()} -> {hi.date()} = {tdays} business days; daily-P&L correlation:")
    lines.append(P.corr().round(2).to_string())
    lines.append(f"\nBOOK COMPOSITIONS at ${DEPOSIT:,} (realized daily P&L, summed across engines):")
    h2 = f"{'book':<36}{'net':>9}{'realDD':>8}{'RF':>7}{'$/tday':>8}{'$/day%':>8}{'worst d':>9}{'pain':>8}{'+days':>7}"
    lines.append(h2); lines.append("-" * len(h2))
    rows = []
    for g in [None] + [k for k in GROUPS["gold"] if k in P]:
        for z in [None] + [k for k in GROUPS["zg"] if k in P]:
            for o in [None] + [k for k in GROUPS["oil"] if k in P]:
                parts = [x for x in (g, z, o) if x]
                if not parts: continue
                p = sum(P[k] for k in parts); st = CD.stats(p)
                rows.append(("+".join(parts), st, CD.pain_sum(p)))
    rows.sort(key=lambda r: -r[1]["net"])
    for label, st, ps in rows[:40]:
        lines.append(f"{label:<36}{st['net']:>9,.0f}{st['maxdd']:>8,.0f}{st['rf']:>7.2f}{st['net']/tdays:>8,.0f}{100*st['net']/tdays/DEPOSIT:>8.2f}{st['worst']:>9,.0f}{ps:>8,.0f}{st['pos_days']:>7.0%}")
    lines.append("\nmonthly net per engine ($):")
    M = P.resample("ME").sum(); M.index = M.index.strftime("%Y-%m")
    lines.append(M.round(0).astype(int).to_string())
    lines.append("\npain windows per engine ($):")
    lines.append(f"{'window':<8}" + "".join(f"{k:>12}" for k in P.columns))
    for nm, (a, b) in CD.PAIN.items():
        seg = P[(P.index >= a) & (P.index <= b)]
        lines.append(f"{nm:<8}" + "".join(f"{seg[k].sum():>12,.0f}" for k in P.columns))
    lines.append("\nHAIRCUT reference: runner HPIN12 @ $3k = $6,759 (10-05) vs the last 100%-tick GUI = $5,952 (09-05) -> runner/real = 1.14 on gold.")
    txt = "\n".join(lines); print(txt)
    io.open(OUT, "w", encoding="utf-8").write(txt + "\n"); print(f"\nwritten {OUT}")
    P.to_csv(os.path.join(HERE, "analysis_data", f"book_10k_daily_{datetime.now():%Y%m%d}.csv"))


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "run"
    names = sys.argv[2:] or list(CELLS)
    if mode == "run": run(names); compose(names)
    else: compose(names)
