//+------------------------------------------------------------------+
//| Marius Book Guard — the ACCOUNT-LEVEL circuit breaker (gap #1).  |
//| 2026-08-08: automates the user's framework-correct Aug-5 manual  |
//| stand-down. Attach to ONE spare chart (any symbol/TF). It never  |
//| opens trades — it only FLATTENS EVERYTHING and keeps the book    |
//| flat when a book-level limit is breached, and notifies.          |
//|                                                                  |
//| Triggers:                                                        |
//|  DAILY: today's P&L (realized+floating) <= -MaxDailyLossPct% of  |
//|         day-start balance  -> flatten + block until next day     |
//|  FLOOR: equity <= EquityFloorUSD -> flatten + block PERMANENTLY  |
//|         (until the user deletes GV "BOOKGUARD_FLOOR_TRIP", F3)   |
//| Restart-safe: trip state = terminal GlobalVariables; daily P&L   |
//| recomputed from deal history (no fragile day-start snapshot).    |
//| Notify: Print + Alert + SendNotification (needs MetaQuotes ID in |
//| Tools->Options->Notifications for phone push) + a Common\Files   |
//| log (book_guard_alerts.csv) that the Python auditor toasts.      |
//+------------------------------------------------------------------+
#property copyright "Marius"
#property version   "1.00"
#property strict
#define BUILD "BOOKGUARD-2026-08-08-A"

#include <Trade\Trade.mqh>
CTrade trade;

input double MaxDailyLossPct = 8.0;    // flatten+block when TODAY's P&L <= -this% of day-start balance (0=off)
input double EquityFloorUSD  = 1900.0; // hard equity floor: flatten+block below this (0=off)
input bool   CloseOnTrip     = true;   // false = ALERT-ONLY mode (no closes)
input double WarnAtPctOfLimit = 0.75;  // early warning when daily loss reaches this fraction of the limit

datetime g_lastWarnDay = 0;

//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetDeviationInPoints(50);
   EventSetTimer(3);
   Print("=====================================================");
   Print("MARIUS BOOK GUARD ", BUILD, " | acct ", AccountInfoInteger(ACCOUNT_LOGIN));
   Print("CONFIG | MaxDailyLossPct=", DoubleToString(MaxDailyLossPct,1),
         "% EquityFloorUSD=", DoubleToString(EquityFloorUSD,0),
         " CloseOnTrip=", CloseOnTrip, " (alert-only=", !CloseOnTrip, ")");
   Print("RESET  | daily trip auto-clears next day; FLOOR trip = delete GV 'BOOKGUARD_FLOOR_TRIP' (F3)");
   return(INIT_SUCCEEDED);
}
void OnDeinit(const int r) { EventKillTimer(); }

string DayTag()   { return TimeToString(TimeCurrent(), TIME_DATE); }
string TripGV()   { return "BOOKGUARD_TRIP_" + DayTag(); }
bool   Tripped()  { return GlobalVariableCheck(TripGV()) || GlobalVariableCheck("BOOKGUARD_FLOOR_TRIP"); }

double TodayRealized()
{
   datetime d0 = StringToTime(DayTag());          // 00:00 server today
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
   SendNotification("BOOK GUARD: " + msg);      // phone push if MetaQuotes ID configured
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

void Check()
{
   double bal  = AccountInfoDouble(ACCOUNT_BALANCE);
   double eq   = AccountInfoDouble(ACCOUNT_EQUITY);
   double real = TodayRealized();
   double dayStartBal = bal - real;
   double dayPnL = real + (eq - bal);            // realized today + floating
   if(dayStartBal <= 0) return;

   if(Tripped())
   {
      if(CloseOnTrip && PositionsTotal() > 0) FlattenAll();   // keep the book flat while tripped
      return;
   }

   bool dailyTrip = (MaxDailyLossPct > 0) && (dayPnL <= -MaxDailyLossPct/100.0 * dayStartBal);
   bool floorTrip = (EquityFloorUSD > 0) && (eq <= EquityFloorUSD);

   if(floorTrip)
   {
      GlobalVariableSet("BOOKGUARD_FLOOR_TRIP", 1.0);
      Note(StringFormat("EQUITY FLOOR TRIPPED: equity %.2f <= %.0f -> %s. Book stays FLAT until GV reset.",
                        eq, EquityFloorUSD, CloseOnTrip ? "FLATTENING ALL" : "ALERT-ONLY"));
      if(CloseOnTrip) FlattenAll();
      return;
   }
   if(dailyTrip)
   {
      GlobalVariableSet(TripGV(), 1.0);
      Note(StringFormat("DAILY LOSS LIMIT TRIPPED: today %.2f (%.1f%% of day-start %.2f) -> %s. Auto-clears next day.",
                        dayPnL, 100.0*dayPnL/dayStartBal, dayStartBal, CloseOnTrip ? "FLATTENING ALL" : "ALERT-ONLY"));
      if(CloseOnTrip) FlattenAll();
      return;
   }

   // early warning once per day
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
