"""run_zgrid_oil.py -- ZGrid (hourly-extension fade + GridStat execution) on SPOTCRUDE, runner paired bench (2026-10-11).
The reversion map's oil NY-60 cell (ac -0.119 both halves) is the only non-gold cell negative in both halves; the
roadmap ranks 'ZGrid on oil' first among research items. Pre-registered bar: net > 0 in BOTH halves with eqDD inside
oil SOLID's band (~11-15%), the NY session beating all-hours, no cell quoted that is a lone spike among its neighbours.
Sizing = oil's own (risk-norm 2.5% like SOLID, PT100/RBT50), not gold's flat lots. SL-on vs SL-off both run (oil SOLID is SL-off)."""
import io, os, sys
from datetime import datetime
from collections import OrderedDict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rolling_retest as rr, run_t2one_bt as R
BASE = OrderedDict(TriggerMode="2", ZLookback="24", EntryZ="2.25", UseSessionFilter="true", SessionStartHour="18", SessionEndHour="23",
                   UseDailyTrendFilter="true", AlignEmaPeriod="200", StagedCutCooldownMin="0", UseSignalLog="false",
                   UseRiskNormalizedLots="true", RiskPctPerTrade="2.5", ProfitTargetUSD="100.0", RescueBookTargetUSD="50.0",
                   BasketMaxLossPct="10.0", UseCompounding="false")
CELLS = OrderedDict([
    ("zo_ny_rn_sl",     {}),                                                     # oil sizing, SL on
    ("zo_ny_rn_nosl",   {"UseEntrySL": "false"}),                                # oil SOLID's exit architecture (no per-entry stop)
    ("zo_ny_z12_sl",    {"ZLookback": "12"}),                                    # the mapped 1-hour window
    ("zo_ny_e25_sl",    {"EntryZ": "2.5"}),                                      # threshold neighbour
    ("zo_ny_e20_sl",    {"EntryZ": "2.0"}),                                      # threshold neighbour
    ("zo_all_rn_sl",    {"UseSessionFilter": "false"}),                          # CONTROL: all hours (the session claim)
    ("zo_ny_nod1_sl",   {"UseDailyTrendFilter": "false"}),                       # does the D1 filter matter on oil
    ("zo_ny_flat01_sl", {"UseRiskNormalizedLots": "false", "LotSize": "0.10", "ProfitTargetUSD": "100.0"}),  # the brief's flat 0.10
])
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "analysis_data", "zgrid_oil_results.txt")
if __name__ == "__main__":
    rr.WINDOW_DAYS = (datetime.now() - datetime(2025, 12, 1)).days + 1
    cells = sys.argv[1:] or list(CELLS)
    hdr = f"ZGRID OIL  SpotCrude M5 Model={rr.MODEL} 2025-12-01 -> {datetime.now():%Y-%m-%d} deposit 3000 (oil sizing: risk-norm 2.5%, PT100/RBT50, floor 10)\n"
    print(hdr); blocks = [hdr]
    for c in cells:
        cfg = OrderedDict(BASE); cfg.update(CELLS[c])
        rr.run_job(c, dict(expert="Marius ZGrid MT5 v1.0", symbol="SpotCrude", setlines=[f"{k}={v}" for k, v in cfg.items()], deposit=3000))
        rp = next((p for p in rr.report_paths(f"retest_{c}") if os.path.exists(p)), None)
        s = R.parse_summary(rp) if rp else None
        blk = (R.analyse(c, rp) + f"\n  report: net {s['net']} PF {s['pf']} quality {s['quality']}%") if rp else f"[{c}] RUN FAILED"
        print(blk + "\n", flush=True); blocks.append(blk)
        io.open(OUT, "w", encoding="utf-8").write("\n\n".join(blocks) + "\n")
    print(f"written {OUT}")
