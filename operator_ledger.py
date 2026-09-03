#!/usr/bin/env python3
"""
OPERATOR-ACTION LEDGER (2026-08-23) -- the fourth layer's missing piece.

The book is automated; the OPERATOR is not. The record shows discretionary actions move
real money in BOTH directions:
  +  2026-08-05 stand-down       -- framework-driven, correct, avoided an unbounded day
  -  2026-07-21 oil hand-closes  -- 4 of 5 baskets closed at +$1..$6 vs a +$100 target
  -  2026-08-21 weekend flatten  -- -$342 MAIN / +$36 DEON while the EAs ran +$237

DESIGN RULE (user, 2026-08-23): this tool MEASURES, it NEVER GOVERNS.
No alerts, no blocking, no advice, no nudges. Every decision stays the operator's. The
ledger only makes the counterfactual visible afterwards, so the value of an intervention
becomes knowable instead of arguable.

  python operator_ledger.py scan               # auto-detect manual (magic 0) closes
  python operator_ledger.py mark <id|date> "why"
  python operator_ledger.py add "action" "why" # non-trade action (AutoTrading off, EA detach)
  python operator_ledger.py report

COUNTERFACTUAL METHOD (fixed 2026-08-23 after the first build marked to CURRENT price --
that made every closed short look brilliant purely because gold ran $400 in three weeks):
each action is marked at +24h and +72h AFTER the action, not at today's price. Those are
horizons on which the engine's own exit (target / trail / floor) plausibly resolves, so
the number answers "was this call right at the time" instead of accumulating weeks of
unrelated drift.
  delta > 0  =>  holding was better -- the action cost money
  delta < 0  =>  the action added value
Honest limit: still a price-path proxy, not a replay of what the EA would have done
(a held position changes later basket decisions). Read the sign and the size, not the cent.
"""
import os, io, csv, sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ADIR = os.path.join(HERE, "analysis_data")
LEDGER = os.path.join(ADIR, "operator_ledger.csv")
COLS = ["id", "time", "account", "action", "symbol", "side", "volume", "entry_price",
        "exit_price", "realised", "cf_24h", "delta_24h", "cf_72h", "delta_72h", "rationale"]
ACCOUNTS = {
    "MAIN": (r"C:\Program Files\Pepperstone MetaTrader 5\terminal64.exe", 51511633),
    "DEON": (r"C:\MT5 Pepperstone Instance Deon\terminal64.exe", 51527827),
}
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.makedirs(ADIR, exist_ok=True)


def load():
    if not os.path.exists(LEDGER):
        return []
    return list(csv.DictReader(io.open(LEDGER, encoding="utf-8")))


def save(rows):
    with io.open(LEDGER, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in COLS})


def price_at(mt5, symbol, when):
    """Close of the H1 bar at/after `when`; None if the feed has nothing there."""
    bars = mt5.copy_rates_from(symbol, mt5.TIMEFRAME_H1, when, 2)
    if bars is None or len(bars) == 0:
        return None
    return float(bars[-1]["close"])


def mark_row(mt5, r):
    """Fill cf/delta at +24h and +72h for one ledger row."""
    try:
        ep = float(r["entry_price"]); rl = float(r["realised"]); vol = float(r["volume"])
    except (ValueError, KeyError):
        return
    sym = r.get("symbol", "")
    if not sym or not ep:
        return
    si = mt5.symbol_info(sym)
    if si is None:
        return
    contract = si.trade_contract_size
    sign = 1 if r["side"] == "BUY" else -1
    t0 = datetime.strptime(r["time"], "%Y-%m-%d %H:%M")
    for hrs, ck, dk in ((24, "cf_24h", "delta_24h"), (72, "cf_72h", "delta_72h")):
        when = t0 + timedelta(hours=hrs)
        if when > datetime.utcnow():
            r[ck] = r[dk] = ""          # horizon not reached yet
            continue
        p = price_at(mt5, sym, when)
        if p is None:
            continue
        cf = (p - ep) * sign * vol * contract
        r[ck] = f"{cf:.2f}"
        r[dk] = f"{cf - rl:.2f}"


