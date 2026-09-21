"""stgrid_bench.py (2026-09-15) -- headless A/B of the new STGrid engine vs the live GOLD HPIN12
cell on the Pepperstone runner, same window / same path. Reuses rolling_retest's launch +
report parser. Every STGrid cell gets an EXPLICIT set file (the 09-06 cached-inputs trap).
Usage: python stgrid_bench.py [full|trail]   (full = 2025.12.01->today, trail = last 18 days)"""
import io, os, sys, time, glob, re, subprocess
from datetime import datetime, timedelta
import rolling_retest as rr

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "analysis_data")
MODE = sys.argv[1] if len(sys.argv) > 1 else "full"
FROM = datetime(2025, 12, 1) if MODE == "full" else datetime.now() - timedelta(days=18)
TAG = datetime.now().strftime("%Y%m%d") + "_" + MODE
STG = "Marius STGrid MT5 v1.0"

def setfile(name, kv):
    if not kv: return ""
    sf = f"stgrid_{name}.set"
    io.open(os.path.join(rr.SETDIR, sf), "w", encoding="utf-16-le").write(
        "﻿" + "\n".join(f"{k}={v}" for k, v in kv.items()) + "\n")
    return f"ExpertParameters={sf}\n"

CELLS = [
    ("ctl_HPIN12",   "GOLD HPIN12", "M5", {}),
    ("stg_s40_al",   STG, "M5", dict(TriggerMode=1, ST_Sensitivity=4.0, ST_AtrPeriod=20, AlignEmaTF=5, AlignEmaPeriod=200, UseSessionFilter="false")),
    ("stg_s25_al",   STG, "M5", dict(TriggerMode=1, ST_Sensitivity=2.5, ST_AtrPeriod=10, AlignEmaTF=5, AlignEmaPeriod=200, UseSessionFilter="false")),
    ("stg_s40_noal", STG, "M5", dict(TriggerMode=1, ST_Sensitivity=4.0, ST_AtrPeriod=20, AlignEmaTF=5, AlignEmaPeriod=0,   UseSessionFilter="false")),
    ("stg_s40_al_M1", STG, "M1", dict(TriggerMode=1, ST_Sensitivity=4.0, ST_AtrPeriod=20, AlignEmaTF=5, AlignEmaPeriod=200, UseSessionFilter="false")),
]

OFF = dict(RescueOnDrawdownPct=0.0, RescueTickArm="false", RescueImmediateLeg="false", RescueBookSingle="false",
           RescueSuspendsStaged="false", RescueLockDir="false", RescueRampByLegs="false")
PINONLY = dict(RescueMaxBaskets=1, RescueRampByLegs="false")   # pin the book once, no ride legs per signal
def stg(sens, per, al=200, tf="M5", extra=None):
    kv = dict(TriggerMode=1, ST_Sensitivity=sens, ST_AtrPeriod=per, AlignEmaTF=5, AlignEmaPeriod=al, UseSessionFilter="false")
    kv.update(extra or {}); return kv
