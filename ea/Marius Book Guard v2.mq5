//+------------------------------------------------------------------+
//| Marius Book Guard v2 — the circuit breaker that can NEUTRALIZE   |
//| instead of amputate (built 2026-09-03, the double-trip autopsy). |
//|                                                                  |
//| WHY v2: on 2026-09-03 04:09 both live guards flattened the gold  |
//| sell grid at -8.2%/-8.3% — realizing -$427 family AT THE EXTREME |
//| of an overnight squeeze, while the engines' own recovery organs  |
//| (the FIBC8 ride at the same 8%, signal-sampled) never got to     |
//| run. A flatten at the extreme converts a recoverable float into  |
//| a certain loss. A 1:1 FREEZE pins the same loss (it cannot grow  |
//| by one cent more, gaps included) but KEEPS the recovery option:  |
//| the hedge is released when the trip clears and the engines'      |
//| own organs resume. The freeze mechanism is live-proven (oil     |
//| DAYRANK: pinned -$353 through 2 further adverse legs, realized   |
//| at exactly the pinned float).                                    |
//|                                                                  |
//| DEFAULTS = v1 behaviour EXACTLY (flatten, realized+floating).    |
//| Every v2 feature is opt-in:                                      |
//|  FreezeOnDailyTrip: daily trip -> open 1:1 opposite hedges per   |
//|    symbol (guard magic 909090) so NET exposure = 0; maintained   |
//|    while tripped (engine adds get re-neutralized); RELEASED     |
//|    automatically when the daily trip clears (next day) — only    |
//|    the guard's own hedges close, the engines' book continues.    |
//|    The EQUITY FLOOR always flattens — that is the ruin line.     |
//|  UseRealizedOnlyDaily: the daily cap counts REALIZED losses only |
//|    (the repeated-cut disease it was built for), with a separate  |
//|    wider FloatBackstopPct on realized+floating as the deep-float |
//|    backstop. Measured basis (08-22): floating-inclusive 8% =     |
//|    7 trips / zero genuine saves on the composed path.            |
//|                                                                  |
//| Needs a HEDGING account. Attach to ONE spare chart per account.  |
//| Never generates entries of its own beyond the neutralizing hedge.|
//+------------------------------------------------------------------+
#property copyright "Marius"
#property version   "2.00"
#property strict
#define BUILD "BOOKGUARD-2026-09-04-C"

#include <Trade\Trade.mqh>
CTrade trade;

input double MaxDailyLossPct   = 15.0;   // trip when the DAILY measure <= -this% of day-start balance (0=off). 2026-09-04: 15 (was 8) - must sit ABOVE gold's pin/ride band (12%) or the guard amputates the treatment
input double EquityFloorUSD    = 1900.0; // hard equity floor: FLATTEN + block below this (0=off) — always flattens
input bool   CloseOnTrip       = true;   // false = ALERT-ONLY mode (no closes, no freezes)
input double WarnAtPctOfLimit  = 0.75;   // early warning at this fraction of the daily limit
//--- v2 (all default-OFF = v1 behaviour) --------------------------------------------
input bool   FreezeOnDailyTrip = true;   // daily trip -> 1:1 NEUTRALIZE (hold, release on clear) instead of flatten. 2026-09-04: default ON (the deployed shape on MAIN+DEON)
input bool   UseRealizedOnlyDaily = false; // daily cap counts realized-only; floating covered by FloatBackstopPct
input double FloatBackstopPct  = 15.0;   // (realized-only mode) realized+floating <= -this% still trips (0=off)
input long   GuardMagic        = 909090; // magic for the guard's own hedge positions (no clash with any engine)
input int    MaxFreezeDays     = 10;     // the OPTION'S EXPIRY (0 = hold forever). A gold 1:1 pin RENTS at
                                          // ~$3.75/night per 0.07x0.07 (swap long -95.58 + short +42.0 pts) =
                                          // ~64%/month of a $212 pin — the freeze is a DAYS instrument, not weeks.
                                          // Gold episodes resolve in ~2 days (p90); 10 days ~ 18% rent = a fair
                                          // premium. At expiry the WHOLE pinned pair is REALIZED (= v1's flatten,
                                          // N days later, minus rent, plus N days of recovery chances).
input double FreezeReleaseFloatPct = 4.0; // (freeze mode) release the hedge only once the ENGINE book's float has
                                          // recovered to better than -this% of balance. Until then the SAME hedge
                                          // HOLDS — it rolls day to day, gap-immune, loss pinned, no churn. The
                                          // 2026-09-03 design answer to "does the hedge roll until price returns?"
                                          // -> YES: calendar clears the trip, PRICE clears the freeze.

