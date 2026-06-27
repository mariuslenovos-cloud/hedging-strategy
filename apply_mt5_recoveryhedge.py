#!/usr/bin/env python3
"""
Port the validated MT4 RECOVERY HEDGE (+ trail + target-scaling) into the MT5 fib C.
Default OFF (UseRecoveryHedge=false) -> base behaviour byte-identical to the current EA.
Adapts the MQL4 OrderSelect logic to MQL5/CTrade (PositionGetTicket, POSITION_TYPE_*,
trade.PositionClose). Same parameters + same logic as the MT4 SAFE build.
"""
import io, sys
PATH = r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\BB16F565FAAA6B23A20C26C49416FF05\MQL5\Experts\Marius Hedger M5 fib C MT5 v1.0.mq5"
s = open(PATH, "rb").read().decode("utf-8")
if "UseRecoveryHedge" in s:
    print("ALREADY PATCHED -- aborting."); sys.exit(1)
had_crlf = "\r\n" in s
s = s.replace("\r\n", "\n")   # normalize for matching; restored on write

def rep(t, old, new):
    assert old in t, f"NOT FOUND:\n{old!r}"
    assert t.count(old) == 1, f"AMBIGUOUS ({t.count(old)}x):\n{old!r}"
    return t.replace(old, new)
def after_line(t, token, payload):
    i = t.find(token); assert i != -1, f"NOT FOUND {token!r}"
    assert t.count(token) == 1, f"AMBIGUOUS token {token!r}"
    nl = t.find("\n", i); return t[:nl+1] + payload + t[nl+1:]

# 0. bump build tag
s = rep(s, '#define BUILD "FIBC-MT5-2026-06-23-G"',
           '#define BUILD "FIBC-MT5-2026-06-27-H"')   # +recovery hedge

# 1. INPUTS (after FirstGateMinSamples)
s = after_line(s, "input int    FirstGateMinSamples  = 10;",
"""//--- RECOVERY HEDGE (the validated MT4 win, session 19v): when the book is deep underwater,
//    STOP feeding the loser and RIDE the winning (trend) side on every Goldminer signal until
//    the whole book recovers to +target. Averaging-in recovers mean-reversion; riding the winner
//    recovers sustained trends (the deep-basket cause). Overrides D1/session/imbalance/MaxSameTrades
//    for the WINNING side only. Catastrophe floor stays the backstop. DEFAULT OFF -> base unchanged.
input bool   UseRecoveryHedge     = false;
input double HedgeTriggerLoss     = 300.0;  // arm when book float <= -this ($)
input double HedgeTriggerPctBal   = 0.0;    // >0: arm when book float <= -this%% of balance (overrides HedgeTriggerLoss; deposit-portable). Validated 3.
input double RecoveryTargetUSD    = 40.0;   // close the WHOLE book once it recovers to +this ($)
input bool   UseRecoveryTrail     = false;  // [opt1] once recovered to +target, TRAIL the winner instead of flat-closing (+4%% on gold)
input double RecoveryTrailGiveback = 20.0;  // give-back ($) from the recovery peak that closes (locks >= effective target)
input double RecoveryTargetPct    = 0.0;    // [opt2] >0: scale target to this %% of the DEEPEST loss rescued (max w/ RecoveryTargetUSD). +3%% on gold at 10.
""")

# 2. GLOBALS (after tradesThisBar)
s = after_line(s, "int      tradesThisBar=0;",
"""bool     g_recovering=false;
int      g_recoverWinDir=-1;     // POSITION_TYPE_BUY / _SELL = the side we ride to recover
bool     g_recoverArmed=false;
double   g_recoverPeak=0;
double   g_recoverDeepest=0;
""")

