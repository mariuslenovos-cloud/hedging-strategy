import sys, re, run_frz_ab as R
R.SYMBOL, R.DEPOSIT = "SpotCrude", 3000
win = sys.argv[1] if len(sys.argv)>1 else "anchor"
if win=="anchor":  R.FROM,R.TO,R.ANCHOR_NET,R.ANCHOR_TR = "2025.12.01","2026.08.19",3033.81,134
elif win=="full":  R.FROM,R.TO,R.ANCHOR_NET,R.ANCHOR_TR = "2025.12.01","2026.09.22",None,None
else:              R.FROM,R.TO,R.ANCHOR_NET,R.ANCHOR_TR = "2026.08.28","2026.09.22",None,None
R.FRZ_RE = re.compile(r"(FREEZE HEDGE:|FREEZE RELEASED|PORTFOLIO STOP|RESCUE BOOK EXIT)")
R.ORDER = ["OIL NDB0","OIL NDB1","OIL NDB2"] if win!="anchor" else ["OIL NDB0"]
_ctl = R.main
def main():
    # the control check inside R.main keys on 'OIL FRZ0'; alias
    res_key = "OIL FRZ0"
    R.main()
sys.argv=sys.argv[:1]
print(f"WINDOW {win}: {R.FROM} -> {R.TO}")
R.main()
