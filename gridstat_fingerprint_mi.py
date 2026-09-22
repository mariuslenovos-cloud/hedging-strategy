#!/usr/bin/env python3
"""
FINGERPRINT MINING on LIVE trades (GOLD + OIL).
Mine what we already have: per-fingerprint LIVE profitability vs the backtest
baseline, so we can ENHANCE (size up) the consistent live winners and drop
consistent live losers -- the AFML "rigor drives sizing" loop on LIVE ground truth.

Source of truth = the ACCOUNT DEALS (clean live record). The signal log supplies
each trade's fingerprint (DIR|session|ATR-regime); the log can be tester-polluted,
so we ANCHOR on real deals and only LOOK UP the fingerprint by (open time, dir).

Read-only. Run once: python gridstat_fingerprint_mi.py
Schedulable (the "automated refresh"): call from Task Scheduler / cron / --watch.
"""
import sys, csv, io, os, time
from datetime import datetime, timedelta
from collections import defaultdict
import MetaTrader5 as mt5

COMMON = r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\Common\Files"

# 2026-08-08 (Layer 2): mine BOTH accounts — the LIVE record (halted since 08-05; resumes
# at re-enable) AND the DEMO TWIN (the gap-meter, where the forward evidence accrues now).
# Same shared signal logs serve both (Common\Files is terminal-shared; nearest-time match).
# Magics this miner deliberately does NOT mine: they carry no GridStat setup fingerprint.
# framework_check (2) imports this so the omission is a declared scope, not a silent hole.
OUT_OF_SCOPE_MAGICS = {
    4901, 4902,                       # fib C XC / SR6F (Goldminer+hedge, own gate, no fingerprint log)
    88231, 88241,                     # SessionDrift / LongVol (clock / bracket engines)
    956272, 938413, 905928, 903865, 903878, 963769, 907634, 985578, 954801, 978941, 985139,   # MM shadow logger instances (985139 = m5 chart)
    59956, 77181,                     # DAYRANK challengers share the incumbents' signal log rows (attributed to 59955/77180)
}
ACCOUNTS = {
    "LIVE": dict(path=r"C:\Program Files\Pepperstone MetaTrader 5\terminal64.exe",
                 login=51511633,
                 streams={
        "XAUUSD":    dict(label="GOLD", magic=59955, log="gridstat_signals_XAUUSD.csv",    bt="gridstat_setups_gold.csv"),
        "SpotCrude": dict(label="OIL-SOLID", magic=77180, log="gridstat_signals_SpotCrude.csv", bt="gridstat_setups_oil_research.csv"),   # 2026-09-22: was 66705 (retired RSQ2) -- the 09-01 repoint missed the miner; every live-oil line shown since was the dead engine's July record
    }),
    "DEMO": dict(path=r"C:\MT5 Pepperstone Instance 2\terminal64.exe",
                 login=61586543,   # new demo twin 2026-08-31
                 streams={
        "XAUUSD":    dict(label="GOLD-FIBC8", magic=59955, log="gridstat_signals_XAUUSD.csv",    bt="gridstat_setups_gold.csv"),
        "SpotCrude": dict(label="OIL-SOLID",  magic=77180, log="gridstat_signals_SpotCrude.csv", bt="gridstat_setups_oil_research.csv"),
        # [08-19] S29 DAYRANK challengers (side-by-side vs the incumbents; own magics). They run
        # signal-log-SILENT -- the incumbent's per-symbol log carries the same signals, so the
        # fingerprint lookup matches their deals by open-time+dir exactly as it does the incumbents'.
        "XAUUSD-DR":    dict(label="GOLD-DAYRANK", symbol="XAUUSD",    magic=59956, log="gridstat_signals_XAUUSD.csv",    bt="gridstat_setups_gold.csv"),
        "SpotCrude-DR": dict(label="OIL-DAYRANK",  symbol="SpotCrude", magic=77181, log="gridstat_signals_SpotCrude.csv", bt="gridstat_setups_oil_research.csv"),
    }),
}

def connect(path, login):
    for _ in range(4):
        mt5.shutdown()
        if mt5.initialize(path=path):
            ai = mt5.account_info()
            if ai and ai.login == login:
                return True
        time.sleep(1)
    return False