# 3. CheckRecoveryHedge() -- insert before the basket-trail section
s = rep(s,
"//--- basket trail (every tick) + catastrophe floor (safety, default off) -------",
"""//--- RECOVERY HEDGE: arm when deep underwater, ride the winning side, exit the whole book in profit.
//    Sets g_recovering. The catastrophe floor (in CheckBasketTrail) stays the backstop.
void CheckRecoveryHedge()
{
   if(!UseRecoveryHedge){ g_recovering=false; return; }
   double bal=AccountInfoDouble(ACCOUNT_BALANCE);
   double bookFloat=BookFloat();

   if(g_recovering)
   {
      // safety: if the whole book got closed elsewhere, end the rescue cleanly
      if(CountOpen(POSITION_TYPE_BUY)==0 && CountOpen(POSITION_TYPE_SELL)==0){
         g_recovering=false; g_recoverWinDir=-1; g_recoverArmed=false; g_recoverPeak=0; g_recoverDeepest=0; return;
      }
      if(bookFloat < g_recoverDeepest) g_recoverDeepest=bookFloat;        // track deepest loss this rescue
      double effTarget = (RecoveryTargetPct>0) ? MathMax(RecoveryTargetUSD,(RecoveryTargetPct/100.0)*(-g_recoverDeepest)) : RecoveryTargetUSD;
      if(UseRecoveryTrail)
      {
         if(bookFloat>=effTarget){ if(!g_recoverArmed) g_recoverArmed=true; if(bookFloat>g_recoverPeak) g_recoverPeak=bookFloat; }
         if(g_recoverArmed){
            double exitLvl=MathMax(effTarget, g_recoverPeak-RecoveryTrailGiveback);
            if(bookFloat<=exitLvl && bookFloat<g_recoverPeak){
               Print("RECOVERY TRAIL exit: book=+",DoubleToString(bookFloat,2)," peak +",DoubleToString(g_recoverPeak,2)," tgt ",DoubleToString(effTarget,0));
               CloseAll(); g_recovering=false; g_recoverWinDir=-1; g_recoverArmed=false; g_recoverPeak=0; g_recoverDeepest=0; peakBasketFloat=0;
            }
         }
         return;
      }
      if(bookFloat>=effTarget){
         Print("RECOVERY COMPLETE: book=+",DoubleToString(bookFloat,2)," (tgt ",DoubleToString(effTarget,0),")");
         CloseAll(); g_recovering=false; g_recoverWinDir=-1; g_recoverDeepest=0; peakBasketFloat=0;
      }
      return;
   }

   // not recovering -> check the arm trigger
   double trigger = (HedgeTriggerPctBal>0) ? (HedgeTriggerPctBal/100.0)*bal : HedgeTriggerLoss;
   if(trigger>0 && bookFloat<=-trigger)
   {
      double bp=SideProfit(POSITION_TYPE_BUY), sp=SideProfit(POSITION_TYPE_SELL);
      g_recoverWinDir = (bp>=sp) ? POSITION_TYPE_BUY : POSITION_TYPE_SELL;  // ride the LESS-negative (trend) side
      g_recovering=true; g_recoverArmed=false; g_recoverPeak=0; g_recoverDeepest=bookFloat;
      Print("RECOVERY ARMED: book=",DoubleToString(bookFloat,2)," trigger=-",DoubleToString(trigger,2)," winDir=",(g_recoverWinDir==POSITION_TYPE_BUY?"BUY":"SELL"));
   }
}

//--- basket trail (every tick) + catastrophe floor (safety, default off) -------""")

# 4. CheckBasketTrail: signature + recovering-skip + floor resets recovery state
s = rep(s, "void CheckBasketTrail()\n{\n   double lotScale=LotScaleInt();",
           "void CheckBasketTrail(bool recovering=false)\n{\n   double lotScale=LotScaleInt();")
s = rep(s,
"""      if(tot <= -floorPct/100.0*AccountInfoDouble(ACCOUNT_BALANCE)){
         Print("BASKET STOP fired float=",DoubleToString(tot,2)," floorPct=",DoubleToString(floorPct,1)); CloseAll(); peakBasketFloat=0; return;
      }
   }""",
"""      if(tot <= -floorPct/100.0*AccountInfoDouble(ACCOUNT_BALANCE)){
         Print("BASKET STOP fired float=",DoubleToString(tot,2)," floorPct=",DoubleToString(floorPct,1)); CloseAll(); peakBasketFloat=0;
         g_recovering=false; g_recoverWinDir=-1; g_recoverArmed=false; g_recoverPeak=0; g_recoverDeepest=0; return;
      }
   }
   if(recovering) return;   // recovery owns the profit-side close; only the floor above runs while rescuing""")

