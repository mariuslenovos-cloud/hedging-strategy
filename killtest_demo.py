"""killtest_demo.py -- proves emergency_stop's close request on the DEMO with a throwaway 0.01 XAUUSD position (market must be open).
Writes analysis_data/killtest_result.txt. Scheduled once for the Monday open (2026-10-12 01:30 local); re-run by hand any time."""
import MetaTrader5 as mt5, time, io, datetime as dt, os
import emergency_stop as E
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "analysis_data", "killtest_result.txt")
lines = [f"KILLTEST {dt.datetime.now():%Y-%m-%d %H:%M:%S}"]
ai = E.attach(*E.ACCTS["DEMO"])
if not ai: lines.append("demo attach FAILED")
else:
    sym = "XAUUSD"; mt5.symbol_select(sym, True); t = mt5.symbol_info_tick(sym)
    r = mt5.order_send(dict(action=mt5.TRADE_ACTION_DEAL, symbol=sym, volume=0.01, type=mt5.ORDER_TYPE_BUY, price=t.ask, deviation=50, magic=0, comment="KILLTEST", type_filling=mt5.ORDER_FILLING_IOC))
    lines.append(f"open: {r.retcode} {r.comment}")
    time.sleep(3)
    p = [x for x in (mt5.positions_get(symbol=sym) or []) if x.comment == "KILLTEST"]
    lines.append(f"KILLTEST positions found: {len(p)}")
    for x in p:
        tk = mt5.symbol_info_tick(sym)
        req = dict(action=mt5.TRADE_ACTION_DEAL, position=x.ticket, symbol=sym, volume=x.volume, type=mt5.ORDER_TYPE_SELL, price=tk.bid, deviation=50, magic=0, comment="EMERGENCY STOP", type_filling=mt5.ORDER_FILLING_IOC)
        rr = mt5.order_send(req)
        if rr is None or rr.retcode not in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_DONE_PARTIAL):
            rr = mt5.order_send(dict(req, type_filling=mt5.ORDER_FILLING_FOK))
        lines.append(f"close: {getattr(rr,'retcode',None)} {getattr(rr,'comment','')}")
    time.sleep(3)
    left = len([x for x in (mt5.positions_get(symbol=sym) or []) if x.comment == "KILLTEST"])
    lines.append(f"KILLTEST left open: {left} -> {'PASS' if (p and left == 0) else 'FAIL'} | other demo positions: {len(mt5.positions_get() or [])}")
    mt5.shutdown()
io.open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n"); print("\n".join(lines))
