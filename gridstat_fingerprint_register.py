#!/usr/bin/env python3
"""
FINGERPRINT REGISTER — the single management view (GOLD + OIL).
Fuses the three sources into one lifecycle table per fingerprint:
  - LIVE GATE DB  (what's trading + the gate win-rate)          = the OLD/official view
  - LIVE MINER    (real per-fingerprint results on live trades) = the GOOD? view
  - SHADOW REFRESH(fresh reproduction win-rate, analysis_data)  = the NEW/candidate view

Each fingerprint gets a STATUS + ACTION so you can manage them like a portfolio:
  NEW        -> in shadow, not in the gate            -> confirm (EA-shadow) then onboard
  GOOD       -> trading + live-confirmed winner       -> SIZE UP
  UNDERPERF  -> trading + live-losing (n>=MINLIVE)    -> review -> drop candidate
  ACCUMULATE -> trading, too few live closes yet       -> hands off, keep gathering
  FLIP-DOWN  -> trading but shadow now below gate      -> confirm -> drop candidate
  IDLE       -> in gate but never fired live yet       -> watch

Read-only. Writes a dated register + appends the current state to a rolling CSV so
changes over time are trackable. Run: python gridstat_fingerprint_register.py
"""
import os, io, csv, sys
from datetime import datetime, timedelta
import MetaTrader5 as mt5
import gridstat_fingerprint_mi as mi   # reuse connect / mine / bt_winrates / parse_log_trades
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass

HERE = os.path.dirname(os.path.abspath(__file__))
ADIR = os.path.join(HERE, "analysis_data")
MINLIVE = 15          # live closes/fingerprint before a live verdict is trusted
WINBAR  = 0.55        # live win-rate to call a fingerprint GOOD

# stream -> (miner cfg key, gate threshold or None, live gate DB, shadow research DB)
# THE SELECTOR each engine actually decides on (2026-09-01 fix):
#   gate      = the win-rate gate, where THAT is the selector (gold: StatsFilterEnabled+MinWinRate)
#   sizing    = the sizing table, where THAT is the selector (oil: mult 0.00 == the engine skips it).
#               Point it at the exact file the locked EA names, or the register reports
#               fingerprints as "trading" that the engine will never trade.
#   cand_bar  = win-rate bar used ONLY to nominate NEW candidates from fresh shadow data,
#               kept separate from the trading gate so a stream whose selector is not a
#               win-rate gate (oil) can still surface upcoming fingerprints.
#   regime_wr = a sell the sizing table zeroes can still fire via UseRegimeSells while the
#               regime is DOWN if its win-rate clears this -> status REGIME-ONLY.
REG = {
    "GOLD": dict(sym="XAUUSD",    gate=0.55, sizing=None,
                 research="gridstat_setups_gold_research.csv", cand_bar=0.55, regime_wr=None),
    "OIL":  dict(sym="SpotCrude", gate=None, sizing="gridstat_sizing_oil_research.csv",
                 research="gridstat_setups_oil_research.csv",  cand_bar=0.55, regime_wr=0.60),
}


# STANDING DECISIONS — fingerprints already adjudicated, with the reason. Without this the
# register re-nominates them on every refresh (the weekly "would ADMIT ..." nag) and the
# operator has to re-derive a decision that was made months ago with evidence. A standing NO
# does not hide the row; it stamps it so a real NEW candidate is distinguishable at a glance.
STANDING_NO = {
    ("GOLD", "SELL|HR_LDN|ATR_NORM"):
        "STANDING NO (2026-08-17): LDN sits in the structurally negative half of the day "
        "(gold AM -0.015R vs PM +0.170R, replicated on oil); a 0.55 crest here is sample "
        "noise on a coin-flip. Re-admit only with the 4-layer countersign answering that.",
}


def sizing_mults(path):
    """setup_key -> size multiplier from the EA's sizing table. mult 0.00 == engine SKIPS it."""
    if not path:
        return None
    fp = _research_path(path)
    if not fp:
        return None
    out = {}
    for r in csv.DictReader(io.open(fp, encoding="utf-8", errors="replace")):
        try:
            out[r["setup_key"].strip()] = float(r["size_mult"])
        except (KeyError, ValueError, AttributeError):
            pass
    return out

def _research_path(path):
    """fresh research CSVs may live in shared Common\\Files (headless tester) or analysis_data."""
    for base in (mi.COMMON, ADIR):
        p = os.path.join(base, path)
        if os.path.exists(p): return p
    return None

def research_wr(path):
    p = _research_path(path)
    if not p: return {}
    rows = list(csv.reader(io.open(p, encoding="utf-8", errors="replace")))
    ix = {h.strip(): i for i, h in enumerate(rows[0])}
    kc, rc = ix.get("setup_key", 0), ix.get("r_multiple")
    tmp = {}
    for r in rows[1:]:
        if rc is None or len(r) <= rc: continue
        try: tmp.setdefault(r[kc].strip(), []).append(float(r[rc]))
        except ValueError: pass
    return {k: (len(v), sum(1 for x in v if x > 0)/len(v)) for k, v in tmp.items()}

