#!/usr/bin/env python3
"""
make_oil_frig_cells.py -- OIL FRIDAY GREEN-STOP cells from the LOCKED SOLID4 source (2026-08-28).

The operator's Friday-risk regime, automated (S35). Oil is where it matters: oil runs
UseEntrySL=false BY DESIGN (red legs recover -- 6 cut-class kills), so its legs carry NO stop at
all, which is exactly why the operator placed one by hand on 2026-08-28.

Generated from the deployed `Marius GridStat MT5 OIL SOLID LOCKED.mq5` because the SOLID lineage
FORKED from the master on 08-04 (UseRegimeSells/RegimeSellMinWR live only in the fork) -- a
master-built cell cannot reproduce SOLID4.

FRIG0 (lever off) is the CONTROL and must reproduce the SOLID4 anchor character
(~$3,383 / RF 6.20 / eqDD 10.87% to 08-27) = injection no-harm, per
[[validate-pipeline-against-known-anchor]].
"""
import io, os, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "ea", "Marius GridStat MT5 OIL SOLID LOCKED.mq5")
TARGETS = [
    (r"C:\MT5 Pepperstone Runner\MQL5\Experts",
     r"C:\MT5 Pepperstone Runner\MetaEditor64.exe", ["/portable"]),
    (r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\C54C4DDE98E7B1FB905AFE04A9333631\MQL5\Experts",
     r"C:\Program Files\Pepperstone MetaTrader 5\MetaEditor64.exe", []),
]
# tag -> (on?, guard hour, offsetATR, lockPct)
CELLS = {
    "OIL FRIG0": ("false", 16, 0.01, 0.0),   # CONTROL -- lever inert, must reproduce the anchor
    "OIL FRIG1": ("true",  16, 0.01, 0.0),   # the operator's hand action: BE+ from 16:00 Friday
    "OIL FRIG2": ("true",  14, 0.01, 0.0),   # earlier cutoff
    "OIL FRIG3": ("true",  16, 0.01, 0.5),   # BE+ but also lock half the open profit
}
# S35b BOOK-LEVEL: bank the WHOLE book on Friday only if it is GREEN (never realizes a red book,
# never leaves a naked leg -- the defect that killed the per-leg version). tag -> (hour, minUSD)
BANK_CELLS = {
    "OIL BANK16": (16, 0.0),
    "OIL BANK20": (20, 0.0),
    "OIL BANK20M": (20, 25.0),   # only bank a book worth banking
}
BANK_FUNC = """
//--- [S35b-INJECT] FRIDAY BANK: bank the WHOLE book on Friday if green. Never realizes a red book.
void ManageFridayBank()
{
   MqlDateTime bdt; TimeToStruct(TimeCurrent(), bdt);
   if(bdt.day_of_week != 5) return;
   if(bdt.hour < FridayBankHour) return;
   int n = 0;
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(tk==0 || !PositionSelectByTicket(tk)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      n++;
   }
   if(n == 0) return;
   double bk = PortfolioFloat();
   if(bk < FridayBankMinUSD) return;
   CloseEverything("FRIDAY BANK book +" + DoubleToString(bk,2));
   g_peakBasketFloat = 0.0; g_rescueDir = -1; g_freezeDir = -1;
}

"""

def build_bank(tag, hour, minusd, src):
    out = src.replace('#define EA_BUILD_VERSION "MT5-2026-08-04-OIL-SOLID4-FWD-LOCKED"',
                      f'#define EA_BUILD_VERSION "OIL-BANK-CELL-{tag.replace(" ", "-")}-2026-08-28"')
    anchor = f'#define EA_BUILD_VERSION "OIL-BANK-CELL-{tag.replace(" ", "-")}-2026-08-28"'
    out = out.replace(anchor, anchor +
                      f"\nconst int    FridayBankHour   = {hour};   // [S35b-INJECT]"
                      f"\nconst double FridayBankMinUSD = {minusd};")
    o = "input bool UseSignalLog          = true;"
    assert out.count(o) == 1
    out = out.replace(o, "const bool UseSignalLog          = false;  // CELL")
    fa = "void ManageBreakEvenSL()"
    assert out.count(fa) == 1
    out = out.replace(fa, BANK_FUNC + fa, 1)
    ca = "   else { ManageBreakEvenSL(); ManageGrid(); }"
    assert out.count(ca) == 1
    out = out.replace(ca, "   else { ManageBreakEvenSL(); ManageGrid(); ManageFridayBank(); }", 1)
    oninit = "int OnInit()\n{\n"
    out = out.replace(oninit, oninit +
                      f'   Print("OIL FRIDAY-BANK CELL {tag} -- SOLID4 LOCKED + hour={hour} '
                      f'minUSD={minusd}");\n', 1)
    return f"//| GENERATED BANK CELL {tag} from SOLID4 LOCKED |\n" + out