datetime g_lastWarnDay = 0;
datetime g_lastHoldDay = 0;

//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetDeviationInPoints(50);
   trade.SetExpertMagicNumber(GuardMagic);
   EventSetTimer(3);
   Print("=====================================================");
   Print("MARIUS BOOK GUARD ", BUILD, " | acct ", AccountInfoInteger(ACCOUNT_LOGIN));
   Print("CONFIG | MaxDailyLossPct=", DoubleToString(MaxDailyLossPct,1),
         "% EquityFloorUSD=", DoubleToString(EquityFloorUSD,0),
         " CloseOnTrip=", CloseOnTrip, " (alert-only=", !CloseOnTrip, ")");
   Print("CONFIG | v2: FreezeOnDailyTrip=", FreezeOnDailyTrip,
         " UseRealizedOnlyDaily=", UseRealizedOnlyDaily,
         " FloatBackstopPct=", DoubleToString(FloatBackstopPct,1),
         "% FreezeReleaseFloatPct=", DoubleToString(FreezeReleaseFloatPct,1),
         "% GuardMagic=", GuardMagic);
   if(FreezeOnDailyTrip && (ENUM_ACCOUNT_MARGIN_MODE)AccountInfoInteger(ACCOUNT_MARGIN_MODE)
      != ACCOUNT_MARGIN_MODE_RETAIL_HEDGING)
      Print("WARNING | freeze mode needs a HEDGING account — this account is not; freeze will fail");
   Print("RESET  | daily trip auto-clears next day; FLOOR trip = delete GV 'BOOKGUARD_FLOOR_TRIP' (F3)");
   return(INIT_SUCCEEDED);
}
void OnDeinit(const int r) { EventKillTimer(); }

string DayTag()      { return TimeToString(TimeCurrent(), TIME_DATE); }
string TripGV()      { return "BOOKGUARD_TRIP_" + DayTag(); }
bool   DailyTripped(){ return GlobalVariableCheck(TripGV()); }
bool   FloorTripped(){ return GlobalVariableCheck("BOOKGUARD_FLOOR_TRIP"); }

double TodayRealized()
{
   datetime d0 = StringToTime(DayTag());
   if(!HistorySelect(d0, TimeCurrent() + 60)) return 0.0;
   double s = 0.0;
   for(int i = HistoryDealsTotal() - 1; i >= 0; i--)
   {
      ulong t = HistoryDealGetTicket(i);
      if(t == 0) continue;
      if(HistoryDealGetInteger(t, DEAL_ENTRY) != DEAL_ENTRY_OUT) continue;
      s += HistoryDealGetDouble(t, DEAL_PROFIT)
         + HistoryDealGetDouble(t, DEAL_SWAP)
         + HistoryDealGetDouble(t, DEAL_COMMISSION);
   }
   return s;
}

void Note(string msg)
{
   Print("BOOK GUARD: ", msg);
   Alert("BOOK GUARD: ", msg);
   SendNotification("BOOK GUARD: " + msg);
   int h = FileOpen("book_guard_alerts.csv",
                    FILE_READ|FILE_WRITE|FILE_CSV|FILE_COMMON|FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_ANSI, ',');
   if(h != INVALID_HANDLE)
   {
      FileSeek(h, 0, SEEK_END);
      FileWrite(h, TimeToString(TimeCurrent(), TIME_DATE|TIME_MINUTES),
                IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN)), msg);
      FileClose(h);
   }
}

void FlattenAll()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(tk > 0) trade.PositionClose(tk);
   }
}

double NormalizeVol(string sym, double v)
{
   double step = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
   double vmin = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
   double vmax = SymbolInfoDouble(sym, SYMBOL_VOLUME_MAX);
   if(step <= 0) step = 0.01;
   v = MathRound(v / step) * step;
   if(v < vmin) return 0.0;
   return MathMin(v, vmax);
}

