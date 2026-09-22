#!/usr/bin/env python3
"""
MISSION CONTROL — the live command center for the whole trading operation.
Reads the live Pepperstone account + the fingerprint register + the R&D factory
state and renders one beautiful, theme-aware page: book equity, per-stream health,
live positions with their grid/rescue levels, the fingerprint lifecycle board, and
the factory heartbeat.

Read-only. Run once:  python mission_control.py        -> mission_control.html
Auto-refresh:         python mission_control.py --watch 60
"""
import os, io, csv, sys, glob, time, json, html as _html
from datetime import datetime, timedelta
from collections import defaultdict
import MetaTrader5 as mt5

HERE = os.path.dirname(os.path.abspath(__file__))
ADIR = os.path.join(HERE, "analysis_data")
VDIR = os.path.join(HERE, "db_versions")
LIVE_TERMINAL = r"C:\Program Files\Pepperstone MetaTrader 5\terminal64.exe"
LIVE_LOGIN = 51511633

# stream identity: magic -> (label, symbol, categorical hue slot, anchor text)
STREAMS = {
    909090: dict(label="GUARD", sym="*",         hue="grey",   anchor_pf=0.0,  anchor="Book Guard v2 hedge legs (account-level, any symbol)"),
    59955: dict(label="GOLD",  sym="XAUUSD",    hue="gold",   anchor_pf=3.87, anchor="HPIN12 · PF 3.87"),  # 2026-09-22: was SF12C2/3.39 -- the live build has been HPIN12 since 09-04 15:08 (GUI anchor $5,952 / PF 3.87)
    77180: dict(label="OIL",   sym="SpotCrude", hue="oil",    anchor_pf=1.47, anchor="SOLID4 · PF 1.47"),  # 2026-09-01: was 66705 (retired RSQ2) -> live oil P&L was invisible here
    4901:  dict(label="fib C", sym="XAUUSD",    hue="fibc",   anchor_pf=1.72, anchor="LOCKED · PF 1.72 · OFF live since 08-22"),
    59801: dict(label="SILVER",sym="XAGUSD",    hue="silver", anchor_pf=2.00, anchor="PAUSED"),
}
START = datetime(2026, 8, 10)       # THE REBUILD ERA: go-live Monday (old era archived in CLAUDE.md — the
INIT_DEPOSIT = 2269.88              # melt-up wound stays out of the fixed builds' scorecards)

def connect():
    for _ in range(6):
        mt5.shutdown()
        if mt5.initialize(path=LIVE_TERMINAL):
            ai = mt5.account_info()
            if ai and ai.login == LIVE_LOGIN:
                return True
        time.sleep(1)
    return False

def gather():
    ai = mt5.account_info()
    ti = mt5.terminal_info()
    deals = mt5.history_deals_get(START, datetime.now() + timedelta(days=1)) or []
    pos = mt5.positions_get() or []
    ticks = {s["sym"]: mt5.symbol_info_tick(s["sym"]) for s in STREAMS.values()}
    atr = {}
    for s in set(x["sym"] for x in STREAMS.values()):
        r = mt5.copy_rates_from_pos(s, mt5.TIMEFRAME_D1, 0, 30)
        if r is not None and len(r) > 15:
            h, l, c = r['high'], r['low'], r['close']
            tr = [max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1])) for i in range(1, len(r))]
            atr[s] = sum(tr[-14:])/14
    # per-stream realized (attribute by opening position's magic)
    pos_magic = {}
    for d in deals:
        if d.entry == mt5.DEAL_ENTRY_IN and d.type in (0, 1):
            pos_magic[d.position_id] = d.magic
    streams = {m: dict(n=0, wins=0, gp=0.0, gl=0.0, net=0.0, man=0.0, mann=0, last=None, **cfg)
               for m, cfg in STREAMS.items()}
    equity_pts = []
    bal = INIT_DEPOSIT
    for d in sorted(deals, key=lambda x: x.time):
        if d.entry != mt5.DEAL_ENTRY_OUT or d.type not in (0, 1):
            continue
        mg = pos_magic.get(d.position_id, d.magic)
        pnl = d.profit + d.swap + d.commission
        bal += pnl
        equity_pts.append((d.time, round(bal, 2)))
        if mg in streams:
            s = streams[mg]; s["n"] += 1; s["net"] += pnl
            s["wins"] += 1 if pnl > 0 else 0
            (s.__setitem__("gp", s["gp"]+pnl) if pnl > 0 else s.__setitem__("gl", s["gl"]+pnl))
            s["last"] = d.time
            if d.magic == 0:                       # closing deal magic 0 = HAND-CLOSE, not the EA
                s["man"] += pnl; s["mann"] += 1
    # today / week
    now = datetime.now(); today0 = datetime(now.year, now.month, now.day)
    def since(dt0):
        return sum(d.profit+d.swap+d.commission for d in deals
                   if d.entry == mt5.DEAL_ENTRY_OUT and d.type in (0, 1)
                   and datetime.fromtimestamp(d.time) >= dt0)
    open_by = defaultdict(lambda: [0, 0.0])
    for p in pos:
        open_by[p.magic][0] += 1; open_by[p.magic][1] += p.profit + p.swap
    return dict(ai=ai, ti=ti, streams=streams, equity=equity_pts, pos=pos, ticks=ticks, atr=atr,
                today=since(today0), week=since(now - timedelta(days=7)), open_by=open_by)

