#!/usr/bin/env python3
"""pin_report_parse.py -- cut an MT5 tester report into the known-answer episodes for the S36 PIN-THEN-RIDE round.
Usage: python pin_report_parse.py <report.htm> [...]
Per report: net/PF/RF/eqDD/trades, History Quality, realized P&L (profit+swap+commission of OUT deals)
inside each pain window, plus month-by-month."""
import io,re,sys,os
from collections import defaultdict
WINDOWS={"Aug-4/5 melt-up":("2026.08.04","2026.08.06"),"Aug-19 whipsaw":("2026.08.18","2026.08.21"),
         "Sep-2/3 squeeze":("2026.09.02","2026.09.05"),"Apr whipsaw":("2026.04.13","2026.04.18"),"May-12":("2026.05.11","2026.05.14")}
# deals table row: time deal symbol type direction volume price order commission swap profit balance comment
ROW=re.compile(r"(20\d\d\.\d\d\.\d\d \d\d:\d\d:\d\d) \d+ XAUUSD (buy|sell) (in|out|in/out) ([\d.]+) ([\d.]+) \d+ (-?[\d.]+) (-?[\d.]+) (-?[\d.]+) ")
def parse(path):
    h=io.open(path,encoding="utf-16",errors="replace").read()
    txt=re.sub(r"<[^>]+>"," ",h); txt=re.sub(r"[ \t]+"," ",txt)
    def grab(k):
        m=re.search(k+r"[^0-9\-]*(-?[0-9][0-9 ,.]*)",txt); return m.group(1).replace(" ","").replace(",","") if m else "?"
    dd=re.search(r"Equity Drawdown Maximal[^0-9]*([0-9.,]+) \(([0-9.]+)%\)",txt)
    outs=[(r[0],float(r[5])+float(r[6])+float(r[7])) for r in ROW.findall(txt) if r[2] in("out","in/out")]
    win={k:round(sum(p for t,p in outs if a<=t[:10]<b),2) for k,(a,b) in WINDOWS.items()}
    mon=defaultdict(float)
    for t,p in outs: mon[t[:7]]+=p
    return dict(net=grab("Total Net Profit"),pf=grab("Profit Factor"),rf=grab("Recovery Factor"),
                eqdd=(dd.group(2)+"%") if dd else "?",quality=grab("History Quality")+"%",closes=len(outs),
                windows=win,months={k:round(v,1) for k,v in sorted(mon.items())})
if __name__=="__main__":
    sys.stdout.reconfigure(encoding="utf-8",errors="replace")
    for p in sys.argv[1:]:
        r=parse(p); print(os.path.basename(p))
        for k,v in r.items(): print(f"   {k}: {v}")
