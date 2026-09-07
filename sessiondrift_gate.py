"""
sessiondrift_gate.py -- the SessionDrift promotion gate, written down BEFORE the review (2026-09-06)
and checked ON 2026-09-20 (Downloads\\SESSIONDRIFT_PROMOTION_NOTE.md, copied to
factory_front/cards/2026-09-06-05_sessiondrift-promotion-gate.md).

    python sessiondrift_gate.py                 # interim read of the demo record vs the 4 gate items
    python sessiondrift_gate.py --tester R.htm  # + gate item 4: demo tracks the tester on the same days
    python sessiondrift_gate.py --rerun         # runs the tester over the demo window on the PEP runner
                                                #   (rolling_retest machinery, EA defaults = the demo config),
                                                #   then checks item 4 against that fresh report
    python sessiondrift_gate.py --live          # the LIVE removal rule (rolling 28d, both live accounts)

Negative tests (each must FAIL for the reason the check exists):
    --min-eps 100          -> item 1 FAIL          --baseline-worst -5    -> item 3 FAIL
    --tester sd_h4.htm     -> item 4 FAIL (no overlapping days: that report ends 08-20)

RECORD SOURCES (rule 6: nothing here is a memory):
  * current demo twin 61586543 -- deal history, magic 88231, queried live (entry/exit/net incl comm+swap);
  * the record BEFORE the twin switch (2026-08-25 -> 08-31, retired account 61552687, not queryable any
    more) = PRE_SWITCH below, from the 08-29 scorecard (5 eps, -$15, worst -$22) + the 08-31 Monday
    resolution (+$18.67). The auditor ledger holds those episodes but its realized_net column is zero on
    rows written before the 09-01 time-basis fix, so it is NOT the source of those nets.
"""
import argparse, io, os, sys, statistics
from datetime import datetime, timedelta

MAGIC        = 88231
DEMO_PATH    = r"C:\MT5 Pepperstone Instance 2\terminal64.exe"
DEMO_LOGIN   = 61586543
LIVE = {  # the two live accounts (removal-rule mode)
    "LIVE": (r"C:\Program Files\Pepperstone MetaTrader 5\terminal64.exe", 51511633),
    "DEON": (r"C:\MT5 Pepperstone Instance Deon\terminal64.exe",           51527827),
}
DEMO_START   = datetime(2026, 8, 25)
SWITCH_DAY   = datetime(2026, 9, 1)        # first episode on the new twin
REVIEW_DAY   = datetime(2026, 9, 20)
PRE_SWITCH   = dict(eps=6, net=-15.00 + 18.67, worst=-22.00,
                    note="old twin 61552687: 08-29 scorecard 5 eps/-$15/worst -$22 + 08-31 close +$18.67")
BASELINE_WORST = -22.00                    # largest demo loss seen by 2026-09-06 (gate item 3, frozen)
STOP_ATR_MULT  = 1.5                       # the running config: stop 1.50 x ATR(D1,14); R = that $ risk at 0.01 lot
LOT_USD_PER_PT = 1.0                       # 0.01 lot XAUUSD = 1 oz = $1 per $1 move
# the demo's config, VERIFIED from its Experts log CONFIG lines (09-04/05/06). The bench MUST run exactly this:
# 2026-09-07 the first --rerun scored item 4 on a report whose Inputs line read ExitHour=5 -- the runner's tester
# had reused its cached inputs from the 08-23 exit-hour sweep because no set file was passed. Never again: the set
# file is explicit AND the report's own Inputs line is asserted before item 4 is scored.
DEMO_INPUTS = dict(EntryHour="1", ExitHour="4", UseGiveBackShort="false", FixedLots="0.01",
                   StopATRMult="1.5", TargetATRMult="0.0", ATRPeriod="14", MagicNumber="88231")


def mt5_connect(path, login):
    import MetaTrader5 as mt5
    for _ in range(3):
        try: mt5.shutdown()
        except Exception: pass
        if mt5.initialize(path=path):
            ai = mt5.account_info()
            if ai and ai.login == login: return mt5
    raise SystemExit(f"cannot attach to login {login} at {path}")