def register_board():
    snaps = sorted(glob.glob(os.path.join(ADIR, "fingerprint_register_2*.csv")))
    if not snaps:
        return {}
    rows = list(csv.DictReader(io.open(snaps[-1], encoding="utf-8", errors="replace")))
    by = defaultdict(list)
    for r in rows:
        by[r["stream"]].append(r)
    return by

def factory_state():
    vers = defaultdict(int)
    for f in glob.glob(os.path.join(VDIR, "*.csv")):
        base = os.path.basename(f).split(".")[0]
        vers[base] += 1
    def mt(p): return datetime.fromtimestamp(os.path.getmtime(p)) if os.path.exists(p) else None
    return dict(
        versions=sum(vers.values()),
        last_refresh=mt(os.path.join(ADIR, "gridstat_setups_gold_research.csv")),
        last_run=mt(os.path.join(ADIR, "mi_daily.log")),
    )

# ---------- the FOUR-LAYER continuous-improvement engine (2026-08-08) ----------
COMMON = r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\Common\Files"
DEMO_TERMINAL = r"C:\MT5 Pepperstone Instance 2\terminal64.exe"
DEMO_LOGIN = 61586543   # new demo twin 2026-08-31 (old 61552687 broker-expired)
TESTED_END = datetime(2026, 7, 14)   # anchor-era boundary: Dec-01 -> Jul-13 = the validated window

_demo_cache = {"t": 0.0, "d": None}
def demo_state(max_age=300):
    """Snapshot of the DEMO TWIN (the gap-meter) — cached 5 min; restores the live connection."""
    if time.time() - _demo_cache["t"] < max_age:
        return _demo_cache["d"]
    d = None
    try:
        mt5.shutdown()
        if mt5.initialize(path=DEMO_TERMINAL):
            ai = mt5.account_info()
            if ai and ai.login == DEMO_LOGIN:
                pos = mt5.positions_get() or []
                by = defaultdict(lambda: [0, 0.0])
                for p in pos:
                    by[p.magic][0] += 1
                    by[p.magic][1] += p.profit + p.swap
                d = dict(balance=ai.balance, equity=ai.equity,
                         open={int(m): (v[0], round(v[1], 2)) for m, v in by.items()})
    except Exception:
        d = None
    finally:
        try: mt5.shutdown()
        except Exception: pass
        connect()                       # hand the connection back to the live terminal
    _demo_cache["t"] = time.time(); _demo_cache["d"] = d
    return d

