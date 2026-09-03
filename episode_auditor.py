#!/usr/bin/env python3
"""
EPISODE AUDITOR (Layer 2, 2026-08-08) — the fragility ledger, for EVERY EA on EVERY account.

Samples each account's book per stream every POLL seconds. An EPISODE = the life of a
stream's open book (first position -> flat). Records the book's DEEPEST float, peak,
max legs, and on close the realized net — then computes the MARGINS aggregate stats hide:
    margin-to-floor = how close the episode came to its catastrophe floor
    knife-edge flag = episode consumed > 60% of its floor budget

The 08-08 lesson this instrument encodes: a config can post PF 2/RF 4 while its episodes
survive by pennies — the path decides. This ledger measures the pennies, live, on the
accounts that matter, so fragility TRENDS are visible before a floor fires.

Covers: LIVE 51511633 (GridStat gold / fib C / oil RSQ2 / silver — armed the moment
trading is re-enabled; zero rows while halted) + DEMO TWIN 61586543 (was 61552687 until 2026-08-31) (GridStat-FIBC8 /
fib C / oil SOLID). One connection at a time -> accounts sampled sequentially per cycle.

Output: analysis_data/episode_ledger.csv (append; one row per completed episode)
State:  analysis_data/episode_state.json (episodes in progress; restart-safe)
Run:    python episode_auditor.py --watch 60     (loop; task "GridStat Episode Auditor")
        python episode_auditor.py                (single sample pass)
Sampling note: 60s sampling under-estimates true intrabar extremes — margins recorded
are OPTIMISTIC bounds; treat trends, not absolutes.
"""
import os, io, sys, csv, json, time
from datetime import datetime, timedelta
import MetaTrader5 as mt5
from alerts import alert

HERE = os.path.dirname(os.path.abspath(__file__))
ADIR = os.path.join(HERE, "analysis_data")
LEDGER = os.path.join(ADIR, "episode_ledger.csv")
STATE = os.path.join(ADIR, "episode_state.json")

# ---- OPERATOR FLOAT LINE (2026-08-25, user request: "a variable I can manage — e.g. -$100").
# When any stream's live book float crosses BELOW this line, an AMBER alert fires (toast +
# Telegram) showing the float and that stream's ladder lines. ADVISORY ONLY — informs, never
# trades (the Sentinel doctrine). Edit the number; the auditor task picks it up on restart.
FLOAT_LINE_USD = -100.0
FLOAT_LINE_OVERRIDES = {}   # optional per-stream, e.g. {"oil-SOLID": -150.0}

# account -> terminal path, login, {magic: (label, symbol, floor % of balance)}
ACCOUNTS = {
    "LIVE": dict(
        path=r"C:\Program Files\Pepperstone MetaTrader 5\terminal64.exe",
        login=51511633,
        streams={
            59955: ("GridStat-gold", "XAUUSD", 20.0),   # SF12C2(+FIBC8 at re-enable), floor 20
            4901:  ("fibC",          "XAUUSD", 20.0),   # XC lock floor 20
            77180: ("oil-SOLID",     "SpotCrude", 10.0),  # 2026-09-01: was 66705 (retired RSQ2 build) ->
                                                              # live oil had NO ledger rows at all until this fix
            59801: ("silver",        "XAGUSD", 20.0),   # paused; harmless to watch
        }),
    "DEMO": dict(
        path=r"C:\MT5 Pepperstone Instance 2\terminal64.exe",
        login=61586543,   # new demo twin 2026-08-31 (old 61552687 'expired'/force-flat)
        streams={
            59955: ("GridStat-gold", "XAUUSD", 20.0),
            4901:  ("fibC",          "XAUUSD", 20.0),
            4902:  ("fibC-SR6",      "XAUUSD", 20.0),   # STATE-RELEASE forward, side-by-side vs 4901 (2026-08-24)
            77180: ("oil-SOLID",     "SpotCrude", 10.0),
            59956: ("gold-DAYRANK",  "XAUUSD", 20.0),    # S29 K3x1.5 cell, side-by-side vs 59955 (2026-08-18)
            77181: ("oil-DAYRANK",   "SpotCrude", 10.0), # S29 K3x1.25 cell, side-by-side vs 77180
            88231: ("sessiondrift",  "XAUUSD", 50.0),   # SessionDrift v0.2 fwd test (no floor mechanism; 50 = ledger-only placeholder)
        }),
    "DEON": dict(   # 2nd live acct — discovered FUNDED $1,965 on 2026-08-10; fib C attached 08-08
        path=r"C:\MT5 Pepperstone Instance Deon\terminal64.exe",
        login=51527827,
        streams={
            4901:  ("fibC",          "XAUUSD", 20.0),
            59955: ("GridStat-gold", "XAUUSD", 20.0),   # OLD build — user removing; watched anyway
            77180: ("oil-SOLID",     "SpotCrude", 10.0),  # 2026-09-01: was 66705 (retired RSQ2 build)
        }),
}
KNIFE_EDGE_CONSUMED = 0.60      # episode used >60% of its floor budget -> knife-edge

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def connect(path, login):
    for _ in range(2):
        try: mt5.shutdown()
        except Exception: pass
        if mt5.initialize(path=path):
            ai = mt5.account_info()
            if ai and ai.login == login:
                return ai
        time.sleep(2)
    return None


