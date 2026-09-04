import os,io,time,subprocess,sys,glob,re
sys.path.insert(0,r"C:\Users\mariu\Downloads\hedging_strategy"); sys.stdout.reconfigure(encoding="utf-8",errors="replace")
import rolling_retest as rr
while rr.runner_busy(): time.sleep(20)
ini=os.path.join(rr.INIDIR,"runner_sync_only.ini")
io.open(ini,"w",encoding="utf-8").write("[Common]\nLogin=61586543\nServer=Pepperstone-Demo\n\n[Experts]\nEnabled=0\nAllowLiveTrading=0\n")
p=subprocess.Popen([rr.RUNNER_EXE]+rr.RUNNER_ARGS+[f"/config:{ini}"])
print("runner open for chart sync...",flush=True); time.sleep(150)
subprocess.run(["taskkill","/PID",str(p.pid),"/F"],capture_output=True); time.sleep(8)
while rr.runner_busy(): time.sleep(10)
out=[]
for cell,rep in [("GOLD HALF56","pin_half56_d6"),("GOLD HPIN","pin_hpin_d6"),("GOLD HPIN3","pin_hpin3_d6"),("GOLD HRES5T","pin_hres5t_d6"),("GOLD HPINSR","pin_hpinsr_d6")]:
    ini=os.path.join(rr.INIDIR,rep+".ini")
    io.open(ini,"w",encoding="utf-8").write(
        "[Common]\nLogin=61586543\nServer=Pepperstone-Demo\n\n[Experts]\nEnabled=0\nAllowLiveTrading=0\n\n"
        f"[Tester]\nExpert={cell}\nSymbol=XAUUSD\nPeriod=M5\nModel=4\nFromDate=2026.09.01\nToDate=2026.09.05\n"
        f"Deposit=2592\nOptimization=0\nReport={rep}\nReplaceReport=1\nShutdownTerminal=1\n")
    for rp in rr.report_paths(rep):
        if os.path.exists(rp): os.remove(rp)
    t0=time.time(); subprocess.run([rr.RUNNER_EXE]+rr.RUNNER_ARGS+[f"/config:{ini}"],timeout=1800)
    got=[rr.parse_report(rp) for rp in rr.report_paths(rep) if os.path.exists(rp) and os.path.getmtime(rp)>=t0-2]
    tl=sorted(glob.glob(r"C:\MT5 Pepperstone Runner\Tester\logs\*.log"),key=os.path.getmtime)[-1]
    t=io.open(tl,encoding="utf-16",errors="replace").read(); seg=t[t.rfind(f"expert file added: Experts\{cell}.ex5"):]
    win=re.search(r"testing of Experts\\"+re.escape(cell)+r"\.ex5 from (\S+ \S+) to (\S+ \S+)",seg)
    line=f"{cell} -> {got[0] if got else 'NO REPORT'} window={win.group(1)+' -> '+win.group(2) if win else '?'} ({time.time()-t0:.0f}s)"
    print(line,flush=True); out.append(line)
    io.open(os.path.join(rr.ADIR,"pin_day4_results.txt"),"w",encoding="utf-8").write("\n".join(out)+"\n")
    if cell=="GOLD HALF56" and win and win.group(2).startswith("2026.09.03"):
        print("STILL CLIPPED at 09-03 00:00 -- stopping chain",flush=True); break
