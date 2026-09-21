#!/usr/bin/env python3
"""
make_oil_frz_cells.py -- OIL FREEZE-RELEASE cells from the LOCKED SOLID4 source (2026-09-18).

WHY (live specimen): MAIN 51511633 has been pinned at -131.56 since 2026-09-16 20:14 --
buys 0.2@104.038 + 0.2@105.190 (VWAP 104.614) frozen by SELL 0.4@101.335. Two findings:

  (1) A STUCK-STATE BUG. g_freezeDir is cleared ONLY by the bounce release (line ~1420) or the
      +RescueBookTargetUSD book exit (~1403). The PORTFOLIO FLOOR's CloseEverything (~1314) does
      NOT clear it, and nor does a hand-close. The EA then still believes it is frozen: it blocks
      every new entry (~766) and returns before all other book management (~1422) until price
      happens to reach the bounce level. Same class as the 2026-09-04 S36d gold permanent-rescue
      -state bug. -> FreezeDisarmOnFlat.

  (2) A RELEASE MIS-CALIBRATION. FreezeReleaseATR=1.5 x ATR(D1,14)=3.913 needs a 5.869-pt bounce
      off the 99.219 low -> release at 105.088, which is ABOVE the buys' break-even 104.614. The
      pin distance |hedge - breakeven| is only 3.279 pts, so the trigger sits 2.59 pts past the
      useful window and the hedge is guaranteed to be cut for ~$150 when the pin is $131.
      Condition: whenever FreezeReleaseATR*ATR > |H - BE| the bounce release is strictly worse
      than releasing at break-even. -> FreezeReleaseCapAtBE.

  (3) The user's ask -- "cash in the hedge when significantly positive, then re-hedge if it keeps
      going against us" -- reformulated so it fires just AFTER the adverse extreme instead of AT
      it: release on a % giveback from the hedge's PEAK profit (fib C's RecoveryTrailGiveback
      shape). The re-hedge branch already exists (g_freezeAnchor: re-freeze only on a NEW adverse
      extreme). NOT built as literally stated: hedge profit is a monotone function of adverse
      distance, so a profit THRESHOLD fires at maximum adversity = unhedging into the knife.
      -> FreezeHarvestTrailPct.

Cells are the deployed `Marius GridStat MT5 OIL SOLID LOCKED.mq5` verbatim + injected consts, so
config fidelity is free. OIL FRZ0 (every lever off) must reproduce the oil_solid_ctl anchor
($3,033.81 / 134 tr to 2026-08-19) = injection no-harm and control cell in one check.
"""
import io, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "ea", "Marius GridStat MT5 OIL SOLID LOCKED.mq5")
TARGETS = [
    (r"C:\MT5 Pepperstone Runner\MQL5\Experts",
     r"C:\MT5 Pepperstone Runner\MetaEditor64.exe", ["/portable"]),
    (r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\C54C4DDE98E7B1FB905AFE04A9333631\MQL5\Experts",
     r"C:\Program Files\Pepperstone MetaTrader 5\MetaEditor64.exe", []),
]

