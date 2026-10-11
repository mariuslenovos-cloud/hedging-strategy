"""run_xm_cov.py -- the covariant $10k gold cells on XM's GOLD tick base (100% REAL ticks Dec-2025 -> Sep-2026) = the second-feed
check of the runner's $186/day finding (gc50_10k). XM spread ~3x Razor -> a cost-sensitive read; the RANKING vs the capped FULL cell is the test."""
import io, os, sys, time, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "factory_front"))
import run_frz_ab as F, cell_d_allocation as CD
XM_EXE = r"C:\Program Files\XM Global MT5\terminal64.exe"
XM_DATA = r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\BB16F565FAAA6B23A20C26C49416FF05"
WIN = ("2025.12.01", "2026.09.30"); DEPOSIT = 10000
CELLS = ["GOLD HPIN12 FULL", "GOLD COV G50 X2", "GOLD COV G37 X2", "GOLD COV G62 X2"]
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "analysis_data", "xm_cov_10k.txt")
def run(cell):
    rep = "xmcov_" + cell.replace(" ", "_"); ini = os.path.join(XM_DATA, "config", rep + ".ini")
    io.open(ini, "w", encoding="utf-8").write("[Experts]\nEnabled=0\nAllowLiveTrading=0\n\n"
        f"[Tester]\nExpert={cell}\nSymbol=GOLD\nPeriod=M5\nModel=4\nFromDate={WIN[0]}\nToDate={WIN[1]}\nDeposit={DEPOSIT}\nOptimization=0\nReport={rep}\nReplaceReport=1\nShutdownTerminal=1\n")
    paths = [os.path.join(XM_DATA, rep + e) for e in (".htm", ".html")]
    for p in paths:
        if os.path.exists(p): os.remove(p)
    t0 = time.time(); print(f"  [{cell}] running on XM...", flush=True)
    subprocess.run([XM_EXE, f"/config:{ini}"], timeout=4 * 3600)
    for p in paths:
        if os.path.exists(p) and os.path.getmtime(p) >= t0 - 2: return p
    return None
if __name__ == "__main__":
    lines = [f"COVARIANT $10k GOLD CELLS ON XM (100% real ticks) GOLD M5 Model=4 {WIN[0]}->{WIN[1]} deposit {DEPOSIT}",
             f"{'cell':<20}{'net':>9}{'PF':>6}{'RF':>6}{'eqDD%':>7}{'tr':>5}{'qual':>5}{'$/tday':>8}{'realDD':>8}{'lots':>12}"]
    for c in (sys.argv[1:] or CELLS):
        p = run(c)
        if not p: lines.append(f"{c:<20} RUN FAILED"); continue
        s = F.parse(p); d = CD.deals(p); d = d[d.dir != "in"]; pp = d.groupby(d.time.dt.date).net.sum(); st = CD.stats(pp); lot = sorted(set(round(x, 2) for x in d.lots))
        lines.append(f"{c:<20}{s['net'] or 0:>9,.0f}{s['pf'] or 0:>6.2f}{s['rf'] or 0:>6.2f}{s['eqdd'] or 0:>7.1f}{s['trades'] or 0:>5}{s['quality'] or 0:>5}{(s['net'] or 0)/max(len(pp),1):>8,.0f}{st['maxdd']:>8,.0f}{(str(min(lot))+'-'+str(max(lot))) if lot else '-':>12}")
        print(lines[-1], flush=True); io.open(OUT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines)); io.open(OUT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
