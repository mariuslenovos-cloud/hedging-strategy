"""emergency_stop.py -- the MANUAL KILL SWITCH (2026-10-11, user: "in case the accounts start making huge losses and I want to stop it").
Closes every open position on an account (all magics), deletes pending orders, then shuts that terminal down so no engine
re-enters. DRY RUN by default: it lists what it WOULD do. Add --confirm to act. This is the one place Python touches the book,
and only on the user's explicit command.
  python emergency_stop.py MAIN            -> dry run (list positions, orders, float)
  python emergency_stop.py MAIN --confirm  -> close all + delete pendings + stop the terminal
  python emergency_stop.py MAIN --confirm --keep-terminal   -> flatten but leave the terminal running (guard stays up)
Restart afterwards: Start-Process "<terminal path>" ; the terminal reloads its charts and EAs and logs in by itself."""
import sys, time, datetime as dt
import MetaTrader5 as mt5
ACCTS = {"MAIN": (r"C:\Program Files\Pepperstone MetaTrader 5\terminal64.exe", 51511633),
         "DEON": (r"C:\MT5 Pepperstone Instance Deon\terminal64.exe", 51527827),
         "DEMO": (r"C:\MT5 Pepperstone Instance 2\terminal64.exe", 61586543)}

def attach(path, login):
    for _ in range(8):
        mt5.shutdown()
        if mt5.initialize(path=path):
            ai = mt5.account_info()
            if ai and ai.login == login: return ai
        time.sleep(1)
    return None

def close_all(confirm):
    closed = []; failed = []
    for p in (mt5.positions_get() or []):
        tick = mt5.symbol_info_tick(p.symbol)
        req = dict(action=mt5.TRADE_ACTION_DEAL, position=p.ticket, symbol=p.symbol, volume=p.volume,
                   type=mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY,
                   price=tick.bid if p.type == mt5.POSITION_TYPE_BUY else tick.ask, deviation=50, magic=0,
                   comment="EMERGENCY STOP", type_filling=mt5.ORDER_FILLING_IOC)
        if not confirm:
            closed.append((p.ticket, p.symbol, p.volume, round(p.profit, 2), "WOULD CLOSE")); continue
        r = mt5.order_send(req)
        if r is None or r.retcode not in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_DONE_PARTIAL):
            r2 = mt5.order_send(dict(req, type_filling=mt5.ORDER_FILLING_FOK))
            if r2 is None or r2.retcode not in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_DONE_PARTIAL):
                failed.append((p.ticket, p.symbol, p.volume, getattr(r, "retcode", None), getattr(r, "comment", ""))); continue
        closed.append((p.ticket, p.symbol, p.volume, round(p.profit, 2), "CLOSED"))
    for o in (mt5.orders_get() or []):
        if confirm: mt5.order_send(dict(action=mt5.TRADE_ACTION_REMOVE, order=o.ticket))
        closed.append((o.ticket, o.symbol, o.volume_current, 0.0, "PENDING " + ("DELETED" if confirm else "WOULD DELETE")))
    return closed, failed

def main():
    name = (sys.argv[1] if len(sys.argv) > 1 else "").upper(); confirm = "--confirm" in sys.argv; keep = "--keep-terminal" in sys.argv
    if name not in ACCTS: print("usage: python emergency_stop.py MAIN|DEON|DEMO [--confirm] [--keep-terminal]"); sys.exit(2)
    path, login = ACCTS[name]
    ai = attach(path, login)
    if not ai: print(f"!! cannot attach to {name} ({login}) -- is the terminal running? To stop engines without it: Stop-Process on {path}"); sys.exit(1)
    pos = mt5.positions_get() or []
    print(f"{'LIVE ACTION' if confirm else 'DRY RUN'} {dt.datetime.now():%Y-%m-%d %H:%M:%S} {name} {login}: balance {ai.balance:.2f} equity {ai.equity:.2f} float {ai.equity-ai.balance:+.2f} | {len(pos)} positions, {len(mt5.orders_get() or [])} pending")
    closed, failed = close_all(confirm)
    for c in closed: print("  ", *c)
    for f in failed: print("   !! FAILED", *f)
    if confirm:
        time.sleep(2); left = mt5.positions_get() or []
        ai2 = mt5.account_info(); print(f"after: balance {ai2.balance:.2f} equity {ai2.equity:.2f}, positions left {len(left)}")
        if left: print("   !! positions still open -- retry, or close them in the Pepperstone app")
    mt5.shutdown()
    if confirm and not keep:
        import subprocess
        subprocess.run(["powershell", "-NoProfile", "-Command", f"Get-Process terminal64 | Where-Object {{ $_.Path -eq '{path}' }} | Stop-Process -Force"], timeout=60)
        time.sleep(3)
        alive = subprocess.run(["powershell", "-NoProfile", "-Command", f"(Get-Process terminal64 -ErrorAction SilentlyContinue | Where-Object {{ $_.Path -eq '{path}' }} | Measure-Object).Count"], capture_output=True, text=True, timeout=60).stdout.strip()
        print(f"terminal stopped: {'YES' if alive == '0' else 'NO (still running)'} -- engines and the Book Guard on {name} are OFF until it is started again")
    elif confirm:
        print("terminal left running (--keep-terminal): the Book Guard stays up; engines may open new positions on their next signal")
    elif not confirm:
        print("dry run only. Add --confirm to execute.")

if __name__ == "__main__":
    main()
