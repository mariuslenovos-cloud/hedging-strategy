import sys, re, run_frz_ab as R
R.SYMBOL, R.DEPOSIT = "SpotCrude", 3000
win = sys.argv[1] if len(sys.argv)>1 else "anchor"
if win=="anchor":  R.FROM,R.TO,R.ANCHOR_NET,R.ANCHOR_TR = "2025.12.01","2026.08.19",3033.81,134
elif win=="full":  R.FROM,R.TO,R.ANCHOR_NET,R.ANCHOR_TR = "2025.12.01","2026.09.22",None,None
else:              R.FROM,R.TO,R.ANCHOR_NET,R.ANCHOR_TR = "2026.08.28","2026.09.22",None,None
R.FRZ_RE = re.compile(r"(rangeTop|rangeBottom|FREEZE HEDGE:|PORTFOLIO STOP)")
R.ORDER = ["OIL RG0"] if win=="anchor" else ["OIL RG0","OIL RG1","OIL RG2","OIL RG3","OIL RG2D5"]
sys.argv=sys.argv[:1]; print(f"WINDOW {win}: {R.FROM} -> {R.TO}"); R.main()