def load_state():
    try: return json.load(open(STATE))
    except Exception: return {}


def save_state(s): json.dump(s, open(STATE, "w"), indent=1)


def append_ledger(row):
    new = not os.path.exists(LEDGER)
    with open(LEDGER, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["closed", "account", "stream", "started", "hours", "legs_max",
                        "deepest", "deepest_pct_bal", "floor_pct", "margin_pct",
                        "budget_consumed", "peak_float", "realized_net", "verdict"])
        w.writerow(row)


def realized_since(magic, symbol, start_ts):
    # NOTE 2026-09-01: MT5 deal times are SERVER time (Pepperstone = local +3h). Using
    # datetime.now() as the upper bound made every deal from the last ~3h invisible -- and the
    # episode's CLOSING batch is always inside that window, because this runs the instant the
    # positions go flat. Result: realized_net silently dropped the final close on every episode
    # (38 of the first 47 ledger rows read exactly 0.00; the 08-21 oil floor read +938.49, the
    # harvests only, with its -584.32 floor cut missing). Look a day ahead of local time.
    deals = mt5.history_deals_get(datetime.fromtimestamp(start_ts - 60),
                                  datetime.now() + timedelta(days=1)) or []
    pm = {}
    for d in deals:
        if d.entry == 0:
            pm[d.position_id] = d.magic
    net = 0.0
    for d in deals:
        if d.entry == 1 and d.symbol == symbol and pm.get(d.position_id, d.magic) == magic:
            net += d.profit + d.swap + d.commission
    return round(net, 2)


def sample_account(acct, cfg, state, exposures=None):
    ai = connect(cfg["path"], cfg["login"])
    if ai is None:
        # only nag about LIVE when it's supposed to be up; a closed terminal = one quiet line
        print(f"{datetime.now():%H:%M} auditor: {acct} terminal unreachable")
        return state
    bal = ai.balance
    if exposures is not None and acct in ("LIVE", "DEON"):     # family heat: LIVE accounts only
        ex = {}
        for p in (mt5.positions_get() or []):
            ex[p.symbol] = ex.get(p.symbol, 0.0) + (p.volume if p.type == 0 else -p.volume)
        exposures[acct] = ex
    for magic, (label, symbol, floor_pct) in cfg["streams"].items():
        pos = [p for p in (mt5.positions_get(symbol=symbol) or []) if p.magic == magic]
        fl = sum(p.profit + p.swap for p in pos)
        key = f"{acct}:{magic}"
        ep = state.get(key)
        if pos:
            if ep is None:                       # episode opens
                state[key] = dict(start=time.time(), deepest=fl, peak=fl,
                                  legs=len(pos), bal=bal)
            else:
                ep["deepest"] = min(ep["deepest"], fl)
                ep["peak"] = max(ep["peak"], fl)
                ep["legs"] = max(ep["legs"], len(pos))
            line = FLOAT_LINE_OVERRIDES.get(label, FLOAT_LINE_USD)
            ep = state[key]
            if line < 0 and fl <= line and not ep.get("line_alerted"):
                ep["line_alerted"] = True
                alert(f"[{acct}] {label} float {fl:+.2f} crossed your {line:.0f} line "
                      f"({len(pos)} leg(s); floor -{floor_pct:.0f}% = {-floor_pct/100*bal:,.0f}$ on bal {bal:,.0f})", "AMBER")
            elif ep.get("line_alerted") and fl > line * 0.5:
                ep["line_alerted"] = False   # re-arm once it has recovered half-way back
        elif ep is not None:                     # episode CLOSED -> ledger row
            deep = ep["deepest"]; b0 = ep.get("bal") or bal
            deep_pct = -deep / b0 * 100 if deep < 0 else 0.0
            margin = floor_pct - deep_pct
            consumed = deep_pct / floor_pct if floor_pct else 0
            net = realized_since(magic, symbol, ep["start"])
            verdict = ("FLOOR" if consumed >= 0.99 else
                       "KNIFE-EDGE" if consumed >= KNIFE_EDGE_CONSUMED else
                       "healthy")
            hrs = (time.time() - ep["start"]) / 3600
            append_ledger([datetime.now().strftime("%Y-%m-%d %H:%M"), acct, label,
                           datetime.fromtimestamp(ep["start"]).strftime("%Y-%m-%d %H:%M"),
                           f"{hrs:.1f}", ep["legs"], f"{deep:.2f}", f"{deep_pct:.2f}",
                           floor_pct, f"{margin:.2f}", f"{consumed:.2f}",
                           f"{ep['peak']:.2f}", f"{net:.2f}", verdict])
            print(f"{datetime.now():%H:%M} EPISODE CLOSED [{acct}] {label}: net {net:+.2f}, "
                  f"deepest {deep:.2f}, floor-margin {margin:.1f}pp -> {verdict}")
            if verdict == "FLOOR":
                alert(f"[{acct}] {label} episode hit the FLOOR: net {net:+.2f} (deepest {deep:.2f})", "RED")
            elif verdict == "KNIFE-EDGE":
                alert(f"[{acct}] {label} episode was KNIFE-EDGE: net {net:+.2f}, "
                      f"used {float(consumed)*100:.0f}% of floor budget", "AMBER")
            del state[key]
    return state