# 5. OpenTrade: force param to bypass gates while rescuing
s = rep(s, "void OpenTrade(int dir)  // dir +1 buy / -1 sell\n{\n   int ptype=(dir>0)?POSITION_TYPE_BUY:POSITION_TYPE_SELL;\n   if(CountOpen(ptype)>=MaxSameTrades) return;",
           "void OpenTrade(int dir, bool force=false)  // dir +1 buy / -1 sell; force = recovery ride (bypass gates)\n{\n   int ptype=(dir>0)?POSITION_TYPE_BUY:POSITION_TYPE_SELL;\n   if(!force && CountOpen(ptype)>=MaxSameTrades) return;")
s = rep(s, "   if(UseFirstEntryGate && CountOpen(ptype)==0)",
           "   if(!force && UseFirstEntryGate && CountOpen(ptype)==0)")
s = rep(s, "   if(UseImbalanceLock){",
           "   if(!force && UseImbalanceLock){")
s = rep(s, "   if(UseMaxBasketLots && TotalOpenLots()+lot > MaxBasketLotsTotal) return;",
           "   if(!force && UseMaxBasketLots && TotalOpenLots()+lot > MaxBasketLotsTotal) return;")
s = rep(s, "   if(ok){ tradesThisBar++; ManageTradeClosures(); }",
           "   if(ok){ tradesThisBar++; if(!force) ManageTradeClosures(); }")

# 6. OnTick: wire recovery in (route entries to the winning side while rescuing)
s = rep(s,
"""   CheckBasketTrail();   // every tick

   if(UseSessionFilter){
      int hr=BarHour(TimeCurrent());
      bool inS=(SessionStartHour<SessionEndHour)?(hr>=SessionStartHour&&hr<SessionEndHour):(hr>=SessionStartHour||hr<SessionEndHour);
      if(!inS) return;
   }
   bool hasOpen=(CountOpen(POSITION_TYPE_BUY)>0||CountOpen(POSITION_TYPE_SELL)>0);
   if(!IsTrendDetected() && !hasOpen) return;
   if(tradesThisBar>=tradesperbar) return;

   int sig=GoldminerSignal();
   if(sig==0) return;
   // SAFETY: D1 trend filter
   if(UseDailyTrendFilter){
      if(sig>0 && !D1Bull()) return;
      if(sig<0 &&  D1Bull()) return;
   }""",
"""   CheckRecoveryHedge();          // arm/exit the deep-basket rescue -> sets g_recovering
   CheckBasketTrail(g_recovering);// catastrophe floor always; basket-trail skipped while rescuing

   if(!g_recovering && UseSessionFilter){
      int hr=BarHour(TimeCurrent());
      bool inS=(SessionStartHour<SessionEndHour)?(hr>=SessionStartHour&&hr<SessionEndHour):(hr>=SessionStartHour||hr<SessionEndHour);
      if(!inS) return;
   }
   if(tradesThisBar>=tradesperbar) return;

   int sig=GoldminerSignal();
   if(sig==0) return;

   // RECOVERY: ride ONLY the winning (trend) side, bypassing D1/session/imbalance/MaxSameTrades
   if(g_recovering){
      int winSig=(g_recoverWinDir==POSITION_TYPE_BUY)?1:-1;
      if(sig==winSig) OpenTrade(sig,true);
      return;
   }

   bool hasOpen=(CountOpen(POSITION_TYPE_BUY)>0||CountOpen(POSITION_TYPE_SELL)>0);
   if(!IsTrendDetected() && !hasOpen) return;
   // SAFETY: D1 trend filter
   if(UseDailyTrendFilter){
      if(sig>0 && !D1Bull()) return;
      if(sig<0 &&  D1Bull()) return;
   }""")

if had_crlf:
    s = s.replace("\n", "\r\n")   # restore Windows line endings
open(PATH, "wb").write(s.encode("utf-8"))
print("MT5 RECOVERY HEDGE PORT APPLIED OK.")
for t in ["UseRecoveryHedge","HedgeTriggerPctBal","RecoveryTargetPct","CheckRecoveryHedge",
          "g_recovering","void OpenTrade(int dir, bool force","CheckBasketTrail(bool recovering",
          "FIBC-MT5-2026-06-27-H"]:
    print(f"  present: {t in s}   {t}")
