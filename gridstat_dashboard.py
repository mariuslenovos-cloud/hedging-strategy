#!/usr/bin/env python3
"""
GridStat live PERFORMANCE dashboard (priority C).
Pulls the live MT5 deal history via the Python API, splits by magic number
(GOLD/SILVER/OILCash), attributes by the POSITION's opening magic (so manual
closes still credit the right EA), and reports:
  - per-stream realized P&L / win% / PF / max DD
  - EXPECTED (validated backtest) vs LIVE  <-- the reference frame
  - portfolio combined DD + correlation (once enough data)
  - open positions + account balance/equity
-> writes gridstat_dashboard.html

Read-only: only reads account history + open positions; never trades.
Run once:   python gridstat_dashboard.py
Auto-watch: python gridstat_dashboard.py --watch 300     (regenerate every 300s)
"""
import sys, time
from datetime import datetime, timedelta
from collections import defaultdict
import statistics as st
from collections import Counter

try:
    import MetaTrader5 as mt5
except Exception as e:
    print("MetaTrader5 not available:", e); sys.exit(1)
try:
    import gridstat_signalscan as ss      # B: signal/decision reproducer (non-invasive)
except Exception:
    ss = None

MAGICS = {57502: "GOLD", 59917: "SILVER", 62092: "OILCash", 3168: "fibC-GOLD"}
START  = datetime(2025, 1, 1)

# validated backtest baselines (Dec2025-Jun2026 ~6.6mo locked configs; CLAUDE.md).
# PF / DD% / win% / trades-per-month are deposit-independent reference values.
EXPECTED = {
    "GOLD":    dict(pf=3.92, dd_pct=20.2, win=0.76, tr_mo=24),
    "SILVER":  dict(pf=2.60, dd_pct=8.7,  win=0.69, tr_mo=11),
    "OILCash": dict(pf=2.29, dd_pct=14.9, win=0.86, tr_mo=22),
    # fib C MT5 locked config (cap=3, 2.5yr GOLD backtest): PF 1.72 / 14.5% DD / ~60% leg-win / ~26 leg-closes per mo
    "fibC-GOLD": dict(pf=1.72, dd_pct=14.5, win=0.60, tr_mo=26),
}

def connect():
    for _ in range(3):
        if mt5.initialize() and mt5.account_info() is not None:
            return True
        time.sleep(1)
    print("MT5 not connected:", mt5.last_error(),
          "\n  -> open the MetaTrader 5 terminal and log into the account first.")
    return False

def stream_label(magic):
    return MAGICS.get(magic, "MANUAL" if magic == 0 else f"magic{magic}")

def metrics(closes):
    if not closes:
        return dict(n=0, net=0.0, win=0.0, pf=0.0, maxdd=0.0)
    pnl = [c[1] for c in closes]
    wins = [p for p in pnl if p > 0]; losses = [p for p in pnl if p < 0]
    run = peak = maxdd = 0.0
    for _, p in closes:
        run += p; peak = max(peak, run); maxdd = max(maxdd, peak - run)
    return dict(n=len(pnl), net=sum(pnl),
                win=(len(wins)/len(pnl) if pnl else 0),
                pf=((sum(wins)/-sum(losses)) if losses else (99.0 if wins else 0.0)),
                maxdd=maxdd)

