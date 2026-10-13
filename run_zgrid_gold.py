"""run_zgrid_gold.py -- ZGrid (GridStat execution + hourly-extension fade trigger) on GOLD, runner paired bench.
Pre-registered bar: a cell must be net-positive with maxDD inside the live gold grid's band (eqDD ~12%) in BOTH halves,
and the NY-session cells must beat the all-hours control (the map's session claim)."""
import io, os, sys
from datetime import datetime
from collections import OrderedDict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rolling_retest as rr, run_t2one_bt as R
BASE = OrderedDict(TriggerMode="2", ZLookback="12", EntryZ="2.0", UseSessionFilter="true", SessionStartHour="18", SessionEndHour="23",
                   AlignEmaPeriod="0", StagedCutCooldownMin="0", UseSignalLog="false")
CELLS = OrderedDict([
    ("zg_ny_z12_e20",  {}),
    ("zg_ny_z12_e25",  {"EntryZ": "2.5"}),
    ("zg_ny_z48_e20",  {"ZLookback": "48"}),
    ("zg_ny_z48_e25",  {"ZLookback": "48", "EntryZ": "2.5"}),
    ("zg_all_z12_e20", {"UseSessionFilter": "false"}),                 # CONTROL: all hours
    ("zg_ny_z12_al200",{"AlignEmaPeriod": "200"}),                     # fade only WITH the M5 EMA200 side
    # round 2 (build B): the selection organs the live gold grid has and round 1 did not run
    ("zg_ny_e25_d1",     {"EntryZ": "2.5", "UseDailyTrendFilter": "true"}),              # D1 EMA50 regime filter (live gold has it)
    ("zg_ny_e25_al200",  {"EntryZ": "2.5", "AlignEmaPeriod": "200"}),                    # alignment now wired in the z path
    ("zg_ny_e25_d1al",   {"EntryZ": "2.5", "UseDailyTrendFilter": "true", "AlignEmaPeriod": "200"}),
    # round 3: pre-registered neighbours of zg_ny_e25_d1al (plateau or spike?)
    ("zg_d1al_e20",     {"EntryZ": "2.0", "UseDailyTrendFilter": "true", "AlignEmaPeriod": "200"}),
    ("zg_d1al_e30",     {"EntryZ": "3.0", "UseDailyTrendFilter": "true", "AlignEmaPeriod": "200"}),
    ("zg_d1al_z24",     {"EntryZ": "2.5", "ZLookback": "24", "UseDailyTrendFilter": "true", "AlignEmaPeriod": "200"}),
    ("zg_d1al_s14",     {"EntryZ": "2.5", "SessionStartHour": "14", "UseDailyTrendFilter": "true", "AlignEmaPeriod": "200"}),
    ("zg_d1al_all",     {"EntryZ": "2.5", "UseSessionFilter": "false", "UseDailyTrendFilter": "true", "AlignEmaPeriod": "200"}),
    ("zg_d1al_e225",    {"EntryZ": "2.25", "UseDailyTrendFilter": "true", "AlignEmaPeriod": "200"}),   # EntryZ plateau check
    ("zg_d1al_e275",    {"EntryZ": "2.75", "UseDailyTrendFilter": "true", "AlignEmaPeriod": "200"}),
    ("zg_d1al_z24_e225",{"EntryZ": "2.25", "ZLookback": "24", "UseDailyTrendFilter": "true", "AlignEmaPeriod": "200"}),
    ("zg_d1al_z24_e20", {"EntryZ": "2.0", "ZLookback": "24", "UseDailyTrendFilter": "true", "AlignEmaPeriod": "200"}),
    ("zg_d1al_z24_e275",{"EntryZ": "2.75", "ZLookback": "24", "UseDailyTrendFilter": "true", "AlignEmaPeriod": "200"}),
    ("zg_d1al_z24_e25", {"EntryZ": "2.5", "ZLookback": "24", "UseDailyTrendFilter": "true", "AlignEmaPeriod": "200"}),   # = zg_d1al_z24 (named for XM)
    # 2026-10-09 21:xx: the user loaded the demo at LotSize 0.02 -- price both 0.02 geometries
    ("zg_z24_e225_lot02_pt50",  {"EntryZ": "2.25", "ZLookback": "24", "UseDailyTrendFilter": "true", "AlignEmaPeriod": "200", "LotSize": "0.02"}),                                            # as loaded (PT 50 = half geometry at double lots)
    ("zg_z24_e225_lot02_pt100", {"EntryZ": "2.25", "ZLookback": "24", "UseDailyTrendFilter": "true", "AlignEmaPeriod": "200", "LotSize": "0.02", "ProfitTargetUSD": "100.0", "RescueBookTargetUSD": "40.0"}),  # scale-covariant (FULL geometry)
    # 2026-10-13 'what is left' cells: the reversion map's other stable gold cells through the same chassis (pre-registered bar in CLAUDE.md 10-13 (3))
    ("zg_asia120",      {"EntryZ": "2.25", "ZLookback": "24", "SessionStartHour": "0", "SessionEndHour": "9", "UseDailyTrendFilter": "true", "AlignEmaPeriod": "200"}),
    ("zg_asia120_nod1", {"EntryZ": "2.25", "ZLookback": "24", "SessionStartHour": "0", "SessionEndHour": "9", "UseDailyTrendFilter": "false", "AlignEmaPeriod": "200"}),
    ("zg_asia120_e25",  {"EntryZ": "2.5", "ZLookback": "24", "SessionStartHour": "0", "SessionEndHour": "9", "UseDailyTrendFilter": "true", "AlignEmaPeriod": "200"}),
    ("zg_ovl15",        {"EntryZ": "2.25", "ZLookback": "6", "SessionStartHour": "14", "SessionEndHour": "18", "UseDailyTrendFilter": "true", "AlignEmaPeriod": "200"}),
    ("zg_ovl15_e25",    {"EntryZ": "2.5", "ZLookback": "6", "SessionStartHour": "14", "SessionEndHour": "18", "UseDailyTrendFilter": "true", "AlignEmaPeriod": "200"}),
    ("zg_ovl60",        {"EntryZ": "2.25", "ZLookback": "12", "SessionStartHour": "14", "SessionEndHour": "18", "UseDailyTrendFilter": "true", "AlignEmaPeriod": "200"}),   # 6-bar window cannot reach z 2.25 ((n-1)/sqrt n = 2.04) -> 1 h
    ("zg_ovl120",       {"EntryZ": "2.25", "ZLookback": "24", "SessionStartHour": "14", "SessionEndHour": "18", "UseDailyTrendFilter": "true", "AlignEmaPeriod": "200"}),
    ("zg_fp55",         {"EntryZ": "2.25", "ZLookback": "24", "UseDailyTrendFilter": "true", "AlignEmaPeriod": "200", "StatsFilterEnabled": "true", "StatsCSVFile": "zgrid_setups_gold.csv", "MinWinRate": "0.55", "MinSamples": "10"}),   # deployed cell + its OWN fingerprint gate
    ("zg_fp60",         {"EntryZ": "2.25", "ZLookback": "24", "UseDailyTrendFilter": "true", "AlignEmaPeriod": "200", "StatsFilterEnabled": "true", "StatsCSVFile": "zgrid_setups_gold.csv", "MinWinRate": "0.60", "MinSamples": "10"}),
    ("zg_shadow_all",    {"EntryZ": "2.5", "UseSessionFilter": "false", "StatsCollectionMode": "true", "StatsCSVFile": "zgrid_setups_gold.csv"}),  # builds THIS trigger's fingerprint DB (all hours)
])
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "analysis_data", "zgrid_gold_results.txt")
if __name__ == "__main__":
    rr.WINDOW_DAYS = (datetime.now() - datetime(2025, 12, 1)).days + 1
    cells = sys.argv[1:] or list(CELLS)
    hdr = f"ZGRID GOLD  XAUUSD M5 Model={rr.MODEL} 2025-12-01 -> {datetime.now():%Y-%m-%d} deposit 2678 (HPIN12 geometry, 0.01)\n"
    print(hdr); blocks = [hdr]
    for c in cells:
        cfg = OrderedDict(BASE); cfg.update(CELLS[c])
        rr.run_job(c, dict(expert="Marius ZGrid MT5 v1.0", symbol="XAUUSD", setlines=[f"{k}={v}" for k, v in cfg.items()], deposit=2678))
        rp = next((p for p in rr.report_paths(f"retest_{c}") if os.path.exists(p)), None)
        s = R.parse_summary(rp) if rp else None
        blk = (R.analyse(c, rp) + f"\n  report: net {s['net']} PF {s['pf']} quality {s['quality']}%") if rp else f"[{c}] RUN FAILED"
        print(blk + "\n", flush=True); blocks.append(blk)
        io.open(OUT, "w", encoding="utf-8").write("\n\n".join(blocks) + "\n")
    print(f"written {OUT}")