def research_wr_by_regime(path, day_regime):
    """Layer-2 regime split: fingerprint -> {'UP': (n, wr), 'DOWN': (n, wr)} using the
    instrument's 5-day momentum sign on each signal's date (day_regime: date->'UP'/'DOWN')."""
    p = _research_path(path)
    if not p: return {}
    rows = list(csv.reader(io.open(p, encoding="utf-8", errors="replace")))
    ix = {h.strip(): i for i, h in enumerate(rows[0])}
    kc, rc, tc = ix.get("setup_key", 0), ix.get("r_multiple"), ix.get("entry_time", 1)
    tmp = {}
    for r in rows[1:]:
        if rc is None or len(r) <= rc: continue
        try:
            rm = float(r[rc])
            day = r[tc].strip()[:10]           # "2026.08.05"
        except (ValueError, IndexError): continue
        reg = day_regime.get(day)
        if reg is None: continue
        d = tmp.setdefault(r[kc].strip(), {"UP": [], "DOWN": []})
        d[reg].append(rm)
    out = {}
    for k, d in tmp.items():
        out[k] = {reg: (len(v), (sum(1 for x in v if x > 0)/len(v)) if v else None)
                  for reg, v in d.items()}
    return out

def build_day_regime(sym):
    """date -> 'UP'/'DOWN' from the D1 5-day momentum sign (needs an open MT5 connection)."""
    r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_D1, 0, 300)
    if r is None or len(r) < 10: return {}, None
    out = {}
    c, t = r['close'], r['time']
    for i in range(5, len(r)):
        day = datetime.fromtimestamp(int(t[i])).strftime("%Y.%m.%d")
        out[day] = "UP" if c[i] > c[i-5] else "DOWN"
    cur = "UP" if c[-1] > c[-6] else "DOWN"
    return out, cur

def classify(in_gate, gate, gate_wr, ln, lwin, lnet, sh_n, sh_wr,
             mult=None, regime_only=False, cand_bar=None, known=False):
    live_ok = ln is not None and ln >= MINLIVE
    bar = cand_bar if cand_bar is not None else gate
    if not in_gate:
        # Explicitly zeroed by the engine's own sizing table = a decision ALREADY MADE.
        # It is not a candidate and must never show size-up progress.
        if known and mult is not None and mult == 0:
            if regime_only:
                return "REGIME-ONLY", "fires only while crash-state/D1-bearish (sizing 0.00)"
            return "ZEROED", "sizing 0.00 = engine SKIPS it (already decided)"
        if bar is not None and sh_wr is not None and sh_wr >= bar and sh_n >= MINLIVE:
            return "NEW", "confirm (EA-shadow) -> onboard"
        return "NEW-thin", "watch shadow (needs samples/edge)"
    # in the gate (trading)
    flip_down = gate is not None and sh_wr is not None and sh_n >= MINLIVE and sh_wr < gate
    if live_ok:
        if lwin >= WINBAR and lnet > 0:
            return "GOOD", "SIZE UP (versioned)"
        if lnet < 0:
            return "UNDERPERF", "review -> DROP candidate"
        return ("FLIP-DOWN" if flip_down else "OK",
                "confirm -> drop candidate" if flip_down else "hold")
    if ln and ln > 0:
        return "ACCUMULATE", f"hands off ({ln}/{MINLIVE} live)"
    return "IDLE", "in gate, no live fills yet"