def episodes(mt5, since, magic=MAGIC):
    """position-level episodes: [(open_dt, close_dt, net, lots, dir)] from the deal history."""
    deals = [d for d in (mt5.history_deals_get(since, datetime.now() + timedelta(days=1)) or []) if d.magic == magic]
    eps = {}
    for d in deals:
        e = eps.setdefault(d.position_id, dict(open=None, close=None, net=0.0, lots=0.0, dir="?"))
        e["net"] += d.profit + d.commission + d.swap
        if d.entry == 0:
            e["open"] = datetime.fromtimestamp(d.time); e["lots"] = d.volume; e["dir"] = "BUY" if d.type == 0 else "SELL"
        else:
            e["close"] = datetime.fromtimestamp(d.time)
    return [e for e in eps.values() if e["close"] is not None]


def atr_d1(mt5, symbol="XAUUSD", period=14, since=None):
    """ATR(D1, period) by day (simple TR mean, close enough for an R unit) -> {date: atr}."""
    import numpy as np
    rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_D1, (since or DEMO_START) - timedelta(days=60), datetime.now())
    if rates is None or len(rates) < period + 2: return {}
    out, tr = {}, []
    prev_close = None
    for r in rates:
        t = datetime.fromtimestamp(r["time"]).date()
        h, l, c = r["high"], r["low"], r["close"]
        tr.append(max(h - l, abs(h - prev_close), abs(l - prev_close)) if prev_close else h - l)
        prev_close = c
        if len(tr) >= period: out[t] = float(np.mean(tr[-period:]))
    return out


def gate(eps, atr_by_day, min_eps, baseline_worst, tester_trades=None):
    """the four items. eps = current-twin episodes; PRE_SWITCH is added as a constant."""
    res = {}
    n = PRE_SWITCH["eps"] + len(eps)
    res["1 episodes >= %d" % min_eps] = (n >= min_eps, f"{n} = {PRE_SWITCH['eps']} pre-switch + {len(eps)} on 61586543")
    net = PRE_SWITCH["net"] + sum(e["net"] for e in eps)
    rs = []
    for e in eps:
        d = e["open"].date()
        a = atr_by_day.get(d) or atr_by_day.get(d - timedelta(days=1)) or atr_by_day.get(d - timedelta(days=3))
        if a: rs.append(e["net"] / (STOP_ATR_MULT * a * LOT_USD_PER_PT * (e["lots"] / 0.01)))
    net_r = sum(rs)
    res["2 net > 0 after cost"] = (net > 0 and (net_r > 0 if rs else True),
                                   f"net ${net:+.2f} ({PRE_SWITCH['net']:+.2f} pre-switch, {sum(e['net'] for e in eps):+.2f} since 09-01); "
                                   f"net R (current twin, R = 1.5xATR(D1) stop at 0.01 lot) {net_r:+.2f} over {len(rs)} eps")
    worst = min([PRE_SWITCH["worst"]] + [e["net"] for e in eps])
    res[f"3 worst episode >= baseline {baseline_worst:+.2f}"] = (worst >= baseline_worst, f"worst {worst:+.2f}")
    if tester_trades is not None:
        by_day_demo = {}
        for e in eps: by_day_demo[e["close"].date()] = by_day_demo.get(e["close"].date(), 0) + e["net"]
        by_day_test = {}
        for t, p in tester_trades: by_day_test[t.date()] = by_day_test.get(t.date(), 0) + p
        common = sorted(set(by_day_demo) & set(by_day_test))
        if not common:
            res["4 demo tracks tester"] = (False, "NO overlapping days between the demo record and the tester report -- rerun the tester over the demo window (--rerun)")
        else:
            diffs = [by_day_demo[d] - by_day_test[d] for d in common]
            sign_ok = sum(1 for d in common if (by_day_demo[d] >= 0) == (by_day_test[d] >= 0))
            mad = statistics.mean(abs(x) for x in diffs)
            ok = sign_ok >= 0.8 * len(common) and abs(sum(diffs)) <= max(30.0, 0.5 * sum(abs(by_day_test[d]) for d in common))
            res["4 demo tracks tester"] = (ok, f"{len(common)} shared days; same sign {sign_ok}/{len(common)}; "
                                              f"demo {sum(by_day_demo[d] for d in common):+.2f} vs tester {sum(by_day_test[d] for d in common):+.2f}; mean |diff|/day {mad:.2f}")
    return res


