import re
def load(path):
    rows=[]
    for ln in open(path,encoding="utf-8",errors="ignore"):
        ln=ln.replace("close at stop","close_at_stop")
        p=ln.split()
        if len(p)<11: continue
        try:
            idx=int(p[0]); date=p[1]; tm=p[2]; typ=p[3]; ordn=int(p[4])
            lots=float(p[5]); price=float(p[6]); profit=float(p[9]); bal=float(p[10])
        except: continue
        rows.append(dict(idx=idx,date=date,tm=tm,typ=typ,ordn=ordn,lots=lots,price=price,profit=profit,bal=bal))
    return rows
def stats(rows,name):
    closes=[r for r in rows if r["typ"].startswith("close")]
    net=rows[-1]["bal"]-3000.0
    # realized running-balance max drawdown
    peak=-1e9; mdd=0
    for r in rows:
        peak=max(peak,r["bal"]); mdd=max(mdd,peak-r["bal"])
    big=sorted([r for r in closes if r["profit"]<-200],key=lambda r:r["profit"])
    tend=[r for r in rows if r["typ"]=="close_at_stop"]
    print(f"\n===== {name} =====")
    print(f"final balance: {rows[-1]['bal']:.2f}   net: {net:+.2f}   trades(closes): {len(closes)}")
    print(f"realized max DD (balance peak-to-trough): {mdd:.2f}")
    print(f"big losing closes (< -$200): {len(big)}  sum={sum(r['profit'] for r in big):+.2f}")
    for r in big:
        print(f"   {r['date']} {r['tm']}  #{r['ordn']:>3} {r['typ']:<13} {r['profit']:>10.2f}  (bal {r['bal']:.0f})")
    if tend:
        print("TEST-END forced closures:")
        for r in tend: print(f"   {r['date']} {r['tm']}  #{r['ordn']:>3} lots {r['lots']}  {r['profit']:>10.2f}")
    return net,mdd
b=load("fibc_safe_ledger.txt"); f=load("fibc_freeze_ledger.txt")
nb,_=stats(b,"BASELINE (freeze OFF)")
nf,_=stats(f,"FREEZE ON")
print(f"\n>>> DELTA net (freeze - baseline): {nf-nb:+.2f}")