def parse_log_trades(path):
    """TRADE rows -> list of (epoch_serverclock, dir, setup_key)."""
    out = []
    try:
        rows = list(csv.reader(io.open(path, encoding="utf-8", errors="replace")))
    except Exception:
        return out
    ix = {h.strip(): i for i, h in enumerate(rows[0])}
    for r in rows[1:]:
        if len(r) <= ix.get("decision", 9):
            continue
        if r[ix["decision"]].strip() != "TRADE":
            continue
        try:
            dt = datetime.strptime(r[ix["time"]].strip(), "%Y.%m.%d %H:%M")
        except ValueError:
            continue
        out.append((dt, r[ix["dir"]].strip(), r[ix["setup_key"]].strip()))
    return out

def bt_winrates(path):
    """backtest fingerprint -> (n, win_rate) from a setups DB."""
    agg = defaultdict(list)
    p = os.path.join(COMMON, path)
    if not os.path.exists(p):
        return {}
    rows = list(csv.reader(io.open(p, encoding="utf-8", errors="replace")))
    ix = {h.strip(): i for i, h in enumerate(rows[0])}
    kc, rc = ix.get("setup_key", 0), ix.get("r_multiple")
    for r in rows[1:]:
        if rc is None or len(r) <= rc:
            continue
        try:
            agg[r[kc].strip()].append(float(r[rc]))
        except ValueError:
            pass
    return {k: (len(v), sum(1 for x in v if x > 0)/len(v)) for k, v in agg.items()}

def _basket_id(comment):
    """extract the _B<id> basket tag (present when MaxConcurrentBaskets>1, e.g. oil); '' otherwise."""
    c = comment or ""; i = c.find("_B")
    if i < 0: return ""
    j = i + 2; num = ""
    while j < len(c) and c[j].isdigit(): num += c[j]; j += 1
    return num

def mine(sym, cfg, deals, livepos=None):
    sym = cfg.get("symbol", sym)   # [08-19] stream key may be an alias (same-symbol challengers); real symbol wins
    # per position: open time/dir/basket-id + realized net + close time
    pos = {}
    # [2026-09-22] TWO passes. The old loop filtered EVERY deal on the EA's magic -- but a hand-close,
    # a Book Guard flatten or a broker force-flat closes with magic 0, so those OUT deals were dropped,
    # the position never got a "close", and the WHOLE BASKET silently vanished from the record (live
    # oil read 3 baskets / 100% where the ledger has 3-3 incl. six hand-closes). Ownership belongs to
    # the OPENING deal; closes are matched by position_id whatever their magic.
    for d in deals:
        if d.symbol != sym or d.magic != cfg["magic"]:
            continue
        if d.entry == mt5.DEAL_ENTRY_IN and d.type in (0, 1):
            p = pos.setdefault(d.position_id, {})
            p["open"] = datetime.utcfromtimestamp(d.time)
            p["dir"]  = "BUY" if d.type == 0 else "SELL"
            p["bid"]  = _basket_id(d.comment)
    for d in deals:
        if d.symbol != sym or d.position_id not in pos:
            continue
        if d.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY) and d.type in (0, 1):
            p = pos[d.position_id]
            p["net"]   = p.get("net", 0.0) + d.profit + d.swap + d.commission
            p["close"] = datetime.utcfromtimestamp(d.time)
            if d.magic != cfg["magic"]: p["hand"] = True     # closed by something other than the EA
    closed = [p for p in pos.values() if "close" in p and "open" in p]
    openpos = [p for p in pos.values() if "close" not in p and "open" in p]
    if livepos:
        for pid, p in pos.items():
            if "close" not in p and pid in livepos: p["float"] = livepos[pid]

    # GROUP legs into BASKETS: a basket's legs (initiating entry + grid recovery adds)
    # all close together (one CloseBasket call). Cluster closed legs by close-time
    # proximity (<=5s) + same direction + same _B id. The WHOLE basket's net is credited
    # to the basket-INITIATING leg's fingerprint (recovery legs carry no signal).
    closed.sort(key=lambda p: p["close"])
    baskets, cur = [], []
    for p in closed:
        if cur and (p["close"] - cur[-1]["close"]).total_seconds() <= 5 \
           and p["dir"] == cur[-1]["dir"] and p["bid"] == cur[-1]["bid"]:
            cur.append(p)
        else:
            if cur: baskets.append(cur)
            cur = [p]
    if cur: baskets.append(cur)

    logtr = parse_log_trades(os.path.join(COMMON, cfg["log"]))
    def nearest_fp(t, direction, offset):
        best, bestd = None, timedelta(minutes=6)
        for lt, ld, key in logtr:
            if ld != direction: continue
            dd = abs((lt - (t + offset)))
            if dd < bestd: bestd, best = dd, key
        return best
    inits = [min(b, key=lambda x: x["open"]) for b in baskets]   # basket-initiating legs
    best_off, best_hits = timedelta(0), -1
    for oh in range(-3, 4):
        off = timedelta(hours=oh)
        hits = sum(1 for it in inits if nearest_fp(it["open"], it["dir"], off))
        if hits > best_hits:
            best_hits, best_off = hits, off

    per = defaultdict(lambda: [0, 0, 0.0, 0])   # baskets, wins, whole-basket net, hand-closed baskets
    unmatched = 0
    for legs in baskets:
        init = min(legs, key=lambda x: x["open"])
        net  = sum(x["net"] for x in legs)
        fp = nearest_fp(init["open"], init["dir"], best_off)
        if fp is None:
            unmatched += 1
            continue
        per[fp][0] += 1
        per[fp][1] += 1 if net > 0 else 0
        per[fp][2] += net
        per[fp][3] += 1 if any(x.get("hand") for x in legs) else 0
    # OPEN episodes (in flight -- e.g. a frozen pair): reported separately, never folded into win%
    opens = defaultdict(lambda: [0, 0.0])
    for p in openpos:
        fp = nearest_fp(p["open"], p["dir"], best_off) or "?"
        opens[fp][0] += 1; opens[fp][1] += p.get("float", 0.0)
    return per, unmatched, best_off, opens

