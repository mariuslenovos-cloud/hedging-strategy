//+------------------------------------------------------------------+
//| Marius LongVol Bracket MT5 v1.0                                  |
//| LONG-VOLATILITY BRACKET (2026-08-24 sim, rebuilt 2026-09-06):    |
//| at server hour ArmHour arm an OCO stop-pair at ref +/- K*ATR(D1);|
//| a breach enters WITH the move, the opposite level is the stop,   |
//| the survivor is closed WindowHours after the arm. No direction   |
//| opinion, pure convexity. One arm per day, one position at a time.|
//| The value is COVARIANCE: the sim earned 93% of its net inside    |
//| the grid's documented pain windows (Jan/Mar/Jun/Aug-19 2026).    |
//| Gates pre-committed BEFORE the first tester run (CLAUDE.md       |
//| 2026-09-06 (2)): tester net >= 50% of the sim's $791 on the same |
//| window, pain-window sum > 0, worst trade <= 5% of $2,390.        |
//| Fail = shelve; H/K/W are NOT re-tuned on the tester.             |
//+------------------------------------------------------------------+
#property copyright "Marius"
#property version   "1.00"
#property strict
#define EA_BUILD "LONGVOL-2026-09-06-A"
#include <Trade/Trade.mqh>
CTrade trade;

input int    ArmHour      = 13;     // server hour of the arm bar (sim survivors: 13; 15 = second family)
input double KATR         = 0.7;    // bracket half-width in ATR(D1) (sim survivors: 0.7 @13:00, 0.5 @15:00)
input int    WindowHours  = 9;      // close the survivor this many hours after the arm (sim: 9 best, 6 next)
input int    ATRPeriod    = 14;     // ATR(D1) period (sim used a 14-day mean of daily ranges, prior days only)
input double FixedLots    = 0.01;   // sleeve size; the 0.01 floor IS the intended size at $2.4k
input int    MagicNumber  = 88241;  // LongVol gold (88231 = SessionDrift; 59955-59957 GridStat gold; 4901/4902 fib C)
input string CommentText  = "LongVol";
input bool   UseTradeLog  = true;   // Common\Files\longvol_trades.csv (deal-out rows)

int      atrHandle = INVALID_HANDLE;
double   g_atrBuf[];
datetime g_armDay   = 0;            // server date (00:00) of the last arm
datetime g_winEnd   = 0;            // arm time + WindowHours
bool     g_armed    = false;
double   g_up = 0, g_dn = 0, g_ref = 0, g_atr = 0;
datetime g_lastBar  = 0;

int OnInit()
{
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(30);
   atrHandle = iATR(_Symbol, PERIOD_D1, ATRPeriod);
   if(atrHandle == INVALID_HANDLE) { Print("ATR handle failed"); return INIT_FAILED; }
   ArraySetAsSeries(g_atrBuf, true);
   Print("MARIUS LONGVOL BRACKET ", EA_BUILD, " | Magic=", MagicNumber);
   Print("CONFIG | LONGVOL | ArmHour=", ArmHour, " KATR=", DoubleToString(KATR, 2), " WindowHours=", WindowHours,
         " ATRPeriod=", ATRPeriod, " FixedLots=", DoubleToString(FixedLots, 2), " TradeLog=", UseTradeLog ? "true" : "false");
   return INIT_SUCCEEDED;
}
void OnDeinit(const int reason) { IndicatorRelease(atrHandle); }

double AtrD1()
{
   if(CopyBuffer(atrHandle, 0, 1, 1, g_atrBuf) < 1) return 0.0;   // last CLOSED daily bar
   return g_atrBuf[0];
}

bool HasPosition()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(PositionSelectByTicket(tk) && PositionGetString(POSITION_SYMBOL) == _Symbol
         && PositionGetInteger(POSITION_MAGIC) == MagicNumber) return true;
   }
   return false;
}

void DeleteMyPendings()
{
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong tk = OrderGetTicket(i);
      if(OrderSelect(tk) && OrderGetString(ORDER_SYMBOL) == _Symbol && OrderGetInteger(ORDER_MAGIC) == MagicNumber)
         trade.OrderDelete(tk);
   }
}

void CloseMine()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(PositionSelectByTicket(tk) && PositionGetString(POSITION_SYMBOL) == _Symbol
         && PositionGetInteger(POSITION_MAGIC) == MagicNumber) trade.PositionClose(tk);
   }
}

double NormLots(double l)
{
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double vmin = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vmax = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   if(step > 0) l = MathRound(l / step) * step;
   return MathMax(vmin, MathMin(l, vmax));
}