def regime_sentinel():
    """LAYER 1 — is TODAY's market inside the envelope the strategies were validated in?
    Compares current ATR(14) + 3-day velocity against their distributions in the tested window."""
    out = []
    for sym, label in (("XAUUSD", "GOLD"), ("SpotCrude", "OIL")):
        r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_D1, 0, 260)
        if r is None or len(r) < 60:
            out.append(dict(sym=label, status="NO DATA", detail="feed unavailable")); continue
        h, l, c, t = r['high'], r['low'], r['close'], r['time']
        trs = [max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1])) for i in range(1, len(r))]
        atr = [sum(trs[i-13:i+1])/14 for i in range(13, len(trs))]
        atr_t = [int(t[i+1]) for i in range(13, len(trs))]
        vel = [abs(c[i]/c[i-3]-1)*100 for i in range(3, len(c))]
        vel_t = [int(t[i]) for i in range(3, len(c))]
        cut = TESTED_END.timestamp()
        atr_ref = [a for a, tt in zip(atr, atr_t) if tt < cut] or atr
        vel_ref = [v for v, tt in zip(vel, vel_t) if tt < cut] or vel
        cur_atr, cur_vel = atr[-1], max(vel[-3:])
        def pct(x, ref): return 100.0*sum(1 for v in ref if v <= x)/max(1, len(ref))
        pa, pv = pct(cur_atr, atr_ref), pct(cur_vel, vel_ref)
        med = sorted(atr_ref)[len(atr_ref)//2] or 1
        worst = max(pa, pv)
        status = "INSIDE" if worst < 90 else ("STRETCHED" if worst < 98 else "OUTSIDE")
        out.append(dict(sym=label, status=status, atr_pct=pa, vel_pct=pv, atr_x=cur_atr/med))
    return out

def db_ages():
    """Age of the gate DB each LIVE/FORWARD EA actually reads:
    GOLD LOCKED + fib C gate -> gridstat_setups_gold.csv; OIL SOLID LOCKED -> the research pair."""
    def mt(p): return datetime.fromtimestamp(os.path.getmtime(p)) if os.path.exists(p) else None
    return {"GOLD": mt(os.path.join(COMMON, "gridstat_setups_gold.csv")),
            "OIL": mt(os.path.join(COMMON, "gridstat_setups_oil_research.csv")),
            "SILVER": mt(os.path.join(COMMON, "gridstat_setups_silver_mt5.csv"))}

def layers_panel(sent, demo, fac, ages, now):
    """Render the four-layer engine cards."""
    PILL = {"INSIDE": "good", "FRESH": "good", "LIVE": "good",
            "STRETCHED": "warning", "QUEUED": "warning", "IDLING": "warning",
            "OUTSIDE": "serious", "STALE": "serious", "PLANNED": "muted", "NO DATA": "muted"}
    def card(title, status, rows):
        pill = PILL.get(status, "muted")
        body = "".join(f'<div class="crow" style="justify-content:space-between"><span>{a}</span><span class="mut">{b}</span></div>'
                       for a, b in rows)
        return (f'<div class="card"><div class="chead"><span class="cname">{title}</span>'
                f'<span class="badge {pill}">{status}</span></div>{body}</div>')
    def dago(dt):
        if not dt: return "never"
        d = (now - dt).days
        return f"{d}d ago" if d else "today"
    # L1
    worst = "INSIDE"
    rows1 = []
    for s in sent:
        rows1.append((f"{s['sym']}: {s['status']}",
                      f"ATR p{s.get('atr_pct',0):.0f} ({s.get('atr_x',0):.1f}× tested) · vel p{s.get('vel_pct',0):.0f}"
                      if 'atr_pct' in s else s.get('detail','')))
    worst = max((s['status'] for s in sent if s['status'] in ("INSIDE","STRETCHED","OUTSIDE")),
                key=lambda x: ["INSIDE","STRETCHED","OUTSIDE"].index(x), default="NO DATA")
    rows1.append(("vs Dec→Jul-13 validated window", "recalibrate what falls outside"))
    l1 = card("① Regime Sentinel", worst, rows1)
    # L2 — the fragility ledger (episode_auditor.py, LIVE + DEMO)
    drows = []
    if demo:
        drows.append(("demo twin (gap-meter)", f"bal ${demo['balance']:,.0f} · eq ${demo['equity']:,.0f}"))
        names = {59955: "GridStat gold", 4901: "fib C", 77180: "oil SOLID", 909090: "Book Guard hedge"}
        for m, (n, fl) in sorted(demo["open"].items()):
            drows.append((names.get(m, f"magic {m}"), f"{n} open · {fl:+,.0f}"))
    st_l2 = "QUEUED"
    stf = os.path.join(ADIR, "episode_state.json")
    alive = os.path.exists(stf) and (time.time() - os.path.getmtime(stf)) < 600
    led = os.path.join(ADIR, "episode_ledger.csv")
    if alive or os.path.exists(led):
        st_l2 = "LIVE" if alive else "IDLING"
        eps = []
        if os.path.exists(led):
            eps = list(csv.DictReader(io.open(led, encoding="utf-8")))
        knife = sum(1 for e in eps[-20:] if e["verdict"] in ("KNIFE-EDGE", "FLOOR"))
        drows.append(("auditor loop", "sampling (60s)" if alive else "not running"))
        drows.append((f"episodes recorded: {len(eps)}",
                      f"knife-edge/floor last 20: {knife}"))
        if eps:
            e = eps[-1]
            drows.append((f"last: [{e['account']}] {e['stream']}",
                          f"net {float(e['realized_net']):+,.0f} · margin {e['margin_pct']}pp · {e['verdict']}"))
        # family heat gauge (improvement #5): combined LIVE-accounts exposure per symbol
        hf = os.path.join(ADIR, "family_heat.json")
        if os.path.exists(hf):
            try:
                heat = json.load(open(hf))
                for sym, d in heat.get("symbols", {}).items():
                    tot, lim = d.get("family_net", 0), d.get("limit")
                    hot = lim and abs(tot) >= lim
                    drows.append((f"family heat {sym}",
                                  f"{tot:+.2f} lots{f' / limit {lim}' if lim else ''}{' ⚠HOT' if hot else ''}"))
            except Exception:
                pass
    else:
        drows.append(("episode-margin ledger", "no data yet"))
    l2 = card("② Episode Auditor", st_l2, drows)
    # L3 — weekly headless re-test (rolling_retest.py)
    rr = os.path.join(ADIR, "rolling_retest.csv")
    if os.path.exists(rr):
        rows3 = list(csv.DictReader(io.open(rr, encoding="utf-8")))
        last_date = rows3[-1]["date"] if rows3 else "—"
        age_ok = rows3 and (now - datetime.strptime(rows3[-1]["date"], "%Y-%m-%d")).days <= 8
        lrows = []
        latest = {}
        # [2026-09-22] only jobs that ran on the LAST run date: retired XM-era jobs (GOLD-FIBC8 -1,212, fibC-XC ...)
        # kept their August rows on the panel as if current -- a stale verdict shown as live.
        for r in rows3:
            if r["date"] == last_date: latest[r["job"]] = r
        for j, r in latest.items():
            lrows.append((j, f"net {float(r['net']):+,.0f} RF {r['rf']} · {r['verdict']}"))
        lrows.append(("last run", last_date))
        l3 = card("③ Rolling Re-test", "LIVE" if age_ok else "IDLING", lrows)
    else:
        l3 = card("③ Rolling Re-test", "PLANNED", [
            ("weekly trailing-8wk headless runs", "task Saturdays 09:00"),
            ("first run", "pending")])
    # L4
    stale = any(a and (now - a).days > 21 for a in ages.values() if a)
    gold_stale = ages.get("GOLD") and (now - ages["GOLD"]).days > 21
    rows4 = [(f"{k} gate DB", dago(v) + (" (audited 08-08: won its A/B, retained)" if k == "GOLD" else ""))
             for k, v in ages.items()]
    rows4.append(("daily loop", dago(fac["last_run"])))
    rows4.append(("miner", "mining LIVE + DEMO (nightly register)"))
    l4 = card("④ Data / Factory", "STALE" if gold_stale else ("LIVE" if fac["last_run"] and (now - fac["last_run"]).days < 2 else "IDLING"), rows4)
    return l1 + l2 + l3 + l4

# ---------- rendering ----------
def f(x, d=2): return f"{x:,.{d}f}"
def esc(s): return _html.escape(str(s))

def render(g, board, fac, refresh):
    ai = g["ai"]; now = datetime.now()
    conn = bool(g["ti"].connected) if g["ti"] else False
    auto = (bool(g["ti"].trade_allowed) if g["ti"] else False) and bool(ai.trade_allowed)
    total_net = ai.balance - INIT_DEPOSIT
    floating = ai.equity - ai.balance
    # equity sparkline path
    eq = g["equity"]
    spark = ""
    if len(eq) > 1:
        xs = [p[0] for p in eq]; ys = [p[1] for p in eq]
        x0, x1 = min(xs), max(xs); y0, y1 = min(ys), max(ys)
        W, H = 1000, 240; pad = 6
        def X(t): return pad + (W-2*pad) * (t-x0)/max(1, (x1-x0))
        def Y(v): return H-pad - (H-2*pad) * (v-y0)/max(1e-9, (y1-y0))
        pts = [(X(t), Y(v)) for t, v in eq]
        line = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        area = f"M{pts[0][0]:.1f},{H-pad} L" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts) + f" L{pts[-1][0]:.1f},{H-pad} Z"
        data = json.dumps([[X(t), Y(v), datetime.fromtimestamp(t).strftime("%m-%d %H:%M"), v] for t, v in eq])
        spark = f"""<svg id="eq" viewBox="0 0 {W} {H}" preserveAspectRatio="none">
          <defs><linearGradient id="eqg" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stop-color="var(--eq)" stop-opacity="0.22"/>
            <stop offset="1" stop-color="var(--eq)" stop-opacity="0"/></linearGradient></defs>
          <path d="{area}" fill="url(#eqg)"/>
          <path d="{line}" fill="none" stroke="var(--eq)" stroke-width="2.5" vector-effect="non-scaling-stroke"/>
          <line id="eqx" y1="{pad}" y2="{H-pad}" stroke="var(--muted)" stroke-width="1" style="display:none"/>
          <circle id="eqd" r="4.5" fill="var(--eq)" stroke="var(--surface)" stroke-width="2" style="display:none"/>
        </svg><div id="eqtip" class="tip"></div><script>window.__EQ={data};</script>"""

    # stat tiles
    def tile(label, val, sub="", cls=""):
        return f'<div class="tile"><div class="tl">{esc(label)}</div><div class="tv {cls}">{val}</div><div class="ts">{esc(sub)}</div></div>'
    net_cls = "up" if total_net >= 0 else "dn"
    flt_cls = "up" if floating >= 0 else "dn"
    # combined book drawdown from the realized equity curve + current draw from peak (incl. floating)
    peak = INIT_DEPOSIT; maxdd = 0.0
    for _, v in eq:
        peak = max(peak, v); maxdd = max(maxdd, peak - v)
    run_peak = max([INIT_DEPOSIT] + [v for _, v in eq])
    cur_dd = max(0.0, run_peak - ai.equity)
    dd_pct = maxdd/run_peak*100 if run_peak else 0
    tiles = "".join([
        tile("Balance", f"${f(ai.balance)}", f"era start 08-10 at ${f(INIT_DEPOSIT)}"),   # 2026-09-22: label said "$3,000 deposit" while P&L is vs the era start
        tile("Total P&L", f'{"+" if total_net>=0 else ""}${f(total_net)}', f"{total_net/INIT_DEPOSIT*100:+.1f}%", net_cls),
        tile("Equity", f"${f(ai.equity)}", f'floating {"+" if floating>=0 else ""}${f(floating)}', flt_cls),
        tile("Book DD", f"${f(maxdd)}", f"{dd_pct:.1f}% max · now ${f(cur_dd,0)}", "dn" if cur_dd > 1 else ""),
        tile("Today", f'{"+" if g["today"]>=0 else ""}${f(g["today"])}', "realized", "up" if g["today"]>=0 else "dn"),
        tile("Last 7 days", f'{"+" if g["week"]>=0 else ""}${f(g["week"])}', "realized, rolling", "up" if g["week"]>=0 else "dn"),   # 2026-09-22: was "This week" but computed rolling 7d (calendar week read -$16.57 vs +$81.86)
    ])

    # stream cards
    cards = ""
    for m, s in g["streams"].items():
        n, net = s["n"], s["net"]
        pf = (s["gp"]/abs(s["gl"])) if s["gl"] < 0 else (99 if s["gp"] > 0 else 0)
        win = (100*s["wins"]/n) if n else 0
        paused = s["label"] == "SILVER"
        ea_net = net - s["man"]                    # what the EA itself earned (hand-closes split out)
        # status light
        if paused: st, stt = "muted", "paused"
        elif not auto: st, stt = "muted", "halted"     # AutoTrading OFF: a stopped stream, not a failing one
        elif n == 0: st, stt = "warning", "idle"
        elif net > 0 and (pf >= s["anchor_pf"]*0.7 or n < 5): st, stt = "good", "on track"
        elif net > 0: st, stt = "good", "positive"
        else: st, stt = "serious", "below anchor"
        opn, opnfl = g["open_by"].get(m, [0, 0.0])
        cards += f"""<div class="card {s['hue']}{' pausd' if paused else ''}">
          <div class="chead"><span class="dot" style="background:var(--{s['hue']})"></span>
            <span class="cname">{esc(s['label'])}</span>
            <span class="badge {st}">{stt}</span></div>
          <div class="cnet {'up' if net>=0 else 'dn'}">{'+' if net>=0 else ''}${f(net)}</div>
          <div class="crow"><span>{n} closes</span><span>{win:.0f}% win</span><span>PF {pf:.2f}</span></div>
          <div class="cfoot">{esc(s['anchor'])}{f' · {opn} open ({"+" if opnfl>=0 else ""}${f(opnfl,0)})' if opn else ''}{f' · hand-closed {s["mann"]}× {"+" if s["man"]>=0 else ""}${f(s["man"],0)} → EA net {"+" if ea_net>=0 else ""}${f(ea_net,0)}' if s["mann"] else ''}</div>
        </div>"""

    # live positions — with entry/current/TP/recovery levels drawn in as a mini gauge
    def gauge(entry, tp, rec, now, floatpos):
        lv = [x for x in (entry, tp, rec, now) if x and x > 0]
        if len(lv) < 2: return ""
        lo, hi = min(lv), max(lv); span = (hi - lo) or 1
        def pc(v): return max(1, min(99, (v-lo)/span*100))
        mk = ""
        if tp: mk += f'<span class="mk tp" style="left:{pc(tp):.0f}%" title="TP/escape {tp}"></span>'
        if rec: mk += f'<span class="mk rc" style="left:{pc(rec):.0f}%" title="recovery add {rec:.3f}"></span>'
        mk += f'<span class="mk be" style="left:{pc(entry):.0f}%" title="entry {entry}"></span>'
        mk += f'<span class="mk now {"up" if floatpos>=0 else "dn"}" style="left:{pc(now):.0f}%" title="now {now}"></span>'
        return f'<div class="gauge"><div class="track"></div>{mk}</div>'
    posrows = ""
    for p in sorted(g["pos"], key=lambda x: (x.symbol, x.price_open)):
        sym = p.symbol; tk = g["ticks"].get(sym); px = tk.bid if tk else p.price_current
        rec = 0
        if sym in g["atr"]:
            sp = min(max(g["atr"][sym]/0.001*0.5, 300), 2000)*0.001 if sym == "SpotCrude" else g["atr"][sym]*0.5
            rec = (p.price_open - sp) if p.type == 0 else (p.price_open + sp)
        cls = "up" if p.profit >= 0 else "dn"
        posrows += f"""<tr><td><b>{esc(sym)}</b></td><td>{'BUY' if p.type==0 else 'SELL'}</td>
          <td class="num">{p.volume}</td><td class="num">{p.price_open}</td><td class="num">{px}</td>
          <td class="num">{p.tp or '—'}</td><td class="num {cls}">{'+' if p.profit>=0 else ''}{f(p.profit)}</td>
          <td>{gauge(p.price_open, p.tp, rec, px, p.profit)}</td></tr>"""
    if not posrows:
        posrows = '<tr><td colspan="8" class="mut" style="text-align:center;padding:18px">no open positions — flat</td></tr>'

    # fingerprint register board (grouped)
    STAT = {"GOOD": ("good", "🟢"), "UNDERPERF": ("serious", "🔻"), "FLIP-DOWN": ("serious", "🔻"),
            "ACCUMULATE": ("cat-blue", "📈"), "OK": ("cat-blue", "•"),
            "NEW": ("warning", "🆕"), "NEW-thin": ("muted", "·"), "IDLE": ("muted", "⏸")}
    def board_col(title, statuses, cap=6):
        items = [(stream, r) for stream, rows in board.items() for r in rows if r["status"] in statuses]
        # strongest first: prefer real live signal, then shadow WR
        items.sort(key=lambda sr: (-int(sr[1]["liveN"] or 0),
                                   -float((sr[1]["shadowWR"] or "0%").rstrip("%") or 0)))
        chips = ""
        for stream, r in items[:cap]:
            sc, ic = STAT.get(r["status"], ("muted", "·"))
            n = int(r["liveN"] or 0)
            extra = f'{r["liveNet"]}' if r["liveN"] != "0" else r["shadowWR"]
            glow = " glow" if r["status"] == "GOOD" else ""
            prog = ""
            if r["status"] in ("ACCUMULATE", "OK"):
                prog = (f'<div class="prog"><div class="pf" style="width:{min(100,n/15*100):.0f}%"></div></div>'
                        f'<span class="pn">{n}/15 to size-up</span>')
            chips += f"""<div class="chip {sc}{glow}"><span class="cs">{ic}</span>
              <span class="cf">{esc(stream)} · {esc(r['fingerprint'])}</span>
              <span class="cx">{esc(r['status'])} · live+demo {esc(r['liveN'])} · {esc(extra)}</span>{prog}</div>"""
        if len(items) > cap:
            chips += f'<div class="chip muted"><span class="cf mut">+{len(items)-cap} more</span></div>'
        if not chips: chips = '<div class="chip muted"><span class="cf mut">none</span></div>'
        return f'<div class="bcol"><div class="bth">{title}</div>{chips}</div>'
    boardhtml = (board_col("✅ GOOD — size up", {"GOOD"}) +
                 board_col("📈 Trading", {"ACCUMULATE", "OK"}) +
                 board_col("🆕 New / candidates", {"NEW", "NEW-thin"}) +
                 board_col("🔻 Review / drop", {"UNDERPERF", "FLIP-DOWN"}))

    # factory strip
    def ago(dt):
        if not dt: return "—"
        s = (now - dt).total_seconds()
        return f"{int(s//3600)}h ago" if s >= 3600 else f"{int(s//60)}m ago"
    onboard_n = sum(1 for rows in board.values() for r in rows if r["status"] == "NEW")
    drop_n = sum(1 for rows in board.values() for r in rows if r["status"] in ("UNDERPERF", "FLIP-DOWN"))
    fac_html = (f'<span>🆕 {onboard_n} onboard candidate{"s" if onboard_n!=1 else ""} · 🔻 {drop_n} to review</span>'
                f'<span>🗄 {fac["versions"]} DB versions</span>'
                f'<span>🔬 shadow refresh {ago(fac["last_refresh"])}</span>'
                f'<span>⏱ daily loop {ago(fac["last_run"])}</span>'
                f'<span>{"🟢 live" if conn else "🔴 offline"} · {"auto-trade on" if auto else "auto-trade OFF"}</span>')

    # four-layer engine panel
    layers = layers_panel(regime_sentinel(), demo_state(), fac, db_ages(), now)

    meta = f'<meta http-equiv="refresh" content="{refresh or 60}">'   # always auto-reload (default 60s)
    return TEMPLATE.format(meta=meta, now=now.strftime("%Y-%m-%d %H:%M:%S"),
        acct=ai.login, server=esc(ai.server), tiles=tiles, spark=spark,
        cards=cards, posrows=posrows, board=boardhtml, factory=fac_html, layers=layers)