CELLSETS = {
    "v1": CELLS,
    "v6": [
        ("v6_cap1",    STG, "M1", stg(2.5, 10, extra=dict(OFF, StagedCutCooldownMin=360, MaxCompoundScale=1))),
        ("v6_vel",     STG, "M1", stg(2.5, 10, extra=dict(OFF, StagedCutCooldownMin=360, UseVelocityGuard="true", VelocityGuardPct=5.0, VelocityGuardDays=5))),
        ("v6_cap1vel", STG, "M1", stg(2.5, 10, extra=dict(OFF, StagedCutCooldownMin=360, MaxCompoundScale=1, UseVelocityGuard="true", VelocityGuardPct=5.0, VelocityGuardDays=5))),
        ("v6_staged16", STG, "M1", stg(2.5, 10, extra=dict(OFF, StagedCutCooldownMin=360, StagedFloorPct=16.0))),
    ],
    "cells": [
        ("cell_CD360", "STGrid CD360", "M1", {}),
        ("cell_CD0",   "STGrid CD0",   "M1", {}),
    ],
    "v5": [
        ("v5_cd240",  STG, "M1", stg(2.5, 10, extra=dict(OFF, StagedCutCooldownMin=240))),
        ("v5_cd480",  STG, "M1", stg(2.5, 10, extra=dict(OFF, StagedCutCooldownMin=480))),
        ("v5_cd720",  STG, "M1", stg(2.5, 10, extra=dict(OFF, StagedCutCooldownMin=720))),
    ],
    "v4": [
        ("v4_cd120",   STG, "M1", stg(2.5, 10, extra=dict(OFF, StagedCutCooldownMin=120))),
        ("v4_cd360",   STG, "M1", stg(2.5, 10, extra=dict(OFF, StagedCutCooldownMin=360))),
        ("v4_cd1440",  STG, "M1", stg(2.5, 10, extra=dict(OFF, StagedCutCooldownMin=1440))),
        ("v4_nostaged", STG, "M1", stg(2.5, 10, extra=dict(OFF, UseStagedFloor="false"))),
        ("v4_staged8", STG, "M1", stg(2.5, 10, extra=dict(OFF, StagedFloorPct=8.0))),
        ("v4_base",    STG, "M1", stg(2.5, 10, extra=OFF)),
    ],
    "v3": [
        ("v3_M1_sess",   STG, "M1", stg(2.5, 10, extra=dict(OFF, UseSessionFilter="true"))),
        ("v3_M1_adx",    STG, "M1", stg(2.5, 10, extra=dict(OFF, ADX_Threshold=25.0, MA_Angle_Threshold=20.0))),
        ("v3_M1_grid3",  STG, "M1", stg(2.5, 10, extra=dict(OFF, MaxGridLevels=3))),
        ("v3_M1_alH1",   STG, "M1", stg(2.5, 10, extra=dict(OFF, AlignEmaTF=16385))),
        ("v3_M1_noal",   STG, "M1", stg(2.5, 10, al=0, extra=OFF)),
        ("v3_M1_shadow", STG, "M1", stg(2.5, 10, extra=dict(OFF, StatsCollectionMode="true", StatsCSVFile="stgrid_setups_gold.csv"))),
    ],
    "v2": [
        ("v2_s25_al_off",  STG, "M5", stg(2.5, 10, extra=OFF)),
        ("v2_s30_al_off",  STG, "M5", stg(3.0, 14, extra=OFF)),
        ("v2_s40_al_off",  STG, "M5", stg(4.0, 20, extra=OFF)),
        ("v2_s40_al_pin1", STG, "M5", stg(4.0, 20, extra=PINONLY)),
        ("v2_s25_al_M1_off", STG, "M1", stg(2.5, 10, extra=OFF)),
    ],
}
CELLS = CELLSETS[sys.argv[2]] if len(sys.argv) > 2 else CELLS
TAG = TAG + ("_" + sys.argv[2] if len(sys.argv) > 2 else "")

def run(name, expert, period, kv):
    report = f"stgrid_{name}_{TAG}"
    ini = os.path.join(rr.INIDIR, report + ".ini")
    io.open(ini, "w", encoding="utf-8").write(
        "[Common]\nLogin=61586543\nServer=Pepperstone-Demo\n\n[Experts]\nEnabled=0\nAllowLiveTrading=0\n\n"
        f"[Tester]\nExpert={expert}\n{setfile(name, kv)}Symbol=XAUUSD\nPeriod={period}\nModel=4\n"
        f"FromDate={FROM:%Y.%m.%d}\nToDate={datetime.now():%Y.%m.%d}\nDeposit=3000\nOptimization=0\n"
        f"Report={report}\nReplaceReport=1\nShutdownTerminal=1\n")
    for rp in rr.report_paths(report):
        if os.path.exists(rp): os.remove(rp)
    if rr.runner_busy():
        print(f"[{name}] runner busy -- aborting"); return None
    t0 = time.time()
    subprocess.run([rr.RUNNER_EXE] + rr.RUNNER_ARGS + [f"/config:{ini}"], timeout=2400)
    tlogs = sorted(glob.glob(os.path.join(rr.RUNNER_DATA, "Tester", "logs", "*.log")), key=os.path.getmtime)
    ttxt = io.open(tlogs[-1], encoding="utf-16", errors="replace").read() if tlogs else ""
    seg = ttxt[ttxt.rfind("expert file added: Experts\\" + expert + ".ex5"):]
    qual = re.findall(r"real ticks begin from (\S+)", seg)
    syncs = re.findall(r"history synchronized from \S+ to (\d{4}\.\d\d\.\d\d)", seg)
    cfg = re.findall(r"CONFIG \| STGRID \|[^\n]*", seg)[:1]
    for rp in rr.report_paths(report):
        if os.path.exists(rp) and os.path.getmtime(rp) >= t0 - 2:
            res = rr.parse_report(rp)
            print(f"[{name}] {os.path.basename(rp)} synced_to={syncs[-1] if syncs else '?'} real_ticks_from={qual[0] if qual else '?'} {time.time()-t0:.0f}s\n   {res}\n   {cfg[0] if cfg else ''}", flush=True)
            return dict(name=name, report=rp, **(res or {}))
    print(f"[{name}] !! no report ({time.time()-t0:.0f}s)"); return None

if __name__ == "__main__":
    rows = []
    for c in CELLS:
        r = run(*c)
        if r: rows.append(r)
    import json
    io.open(os.path.join(OUT, f"stgrid_bench_{TAG}.json"), "w").write(json.dumps(rows, indent=1, default=str))
    print("\nSUMMARY", MODE, FROM.date(), "->", datetime.now().date())
    for r in rows: print(" ", {k: v for k, v in r.items() if k != "report"})
