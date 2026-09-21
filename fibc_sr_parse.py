"""
fibc_sr_parse.py — parse the STATE-RELEASE kill-test reports (runner .htm, UTF-16)
plus episode decomposition from the deals table. Usage: python fibc_sr_parse.py A B C
"""
import io, os, re, sys
from datetime import datetime, timedelta

RUN = r"C:\MT5 Pepperstone Runner"

def txt_of(path):
    for enc in ("utf-16", "utf-8", "cp1252"):
        try: return io.open(path, encoding=enc, errors="strict").read()
        except Exception: continue
    return io.open(path, encoding="utf-16", errors="ignore").read()

def parse(tag):
    path = os.path.join(RUN, f"fibc_sr_{tag}.htm")
    if not os.path.exists(path):
        path = os.path.join(RUN, f"fibc_sr_{tag}.html")
    if not os.path.exists(path):
        print(f"[{tag}] no report yet"); return None
    raw = txt_of(path)
    text = re.sub(r"<[^>]+>", "|", raw)
    text = re.sub(r"(\s*\|\s*)+", "|", text)          # collapse (the documented gotcha)
    def grab(label):
        m = re.search(re.escape(label) + r":?\|([^|]+)", text)
        return m.group(1).strip() if m else "?"
    stats = {k: grab(k) for k in
             ("Total Net Profit", "Profit Factor", "Recovery Factor",
              "Equity Drawdown Maximal", "Balance Drawdown Maximal", "Total Trades")}
    # deals table: time | deal | symbol | type | direction | volume | price | order | commission | swap | profit | balance | comment
    deals = []
    for m in re.finditer(r"\|(\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2})\|(\d+)\|XAUUSD\|(buy|sell)\|(in|out|in/out)\|([\d.]+)"
                         r"\|([\d. ]+)\|(\d+)\|([-\d. ]+)\|([-\d. ]+)\|([-\d. ]+)\|([-\d. ]+)\|", text):
        t = datetime.strptime(m.group(1), "%Y.%m.%d %H:%M:%S")
        deals.append(dict(t=t, typ=m.group(3), entry=m.group(4), vol=float(m.group(5)),
                          price=float(m.group(6).replace(" ", "")),
                          profit=float(m.group(10).replace(" ", "")) + float(m.group(9).replace(" ", "")),
                          bal=float(m.group(11).replace(" ", ""))))
    outs = [d for d in deals if d["entry"] in ("out", "in/out")]
    # flat-to-flat episodes: group closes separated <= 180s (house parser convention)
    episodes = []
    for d in outs:
        if episodes and (d["t"] - episodes[-1]["end"]).total_seconds() <= 180:
            episodes[-1]["pnl"] += d["profit"]; episodes[-1]["end"] = d["t"]; episodes[-1]["n"] += 1
        else:
            episodes.append(dict(start=d["t"], end=d["t"], pnl=d["profit"], n=1))
    losers = [e for e in episodes if e["pnl"] < -1.0]
    print(f"\n===== fibc_sr_{tag} =====")
    for k, v in stats.items(): print(f"  {k}: {v}")
    print(f"  deals parsed: {len(deals)} (closes {len(outs)})  episodes: {len(episodes)}")
    print(f"  NET-LOSING episodes (< -$1): {len(losers)}")
    for e in sorted(losers, key=lambda x: x["pnl"])[:10]:
        print(f"    {e['start']:%Y-%m-%d %H:%M} .. {e['end']:%H:%M}  n{e['n']}  {e['pnl']:+9.2f}")
    if episodes:
        worst = min(episodes, key=lambda x: x["pnl"])
        print(f"  worst episode: {worst['pnl']:+.2f} ({worst['start']:%Y-%m-%d})")
    return stats

if __name__ == "__main__":
    for tag in (sys.argv[1:] or ["A", "B", "C"]):
        parse(tag)