def rerun_tester():
    """tester over DEMO_START->now on the PEP runner with the EA's source defaults (= the demo config:
    EntryHour 1 / ExitHour 4 / FixedLots 0.01 / StopATRMult 1.5). Reuses rolling_retest's run_job, which
    refuses to publish on a dead login or stale history (the rule-6 bench precondition)."""
    import rolling_retest as rr
    rr.WINDOW_DAYS = (datetime.now() - DEMO_START).days + 1
    name = "SESSDRIFT-demo-window"
    setlines = [f"{k}={v}" for k, v in DEMO_INPUTS.items()]
    rr.run_job(name, dict(expert="Marius SessionDrift GOLD", symbol="XAUUSD", setlines=setlines, deposit=5000))
    for rp in rr.report_paths(f"retest_{name}"):
        if os.path.exists(rp): return rp
    return None


def report_inputs_ok(path):
    """bench precondition for item 4: the report's own Inputs line must equal the demo config."""
    import re
    raw = io.open(path, encoding="utf-16", errors="replace").read()
    i = raw.find("Inputs")
    seg = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw[i:i + 2000])) if i >= 0 else ""
    got = dict(re.findall(r"(\w+)=([\w.\-]+)", seg))
    bad = {k: (got.get(k), v) for k, v in DEMO_INPUTS.items() if k != "MagicNumber" and got.get(k) != v}
    return (not bad), bad


def live_removal(baseline_worst):
    import painwindow_check  # noqa (import check only)
    since = datetime.now() - timedelta(days=28)
    out = {}
    for acct, (path, login) in LIVE.items():
        try: m = mt5_connect(path, login)
        except SystemExit as e: out[acct] = (None, str(e)); continue
        eps = episodes(m, since); atr = atr_d1(m, since=since)
        if not eps: out[acct] = (None, "no live episodes for 88231 in 28d"); continue
        net = sum(e["net"] for e in eps); worst = min(e["net"] for e in eps)
        remove = net < 0 or worst < 1.5 * baseline_worst
        out[acct] = (remove, f"{len(eps)} eps / net {net:+.2f} / worst {worst:+.2f} vs limit {1.5*baseline_worst:+.2f}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tester", help="tester report .htm covering the demo window (gate item 4)")
    ap.add_argument("--rerun", action="store_true", help="produce that report on the PEP runner first")
    ap.add_argument("--live", action="store_true", help="the live removal rule instead of the promotion gate")
    ap.add_argument("--min-eps", type=int, default=20)
    ap.add_argument("--baseline-worst", type=float, default=BASELINE_WORST)
    a = ap.parse_args()

    if a.live:
        print("SESSIONDRIFT LIVE REMOVAL RULE (rolling 28d; remove if net<0 or an episode < 1.5x demo worst)")
        for acct, (rem, msg) in live_removal(a.baseline_worst).items():
            print(f"  [{'REMOVE' if rem else ('n/a' if rem is None else 'keep')}] {acct}: {msg}")
        return

    m = mt5_connect(DEMO_PATH, DEMO_LOGIN)
    eps = sorted(episodes(m, SWITCH_DAY - timedelta(days=1)), key=lambda e: e["open"])
    atr = atr_d1(m)
    print(f"SESSIONDRIFT PROMOTION GATE  (demo since {DEMO_START:%Y-%m-%d}; review {REVIEW_DAY:%Y-%m-%d}; today {datetime.now():%Y-%m-%d})")
    print(f"  pre-switch record: {PRE_SWITCH['note']}")
    for e in eps:
        print(f"  {e['open']:%m-%d %H:%M} {e['dir']} {e['lots']:.2f} -> {e['close']:%H:%M}  {e['net']:+7.2f}")
    tester = None
    if a.rerun:
        rp = rerun_tester()
        if rp is None: print("  !! tester rerun produced no report (see rolling_retest alerts)")
        else: a.tester = rp; print(f"  tester report: {rp}")
    if a.tester:
        import painwindow_check as pw
        ok, bad = report_inputs_ok(a.tester)
        if not ok:
            print(f"  !! tester report ran the WRONG config (report Inputs vs demo): {bad} -- item 4 NOT scored on it")
        else:
            tester = pw.parse_report(a.tester)
    res = gate(eps, atr, a.min_eps, a.baseline_worst, tester)
    allok = True
    for k, (ok, msg) in res.items():
        allok &= ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {k}: {msg}")
    if tester is None:
        print("  [FAIL] 4 demo tracks tester: not checked (no report, or the report ran the wrong config)")
        allok = False
    days_left = (REVIEW_DAY - datetime.now()).days
    print(f"  VERDICT: {'PROMOTABLE' if allok else 'HOLD'}" + (f" (review in {days_left}d -- a PASS before the date does not shorten the hold)" if days_left > 0 else ""))
    m.shutdown()


if __name__ == "__main__":
    main()