FUNC = '''
//--- [S35-INJECT] FRIDAY GREEN-STOP: protect PROFIT on Fridays, never realize a red leg.
//    GREEN LEGS ONLY (a red oil leg recovers -- that recovery IS the edge, 6 cut-class kills);
//    SKIPPED while a rescue/freeze is armed (those manage the WHOLE book; stopping one leg strips
//    the structure); never loosens an existing stop; respects the broker stops level.
void ManageFridayGreenStop()
{
   if(!UseFridayGreenStop) return;
   MqlDateTime fdt; TimeToStruct(TimeCurrent(), fdt);
   if(fdt.day_of_week != 5) return;
   if(fdt.hour < FridayGuardHour) return;
   if(g_rescueDir >= 0 || g_freezeDir >= 0) return;

   double atr = ReadBuf(hATR_D1, 0, 1);
   if(atr <= 0) return;
   double off      = FridayStopOffsetATR * atr;
   double stopsLvl = (double)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * point;
   int    dgt      = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);

   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(tk==0 || !PositionSelectByTicket(tk)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetDouble(POSITION_PROFIT) <= 0) continue;   // GREEN ONLY
      long   ptype = PositionGetInteger(POSITION_TYPE);
      double op    = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl    = PositionGetDouble(POSITION_SL);
      double tp    = PositionGetDouble(POSITION_TP);
      double cur   = (ptype==POSITION_TYPE_BUY) ? Bid_() : Ask_();
      double want;
      if(ptype == POSITION_TYPE_BUY)
      {
         want = op + off;
         if(FridayStopLockPct > 0) want = MathMax(want, op + FridayStopLockPct*(cur-op));
         if(want >= cur - stopsLvl) continue;
         if(sl != 0 && sl >= want)  continue;
      }
      else
      {
         want = op - off;
         if(FridayStopLockPct > 0) want = MathMin(want, op - FridayStopLockPct*(op-cur));
         if(want <= cur + stopsLvl) continue;
         if(sl != 0 && sl <= want)  continue;
      }
      want = NormalizeDouble(want, dgt);
      if(trade.PositionModify(tk, want, tp))
         PrintFormat("FRIDAY GREEN-STOP: #%I64u %s @ %.*f -> SL %.*f", tk,
                     (ptype==POSITION_TYPE_BUY ? "BUY" : "SELL"), dgt, op, dgt, want);
   }
}

'''


def build(tag, on, hour, off, lock, src):
    out = src.replace('#define EA_BUILD_VERSION "MT5-2026-08-04-OIL-SOLID4-FWD-LOCKED"',
                      f'#define EA_BUILD_VERSION "OIL-FRIG-CELL-{tag.replace(" ", "-")}-2026-08-28"')
    anchor = f'#define EA_BUILD_VERSION "OIL-FRIG-CELL-{tag.replace(" ", "-")}-2026-08-28"'
    out = out.replace(anchor, anchor +
                      f"\nconst bool   UseFridayGreenStop  = {on};   // [S35-INJECT]"
                      f"\nconst int    FridayGuardHour     = {hour};"
                      f"\nconst double FridayStopOffsetATR = {off};"
                      f"\nconst double FridayStopLockPct   = {lock};")

    o = "input bool UseSignalLog          = true;"
    assert out.count(o) == 1, "UseSignalLog anchor"
    out = out.replace(o, "const bool UseSignalLog          = false;  // CELL: never pollute the shared CSV")

    fa = "void ManageBreakEvenSL()"
    assert out.count(fa) == 1, "ManageBreakEvenSL anchor"
    out = out.replace(fa, FUNC + fa, 1)

    ca = "   else { ManageBreakEvenSL(); ManageGrid(); }"
    assert out.count(ca) == 1, "OnTick call anchor"
    out = out.replace(ca, "   else { ManageBreakEvenSL(); ManageGrid(); ManageFridayGreenStop(); }", 1)

    oninit = "int OnInit()\n{\n"
    assert oninit in out
    out = out.replace(oninit, oninit +
                      f'   Print("OIL FRIDAY-GREEN-STOP CELL {tag} -- SOLID4 LOCKED + on={on} hour={hour} '
                      f'offATR={off} lockPct={lock}");\n', 1)
    return f"//| GENERATED FRIG CELL {tag} from SOLID4 LOCKED -- regen via make_oil_frig_cells.py |\n" + out


def main():
    import sys
    only = set(sys.argv[1:])
    src = io.open(SRC, encoding="utf-8", errors="replace").read()
    ALL = {t: ("frig", v) for t, v in CELLS.items()}
    ALL.update({t: ("bank", v) for t, v in BANK_CELLS.items()})
    for tag, (kind, v) in ALL.items():
        if only and tag not in only:
            continue
        code = build(tag, *v, src) if kind == "frig" else build_bank(tag, v[0], v[1], src)
        for expdir, metaed, extra in TARGETS:
            path = os.path.join(expdir, f"{tag}.mq5")
            io.open(path, "w", encoding="utf-8").write(code)
            log = path[:-4] + ".clog"
            subprocess.run(f'"{metaed}" {" ".join(extra)} /compile:"{path}" /log:"{log}"', check=False)
            res = "?"
            for enc in ("utf-16", "cp1252"):
                try:
                    lines = [l for l in io.open(log, encoding=enc).read().splitlines() if "Result" in l]
                    if lines:
                        res = lines[-1].strip()
                        break
                except Exception:
                    continue
            print(f"{tag:11s} {res}")
        io.open(os.path.join(HERE, "ea", f"{tag}.mq5"), "w", encoding="utf-8").write(code)


if __name__ == "__main__":
    main()
