#!/usr/bin/env python3
"""
MORNING CHECK (2026-08-08, user mandate) — runs BEFORE the trading day so the operator
can glance the dashboard and decide. Automates the pipeline up to the DECISION POINT;
promotion/suspension stays human-gated (the NDB lesson: a fresh table must WIN an A/B,
never auto-promote).

Daily:   ① Regime Sentinel vs the validated envelope   ② demo-twin delta since yesterday
         ③ DB ages + daily-loop health                 ④ register lifecycle actions due
         + regenerates mission_control.html
Monday:  headless gold shadow refresh (tester-CLI on the XM runner) → audit vs production
         → if the fib C / GridStat PASS-SETS would change: flag "A/B REQUIRED (FIBC NDB)"

Output:  analysis_data/morning_brief_<date>.txt (+ morning_check.log via the .bat)
Schedule: task "GridStat Morning Check" 07:30 daily.
"""
import os, io, sys, csv, glob, json, math, time, subprocess
from datetime import datetime
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ADIR = os.path.join(HERE, "analysis_data")
COMMON = r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\Common\Files"
STATE = os.path.join(ADIR, "morning_state.json")
XM_TERMINAL = r"C:\Program Files\XM Global MT5\terminal64.exe"   # headless shadow RUNNER only (not a bench)
XM_SETDIR = r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\BB16F565FAAA6B23A20C26C49416FF05\MQL5\Profiles\Tester"
SCRATCH = os.path.join(ADIR, "tester_ini")

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.makedirs(ADIR, exist_ok=True); os.makedirs(SCRATCH, exist_ok=True)
import mission_control as mc          # reuse sentinel / demo / ages / connect
from alerts import alert


def load_state():
    try: return json.load(open(STATE))
    except Exception: return {}

def save_state(s): json.dump(s, open(STATE, "w"), indent=1)


def wilson_lb(w, n, z=1.96):
    if n == 0: return 0.0
    p = w / n
    return (p + z*z/(2*n) - z*math.sqrt((p*(1-p) + z*z/(4*n))/n)) / (1 + z*z/n)


def db_stats(path):
    """fingerprint -> (n, wins) from a shadow/gate CSV."""
    out = defaultdict(lambda: [0, 0])
    try:
        for r in csv.DictReader(io.open(path, encoding="utf-8", errors="replace")):
            try: rm = float(r["r_multiple"])
            except Exception: continue
            k = r["setup_key"]; out[k][0] += 1; out[k][1] += 1 if rm > 0 else 0
    except FileNotFoundError:
        return None
    return out


def pass_set(stats, buy_thr, sell_thr, min_n):
    s = set()
    if not stats: return s
    for k, (n, w) in stats.items():
        if n < min_n: continue
        wr = w / n
        thr = sell_thr if k.startswith("SELL") else buy_thr
        if wr >= thr: s.add(k)
    return s


