"""make_oil_rg_cells.py -- OIL RANGE-GUARD cells from the LOCKED SOLID4 source (2026-09-22).

User: "why does it want to buy in a downtrend -- that is fundamentally the problem." The two frozen buys
(09-14 @104.038, 09-15 @105.190) were taken AT the 10-day high after a +14% run with the D1 slope up --
every deployed filter said yes; the top came after. S37 on gold ("no NEW basket start within X% of the
N-day high for a BUY / low for a SELL") would have blocked both. It was REJECTED on gold (cut the curve
in half: the Goldminer fires at range extremes by construction) and NEVER tested on oil. Prior LOW for
the same reason -- the 09-03/07/09/10 winners were also at the highs -- but it maps exactly onto the
user's complaint and costs two minutes. Injected as a const + one gate line after the crash-state check.
RG0 (pct 0 = inert) must reproduce the oil_solid_ctl anchor ($3,033.81 / 134 tr to 2026-08-19).
"""
import io, os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "ea", "Marius GridStat MT5 OIL SOLID LOCKED.mq5")
TARGETS = [(r"C:\MT5 Pepperstone Runner\MQL5\Experts", r"C:\MT5 Pepperstone Runner\MetaEditor64.exe", "/portable"),
           (r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\C54C4DDE98E7B1FB905AFE04A9333631\MQL5\Experts",
            r"C:\Program Files\Pepperstone MetaTrader 5\MetaEditor64.exe", "")]
CELLS = {"OIL RG0": (0.0, 10), "OIL RG1": (1.0, 10), "OIL RG2": (2.0, 10), "OIL RG3": (3.0, 10), "OIL RG2D5": (2.0, 5)}

HELPER = '''
// [RG-INJECT] S37 range guard, ported to the SOLID fork: is a NEW basket start too close to the N-day extreme?
string RangeGuardSkip(int dir)
{
   if(RangeGuardPct <= 0.0) return "";
   double hi = -1e9, lo = 1e9;
   for(int i = 1; i <= RangeGuardDays; i++)
   {
      double h = iHigh(_Symbol, PERIOD_D1, i), l = iLow(_Symbol, PERIOD_D1, i);
      if(h > hi) hi = h;
      if(l < lo) lo = l;
   }
   double px = Bid_();
   if(dir == (int)ORDER_TYPE_BUY  && hi > 0 && px >= hi * (1.0 - RangeGuardPct/100.0))
      return "rangeTop(" + DoubleToString(100.0*(hi-px)/hi, 2) + "%<" + DoubleToString(RangeGuardPct,1) + "%)";
   if(dir == (int)ORDER_TYPE_SELL && lo < 1e8 && px <= lo * (1.0 + RangeGuardPct/100.0))
      return "rangeBottom(" + DoubleToString(100.0*(px-lo)/lo, 2) + "%<" + DoubleToString(RangeGuardPct,1) + "%)";
   return "";
}
'''

def build(tag, pct, days, src):
    stamp = f'OIL-RG-CELL-{tag.split()[-1]}-2026-09-22'
    bd = '#define EA_BUILD_VERSION "MT5-2026-08-04-OIL-SOLID4-FWD-LOCKED"'; assert src.count(bd) == 1
    out = src.replace(bd, f'#define EA_BUILD_VERSION "{stamp}"\n'
                          f'const double RangeGuardPct  = {pct};   // [RG-INJECT] no NEW BUY within this % of the N-day high / SELL of the low (0 = off)\n'
                          f'const int    RangeGuardDays = {days};  // [RG-INJECT]')
    ce = "void CloseEverything(string reason)"; assert out.count(ce) == 1
    out = out.replace(ce, HELPER + "\n" + ce)
    g = '   if(skip=="" && !rescue && IsOverextended()) skip = "overextended";'; assert out.count(g) == 1
    out = out.replace(g, g + '\n   if(skip=="" && !rescue && !crashSell && !regimeSell) { string rgs = RangeGuardSkip(dir); if(rgs != "") skip = rgs; }   // [RG-INJECT] new basket starts only')
    o = "input bool UseSignalLog          = true;"; assert out.count(o) == 1
    out = out.replace(o, "const bool UseSignalLog          = false;  // CELL")
    oi = "int OnInit()\n{\n"; assert oi in out
    out = out.replace(oi, oi + f'   Print("OIL RANGE-GUARD CELL {tag} -- SOLID4 LOCKED + RangeGuardPct={pct} days={days}");\n', 1)
    return out

if __name__ == "__main__":
    src = io.open(SRC, encoding="utf-8", errors="replace").read()
    for tag, (pct, days) in CELLS.items():
        if sys.argv[1:] and tag not in sys.argv[1:]: continue
        code = build(tag, pct, days, src)
        for expdir, me, extra in TARGETS:
            p = os.path.join(expdir, tag + ".mq5"); io.open(p, "w", encoding="utf-8").write(code); log = p[:-4] + ".clog"
            subprocess.run(f'"{me}" {extra} /compile:"{p}" /log:"{log}"', check=False)
            r = [l for l in io.open(log, encoding="utf-16", errors="replace").read().splitlines() if "Result" in l]
            print(tag, r[-1].strip() if r else "?")
        io.open(os.path.join(HERE, "ea", tag + ".mq5"), "w", encoding="utf-8").write(code)
