"""run_gold_full_ab.py -- GOLD HPIN12 (half, live) vs GOLD HPIN12 FULL at the LIVE balance on the PEP runner.
Two windows: trailing (real ticks) + full curve (generated, paired ranking only). 2026-09-21."""
import sys, run_frz_ab as R
R.SYMBOL, R.DEPOSIT = "XAUUSD", 2592
R.ANCHOR_NET, R.ANCHOR_TR = None, None
win = sys.argv[1] if len(sys.argv) > 1 else "trail"
R.FROM, R.TO = ("2026.08.28", "2026.09.21") if win == "trail" else ("2025.12.01", "2026.09.21")
R.FRZ_RE = __import__("re").compile(r"(RESCUE PIN|PIN BUY|PIN SELL|STAGED FLOOR|PORTFOLIO STOP|RESCUE BOOK EXIT|RESCUE DISARMED)")
R.ORDER = ["GOLD HPIN12", "GOLD HPIN12 FULL PT50", "GOLD HPIN12 FULL PT50 G3"]
_run = R.run
def run(cell):
    r, fl = _run(cell)
    return r, fl
R.run = run
print(f"WINDOW {win}: {R.FROM} -> {R.TO}  deposit {R.DEPOSIT}")
sys.argv = sys.argv[:1]
R.main()