def main():
    print(f"FINGERPRINT MINING (live + demo twin) | {datetime.now():%Y-%m-%d %H:%M}\n")
    for acct, acfg in ACCOUNTS.items():
        if not connect(acfg["path"], acfg["login"]):
            print(f"[{acct}] not connected — skipped\n"); continue
        deals = mt5.history_deals_get(datetime(2026, 7, 13), datetime.now() + timedelta(days=1)) or []
        livepos = {p.identifier: p.profit + p.swap for p in (mt5.positions_get() or [])}
        mt5.shutdown()
        for sym, cfg in acfg["streams"].items():
            per, unmatched, off, opens = mine(sym, cfg, deals, livepos)
            bt = bt_winrates(cfg["bt"])
            tot_n = sum(v[0] for v in per.values())
            print(f"===== [{acct}] {cfg['label']} ({sym}) | {tot_n} closed baskets fingerprinted"
                  f"{' (clock offset '+str(int(off.total_seconds()//3600))+'h)' if off else ''}"
                  f"{f' | {unmatched} unmatched' if unmatched else ''}")
            if not per:
                print("   (no closed trades yet)\n"); continue
            print(f"   {'fingerprint':30}{'N':>6}{'Win%':>7}{'Net$':>10}{'hand':>5}{'btN':>5}{'btWin%':>7}  read")
            for fp in sorted(per, key=lambda k: -per[k][2]):
                n, w, net, hand = per[fp]
                bn, bwr = bt.get(fp, (0, None))
                btw = f"{100*bwr:.0f}%" if bwr is not None else " -"
                if n < 5:
                    read = "thin (accumulating)"
                elif w/n >= 0.6 and net > 0:
                    read = "WINNER -> size-up candidate (needs 4-layer countersign)"
                elif net < 0:
                    read = "loser -> review"
                else:
                    read = "neutral"
                print(f"   {fp:30}{n:>6}{100*w/n:>6.0f}%{net:>10.2f}{hand:>5}{bn:>5}{btw:>7}  {read}")
            for fp, (on, fl) in opens.items():
                print(f"   {fp:30}{'OPEN':>6}{'':>7}{fl:>10.2f}{'':>5}{'':>5}{'':>7}  in flight ({on} leg{'s' if on!=1 else ''}) -- not in the stats above")
            print()
    print("NOTE: act on WINNER/loser only at n>=~15-20 per fingerprint, and promotion requires")
    print("the FOUR-LAYER countersign (regime + episode margins + re-test + register bar).")

if __name__ == "__main__":
    main()