//--- maintain per-symbol NET exposure == 0 while frozen. Idempotent: called every check
//--- while the daily trip stands, so engine legs opened after the trip get re-neutralized.
void MaintainFreeze()
{
   string syms[64]; int ns = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(tk == 0) continue;
      string s = PositionGetString(POSITION_SYMBOL);
      bool seen = false;
      for(int j = 0; j < ns; j++) if(syms[j] == s) { seen = true; break; }
      if(!seen && ns < 64) syms[ns++] = s;
   }
   for(int j = 0; j < ns; j++)
   {
      string sym = syms[j];
      double netEngines = 0.0, netGuard = 0.0;   // signed lots, buy = +
      for(int i = PositionsTotal() - 1; i >= 0; i--)
      {
         ulong tk = PositionGetTicket(i);
         if(tk == 0 || PositionGetString(POSITION_SYMBOL) != sym) continue;
         double v = PositionGetDouble(POSITION_VOLUME);
         double sv = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? v : -v;
         if(PositionGetInteger(POSITION_MAGIC) == GuardMagic) netGuard += sv; else netEngines += sv;
      }
      double residual = netEngines + netGuard;             // want 0
      double addVol = NormalizeVol(sym, MathAbs(residual));
      if(addVol <= 0.0) continue;
      bool ok;
      if(residual > 0) ok = trade.Sell(addVol, sym, 0, 0, 0, "BGFRZ");
      else             ok = trade.Buy (addVol, sym, 0, 0, 0, "BGFRZ");
      if(ok)
      {
         if(!GlobalVariableCheck("BOOKGUARD_FRZ_SINCE"))
            GlobalVariableSet("BOOKGUARD_FRZ_SINCE", (double)TimeCurrent());
         Note(StringFormat("FREEZE: %s book net %.2f -> hedged %.2f %s. Loss PINNED; releases on recovery, expires day %d.",
                               sym, netEngines, addVol, (residual > 0 ? "SELL" : "BUY"), MaxFreezeDays));
      }
      else   Note(StringFormat("FREEZE FAILED on %s (ret %d) — book NOT fully neutral, will retry.",
                               sym, (int)trade.ResultRetcode()));
   }
}

void ReleaseFreeze()
{
   int released = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(tk == 0) continue;
      if(PositionGetInteger(POSITION_MAGIC) != GuardMagic) continue;
      if(trade.PositionClose(tk)) released++;
   }
   if(released > 0)
      Note(StringFormat("FREEZE RELEASED: %d guard hedge(s) closed — the trip cleared, engines resume unhedged.",
                        released));
}

double EngineFloat()   // the float that WOULD be re-exposed if the hedge released now
{
   double f = 0.0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(tk == 0) continue;
      if(PositionGetInteger(POSITION_MAGIC) == GuardMagic) continue;
      f += PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
   }
   return f;
}

bool HaveGuardPositions()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(tk > 0 && PositionGetInteger(POSITION_MAGIC) == GuardMagic) return true;
   }
   return false;
}