def generate(refresh_sec, write=True):
    ai = mt5.account_info()
    if ai is None:                              # terminal dropped / not logged in
        mt5.initialize(); ai = mt5.account_info()
    if ai is None:
        msg = ("MT5 not connected - open the MetaTrader 5 terminal, log into the account, "
               "and keep it running. (account_info() returned None)")
        print("[" + datetime.now().strftime("%H:%M:%S") + "] " + msg)
        meta = f'<meta http-equiv="refresh" content="{refresh_sec}">' if refresh_sec else ''
        html = (f"<!DOCTYPE html><html><head><meta charset='utf-8'>{meta}</head>"
                f"<body style='font:14px Segoe UI;margin:24px'><h2>Dashboard offline</h2>"
                f"<p style='color:#c0252b'>&#9888; {msg}</p>"
                f"<p class=muted>{datetime.now():%Y-%m-%d %H:%M:%S} - will retry on next refresh.</p></body></html>")
        if write:
            with open("gridstat_dashboard.html", "w", encoding="utf-8") as fp: fp.write(html)
        return html
    to = datetime.now() + timedelta(days=1)
    deals = mt5.history_deals_get(START, to) or []

    pos_magic = {}; deposits = 0.0; first_trade = None
    for d in deals:
        if d.type == mt5.DEAL_TYPE_BALANCE:
            deposits += d.profit
        if d.entry == mt5.DEAL_ENTRY_IN and d.type in (mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL):
            pos_magic[d.position_id] = d.magic
            tt = datetime.fromtimestamp(d.time)
            first_trade = tt if first_trade is None else min(first_trade, tt)

    per = defaultdict(list); daily = defaultdict(lambda: defaultdict(float))
    for d in sorted(deals, key=lambda x: x.time):
        if d.entry != mt5.DEAL_ENTRY_OUT or d.type not in (mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL):
            continue
        lbl = stream_label(pos_magic.get(d.position_id, d.magic))
        t = datetime.fromtimestamp(d.time); pnl = d.profit + d.commission + d.swap
        per[lbl].append((t, pnl)); daily[lbl][t.date()] += pnl

    order = [l for l in ("GOLD", "SILVER", "OILCash", "MANUAL") if l in per] + \
            [l for l in per if l not in ("GOLD", "SILVER", "OILCash", "MANUAL")]
    M = {l: metrics(per[l]) for l in order}
    days_live = max(1, (datetime.now() - first_trade).days) if first_trade else 1

    ea = [l for l in ("GOLD", "SILVER", "OILCash", "fibC-GOLD") if l in per]
    comb = metrics(sorted([c for l in ea for c in per[l]], key=lambda x: x[0]))
    sum_dd = sum(M[l]["maxdd"] for l in ea)
    div = (sum_dd / comb["maxdd"]) if comb["maxdd"] > 0 else 0.0

    def corr(a, b):
        days = sorted(set(daily[a]) & set(daily[b]))
        if len(days) < 4: return None
        try: return st.correlation([daily[a][d] for d in days], [daily[b][d] for d in days])
        except Exception: return None

    pos = mt5.positions_get() or []
    open_by = defaultdict(lambda: [0, 0.0])
    for p in pos:
        l = stream_label(p.magic); open_by[l][0] += 1; open_by[l][1] += p.profit

    def f(x): return f"{x:,.2f}"
    def cls(x): return "pos" if x > 0 else ("neg" if x < 0 else "")

    # ========== B: recent signals (last 3 days), reproduced + cross-checked ==========
    devents = []
    if ss is not None:
        dbs2 = defaultdict(list)
        for d in deals:
            if d.entry == mt5.DEAL_ENTRY_IN and d.type in (mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL):
                dbs2[d.symbol].append(d.time)
        for sym, scfg in ss.STREAMS.items():
            try: devents += ss.scan(sym, scfg, 3, dbs2)
            except Exception as ex: print("  signalscan", sym, "err:", ex)
        devents.sort(key=lambda e: e["time"])

    # ========== A: operational status + alerts ==========
    ti = mt5.terminal_info()
    connected = bool(ti.connected) if ti else False
    autotrade = (bool(ti.trade_allowed) if ti else False) and bool(ai.trade_allowed)
    ping = (ti.ping_last/1000.0) if ti and ti.ping_last else 0.0
    nowts = datetime.now().timestamp(); wd = datetime.now().weekday()
    streams = list(ss.STREAMS) if ss else []
    feed = {}; last_trade = {}; last_signal = {}
    for sym in streams:
        tk = mt5.symbol_info_tick(sym)
        feed[sym] = (nowts - tk.time)/60.0 if tk and tk.time else 9999.0
        tms = [d.time for d in deals if d.symbol == sym and d.entry == mt5.DEAL_ENTRY_IN and d.type in (mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL)]
        last_trade[sym] = (nowts - max(tms))/3600.0 if tms else None
        ev = [e for e in devents if e["sym"] == sym]
        last_signal[sym] = (datetime.now() - ev[-1]["time"]).total_seconds()/3600.0 if ev else None
    alerts = []
    if not connected: alerts.append("Terminal NOT connected to broker")
    if not autotrade: alerts.append("AutoTrading is OFF")
    for sym in streams:
        if wd < 5 and feed[sym] > 20: alerts.append(f"{sym}: quotes stale {feed[sym]:.0f} min (chart frozen or market closed)")
    fpct = (ai.equity - ai.balance)/ai.balance*100 if ai.balance else 0
    if fpct < -10: alerts.append(f"Account floating {fpct:.0f}% (deep open drawdown)")
    def agestr(hh):
        if hh is None: return "<span class=muted>never</span>"
        return f"{hh*60:.0f} min" if hh < 2 else (f"{hh:.0f} h" if hh < 48 else f"{hh/24:.0f} d")
    sstat = ""
    for sym in streams:
        ob = open_by.get(sym, [0, 0.0]); fcls = "neg" if (wd < 5 and feed[sym] > 20) else ""
        sstat += (f"<tr><td><b>{sym}</b></td><td class='{fcls}'>{feed[sym]:.0f} min</td>"
                  f"<td>{agestr(last_signal[sym])}</td><td>{agestr(last_trade[sym])}</td>"
                  f"<td>{ob[0]}</td><td class='{cls(ob[1])}'>{f(ob[1])}</td></tr>")
    alerts_html = ("<div style='color:#c0252b;font-weight:bold;margin-top:6px'>&#9888; " + "<br>&#9888; ".join(alerts) + "</div>") if alerts else "<div class=pos style='margin-top:6px'>&#10003; no alerts</div>"
    status_html = (f"<h2>Status &amp; alerts</h2>"
        f"<table><tr><th>Connected</th><th>AutoTrading</th><th>Ping</th></tr>"
        f"<tr><td class='{'pos' if connected else 'neg'}'>{'yes' if connected else 'NO'}</td>"
        f"<td class='{'pos' if autotrade else 'neg'}'>{'on' if autotrade else 'OFF'}</td><td>{ping:.0f} ms</td></tr></table>"
        f"<table><tr><th>Stream</th><th>Quote age</th><th>Last signal</th><th>Last trade</th><th>Open</th><th>Float</th></tr>{sstat}</table>{alerts_html}")

    sig_sum = ""
    for sym in streams:
        ev = [e for e in devents if e["sym"] == sym]
        ntr = sum(1 for e in ev if e["decision"] == "TRADE"); nea = sum(1 for e in ev if e["ea_traded"] == "Y")
        sk = Counter(e["decision"].split("~")[0] for e in ev if e["decision"].startswith("SKIP"))
        sig_sum += f"<tr><td><b>{sym}</b></td><td>{len(ev)}</td><td>{ntr}</td><td>{nea}</td><td>{sk.most_common(1)[0][0] if sk else '&mdash;'}</td></tr>"
    sig_det = ""
    for e in devents[-15:]:
        dcls = "pos" if e["decision"] == "TRADE" else "muted"; eacls = "pos" if e["ea_traded"] == "Y" else ""
        sig_det += (f"<tr><td>{e['time']:%m-%d %H:%M}</td><td>{e['sym']}</td><td>{e['dir']}</td><td>{e['key']}</td>"
                    f"<td>{e['wr']:.2f}</td><td class='{dcls}'>{e['decision']}</td><td class='{eacls}'>{e['ea_traded']}</td></tr>")
    sig_panel = (f"<h2>Recent signals &amp; decisions (last 3 days)</h2>"
        f"<table><tr><th>Stream</th><th>Fires</th><th>Repro TRADE</th><th>EA traded</th><th>Top skip</th></tr>{sig_sum}</table>"
        f"<h3>Last 15 fires</h3><table><tr><th>Time</th><th>Sym</th><th>Dir</th><th>Fingerprint</th><th>WR</th><th>Decision</th><th>EA?</th></tr>{sig_det}</table>"
        f"<div class=muted>GOLD/SILVER trade/skip at the ADX &amp; ATR-regime boundaries are parity-approximate &mdash; trust the EA? column. OIL decisions are faithful.</div>")

    # ---------- HTML ----------
    perf_rows = ""
    for l in order:
        m = M[l]; ob = open_by.get(l, [0, 0.0])
        perf_rows += (f"<tr><td><b>{l}</b></td><td>{m['n']}</td>"
                      f"<td class='{cls(m['net'])}'>{f(m['net'])}</td><td>{m['win']*100:.0f}%</td>"
                      f"<td>{m['pf']:.2f}</td><td>{f(m['maxdd'])}</td>"
                      f"<td>{ob[0]}</td><td class='{cls(ob[1])}'>{f(ob[1])}</td></tr>")

    # expected vs live
    ev_rows = ""
    for l in ("GOLD", "SILVER", "OILCash", "fibC-GOLD"):
        e = EXPECTED[l]; m = M.get(l, dict(n=0, win=0, pf=0))
        live_tr_mo = (m["n"] / days_live * 30) if m["n"] else 0
        thin = m["n"] < 10
        live_pf  = "—" if thin else f"{m['pf']:.2f}"
        live_win = "—" if m["n"] == 0 else f"{m['win']*100:.0f}%"
        ratio = (live_tr_mo / e["tr_mo"]) if e["tr_mo"] else 0
        rcls = "pos" if ratio >= 0.7 else ("neg" if ratio < 0.4 else "")
        ev_rows += (f"<tr><td><b>{l}</b></td>"
                    f"<td>{e['tr_mo']}</td><td class='{rcls}'>{live_tr_mo:.0f}</td><td class='{rcls}'>{ratio*100:.0f}%</td>"
                    f"<td>{e['win']*100:.0f}%</td><td>{live_win}</td>"
                    f"<td>{e['pf']:.2f}</td><td>{live_pf}</td>"
                    f"<td>{m['n']}{' <span class=muted>(thin)</span>' if thin else ''}</td></tr>")

    cm = ""
    for i, a in enumerate(ea):
        for b in ea[i+1:]:
            c = corr(a, b)
            cm += f"<tr><td>{a} vs {b}</td><td>{'n/a' if c is None else f'{c:+.2f}'}</td></tr>"

    meta = f'<meta http-equiv="refresh" content="{refresh_sec}">' if refresh_sec else ''
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    out = f"""<!DOCTYPE html><html><head><meta charset="utf-8">{meta}
<title>GridStat Dashboard</title><style>
body{{font:13px Segoe UI,Arial;margin:24px;color:#1a1a1a}}
h1{{font-size:20px}} h2{{font-size:15px;margin-top:22px;border-bottom:1px solid #ccc;padding-bottom:4px}}
table{{border-collapse:collapse;margin-top:8px}} td,th{{border:1px solid #ccc;padding:5px 10px;text-align:right}}
td:first-child,th:first-child{{text-align:left}} th{{background:#f0f0f0}}
.pos{{color:#0a7d28}} .neg{{color:#c0252b}} .muted{{color:#888}}
</style></head><body>
<h1>GridStat Performance Dashboard</h1>
<div class="muted">Account {ai.login} ({ai.server}) &middot; {now}{' &middot; auto-refresh '+str(refresh_sec)+'s' if refresh_sec else ''}
 &middot; book age {days_live} day(s) &middot; deposits {f(deposits)}</div>

{status_html}

<h2>Account</h2>
<table><tr><th>Balance</th><th>Equity</th><th>Floating</th><th>Open positions</th></tr>
<tr><td>{f(ai.balance)}</td><td>{f(ai.equity)}</td><td class='{cls(ai.equity-ai.balance)}'>{f(ai.equity-ai.balance)}</td><td>{len(pos)}</td></tr></table>

<h2>Expected (validated backtest) vs Live</h2>
<table><tr><th>Stream</th><th>Exp tr/mo</th><th>Live tr/mo</th><th>vs exp</th><th>Exp win</th><th>Live win</th><th>Exp PF</th><th>Live PF</th><th>Live n</th></tr>
{ev_rows}</table>
<div class="muted">"Live tr/mo" = live trades extrapolated over the {days_live}-day book age (noisy while young). PF/win shown only once a stream has &ge;10 live trades. Frequency is the meaningful early signal: well below "vs exp" = the EA is trading too little (off, blocked, or no signal).</div>

<h2>Per-stream realized performance</h2>
<table><tr><th>Stream</th><th>Trades</th><th>Net P&amp;L</th><th>Win%</th><th>PF</th><th>Max DD</th><th>Open now</th><th>Float</th></tr>
{perf_rows}</table>

<h2>Portfolio (EA streams &mdash; combined book)</h2>
<table>
<tr><td>Combined net</td><td class='{cls(comb['net'])}'>{f(comb['net'])}</td></tr>
<tr><td>Combined max DD</td><td>{f(comb['maxdd'])}</td></tr>
<tr><td>Sum of individual DDs</td><td>{f(sum_dd)}</td></tr>
<tr><td>Diversification ratio</td><td>{div:.2f}x</td></tr></table>
<h3>Cross-stream correlation (daily realized P&amp;L)</h3>
<table><tr><th>Pair</th><th>corr</th></tr>{cm if cm else '<tr><td colspan=2 class=muted>not enough overlapping days yet</td></tr>'}</table>
<p class="muted">Read-only snapshot from live MT5 deal history. Correlation / combined-DD need months of data to be meaningful &mdash; treat as indicative until the book matures.</p>

{sig_panel}
</body></html>"""
    if write:
        with open("gridstat_dashboard.html", "w", encoding="utf-8") as fp:
            fp.write(out)
        print(f"[{now}] {ai.login} bal {f(ai.balance)} eq {f(ai.equity)} open {len(pos)} | "
              f"book {days_live}d | EA net {f(comb['net'])}")
        for l in ("GOLD", "SILVER", "OILCash", "fibC-GOLD"):
            m = M.get(l, dict(n=0, net=0, win=0, pf=0)); e = EXPECTED[l]
            live_mo = (m['n']/days_live*30) if m['n'] else 0
            print(f"   {l:>8}: live {m['n']:>2} tr ({live_mo:>4.0f}/mo vs exp {e['tr_mo']}/mo)  net {m['net']:>8.2f}")
    return out