TEMPLATE = r"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">{meta}
<title>Mission Control</title><style>
:root{{--gold:#eda100;--oil:#008300;--fibc:#2a78d6;--silver:#e87ba4;--eq:#2a78d6;
  --good:#0ca30c;--warning:#fab219;--serious:#ec835a;--critical:#d03b3b;--cat-blue:#2a78d6;
  --plane:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
  --grid:#e1e0d9;--border:rgba(11,11,11,.10);--up:#006300;--dn:#c0392b;}}
@media(prefers-color-scheme:dark){{:root:where(:not([data-theme=light])){{
  --gold:#c98500;--oil:#008300;--fibc:#3987e5;--silver:#d55181;--eq:#3987e5;
  --plane:#0d0d0d;--surface:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--muted:#898781;
  --grid:#2c2c2a;--border:rgba(255,255,255,.10);--up:#0ca30c;--dn:#e66767;}}}}
:root[data-theme=dark]{{--gold:#c98500;--oil:#008300;--fibc:#3987e5;--silver:#d55181;--eq:#3987e5;
  --plane:#0d0d0d;--surface:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--muted:#898781;
  --grid:#2c2c2a;--border:rgba(255,255,255,.10);--up:#0ca30c;--dn:#e66767;}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--plane);color:var(--ink);font:14px/1.4 system-ui,-apple-system,"Segoe UI",sans-serif;
  padding:20px;max-width:1180px;margin:0 auto}}
.top{{display:flex;align-items:baseline;gap:14px;margin-bottom:16px}}
.top h1{{font-size:19px;margin:0;letter-spacing:.06em;font-weight:700}}
.top .sub{{color:var(--muted);font-size:12.5px}}
.top .rt{{margin-left:auto;color:var(--muted);font-size:12px;font-variant-numeric:tabular-nums}}
.grid5{{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;margin-bottom:14px}}
.tile{{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:14px 16px}}
.tl{{color:var(--muted);font-size:11.5px;text-transform:uppercase;letter-spacing:.05em}}
.tv{{font-size:23px;font-weight:650;margin-top:3px}}.ts{{color:var(--ink2);font-size:12px;margin-top:2px}}
.up{{color:var(--up)}}.dn{{color:var(--dn)}}
.panel{{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:16px 18px;margin-bottom:14px}}
.ph{{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:0 0 12px}}
#eq{{width:100%;height:210px;display:block;overflow:visible}}
.tip{{position:absolute;pointer-events:none;background:var(--ink);color:var(--surface);font-size:11.5px;
  padding:5px 8px;border-radius:7px;transform:translate(-50%,-135%);white-space:nowrap;display:none;
  font-variant-numeric:tabular-nums;z-index:9}}
.grid4{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}
.card{{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:13px 15px;position:relative;overflow:hidden}}
.card:before{{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--fibc)}}
.card.gold:before{{background:var(--gold)}}.card.oil:before{{background:var(--oil)}}
.card.fibc:before{{background:var(--fibc)}}.card.silver:before{{background:var(--silver)}}
.card.pausd{{opacity:.55}}
.chead{{display:flex;align-items:center;gap:7px;margin-bottom:7px}}
.dot{{width:9px;height:9px;border-radius:50%}}.cname{{font-weight:650;font-size:13.5px}}
.badge{{margin-left:auto;font-size:10.5px;padding:2px 7px;border-radius:20px;border:1px solid var(--border);color:var(--ink2)}}
.badge.good{{color:var(--good);border-color:var(--good)}}.badge.serious{{color:var(--serious);border-color:var(--serious)}}
.badge.warning{{color:var(--warning);border-color:var(--warning)}}.badge.muted{{color:var(--muted)}}
.cnet{{font-size:21px;font-weight:650}}.crow{{display:flex;gap:12px;color:var(--ink2);font-size:12px;margin-top:3px}}
.cfoot{{color:var(--muted);font-size:11px;margin-top:6px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{text-align:left;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.04em;padding:0 8px 8px;font-weight:600}}
td{{padding:7px 8px;border-top:1px solid var(--grid)}}.num{{text-align:right;font-variant-numeric:tabular-nums}}
.mut{{color:var(--muted);font-size:12px}}
.board{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}
.bcol .bth{{font-size:11.5px;font-weight:650;margin-bottom:8px;color:var(--ink2)}}
.chip{{background:var(--plane);border:1px solid var(--border);border-radius:9px;padding:7px 9px;margin-bottom:7px}}
.chip .cs{{font-size:12px}}.chip .cf{{display:block;font-size:11.5px;font-weight:600;margin:1px 0}}
.chip .cx{{display:block;font-size:10.5px;color:var(--muted);font-variant-numeric:tabular-nums}}
.chip.good{{border-left:3px solid var(--good)}}.chip.serious{{border-left:3px solid var(--serious)}}
.chip.warning{{border-left:3px solid var(--warning)}}.chip.cat-blue{{border-left:3px solid var(--cat-blue)}}
.chip.muted{{opacity:.7}}
.chip.glow{{border:1px solid var(--good);box-shadow:0 0 0 1px var(--good);animation:pulse 1.6s ease-in-out infinite}}
@keyframes pulse{{0%,100%{{box-shadow:0 0 0 1px var(--good),0 0 4px rgba(12,163,12,.15)}}50%{{box-shadow:0 0 0 1px var(--good),0 0 16px rgba(12,163,12,.55)}}}}
.prog{{height:4px;background:var(--grid);border-radius:3px;margin-top:6px;overflow:hidden}}
.prog .pf{{height:100%;background:var(--cat-blue);border-radius:3px}}
.pn{{display:block;font-size:9.5px;color:var(--muted);margin-top:2px}}
.gauge{{position:relative;height:20px;width:150px}}
.gauge .track{{position:absolute;top:9px;left:0;right:0;height:3px;border-radius:2px;background:var(--grid)}}
.gauge .mk{{position:absolute;top:4px;width:2px;height:13px;transform:translateX(-1px)}}
.gauge .mk.tp{{background:var(--good)}}.gauge .mk.rc{{background:var(--serious)}}
.gauge .mk.be{{background:var(--muted);opacity:.6}}
.gauge .mk.now{{top:6px;width:9px;height:9px;border-radius:50%;transform:translateX(-4.5px);border:2px solid var(--surface)}}
.gauge .mk.now.up{{background:var(--good)}}.gauge .mk.now.dn{{background:var(--dn)}}
.factory{{display:flex;flex-wrap:wrap;gap:18px;color:var(--ink2);font-size:12px;
  background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:11px 16px}}
@media(max-width:820px){{.grid5,.grid4,.board{{grid-template-columns:repeat(2,1fr)}}}}
</style></head><body>
<div class="top"><h1>◆ MISSION CONTROL</h1>
  <span class="sub">Pepperstone {acct} · {server}</span>
  <span class="rt">{now}</span></div>
<div class="grid5">{tiles}</div>
<div class="panel"><div class="ph">Book equity — since go-live</div>{spark}</div>
<div class="panel"><div class="ph">Streams</div><div class="grid4">{cards}</div></div>
<div class="panel"><div class="ph">Continuous-improvement engine — the four layers</div><div class="grid4">{layers}</div></div>
<div class="panel"><div class="ph">Live positions</div>
  <table><tr><th>symbol</th><th>side</th><th class="num">lots</th><th class="num">entry</th>
    <th class="num">now</th><th class="num">TP</th><th class="num">float</th><th>next level</th></tr>
    {posrows}</table></div>
<div class="panel"><div class="ph">Fingerprint register — lifecycle</div><div class="board">{board}</div></div>
<div class="factory">{factory}</div>
<script>
var svg=document.getElementById('eq');
if(svg&&window.__EQ){{var D=window.__EQ,x=document.getElementById('eqx'),dot=document.getElementById('eqd'),tip=document.getElementById('eqtip');
var vb=svg.viewBox.baseVal;
svg.addEventListener('mousemove',function(e){{var r=svg.getBoundingClientRect();var mx=(e.clientX-r.left)/r.width*vb.width;
var best=D[0],bd=1e9;for(var i=0;i<D.length;i++){{var d=Math.abs(D[i][0]-mx);if(d<bd){{bd=d;best=D[i];}}}}
var sx=r.left+best[0]/vb.width*r.width,sy=r.top+best[1]/vb.height*r.height;
x.setAttribute('x1',best[0]);x.setAttribute('x2',best[0]);x.style.display='';
dot.setAttribute('cx',best[0]);dot.setAttribute('cy',best[1]);dot.style.display='';
tip.style.display='';tip.style.left=sx+'px';tip.style.top=sy+'px';
tip.innerHTML='$'+best[3].toLocaleString(undefined,{{minimumFractionDigits:2}})+' &middot; '+best[2];}});
svg.addEventListener('mouseleave',function(){{x.style.display='none';dot.style.display='none';tip.style.display='none';}});}}
</script></body></html>"""

def serve(port):
    """Live server: regenerates the page FRESH on every request, no-cache -> always current
    (avoids the file:// browser-cache trap). One process; leave it running."""
    from http.server import BaseHTTPRequestHandler, HTTPServer
    def page(refresh):
        if mt5.account_info() is None:      # reconnect if the terminal dropped
            connect()
        return render(gather(), register_board(), factory_state(), refresh)
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                body = page(15).encode("utf-8")          # refresh every 15s while live
            except Exception as e:
                body = (f"<body style='font:14px system-ui;padding:24px'>"
                        f"<h3>Mission Control — momentary error</h3><pre>{esc(e)}</pre>"
                        f"<p>retrying on next refresh…</p><meta http-equiv=refresh content=5></body>").encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.end_headers(); self.wfile.write(body)
        def log_message(self, *a): pass
    print(f"\n  Mission Control is LIVE at:  http://localhost:{port}\n"
          f"  Open that in your browser and leave this window running. Ctrl+C to stop.\n")
    try:
        HTTPServer(("127.0.0.1", port), H).serve_forever()
    except KeyboardInterrupt:
        print("stopped.")
    finally:
        mt5.shutdown()

def main():
    args = sys.argv[1:]
    def argnum(flag, default):
        if flag in args:
            i = args.index(flag)
            return int(args[i+1]) if i+1 < len(args) and args[i+1].isdigit() else default
        return None
    port = argnum("--serve", 8770)
    watch = argnum("--watch", 60)
    if not connect():
        print("Not connected to the live Pepperstone account (51511633). Open the terminal + log in."); return
    if port is not None:                    # LIVE SERVER (recommended) — always-fresh, no cache
        serve(port); return
    try:                                    # file mode (one-shot, or --watch loop)
        while True:
            g = gather()
            out = render(g, register_board(), factory_state(), watch)
            with io.open(os.path.join(HERE, "mission_control.html"), "w", encoding="utf-8") as fp:
                fp.write(out)
            print(f"[{datetime.now():%H:%M:%S}] mission_control.html  | bal ${g['ai'].balance:,.2f} "
                  f"eq ${g['ai'].equity:,.2f} | {len(g['pos'])} open")
            if watch is None: break
            time.sleep(watch)
    except KeyboardInterrupt:
        print("stopped.")
    finally:
        mt5.shutdown()

if __name__ == "__main__":
    main()