def weekly_shadow_refresh(brief):
    """Monday: headless shadow (the proven Layer-3 pipeline) -> audit pass-sets vs production."""
    ini = os.path.join(SCRATCH, "gold_shadow.ini")
    setf = os.path.join(XM_SETDIR, "gold_shadow.set")
    lines = ["StatsCollectionMode=true", "StatsCSVFile=gridstat_setups_gold_research.csv",
             "grisk=4", "UseSignalLog=false"]
    io.open(setf, "w", encoding="utf-16-le").write("﻿" + "\n".join(lines) + "\n")
    io.open(ini, "w", encoding="utf-8").write(
        # [Experts] kill-switch (2026-08-18 incident: XM charts carry ARMED locked EAs on demo
        # 166789143 — an unguarded headless launch let its silver EA trade. Chart EAs disabled
        # for every headless run; the tester's own EA is unaffected.)
        "[Experts]\nEnabled=0\nAllowLiveTrading=0\n\n"
        "[Tester]\nExpert=Marius GridStat MT5 v1.0\nExpertParameters=gold_shadow.set\n"
        "Symbol=GOLD\nPeriod=M5\nModel=1\nFromDate=2025.12.01\n"
        f"ToDate={datetime.now():%Y.%m.%d}\nDeposit=3000\nOptimization=0\n"
        "Report=gold_shadow_report\nReplaceReport=1\nShutdownTerminal=1\n")
    brief.append("WEEKLY REFRESH: launching headless shadow (XM runner)...")
    try:
        r = subprocess.run([XM_TERMINAL, f"/config:{ini}"], timeout=900)
        brief.append(f"  tester exit code {r.returncode}")
    except Exception as e:
        brief.append(f"  !! shadow run failed: {e}"); return
    fresh = db_stats(os.path.join(COMMON, "gridstat_setups_gold_research.csv"))
    prod = db_stats(os.path.join(COMMON, "gridstat_setups_gold.csv"))
    if not fresh or not prod:
        brief.append("  !! audit skipped (missing CSV)"); return
    # pass-set comparison at BOTH consumers' gates
    changes = []
    for label, bt, st in (("fibC(0.55/0.65)", 0.55, 0.65), ("GridStat(0.55)", 0.55, 0.55)):
        po, pn = pass_set(prod, bt, st, 10), pass_set(fresh, bt, st, 10)
        for k in sorted(pn - po): changes.append(f"{label}: would ADMIT {k}")
        for k in sorted(po - pn): changes.append(f"{label}: would DROP {k}")
    if changes:
        brief.append("  ⚠ PASS-SET CHANGES — A/B REQUIRED before any promote (run cell FIBC NDB; "
                     "the 08-08 lesson: fresh tables must WIN, never auto-promote):")
        for c in changes: brief.append(f"    {c}")
    else:
        brief.append("  ✓ audit clean: fresh data does NOT change any pass-set — production DB stands, no action")