_cache = {"html": "", "ts": 0.0}
def serve(port, ttl=20, browser_refresh=30):
    """tiny HTTP server: regenerates live from MT5 per request (cached <= ttl s)."""
    import socket
    from http.server import BaseHTTPRequestHandler, HTTPServer
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.split("?")[0] not in ("/", "/index.html", "/gridstat_dashboard.html"):
                self.send_response(404); self.end_headers(); return
            now = time.time()
            if now - _cache["ts"] > ttl:
                try: _cache["html"] = generate(browser_refresh, write=False); _cache["ts"] = now
                except Exception as e: _cache["html"] = f"<html><body><pre>error: {e}</pre></body></html>"
            b = _cache["html"].encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b))); self.end_headers()
            try: self.wfile.write(b)
            except Exception: pass
        def log_message(self, *a): pass
    try: ip = socket.gethostbyname(socket.gethostname())
    except Exception: ip = "127.0.0.1"
    try:
        srv = HTTPServer(("0.0.0.0", port), H)
    except OSError as e:
        print(f"Could not bind port {port}: {e}")
        print(f"  -> a dashboard is likely already running on it. Open http://localhost:{port}, or use another port:")
        print(f"     python gridstat_dashboard.py --serve 8050")
        return
    print(f"GridStat dashboard serving (Ctrl+C to stop):")
    print(f"   this PC : http://localhost:{port}")
    print(f"   network : http://{ip}:{port}   (phone/2nd screen on the same wifi; allow the port in Windows Firewall if blocked)")
    srv.serve_forever()

def main():
    args = sys.argv
    def argval(flag, default):
        if flag in args:
            i = args.index(flag)
            return int(args[i+1]) if i+1 < len(args) and args[i+1].isdigit() else default
        return None
    serveport = argval("--serve", 8000)
    watch = argval("--watch", 300)
    once = "--once" in args
    if not connect():
        if once:
            print("MT5 not connected - nothing to write. Open the terminal + log in first."); return
        print("  -> starting anyway; the page will show 'offline' and recover once MT5 is connected.")
    try:
        if once:
            generate(0); print("wrote gridstat_dashboard.html")
        elif watch is not None:
            print(f"watch mode: regenerating every {watch}s (Ctrl+C to stop). Open gridstat_dashboard.html in a browser.")
            while True:
                generate(watch); time.sleep(watch)
        else:
            serve(serveport if serveport is not None else 8000)   # DEFAULT = serve on 8000
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        mt5.shutdown()

if __name__ == "__main__":
    main()