# tag -> (disarm_fix, cap_at_breakeven, harvest_trail_pct)
CELLS = {
    # tag -> (disarm_fix, cap_at_breakeven, harvest_trail_pct, post_floor_cooldown_bars)
    "OIL FRZ0":       (False, False,  0.0,   0, 0.0, False),   # CONTROL: everything off -> must reproduce the anchor
    "OIL FRZFIX":     (True,  False,  0.0,   0, 0.0, False),   # the stuck-state fix ALONE (prices the defect)
    "OIL FRZBE":      (True,  True,   0.0,   0, 0.0, False),   # + release capped at the losing side's break-even
    "OIL FRZT25":     (True,  False, 25.0,   0, 0.0, False),   # + harvest trail on the hedge's peak profit
    "OIL FRZT40":     (True,  False, 40.0,   0, 0.0, False),
    "OIL FRZT60":     (True,  False, 60.0,   0, 0.0, False),
    "OIL FRZBET40":   (True,  True,  40.0,   0, 0.0, False),
    # the stuck state was an ACCIDENTAL post-floor cooldown (all 7 disarms fired with book 0.00).
    # These make it deliberate and time-bounded instead of price-bounded:
    "OIL FRZC288":    (True,  False,  0.0, 288, 0.0, False),   # fix + 24h no-new-entry cooldown after a flatten
    "OIL FRZC864":    (True,  False,  0.0, 864, 0.0, False),   # fix + 72h
    "OIL FRZT40C288": (True,  False, 40.0, 288, 0.0, False),   # fix + trail40 + 24h  <- the combined candidate
    "OIL FRZT40C864": (True,  False, 40.0, 864, 0.0, False),
    # the accidental block was a PRICE condition (no re-entry until price retraced
    # FreezeReleaseATR x ATR off the adverse extreme), not a clock. Made deliberate:
    "OIL FRZR15":     (True,  False,  0.0,   0, 1.5, False),   # must ~reproduce FRZ0 = mechanism identified
    "OIL FRZR10":     (True,  False,  0.0,   0, 1.0, False),
    "OIL FRZR20":     (True,  False,  0.0,   0, 2.0, False),
    "OIL FRZT40R15":  (True,  False, 40.0,   0, 1.5, False),   # <- keep the protection AND harvest
    "OIL FRZT25R15":  (True,  False, 25.0,   0, 1.5, False),
    "OIL FRZT60R15":  (True,  False, 60.0,   0, 1.5, False),
    # same gate but TRAILING the running extreme, which is what the accidental block does:
    "OIL FRZRT15":    (True,  False,  0.0,   0, 1.5, False),
    "OIL FRZRT10":    (True,  False,  0.0,   0, 1.0, False),
    "OIL FRZT40RT15": (True,  False, 40.0,   0, 1.5, False),
    "OIL FRZT25RT15": (True,  False, 25.0,   0, 1.5, False),
    # PARK MODE (2026-09-21): the frozen pair is walled off from the engine (it is neutral -- zero
    # directional risk, ~zero carry); the engine keeps trading a FRESH book around it; the pair
    # still releases on its own bounce rule. = FreezeAllowEntries done with proper separation.
    "OIL FRZPARK":     (True,  False,  0.0,   0, 0.0, True),
    "OIL FRZPARKRT15": (True,  False,  0.0,   0, 1.5, True),
    "OIL FRZPARKT40":  (True,  False, 40.0,   0, 0.0, True),
}


BUILD_DEF = '#define EA_BUILD_VERSION "MT5-2026-08-04-OIL-SOLID4-FWD-LOCKED"'

HELPERS = '''
// [FRZ-INJECT] ---- freeze-leg helpers -------------------------------------------------------
int FrzLegCount()
{
   int n = 0;
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(tk==0 || !PositionSelectByTicket(tk)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(StringFind(PositionGetString(POSITION_COMMENT), "_FRZ") < 0) continue;
      n++;
   }
   return n;
}
double FrzFloat()
{
   double s = 0.0;
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(tk==0 || !PositionSelectByTicket(tk)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(StringFind(PositionGetString(POSITION_COMMENT), "_FRZ") < 0) continue;
      s += PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
   }
   return s;
}
double LoseSideBE(int loseDir)   // volume-weighted entry of the FROZEN side, _FRZ legs excluded
{
   double lots = 0.0, notional = 0.0;
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(tk==0 || !PositionSelectByTicket(tk)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if((int)PositionGetInteger(POSITION_TYPE) != loseDir) continue;
      if(StringFind(PositionGetString(POSITION_COMMENT), "_FRZ") >= 0) continue;
      if(FreezeParkMode && !IsParked(tk)) continue;
      double v = PositionGetDouble(POSITION_VOLUME);
      lots += v; notional += v * PositionGetDouble(POSITION_PRICE_OPEN);
   }
   return (lots > 0.0) ? notional / lots : 0.0;
}
'''

PARK_HELPERS = '''
// [PARK-INJECT] ---- parked-pair helpers ------------------------------------------------------
bool IsParked(ulong tk)
{
   if(!PositionSelectByTicket(tk)) return false;
   if(StringFind(PositionGetString(POSITION_COMMENT), "_FRZ") >= 0) return true;
   for(int k=0; k<ArraySize(g_parked); k++) if(g_parked[k] == tk) return true;
   return false;
}
void ParkLegs(int loseDir)   // snapshot the losing side's legs at freeze-arm: they leave the active book
{
   ArrayFree(g_parked);
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(tk==0 || !PositionSelectByTicket(tk)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if((int)PositionGetInteger(POSITION_TYPE) != loseDir) continue;
      if(StringFind(PositionGetString(POSITION_COMMENT), "_FRZ") >= 0) continue;
      int n = ArraySize(g_parked); ArrayResize(g_parked, n+1); g_parked[n] = tk;
   }
   Print("FREEZE PARK: ", ArraySize(g_parked), " losing leg(s) walled off; engine continues on a fresh book");
}
'''