GUARD_LOG = r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\Common\Files\book_guard_alerts.csv"
HEAT_FILE = os.path.join(ADIR, "family_heat.json")
# family-wide net-exposure alert thresholds (lots, LIVE accounts only; ~$12/pt gold, ~$90/pt oil at limit)
HEAT_LIMITS = {"XAUUSD": 0.12, "SpotCrude": 0.90}


def write_family_heat(state, exposures):
    """exposures: {acct: {symbol: net_lots}} for LIVE accounts. Publishes the combined view
    + AMBER alert on threshold cross (once per hot period per symbol)."""
    fam = {}
    for acct, syms in exposures.items():
        for sym, net in syms.items():
            fam.setdefault(sym, {})[acct] = round(net, 2)
    out = {"ts": datetime.now().strftime("%Y-%m-%d %H:%M"), "symbols": {}}
    for sym, per in fam.items():
        total = round(sum(per.values()), 2)
        out["symbols"][sym] = {"per_account": per, "family_net": total,
                               "limit": HEAT_LIMITS.get(sym)}
        lim = HEAT_LIMITS.get(sym)
        hotkey = f"_heat_{sym}"
        if lim and abs(total) >= lim:
            if not state.get(hotkey):
                alert(f"FAMILY HEAT: combined live {sym} exposure {total:+.2f} lots "
                      f"(limit {lim}) across both accounts — correlated book running hot", "AMBER")
                state[hotkey] = True
        else:
            state.pop(hotkey, None)
    try:
        json.dump(out, open(HEAT_FILE, "w"), indent=1)
    except Exception:
        pass
    return state

def check_guard(state):
    """Relay Book Guard EA events (Common\\Files log) to toast/phone."""
    try:
        sz = os.path.getsize(GUARD_LOG)
    except OSError:
        return state
    prev = state.get("_guard_sz", 0)
    if sz > prev:
        try:
            lines = io.open(GUARD_LOG, encoding="utf-8", errors="replace").read().splitlines()
            for ln in lines[-3:]:
                alert(f"BOOK GUARD: {ln}", "RED")
        except Exception:
            pass
    state["_guard_sz"] = sz
    return state


def main():
    watch = None
    if "--watch" in sys.argv:
        i = sys.argv.index("--watch")
        watch = int(sys.argv[i+1]) if i+1 < len(sys.argv) and sys.argv[i+1].isdigit() else 60
    state = load_state()
    accts = " + ".join(f"{k} {c['login']}" for k, c in ACCOUNTS.items())
    print(f"{datetime.now():%H:%M} EPISODE AUDITOR armed ({accts}; "
          f"{'loop ' + str(watch) + 's' if watch else 'single pass'}) -> {LEDGER}")
    while True:
        exposures = {}
        for acct, cfg in ACCOUNTS.items():
            state = sample_account(acct, cfg, state, exposures)
        state = write_family_heat(state, exposures)
        state = check_guard(state)
        save_state(state)
        if not watch: break
        time.sleep(watch)
    try: mt5.shutdown()
    except Exception: pass


if __name__ == "__main__":
    main()