def gold_macro_flag():
    """[C-overlay 2026-08-18] ADVISORY gold-macro gauge, feed-native: the Asia-window
    (01-09 server) 20-day rolling drift vs its own ~90-day distribution. The 08-18 study:
    that window carries ~all of gold's drift (+11.2bp/day, both halves) and bleeds in
    chop — so its trailing state = a macro tailwind/headwind gauge with no external feed.
    ADVISORY ONLY (Sentinel doctrine: informs, never blocks). History -> macro_flag_history.csv
    so predictive value is MEASURED against episodes before anyone trusts it."""
    try:
        import MetaTrader5 as mt5
        bars = None
        for _ in range(3):
            bars = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_M5, 0, 32000)
            if bars is not None and len(bars) > 5000: break
            time.sleep(3)
        if bars is None or len(bars) < 5000: return None
        day_bp = {}
        for i in range(1, len(bars)):
            t = datetime.utcfromtimestamp(int(bars[i]["time"]))
            if 1 <= t.hour < 10:
                r = (bars[i]["close"] - bars[i-1]["close"]) / bars[i-1]["close"] * 1e4
                day_bp[t.date()] = day_bp.get(t.date(), 0.0) + r
        days = sorted(day_bp)
        if len(days) < 40: return None
        series = [day_bp[d] for d in days]
        rolls = [sum(series[i-20:i]) for i in range(20, len(series) + 1)]
        cur = rolls[-1]
        pct = 100.0 * sum(1 for x in rolls if x <= cur) / len(rolls)
        flag = "TAILWIND" if pct >= 60 else ("HEADWIND" if pct <= 40 else "NEUTRAL")
        hist = os.path.join(ADIR, "macro_flag_history.csv")
        new = not os.path.exists(hist)
        with open(hist, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new: w.writerow(["date", "asia20_bp", "pctile", "flag"])
            w.writerow([datetime.now().strftime("%Y-%m-%d"), f"{cur:.0f}", f"{pct:.0f}", flag])
        return dict(bp=cur, pct=pct, flag=flag)
    except Exception:
        return None


def main():
    now = datetime.now()
    brief = [f"=== MORNING CHECK {now:%Y-%m-%d %H:%M} ===", ""]
    state = load_state()
    decisions = []

    if not mc.connect():
        brief.append("!! live terminal unreachable — Sentinel/dashboard skipped. CHECK TERMINALS.")
        decisions.append("Terminal offline — investigate before trading day")
    else:
        # ①a ARMED CHECK -- the operator's Friday-risk regime (2026-08-28) can leave AutoTrading OFF
        #     over the weekend by design. A silently-disarmed engine is the documented fib C
        #     "silent month" failure (June 2026: chart/terminal not running, invisible for weeks).
        #     Pure observability: report, never re-arm.
        try:
            import MetaTrader5 as _mt5
            for _n, _p, _l in (("LIVE MAIN", r"C:\Program Files\Pepperstone MetaTrader 5\terminal64.exe", 51511633),
                               ("LIVE DEON", r"C:\MT5 Pepperstone Instance Deon\terminal64.exe", 51527827)):
                _mt5.shutdown()
                if not (_mt5.initialize(path=_p) and _mt5.account_info()
                        and _mt5.account_info().login == _l):
                    brief.append(f"①a {_n}: UNREACHABLE")
                    decisions.append(f"{_n} unreachable — engines may not be running")
                    continue
                _ti = _mt5.terminal_info()
                _armed = bool(_ti.trade_allowed) if _ti else False
                _open = len(_mt5.positions_get() or [])
                brief.append(f"①a {_n}: AutoTrading {'ON' if _armed else '!! OFF !!'} · {_open} open")
                if not _armed:
                    decisions.append(f"{_n}: AUTOTRADING IS OFF — engines are not trading "
                                     f"(re-arm if the Friday stand-down is over)")
            _mt5.shutdown(); mc.connect()
        except Exception as _e:
            brief.append(f"①a armed-check failed: {_e}")

        # ① Sentinel
        sent = mc.regime_sentinel()
        brief.append("① REGIME SENTINEL (vs the Dec→Jul-13 validated envelope):")
        for s in sent:
            if "atr_pct" in s:
                brief.append(f"   {s['sym']}: {s['status']}  ATR p{s['atr_pct']:.0f} "
                             f"({s['atr_x']:.1f}× tested) · velocity p{s['vel_pct']:.0f}")
                if s["status"] == "OUTSIDE":
                    decisions.append(f"{s['sym']} OUTSIDE envelope — regime-conditional fingerprints "
                                     f"(SELL|HR_OVL|ATR_EXP class) suspect; consider standing down counter-trend entries")
            else:
                brief.append(f"   {s['sym']}: {s.get('status','?')} {s.get('detail','')}")
        # ①b gold-macro advisory (the C-overlay, feed-native Asia-drift gauge — informs, never blocks)
        mf = gold_macro_flag()
        if mf:
            brief.append(f"   GOLD-MACRO (advisory): {mf['flag']}  Asia-window 20d drift {mf['bp']:+.0f}bp (p{mf['pct']:.0f} of trailing dist)")
        # ①c slot-quality assertion (user standard 2026-08-20: 'ensure the best probable trade is logged')
        # — flags any signal skipped ONLY for slot occupancy whose gate-WR beat the seat occupant's.
        try:
            import csv as _csv
            _rows = []
            for _r in _csv.reader(io.open(os.path.join(COMMON, "gridstat_signals_XAUUSD.csv"),
                                          encoding="utf-8", errors="replace")):
                if len(_r) >= 10 and _r[0].startswith(f"{now:%Y.%m.%d}"[:8]):
                    try: _rows.append((datetime.strptime(_r[0], "%Y.%m.%d %H:%M"), float(_r[7]), _r[2], _r[9]))
                    except Exception: continue
            # 2026-09-06: three terminals (MAIN/DEON/DEMO) append to the SAME shared file, so one signal appears
            # 2-3x; count distinct (time, setup, decision), not rows, or one skip reads as "3 outranked".
            _rows = sorted({(t, w, k, d) for (t, w, k, d) in _rows})
            _tr = [x for x in _rows if x[3].startswith("TRADE")]
            _sk = [x for x in _rows if "maxBaskets" in x[3]]
            _bad = 0
            for _s in _sk:
                _prior = [x for x in _tr if x[0] < _s[0]]
                if _prior and _s[1] > max(_prior, key=lambda x: x[0])[1] + 1e-9:
                    _bad += 1
            brief.append(f"   SLOT-QUALITY: {len(_tr)} trades / {len(_sk)} slot-skips this month"
                         + (f" — ⚠ {_bad} outranked the seat" if _bad else " — no better signal locked out"))
            if _bad:
                decisions.append(f"SLOT-QUALITY: {_bad} higher-WR signal(s) skipped behind a lower-WR seat — "
                                 "review whether the rank-order question deserves a study")
        except Exception:
            pass
        # ② demo twin delta
        demo = mc.demo_state(max_age=0)
        brief.append("")
        brief.append("② DEMO TWIN (the gap-meter):")
        if demo:
            prev = state.get("demo_balance")
            delta = f" ({demo['balance']-prev:+,.2f} since last check)" if prev is not None else ""
            brief.append(f"   balance ${demo['balance']:,.2f}{delta} · equity ${demo['equity']:,.2f}")
            names = {59955: "GridStat gold", 4901: "fib C", 77180: "oil SOLID"}
            for m, (n, fl) in sorted(demo["open"].items()):
                brief.append(f"   {names.get(m, m)}: {n} open, float {fl:+,.2f}")
            state["demo_balance"] = demo["balance"]
            if prev is not None and demo["balance"] - prev < -300:
                decisions.append(f"Demo twin dropped {demo['balance']-prev:+,.2f} overnight — read the episode before anything else")
        else:
            brief.append("   !! unreachable"); decisions.append("Demo twin unreachable — check terminal")

    # ③ data/factory
    ages = mc.db_ages(); fac = mc.factory_state()
    brief.append("")
    brief.append("③ DATA / FACTORY:")
    for k, v in ages.items():
        d = (now - v).days if v else None
        brief.append(f"   {k} gate DB: {f'{d}d old' if d is not None else 'MISSING'}")
    lr = fac["last_run"]
    brief.append(f"   nightly loop: {'ran ' + lr.strftime('%m-%d %H:%M') if lr else 'NEVER'}")
    if lr and (now - lr).days >= 2:
        decisions.append("Nightly loop has not run for 2+ days — check task/terminal")

    # ④ register lifecycle actions due
    brief.append("")
    brief.append("④ FINGERPRINT REGISTER — lifecycle actions due:")
    snaps = sorted(glob.glob(os.path.join(ADIR, "fingerprint_register_2*.csv")))
    # decided items don't re-nag: anything with a logged decision in the last 30 days is suppressed
    decided = set()
    dpath = os.path.join(ADIR, "fingerprint_decisions.csv")
    if os.path.exists(dpath):
        for r in csv.DictReader(io.open(dpath, encoding="utf-8", errors="replace")):
            try:
                if (now - datetime.strptime(r["date"], "%Y-%m-%d")).days <= 30:
                    decided.add((r["stream"], r["fingerprint"]))
            except Exception: pass
    if snaps:
        rows = list(csv.DictReader(io.open(snaps[-1], encoding="utf-8", errors="replace")))
        due = [r for r in rows if r["status"] in ("GOOD", "NEW", "UNDERPERF", "FLIP-DOWN")
               and (r["stream"], r["fingerprint"]) not in decided]
        if due:
            for r in due:
                brief.append(f"   {r['stream']} {r['fingerprint']}: {r['status']} -> {r['action']}")
                decisions.append(f"Register: {r['stream']} {r['fingerprint']} = {r['status']} ({r['action']})")
        else:
            brief.append("   none due (all IDLE/ACCUMULATE — promotion needs the 4-layer countersign)")
    else:
        brief.append("   no register snapshot found")

    # ⑤ Layer-2/3 artifacts: fragility ledger + rolling re-test verdicts
    brief.append("")
    brief.append("⑤ FRAGILITY + RE-TEST:")
    led = os.path.join(ADIR, "episode_ledger.csv")
    if os.path.exists(led):
        eps = list(csv.DictReader(io.open(led, encoding="utf-8")))
        recent = eps[-20:]
        knife = [e for e in recent if e["verdict"] in ("KNIFE-EDGE", "FLOOR")]
        brief.append(f"   episodes recorded {len(eps)} · knife-edge/floor in last 20: {len(knife)}")
        for e in knife[-3:]:
            brief.append(f"     [{e['account']}] {e['stream']} {e['closed']}: net {e['realized_net']} "
                         f"margin {e['margin_pct']}pp -> {e['verdict']}")
            decisions.append(f"{e['stream']} episode was {e['verdict']} (margin {e['margin_pct']}pp) — review the ledger")
    else:
        brief.append("   episode ledger: no completed episodes yet")
    # MARGIN-DRIVEN SIZE GOVERNOR (improvement #4, built 08-14; "aggression proposed by data"):
    # trailing episode margins per stream -> FAT (median budget_consumed < 0.35 over >=8 eps) =
    # quantified evidence the stream can carry MORE size at its next review; TIGHT (> 0.60) =
    # derate advised BEFORE anything breaks. Size changes stay human-gated (4-layer countersign).
    if os.path.exists(led):
        from collections import defaultdict as _dd
        by_stream = _dd(list)
        for e in eps:
            try: by_stream[f"{e['account']}:{e['stream']}"].append(float(e["budget_consumed"]))
            except Exception: pass
        gov = []
        for k, vals in by_stream.items():
            tail = vals[-10:]
            if len(tail) < 8:
                gov.append(f"   governor {k}: accumulating ({len(vals)} eps, need 8)")
                continue
            med = sorted(tail)[len(tail)//2]
            if med < 0.35:
                gov.append(f"   governor {k}: FAT margins (median {med:.0%} of floor budget) -> size-up case forming")
                decisions.append(f"Governor: {k} margins are FAT ({med:.0%} budget used) — consider size-up at next review")
            elif med > 0.60:
                gov.append(f"   governor {k}: TIGHT margins ({med:.0%}) -> derate advised")
                decisions.append(f"Governor: {k} margins TIGHT ({med:.0%}) — derate before it breaks")
            else:
                gov.append(f"   governor {k}: normal ({med:.0%})")
        for g in gov: brief.append(g)
    rrf = os.path.join(ADIR, "rolling_retest.csv")
    if os.path.exists(rrf):
        rows = list(csv.DictReader(io.open(rrf, encoding="utf-8")))
        # (2026-08-27) show only jobs the re-test STILL RUNS. Retired jobs keep their history in the
        # CSV but stop nagging the brief: the XM-era rows (OHLC model on a retired feed = the
        # phantom-disaster mode) and any config that has been superseded on the terminals.
        try:
            import rolling_retest as _rr
            live_jobs = set(_rr.JOBS.keys())
        except Exception:
            live_jobs = None
        latest = {}
        for r in rows:
            if live_jobs and r["job"] not in live_jobs: continue
            latest[r["job"]] = r
        for j, r in latest.items():
            brief.append(f"   re-test {j} ({r['date']}): net {r['net']} RF {r['rf']} -> {r['verdict']}")
            if "DEGRADED" in r["verdict"]:
                decisions.append(f"Re-test: {j} DEGRADED on the trailing window — investigate before trusting the stream")
    else:
        brief.append("   rolling re-test: no runs yet (Saturdays 09:00)")

    # Monday: the automated fingerprint cycle (shadow -> audit -> A/B flag; NEVER auto-promote)
    if now.weekday() == 0:
        brief.append("")
        weekly_shadow_refresh(brief)
        # RESEARCH PROBE (2026-10-11, user: "put a process in place to probe" the shelved research): every killed/shelved/open
        # item in analysis_data/research_registry.csv is re-probed when its trigger (capital / sample / date / event) fires.
        brief.append("")
        try:
            import research_probe
            _due = research_probe.main(brief, with_balance=True)
            for _r, _why in _due:
                decisions.append(f"RESEARCH PROBE due: {_r['id']} ({_why}) -> run: {_r['probe']}")
        except Exception as _e:
            brief.append(f"RESEARCH PROBE: failed ({_e})")
        # OIL: same cycle, on the PEP deployment feed, with its own control cell. Added
        # 2026-09-01 — oil's table had gone 33 days stale while gold refreshed weekly, and
        # oil has the least selection redundancy in the book (2 tradeable fingerprints).
        brief.append("")
        brief.append("WEEKLY REFRESH (OIL, PEP runner):")
        try:
            r = subprocess.run([sys.executable, os.path.join(HERE, "oil_shadow_refresh.py")],
                               capture_output=True, text=True, timeout=2700)
            out = (r.stdout or "") + (r.stderr or "")
            for line in out.splitlines():
                t = line.strip()
                if any(t.startswith(x) for x in ("=== FEED CONTROL", "⛔", "✓ feed", "side flips",
                                                 "size changes", "new fingerprints")):
                    brief.append(f"   {t}")
                if t.startswith("⚠ WOULD DROP") or "WOULD ADMIT (deployed skips it, no standing" in t:
                    brief.append(f"   {t}")
            if "⛔ VOID" in out:
                decisions.append("OIL refresh VOID — the runner could not reproduce its baseline; "
                                 "fix the feed before reading the fingerprint report")
            elif "WOULD DROP" in out or "no standing override" in out:
                decisions.append("OIL refresh: a fingerprint changed side on the deployment feed — "
                                 "trade-mode A/B required before touching the sizing table")
        except Exception as e:
            brief.append(f"   !! oil refresh failed: {e}")

    # ⑥ FRAMEWORK SELF-TEST — the control cell for the monitoring layer itself.
    # Three silent defects in two days (realized_net time-window, register-vs-sizing,
    # stale oil magic) all shared one cause: no tool ever reconciled itself against the
    # account's own deal history. A monitor that breaks looks calm, so re-prove it daily.
    brief.append("")
    brief.append("⑥ FRAMEWORK SELF-TEST:")
    try:
        r = subprocess.run([sys.executable, os.path.join(HERE, "framework_check.py")],
                           capture_output=True, text=True, timeout=600)
        out = (r.stdout or "") + (r.stderr or "")
        passed = next((l.strip() for l in out.splitlines() if "checks passed" in l), "?")
        brief.append(f"   {passed}")
        if r.returncode == 1:
            fails = [l.strip("  - ").strip() for l in out.splitlines()
                     if l.startswith("  - ")]
            for f in fails:
                brief.append(f"   !! {f}")
            decisions.append(
                f"FRAMEWORK: {len(fails)} self-test failure(s) — a monitoring tool is reporting "
                f"something it cannot see; fix before trusting its numbers ({fails[0] if fails else ''})")
        elif r.returncode != 0:
            brief.append("   could not run (no terminal reachable)")
    except Exception as e:
        brief.append(f"   self-test failed to run: {e}")

    # regenerate the dashboard file for the morning glance
    try:
        subprocess.run([sys.executable, os.path.join(HERE, "mission_control.py")], timeout=180)
        brief.append("")
        brief.append("dashboard regenerated -> mission_control.html (or run --serve for live)")
    except Exception as e:
        brief.append(f"dashboard regen failed: {e}")

    # DECISION SUMMARY — the only part that must be read
    brief.append("")
    brief.append("=== DECISIONS NEEDED THIS MORNING ===")
    if decisions:
        for i, d in enumerate(decisions, 1): brief.append(f" {i}. {d}")
    else:
        brief.append(" NONE — all green, hands off.")

    # DAILY PHONE PUSH (2026-08-11, user: the report must ARRIVE, not sit in a file):
    # a compact summary goes to Telegram EVERY morning, decisions or not.
    try:
        sent_line = next((b for b in brief if "GOLD:" in b), "").strip()
        demo_line = next((b for b in brief if "balance $" in b), "").strip()
        summary = (f"Morning brief {now:%a %m-%d}\n"
                   f"{sent_line}\n{demo_line}\n"
                   + (f"DECISIONS ({len(decisions)}):\n" +
                      "\n".join(f"• {d}" for d in decisions[:4])
                      if decisions else "No decisions — all green, hands off."))
        alert(summary, "AMBER" if decisions else "INFO",
              title="GridStat Morning Brief", telegram=True)
    except Exception as e:
        brief.append(f"(push failed: {e})")

    out = "\n".join(brief)
    print(out)
    io.open(os.path.join(ADIR, f"morning_brief_{now:%Y%m%d}.txt"), "w", encoding="utf-8").write(out)
    save_state(state)
    try: mc.mt5.shutdown()
    except Exception: pass


if __name__ == "__main__":
    main()