DISARM = '''      // [FRZ-INJECT] STUCK-STATE FIX -- run BEFORE the arm/hold branches so a stale freeze state can
      // never block the engine. g_freezeDir is otherwise cleared only by the bounce release or the
      // +target book exit, so a portfolio-floor CloseEverything (or a hand-closed hedge) leaves the EA
      // believing it is frozen: entries blocked and all other book management skipped until price
      // reaches the bounce level. Same class as the S36d gold permanent-rescue-state bug.
      if(FreezeDisarmOnFlat && g_freezeDir >= 0 && FrzLegCount() == 0)
      {
         Print("FREEZE DISARMED: no _FRZ legs remain (book ", DoubleToString(PortfolioFloat(),2), ")");
         if(FreezePostFloorRetraceATR > 0.0 && PositionsTotal() == 0)
         { g_pfExtreme = g_freezeExtreme; g_pfDir = g_freezeDir; }
         g_freezeDir = -1; g_frzPeak = 0.0; ArrayFree(g_parked);
         if(PositionsTotal() == 0)
         {
            g_freezeAnchor = 0.0;
            if(FreezeCooldownBars > 0)
               g_flatUntil = TimeCurrent() + (datetime)(FreezeCooldownBars * PeriodSeconds(_Period));
         }
      }
'''

RELEASE = '''
         // [FRZ-INJECT] hedge-profit peak + the two alternative release triggers ------------------
         double frzNow = FrzFloat();
         if(frzNow > g_frzPeak) g_frzPeak = frzNow;
         // (a) cap the release level at the losing side's break-even: past BE the bounce rule cuts
         //     the hedge for MORE than the pin it was holding (live specimen 2026-09-18: -150 vs -131).
         if(FreezeReleaseCapAtBE && !bounce)
         {
            double frzBE = LoseSideBE(g_freezeDir);
            if(frzBE > 0.0)
               bounce = (g_freezeDir == (int)ORDER_TYPE_BUY) ? (px >= frzBE) : (px <= frzBE);
         }
         // (b) harvest trail: release once the hedge gives back this % of its PEAK profit, i.e. just
         //     AFTER the adverse extreme rather than at it. Arms only once the peak is material.
         if(FreezeHarvestTrailPct > 0.0 && !bounce &&
            g_frzPeak >= FreezeHarvestMinPctBal/100.0 * Bal_() &&
            frzNow <= g_frzPeak * (1.0 - FreezeHarvestTrailPct/100.0))
         {
            Print("FREEZE HARVEST TRAIL: hedge ", DoubleToString(frzNow,2), " gave back ",
                  DoubleToString(FreezeHarvestTrailPct,0), "% of peak ", DoubleToString(g_frzPeak,2));
            bounce = true;
         }
'''