def main():
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"FINGERPRINT REGISTER | {stamp}\n")

    # evidence from BOTH accounts (live halted -> the demo twin carries the record)
    per_all = {}          # (stream label) -> merged fingerprint results
    deals_by_acct = {}
    for acct, acfg in mi.ACCOUNTS.items():
        if not mi.connect(acfg["path"], acfg["login"]):
            print(f"[{acct}] not connected — its evidence skipped"); continue
        deals_by_acct[acct] = mt5.history_deals_get(datetime(2026,7,13), datetime.now()+timedelta(days=1)) or []
        if acct == "LIVE":            # regimes computed once, while connected
            global _DAYREG, _CURREG
            _DAYREG, _CURREG = {}, {}
            for label, cfg in REG.items():
                _DAYREG[label], _CURREG[label] = build_day_regime(cfg["sym"])
        mt5.shutdown()

    reg_rows = []
    for label, cfg in REG.items():
        gate = cfg["gate"]
        # merge LIVE + DEMO mining for this symbol
        per = {}
        for acct, deals in deals_by_acct.items():
            micfg = mi.ACCOUNTS[acct]["streams"].get(cfg["sym"])
            if not micfg: continue
            p, _, _ = mi.mine(cfg["sym"], micfg, deals)
            for k, v in p.items():
                a = per.setdefault(k, [0, 0, 0.0])
                a[0] += v[0]; a[1] += v[1]; a[2] += v[2]
        live_gate = mi.bt_winrates(mi.ACCOUNTS["LIVE"]["streams"][cfg["sym"]]["bt"])
        mults = sizing_mults(cfg.get("sizing"))
        shadow = research_wr(cfg["research"])
        by_reg = research_wr_by_regime(cfg["research"], _DAYREG.get(label, {}))
        curreg = _CURREG.get(label)
        keys = sorted(set(live_gate) | set(per) | set(shadow),
                      key=lambda k: -(per.get(k,[0])[0]))
        selector = ("win-rate gate %s" % gate if gate else
                    "sizing table %s (mult 0.00 = skip)" % cfg["sizing"] if mults is not None
                    else "OFF (trades all)")
        print(f"===== {label} (selector: {selector}) "
              f"| {sum(v[0] for v in per.values())} closes (live+demo) | current regime: {curreg or '?'}")
        print(f"   {'fingerprint':30}{'status':12}{'mult':>6}{'gateWR':>7}{'N':>4}{'Win':>5}{'Net':>9}{'shWR':>6}{'wrUP':>7}{'wrDN':>7}  action")
        for k in keys:
            gn, gw = live_gate.get(k, (0, None))
            n, wins, net = per.get(k, [0, 0, 0.0])
            ln, lwin = (n, (wins/n if n else 0.0))
            sn, sw = shadow.get(k, (0, None))
            # Judge against the EA's REAL selector: gold = the win-rate gate; oil = the
            # sizing table, which the win-rate gate never sees.
            mult = mults.get(k) if mults is not None else None
            known = mults is not None and k in mults
            regime_only = (bool(cfg.get("regime_wr")) and k.startswith("SELL")
                           and gw is not None and gw >= cfg["regime_wr"])
            if mults is not None:
                in_gate = mult is not None and mult > 0
            else:
                in_gate = (k in live_gate) and (gate is None or (gw is not None and gw >= gate))
            status, action = classify(in_gate, gate, gw, ln if n else None, lwin, net, sn, sw,
                                      mult=mult, regime_only=regime_only,
                                      cand_bar=cfg.get("cand_bar"), known=known)
            standing = STANDING_NO.get((label, k))
            if standing and status in ("NEW", "NEW-thin"):
                status, action = "NEW-BLOCKED", standing
            # REGIME COLUMNS + the governance flag: in-gate fingerprint whose win-rate in the
            # CURRENT regime falls below the gate (n>=8) = regime-conditional -> suspend candidate
            rg = by_reg.get(k, {})
            un, uw = rg.get("UP", (0, None)); dn, dw = rg.get("DOWN", (0, None))
            cur_n, cur_w = (un, uw) if curreg == "UP" else (dn, dw) if curreg == "DOWN" else (0, None)
            if in_gate and gate and cur_w is not None and cur_n >= 8 and cur_w < gate:
                action = f"⚠ REGIME-BLOCKED candidate (wr {100*cur_w:.0f}% in current {curreg}) · " + action
            gw_s = f"{100*gw:.0f}%" if gw is not None else "  -"
            sw_s = f"{100*sw:.0f}%" if sw is not None else " -"
            lw_s = f"{100*lwin:.0f}%" if n else "  -"
            uw_s = f"{100*uw:.0f}%({un})" if uw is not None else "-"
            dw_s = f"{100*dw:.0f}%({dn})" if dw is not None else "-"
            mu_s = f"{mult:.2f}" if mult is not None else "  -"
            if n or gn >= 5 or (sn >= 15):
                print(f"   {k:30}{status:12}{mu_s:>6}{gw_s:>7}{n:>4}{lw_s:>5}{net:>9.2f}{sw_s:>6}{uw_s:>7}{dw_s:>7}  {action}")
                reg_rows.append([stamp, label, k, status, mu_s.strip(), gw_s, n, lw_s,
                                 f"{net:.2f}", sw_s, uw_s, dw_s, curreg or "?", action])
        print()

    # persist: dated snapshot + rolling history (so new vs old is trackable over time)
    os.makedirs(ADIR, exist_ok=True)
    hdr = ["asof","stream","fingerprint","status","sizeMult","gateWR","liveN","liveWin","liveNet",
           "shadowWR","wrUp","wrDown","curRegime","action"]
    snap = os.path.join(ADIR, f"fingerprint_register_{datetime.now():%Y%m%d}.csv")
    with io.open(snap, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f); w.writerow(hdr); w.writerows(reg_rows)
    roll = os.path.join(ADIR, "fingerprint_register_history.csv")
    new = not os.path.exists(roll)
    with io.open(roll, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if new: w.writerow(hdr)
        w.writerows(reg_rows)
    print(f"register -> {snap}  (+ appended to fingerprint_register_history.csv)")
    print("MANAGE: GOOD -> gridstat_db_version.py promote (size-up, versioned) | NEW -> confirm via EA-shadow then promote |")
    print("        UNDERPERF/FLIP-DOWN -> drop after 2 reviews | log the decision in fingerprint_decisions.csv.")

if __name__ == "__main__":
    main()
