import sys
try:
    import MetaTrader5 as mt5
except Exception as e:
    print("MetaTrader5 import FAILED:", e); sys.exit(1)
from datetime import datetime, timedelta
ok=False
for attempt in range(3):
    if mt5.initialize():
        ok=True; break
print("initialize:", ok, mt5.last_error() if not ok else "")
if not ok: sys.exit(1)
ai=mt5.account_info()
print("account:", ai.login if ai else None, "| server:", ai.server if ai else None, "| balance:", ai.balance if ai else None, "| equity:", ai.equity if ai else None)
to=datetime.now()+timedelta(days=1); frm=to-timedelta(days=60)
deals=mt5.history_deals_get(frm,to)
print("deals pulled (60d):", len(deals) if deals else 0)
MAGS={57502:"GOLD",59917:"SILVER",62092:"OILCash"}
from collections import defaultdict
cnt=defaultdict(int); prof=defaultdict(float); syms=defaultdict(set); allmags=defaultdict(int)
if deals:
    for d in deals:
        allmags[d.magic]+=1
        cnt[d.magic]+=1; prof[d.magic]+=d.profit; syms[d.magic].add(d.symbol)
    print("\nmagic breakdown (last 60d):")
    for m in sorted(allmags, key=lambda x:-allmags[x]):
        print(f"  magic {m:>8} {MAGS.get(m,'?'):>8}  deals {cnt[m]:>4}  netP {prof[m]:>10.2f}  syms {sorted(syms[m])}")
    # positions open now
    pos=mt5.positions_get()
    print("\nopen positions now:", len(pos) if pos else 0)
    if pos:
        for p in pos: print(f"  {p.symbol} {('BUY' if p.type==0 else 'SELL')} {p.volume} magic {p.magic} float {p.profit:.2f}")
mt5.shutdown()