def build(tag, disarm, cap_be, trail, cooldown, retrace, park, src):
    stamp = f'OIL-FRZ-CELL-{tag.replace(" ", "-")}-2026-09-18'
    assert src.count(BUILD_DEF) == 1, "build define anchor"
    import re as _re
    enum = _re.compile(r'(ulong (\w+) = PositionGetTicket\(\w+\);\n(\s*)if\(\2==0 \|\| !PositionSelectByTicket\(\2\)\) continue;\n\s*if\(PositionGetInteger\(POSITION_MAGIC\) != MagicNumber\) continue;)')
    n_sites = len(enum.findall(src))
    assert n_sites == 15, f"expected 15 enumeration sites, found {n_sites}"
    out = enum.sub(lambda m: m.group(1) + "\n" + m.group(3) + "if(FreezeParkMode && IsParked(" + m.group(2) + ")) continue;   // [PARK-INJECT] parked legs are not the engine's book", src)
    # exempt the freeze release loop: it must still close the (parked) _FRZ legs
    rel_loop = _re.compile(r'(\n\s*)if\(FreezeParkMode && IsParked\(tk\)\) continue;   // \[PARK-INJECT\][^\n]*(\n\s*if\(PositionGetString\(POSITION_SYMBOL\) != _Symbol\) continue;\n\s*if\(StringFind\(PositionGetString\(POSITION_COMMENT\), "_FRZ"\) < 0\) continue;\n\s*trade\.PositionClose\(tk\);)')
    out, n_ex = rel_loop.subn(r'\2', out)
    assert n_ex == 1, f"release-loop exemption applied {n_ex} times"
    out = out.replace(BUILD_DEF, f'#define EA_BUILD_VERSION "{stamp}"')

    # consts
    anchor = f'#define EA_BUILD_VERSION "{stamp}"'
    out = out.replace(anchor, anchor + f'''
const bool   FreezeDisarmOnFlat     = {str(disarm).lower()};   // [FRZ-INJECT] clear a stale freeze state when no _FRZ legs remain
const bool   FreezeReleaseCapAtBE   = {str(cap_be).lower()};   // [FRZ-INJECT] cap the release level at the losing side's break-even
const double FreezeHarvestTrailPct  = {trail};   // [FRZ-INJECT] release on this %% giveback from the hedge's PEAK profit (0 = off)
const double FreezeHarvestMinPctBal = 1.0;    // [FRZ-INJECT] the trail arms only once the hedge peak >= this %% of balance
const int    FreezeCooldownBars     = {cooldown};    // [FRZ-INJECT] block NEW entries for N bars after a freeze episode flattens (0 = off)\nconst double FreezePostFloorRetraceATR = {retrace};  // [FRZ-INJECT] after a flatten, no NEW entries until price retraces this x ATR(D1) off the episode extreme (0 = off)\nconst bool   FreezeParkMode         = {str(park).lower()};   // [PARK-INJECT] wall the frozen pair off and keep trading a fresh book around it''')

    # global peak tracker
    g = "int      g_freezeDir = -1;"
    assert out.count(g) == 1, "g_freezeDir global anchor"
    out = out.replace(g, g + '\ndouble   g_frzPeak = 0.0;      // [FRZ-INJECT] peak $ profit of the _FRZ legs this freeze'
                             '\ndatetime g_flatUntil = 0;      // [FRZ-INJECT] no new entries until this time (post-floor cooldown)'
                             '\ndouble   g_pfExtreme = 0.0;    // [FRZ-INJECT] adverse extreme of the episode that just flattened'
                             '\nint      g_pfDir = -1;         // [FRZ-INJECT] its frozen side, -1 = no post-floor gate armed'
                             '\nulong    g_parked[];           // [PARK-INJECT] tickets of the frozen (parked) losing legs; _FRZ legs are parked by comment')

    # helpers ahead of CloseEverything
    ce = "void CloseEverything(string reason)"
    assert out.count(ce) == 1, "CloseEverything anchor"
    out = out.replace(ce, HELPERS + PARK_HELPERS + "\n" + ce)

    # post-floor entry cooldown, right before the frozen-entries guard
    eg = ("   if(UseFreezeHedge && g_freezeDir >= 0) return;   "
          "// FROZEN: no new entries on either side (freeze holds the book)")
    assert out.count(eg) == 1, "entry gate anchor"
    COOL = ("   // [FRZ-INJECT] post-floor cooldown: the stuck-state bug was acting as an accidental one\n"
            "   if(FreezeCooldownBars > 0 && TimeCurrent() < g_flatUntil) return;\n"
            "   // [FRZ-INJECT] post-floor RETRACE gate: no new entries until the adverse move has actually\n"
            "   // turned -- this is what the stuck state was doing by accident (a price condition, not a clock).\n"
            "   if(FreezePostFloorRetraceATR > 0.0 && g_pfDir >= 0)\n"
            "   {\n"
            "      double pfAtr = ReadBuf(hATR_D1,0,1), pfPx = Bid_();\n"
            "      bool pfOk;\n"
            "      if(g_pfDir == (int)ORDER_TYPE_BUY)   // frozen LONGS: adverse = down, so TRAIL the low\n"
            "      { if(pfPx < g_pfExtreme) g_pfExtreme = pfPx;\n"
            "        pfOk = (pfPx >= g_pfExtreme + FreezePostFloorRetraceATR*pfAtr); }\n"
            "      else                                 // frozen SHORTS: adverse = up, trail the high\n"
            "      { if(pfPx > g_pfExtreme) g_pfExtreme = pfPx;\n"
            "        pfOk = (pfPx <= g_pfExtreme - FreezePostFloorRetraceATR*pfAtr); }\n"
            "      if(!pfOk) return;\n"
            "      Print(\"POST-FLOOR GATE CLEARED at \", DoubleToString(Bid_(),3));\n"
            "      g_pfDir = -1;\n"
            "   }\n")
    eg_park = eg.replace("if(UseFreezeHedge && g_freezeDir >= 0) return;",
                         "if(UseFreezeHedge && g_freezeDir >= 0 && !FreezeParkMode) return;")
    out = out.replace(eg, COOL + eg_park)

    # disarm guard ahead of the arm branch
    arm = "      if(g_freezeDir < 0 && PortfolioFloat() <= -RescueOnDrawdownPct/100.0 * Bal_())"
    assert out.count(arm) == 1, "freeze arm anchor"
    out = out.replace(arm, DISARM + arm)

    # peak reset at arm
    setdir = "               g_freezeDir = loseDir; g_freezeExtreme = px;"
    assert out.count(setdir) == 1, "arm set anchor"
    out = out.replace(setdir, setdir + " g_frzPeak = 0.0;\n               if(FreezeParkMode) ParkLegs(loseDir);")

    # the alternative release triggers, right after the ATR bounce computation
    shorts = ("         { if(px > g_freezeExtreme) g_freezeExtreme = px; "
              "bounce = (px <= g_freezeExtreme - FreezeReleaseATR*atrD1f); }")
    assert out.count(shorts) == 1, "bounce computation anchor"
    out = out.replace(shorts, shorts + "\n" + RELEASE)

    bt = "         if(PortfolioFloat() >= RescueBookTargetUSD)   // whole book green while frozen -> bank it all"
    assert out.count(bt) == 1, "freeze book-exit anchor"
    out = out.replace(bt, "         if(!FreezeParkMode && PortfolioFloat() >= RescueBookTargetUSD)   // whole book green while frozen -> bank it all")
    fr = "         if(g_freezeDir >= 0) return;                   // frozen: no other book management this tick"
    assert out.count(fr) == 1, "freeze return anchor"
    out = out.replace(fr, "         if(g_freezeDir >= 0 && !FreezeParkMode) return;   // frozen: no other book management this tick (park mode: the active book carries on)")

    # peak reset on release / book exit
    rel = "            g_freezeAnchor = g_freezeExtreme;   // anti-churn: re-freeze only beyond this"
    assert out.count(rel) == 1, "release anchor"
    out = out.replace(rel, rel + "\n               g_frzPeak = 0.0;")
    bx = "            g_freezeDir = -1; g_freezeAnchor = 0.0; g_peakBasketFloat = 0.0;"
    assert out.count(bx) == 1, "book-exit anchor"
    out = out.replace(bx, bx.rstrip() + " g_frzPeak = 0.0;")

    # tester rule: never pollute the shared signal CSV
    o = "input bool UseSignalLog          = true;"
    assert out.count(o) == 1, "UseSignalLog anchor"
    out = out.replace(o, "const bool UseSignalLog          = false;  // CELL: never pollute the shared CSV")

    # cell banner
    oninit = "int OnInit()\n{\n"
    assert oninit in out, "OnInit anchor"
    out = out.replace(oninit, oninit +
                      f'   Print("OIL FREEZE CELL {tag} -- SOLID4 LOCKED + disarm={str(disarm).lower()}'
                      f' capBE={str(cap_be).lower()} trail={trail}%");\n', 1)
    return f"//| GENERATED FRZ CELL {tag} from SOLID4 LOCKED -- regen via make_oil_frz_cells.py |\n" + out


def main():
    only = set(sys.argv[1:])
    src = io.open(SRC, encoding="utf-8", errors="replace").read()
    for tag, (disarm, cap_be, trail, cooldown, retrace, park) in CELLS.items():
        if only and tag not in only:
            continue
        code = build(tag, disarm, cap_be, trail, cooldown, retrace, park, src)
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
                        res = lines[-1].strip(); break
                except Exception:
                    continue
            print(f"{tag:<14} [{expdir.split(chr(92))[2][:22]:<22}] {res}")
        io.open(os.path.join(HERE, "ea", f"{tag}.mq5"), "w", encoding="utf-8").write(code)


if __name__ == "__main__":
    main()