def scan(days=40):
    import MetaTrader5 as mt5
    rows = load()
    have = {r["id"] for r in rows}
    added = 0
    for name, (path, login) in ACCOUNTS.items():
        if not mt5.initialize(path=path):
            print(f"  {name}: terminal unreachable -- skipped")
            continue
        a = mt5.account_info()
        if a is None or a.login != login:
            print(f"  {name}: wrong login -- skipped")
            mt5.shutdown()
            continue
        deals = mt5.history_deals_get(datetime.now() - timedelta(days=days),
                                      datetime.now() + timedelta(days=1)) or []
        opens = {d.position_id: d for d in deals if d.entry == mt5.DEAL_ENTRY_IN}
        for d in deals:
            # a MANUAL close = a closing deal with no magic (every EA stamps its own)
            if d.entry != mt5.DEAL_ENTRY_OUT or d.magic != 0 or not d.symbol:
                continue
            did = f"{login}-{d.ticket}"
            if did in have:
                continue
            op = opens.get(d.position_id)
            was_long = (d.type == mt5.DEAL_TYPE_SELL)   # closing deal is the opposite side
            row = dict(
                id=did, time=f"{datetime.utcfromtimestamp(d.time):%Y-%m-%d %H:%M}", account=name,
                action="manual close", symbol=d.symbol, side="BUY" if was_long else "SELL",
                volume=f"{d.volume:.2f}", entry_price=f"{(op.price if op else 0.0):.2f}",
                exit_price=f"{d.price:.2f}",
                realised=f"{d.profit + d.swap + d.commission:.2f}",
                cf_24h="", delta_24h="", cf_72h="", delta_72h="", rationale="")
            mark_row(mt5, row)
            rows.append(row)
            added += 1
        mt5.shutdown()
    rows.sort(key=lambda r: r["time"])
    save(rows)
    print(f"scan: {added} new manual action(s) recorded ({len(rows)} total)")


def refresh():
    import MetaTrader5 as mt5
    rows = load()
    if not rows:
        return
    for name, (path, login) in ACCOUNTS.items():
        if not mt5.initialize(path=path):
            continue
        for r in rows:
            if r.get("symbol"):
                mt5.symbol_select(r["symbol"], True)
                mark_row(mt5, r)
        mt5.shutdown()
        break
    save(rows)


def report():
    rows = load()
    if not rows:
        print("ledger empty -- run:  python operator_ledger.py scan")
        return
    print(f"=== OPERATOR-ACTION LEDGER ({len(rows)} actions) ===")
    print(f"{'time':<17}{'acct':<6}{'sym':<10}{'side':<5}{'realised':>10}"
          f"{'d+24h':>10}{'d+72h':>10}  rationale")
    tot_r = t24 = t72 = 0.0
    n24 = n72 = 0
    byday = {}
    for r in rows:
        try:
            tot_r += float(r["realised"])
        except ValueError:
            pass
        for key, acc in (("delta_24h", "24"), ("delta_72h", "72")):
            v = r.get(key, "")
            if v:
                try:
                    val = float(v)
                    if acc == "24":
                        t24 += val
                        n24 += 1
                    else:
                        t72 += val
                        n72 += 1
                except ValueError:
                    pass
        d = r["time"][:10]
        try:
            byday.setdefault(d, [0.0, 0.0, 0])
            byday[d][0] += float(r["realised"])
            byday[d][1] += float(r.get("delta_24h") or 0)
            byday[d][2] += 1
        except ValueError:
            pass
        print(f"{r['time']:<17}{r['account']:<6}{r.get('symbol',''):<10}{r.get('side',''):<5}"
              f"{r['realised']:>10}{r.get('delta_24h',''):>10}{r.get('delta_72h',''):>10}"
              f"  {r.get('rationale','')[:34]}")

    print(f"\n--- BY INTERVENTION DAY (delta>0 = holding was better; delta<0 = the action helped) ---")
    for d in sorted(byday):
        rl, dl, n = byday[d]
        verdict = "action HELPED" if dl < 0 else "holding was better"
        print(f"  {d}  {n:2d} closes  realised {rl:+9.2f}   delta+24h {dl:+9.2f}   {verdict}")

    print(f"\ninterventions: {len(rows)} actions across {len(byday)} day(s)")
    print(f"realised on those actions: {tot_r:+,.2f}")
    if n24:
        v = "holding would have been better -- net cost" if t24 > 0 else "the actions ADDED value"
        print(f"cumulative delta at +24h ({n24} marked): {t24:+,.2f}  -> {v}")
    if n72:
        v = "holding would have been better -- net cost" if t72 > 0 else "the actions ADDED value"
        print(f"cumulative delta at +72h ({n72} marked): {t72:+,.2f}  -> {v}")
    print("\nKPI = intervention frequency and its cumulative delta.")
    print("This tool measures only; every decision remains the operator's.")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    if cmd == "scan":
        scan(); refresh(); report()
    elif cmd == "refresh":
        refresh(); report()
    elif cmd == "mark" and len(sys.argv) >= 4:
        rows = load()
        hit = 0
        for r in rows:
            if r["id"] == sys.argv[2] or r["time"].startswith(sys.argv[2]):
                r["rationale"] = sys.argv[3]
                hit += 1
        save(rows)
        print(f"rationale saved on {hit} row(s)")
        report()
    elif cmd == "add" and len(sys.argv) >= 4:
        rows = load()
        rows.append(dict(id=f"manual-{len(rows)+1}", time=f"{datetime.now():%Y-%m-%d %H:%M}",
                         account="", action=sys.argv[2], symbol="", side="", volume="",
                         entry_price="", exit_price="", realised="0.00",
                         cf_24h="", delta_24h="", cf_72h="", delta_72h="", rationale=sys.argv[3]))
        save(rows)
        print("action recorded")
        report()
    else:
        report()


if __name__ == "__main__":
    main()