void Arm(datetime barTime)
{
   double atr = AtrD1();
   if(atr <= 0) { Print("ARM skipped: ATR unavailable"); return; }
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK), bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ref = (ask + bid) / 2.0;
   double up = NormalizeDouble(ref + KATR * atr, _Digits), dn = NormalizeDouble(ref - KATR * atr, _Digits);
   double stops = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * _Point;
   if(up - ask < stops || bid - dn < stops) { Print("ARM skipped: bracket inside stops level"); return; }
   double lots = NormLots(FixedLots);
   bool ok1 = trade.BuyStop (lots, up, _Symbol, dn, 0.0, ORDER_TIME_GTC, 0, CommentText);
   bool ok2 = trade.SellStop(lots, dn, _Symbol, up, 0.0, ORDER_TIME_GTC, 0, CommentText);
   if(!ok1 || !ok2) { Print("ARM order error: buystop=", ok1, " sellstop=", ok2, " ret=", trade.ResultRetcode()); DeleteMyPendings(); return; }
   g_ref = ref; g_atr = atr; g_up = up; g_dn = dn;
   g_winEnd = barTime + (datetime)(WindowHours * 3600);
   g_armed  = true;
   MqlDateTime st; TimeToStruct(barTime, st); st.hour = 0; st.min = 0; st.sec = 0;
   g_armDay = StructToTime(st);
   Print("ARMED ", TimeToString(barTime), " ref=", DoubleToString(ref, _Digits), " ATR(D1)=", DoubleToString(atr, 2),
         " up=", DoubleToString(up, _Digits), " dn=", DoubleToString(dn, _Digits), " until ", TimeToString(g_winEnd));
}

void OnTick()
{
   datetime now = TimeCurrent();
   // OCO: once a position exists, no pending may remain
   if(g_armed && HasPosition() && OrdersTotal() > 0) DeleteMyPendings();
   // window exit: close the survivor, cancel anything left
   if(g_armed && now >= g_winEnd)
   {
      CloseMine(); DeleteMyPendings(); g_armed = false;
      Print("WINDOW END ", TimeToString(now));
   }
   datetime bt = iTime(_Symbol, PERIOD_M1, 0);
   if(bt == g_lastBar) return;
   g_lastBar = bt;
   MqlDateTime st; TimeToStruct(bt, st);
   if(g_armed) return;
   if(st.hour != ArmHour || st.min != 0) return;                 // the first M1 bar of the arm hour
   st.hour = 0; st.min = 0; st.sec = 0;
   if(StructToTime(st) == g_armDay) return;                       // one arm per server day
   if(HasPosition()) return;
   Arm(bt);
}

void OnTradeTransaction(const MqlTradeTransaction &t, const MqlTradeRequest &r, const MqlTradeResult &res)
{
   if(t.type != TRADE_TRANSACTION_DEAL_ADD) return;
   if(!HistoryDealSelect(t.deal)) return;
   if(HistoryDealGetInteger(t.deal, DEAL_MAGIC) != MagicNumber) return;
   if(HistoryDealGetString(t.deal, DEAL_SYMBOL) != _Symbol) return;
   long entry = HistoryDealGetInteger(t.deal, DEAL_ENTRY);
   if(entry == DEAL_ENTRY_IN) { DeleteMyPendings(); return; }   // OCO at the fill, not the next tick
   if(entry != DEAL_ENTRY_OUT || !UseTradeLog) return;
   int h = FileOpen("longvol_trades.csv", FILE_READ | FILE_WRITE | FILE_CSV | FILE_COMMON | FILE_ANSI | FILE_SHARE_READ | FILE_SHARE_WRITE, ',');
   if(h == INVALID_HANDLE) return;
   if(FileSize(h) == 0) FileWrite(h, "close_time", "symbol", "type", "lots", "price", "profit", "swap", "comm", "reason", "ref", "atr", "login", "build");
   FileSeek(h, 0, SEEK_END);
   FileWrite(h, TimeToString((datetime)HistoryDealGetInteger(t.deal, DEAL_TIME), TIME_DATE | TIME_MINUTES),
             _Symbol, (int)HistoryDealGetInteger(t.deal, DEAL_TYPE), DoubleToString(HistoryDealGetDouble(t.deal, DEAL_VOLUME), 2),
             DoubleToString(HistoryDealGetDouble(t.deal, DEAL_PRICE), _Digits),
             DoubleToString(HistoryDealGetDouble(t.deal, DEAL_PROFIT), 2), DoubleToString(HistoryDealGetDouble(t.deal, DEAL_SWAP), 2),
             DoubleToString(HistoryDealGetDouble(t.deal, DEAL_COMMISSION), 2), (int)HistoryDealGetInteger(t.deal, DEAL_REASON),
             DoubleToString(g_ref, _Digits), DoubleToString(g_atr, 2), IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN)), EA_BUILD);
   FileClose(h);
}
//+------------------------------------------------------------------+