void Check()
{
   double bal  = AccountInfoDouble(ACCOUNT_BALANCE);
   double eq   = AccountInfoDouble(ACCOUNT_EQUITY);
   double real = TodayRealized();
   double dayStartBal = bal - real;
   double dayPnL = real + (eq - bal);            // realized today + floating
   if(dayStartBal <= 0) return;

   if(FloorTripped())
   {
      if(CloseOnTrip && PositionsTotal() > 0) FlattenAll();
      return;
   }
   if(DailyTripped())
   {
      if(!CloseOnTrip) return;
      if(FreezeOnDailyTrip) MaintainFreeze();               // hold neutral, never deepen
      else if(PositionsTotal() > 0) FlattenAll();           // v1 behaviour
      return;
   }
   // trip cleared (new day). PRICE-AWARE release (2026-09-03 fix): a calendar boundary is
   // not evidence the danger passed. Release ONLY when the engine book's float has recovered
   // inside -FreezeReleaseFloatPct% of balance; otherwise HOLD the same hedge — pinned,
   // gap-immune, rolling day to day until price returns. Without this, floating-inclusive
   // mode would release+instantly-re-trip every midnight (churn), and a still-deep book
   // would be re-exposed for the seconds between release and re-trip.
   if(FreezeOnDailyTrip && HaveGuardPositions())
   {
      bool floorNow = (EquityFloorUSD > 0) && (eq <= EquityFloorUSD);
      double ef = EngineFloat();
      double age = GlobalVariableCheck("BOOKGUARD_FRZ_SINCE")
                   ? (TimeCurrent() - (datetime)GlobalVariableGet("BOOKGUARD_FRZ_SINCE")) / 86400.0 : 0.0;
      // THE EXPIRY (2026-09-03, "what if it never comes back in 30 days?"): the freeze is an
      // option whose premium is the nightly swap rent. Past MaxFreezeDays the premium has eaten
      // a meaningful share of the pin -> realize the WHOLE pinned pair. Outcome = v1's flatten,
      // N days later, minus rent — never worse than that, and usually the release fired long ago.
      if(!floorNow && MaxFreezeDays > 0 && age >= MaxFreezeDays)
      {
         double rent = 0.0;
         for(int i = PositionsTotal() - 1; i >= 0; i--)
            if(PositionGetTicket(i) > 0) rent += PositionGetDouble(POSITION_SWAP);
         Note(StringFormat("FREEZE EXPIRED after %.0f days (engine float still %.2f, swap rent paid %.2f) "
                           "-> REALIZING the pinned pair. The option ran out; the loss is booked.",
                           age, ef, rent));
         FlattenAll();
         GlobalVariableDel("BOOKGUARD_FRZ_SINCE");
         return;
      }
      if(!floorNow && ef < -FreezeReleaseFloatPct/100.0 * dayStartBal)
      {
         MaintainFreeze();                             // stay neutral; re-hedge any engine adds
         datetime today = StringToTime(DayTag());
         if(g_lastHoldDay != today)
         {
            g_lastHoldDay = today;
            double rent = 0.0;
            for(int i = PositionsTotal() - 1; i >= 0; i--)
               if(PositionGetTicket(i) > 0) rent += PositionGetDouble(POSITION_SWAP);
            Note(StringFormat("FREEZE HELD day %.0f/%d: engine float %.2f (%.1f%% of %.2f), swap rent so far %.2f; "
                              "releases when float recovers above -%.1f%%.",
                              age, MaxFreezeDays, ef, 100.0*ef/dayStartBal, dayStartBal, rent,
                              FreezeReleaseFloatPct));
         }
         return;                                       // do NOT re-trip on the pinned float
      }
      if(!floorNow) { ReleaseFreeze(); GlobalVariableDel("BOOKGUARD_FRZ_SINCE"); }
   }

   bool floorTrip = (EquityFloorUSD > 0) && (eq <= EquityFloorUSD);
   double dailyMeasure = UseRealizedOnlyDaily ? real : dayPnL;
   bool dailyTrip = (MaxDailyLossPct > 0) && (dailyMeasure <= -MaxDailyLossPct/100.0 * dayStartBal);
   // realized-only mode still needs a deep-float backstop (wider, so the engines' own
   // organs — rescue/staged/floor — get to run in order before the account-level line)
   bool backstop = UseRealizedOnlyDaily && (FloatBackstopPct > 0)
                   && (dayPnL <= -FloatBackstopPct/100.0 * dayStartBal);

   if(floorTrip)
   {
      GlobalVariableSet("BOOKGUARD_FLOOR_TRIP", 1.0);
      Note(StringFormat("EQUITY FLOOR TRIPPED: equity %.2f <= %.0f -> %s. Book stays FLAT until GV reset.",
                        eq, EquityFloorUSD, CloseOnTrip ? "FLATTENING ALL" : "ALERT-ONLY"));
      if(CloseOnTrip) FlattenAll();                          // the ruin line ALWAYS flattens
      return;
   }
   if(dailyTrip || backstop)
   {
      GlobalVariableSet(TripGV(), 1.0);
      string what = backstop && !dailyTrip
                    ? StringFormat("FLOAT BACKSTOP TRIPPED: day P&L %.2f (%.1f%% of day-start %.2f)",
                                   dayPnL, 100.0*dayPnL/dayStartBal, dayStartBal)
                    : StringFormat("DAILY LOSS LIMIT TRIPPED: %s %.2f (%.1f%% of day-start %.2f)",
                                   UseRealizedOnlyDaily ? "realized" : "today",
                                   dailyMeasure, 100.0*dailyMeasure/dayStartBal, dayStartBal);
      string act = !CloseOnTrip ? "ALERT-ONLY"
                   : (FreezeOnDailyTrip ? "FREEZING 1:1 (loss pinned, releases next day)" : "FLATTENING ALL");
      Note(what + " -> " + act + ". Auto-clears next day.");
      if(CloseOnTrip)
      {
         if(FreezeOnDailyTrip) MaintainFreeze();
         else FlattenAll();
      }
      return;
   }

   if(MaxDailyLossPct > 0 && dayPnL <= -WarnAtPctOfLimit * MaxDailyLossPct/100.0 * dayStartBal)
   {
      datetime today = StringToTime(DayTag());
      if(g_lastWarnDay != today)
      {
         g_lastWarnDay = today;
         Note(StringFormat("WARNING: today %.2f = %.0f%% of the daily limit (limit %.1f%% of %.2f).",
                           dayPnL, 100.0*WarnAtPctOfLimit, MaxDailyLossPct, dayStartBal));
      }
   }
}

void OnTimer() { Check(); }
void OnTick()  { Check(); }
//+------------------------------------------------------------------+
