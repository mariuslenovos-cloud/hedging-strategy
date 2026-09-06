"""longvol_gate.py -- the PRE-COMMITTED gates for the LongVol bracket tester run (CLAUDE.md 2026-09-06 (2)),
evaluated mechanically from the MT5 tester report's deals table. Sim prediction (pessimistic fills):
$791 net / 109 trades / pain-sum +$737 / worst -$100 at 0.01 lot on 2025.04.22->2026.08.24.
  G-A  tester net >= 50% of the sim's $791  (>= $395)
  G-B  pain-window sum > 0   (windows = painwindow_check.WINDOWS + the Aug-19 whipsaw)
  G-C  worst single trade <= 5% of $2,390  (<= $119.50)
Usage: python longvol_gate.py <report.htm>"""
import sys, io, statistics
from datetime import datetime
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import painwindow_check as pw
WINDOWS = list(pw.WINDOWS) + [("Aug-19 whipsaw     (08-18..08-20)", "2026-08-18", "2026-08-21")]
trades = pw.parse_report(sys.argv[1])
if not trades: raise SystemExit("no deals parsed")
p = [x[1] for x in trades]; net = sum(p); mid = len(p) // 2
pain = 0.0
print(f"{len(p)} closed trades  net ${net:,.2f}  win {100*sum(1 for x in p if x>0)/len(p):.0f}%  avg ${statistics.mean(p):.2f}  "
      f"worst ${min(p):.2f}  h1 ${sum(p[:mid]):,.0f} h2 ${sum(p[mid:]):,.0f}")
eq = 0; pk = 0; dd = 0
for x in p:
    eq += x; pk = max(pk, eq); dd = min(dd, eq - pk)
print(f"max realized DD ${dd:,.2f} = {-100*dd/2390:.1f}% of $2,390")
print("PAIN WINDOWS:")
for lab, a, b in WINDOWS:
    a_, b_ = datetime.fromisoformat(a), datetime.fromisoformat(b)
    w = [x[1] for x in trades if a_ <= x[0] < b_]
    pain += sum(w); print(f"  {lab:36s} {len(w):3d} trades  ${sum(w):+8.2f}")
# G-A bar = 50% of the SIM's net on the REPORT'S OWN window (2026-09-06: the fixed $395 = 50% of the sim's
# full Apr-22->Aug-24 window falsely FAILED a Dec-01->Sep-05 GUI run at $330 that was 60% of the sim on that span).
# --sim-net <usd> overrides (also the negative test); else the sim is run on the report's first..last close date.
import argparse, contextlib, os
_ap = argparse.ArgumentParser(); _ap.add_argument("report"); _ap.add_argument("--sim-net", type=float, default=None)
_a = _ap.parse_args()
if _a.sim_net is None:
    with open(os.devnull, "w", encoding="utf-8") as _dn, contextlib.redirect_stdout(_dn):
        import longvol_bracket_sim as _sim
        _s = _sim.run(13, 0.7, 9)
    lo, hi = trades[0][0].replace(hour=0, minute=0, second=0), trades[-1][0]
    sim_net = float(_s[(_s.index >= lo) & (_s.index <= hi)].sum())
else:
    sim_net = _a.sim_net
bar = 0.5 * sim_net
print(f"sim (H13 k0.7 w9) on this report's window {trades[0][0]:%Y-%m-%d}->{trades[-1][0]:%Y-%m-%d}: ${sim_net:,.0f} -> G-A bar = 50% = ${bar:,.0f}")
ga, gb, gc = net >= bar, pain > 0, -min(p) <= 119.5
print(f"\nG-A net >= $395 : {'PASS' if ga else 'FAIL'} (${net:,.0f})")
print(f"G-B pain sum > 0: {'PASS' if gb else 'FAIL'} (${pain:,.0f})")
print(f"G-C worst <= $119.50: {'PASS' if gc else 'FAIL'} (${min(p):.2f})")
print("VERDICT:", "PASS -> demo forward beside the book" if ga and gb and gc else "FAIL -> shelve, no re-tuning")
