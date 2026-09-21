//+------------------------------------------------------------------+
//|  Marius Overnight ON4 v1.0 — the OVERNIGHT INDEX PREMIUM engine   |
//|                                                                   |
//|  THE SECOND ENGINE (2026-07-31): hold equity index exposure ONLY  |
//|  overnight — BUY at the cash close, SELL at the next cash open,   |
//|  flat all day. One market per chart; run 4 charts = the ON-4 book |
//|  (US500 / NAS100 / GER40 / JPN225).                               |
//|                                                                   |
//|  STRUCTURAL EDGE: the equity risk premium concentrates overnight  |
//|  (NY Fed "overnight drift"; earnings/news land off-hours). It is  |
//|  a RISK PREMIUM (paid for holding gap risk), not an arb.          |
//|  EVIDENCE (edge_overnight2.py, traded ETF prices, net of cost):   |
//|  portfolio Sharpe 0.76 full / +1.50 recent-3y (+15.6% ann);       |
//|  live-terminal cost check: net ~3.5-4.5bp/night survives on PEP.  |
//|  KNOWN RISK: overnight equity beta -> bear years (2022) negative. |
//|                                                                   |
//|  Session times auto-derive from the symbol (server GMT+2/+3,      |
//|  NY-anchored broker). DST caveat: GER/JPN windows can drift 1h in |
//|  off-season — override via inputs if needed.                      |
//+------------------------------------------------------------------+
#property copyright "Marius"
#property version   "1.00"

#define EA_BUILD_VERSION "ON4-2026-07-31-A"

#include <Trade/Trade.mqh>
CTrade trade;

//--- sizing
input double NotionalPct     = 50.0;   // position notional as % of balance (per market; 4 markets ~= 2x book overnight)
input double MaxSpreadBp     = 5.0;    // skip entry if spread > this (bp of price); 0 = no check
//--- session times: -1 = AUTO from symbol name (see table below)
input int    EntryHour       = -1;     // server hour to BUY (just before cash close)
input int    EntryMinute     = -1;
input int    ExitHour        = -1;     // server hour to SELL (just after next cash open)
input int    ExitMinute      = -1;
input int    WindowMinutes   = 20;     // act within [time, time+window)
input bool   SkipFridayEntry = false;  // true = no weekend holds (measured edge INCLUDES weekends; test both)
input bool   UseTradeLog     = true;   // append closed trades -> Common\Files\on4_trades.csv

long   MagicNumber;
int    gEntryM = -1, gExitM = -1;

//+------------------------------------------------------------------+
int OnInit()
{
   // auto session times by symbol (server time, GMT+3 summer / NY-anchored)
   string s = _Symbol;
   int eh=-1, em=50, xh=-1, xm=35;
   if(StringFind(s,"US500")>=0 || StringFind(s,"SPX")>=0 ||
      StringFind(s,"NAS100")>=0 || StringFind(s,"USTEC")>=0 || StringFind(s,"US30")>=0)
      { eh=22; em=50; xh=16; xm=35; }                     // NYSE: close 23:00, open 16:30 server
   else if(StringFind(s,"GER40")>=0 || StringFind(s,"DE40")>=0 || StringFind(s,"DAX")>=0)
      { eh=18; em=20; xh=10; xm=5; }                      // Xetra: close 18:30, open 10:00 server
   else if(StringFind(s,"JPN225")>=0 || StringFind(s,"JP225")>=0 || StringFind(s,"NIK")>=0)
      { eh=8;  em=50; xh=3;  xm=5; }                      // TSE: close 09:00, open 03:00 server
   if(EntryHour >= 0) { eh = EntryHour; em = (EntryMinute>=0? EntryMinute:0); }
   if(ExitHour  >= 0) { xh = ExitHour;  xm = (ExitMinute >=0? ExitMinute :0); }
   if(eh < 0 || xh < 0)
   {
      Print("ON4: unknown symbol '", s, "' and no manual times set -> set Entry/Exit Hour/Minute inputs");
      return(INIT_FAILED);
   }
   gEntryM = eh*60+em;  gExitM = xh*60+xm;
   // magic unique per symbol (no clash with GridStat/fibC ranges)
   int h = 0; string key = "ON4"+s;
   for(int i=0; i<StringLen(key); i++) h = (h*31 + StringGetCharacter(key,i)) % 100000;
   MagicNumber = 200000 + h;
   trade.SetExpertMagicNumber(MagicNumber);
   Print("MARIUS OVERNIGHT ", EA_BUILD_VERSION, " | ", s,
         " | entry ", eh, ":", StringFormat("%02d",em), " exit ", xh, ":", StringFormat("%02d",xm),
         " (server) | NotionalPct=", DoubleToString(NotionalPct,0),
         "% | SkipFridayEntry=", SkipFridayEntry, " | magic ", MagicNumber);
   Print("CONFIG | overnight-only hold: buy cash close -> sell cash open; edge=overnight drift (risk premium)");
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
bool MyPosition(ulong &ticket)
{
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(tk==0 || !PositionSelectByTicket(tk)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      ticket = tk; return true;
   }
   return false;
}

bool InWindow(int nowM, int targetM)
{
   int d = nowM - targetM;
   if(d < 0) d += 1440;
   return (d >= 0 && d < WindowMinutes);
}

//+------------------------------------------------------------------+
void OnTick()
{
   MqlDateTime dt; TimeToStruct(TimeCurrent(), dt);
   int nowM = dt.hour*60 + dt.min;
   ulong tk; bool have = MyPosition(tk);

   // EXIT: at the cash open (or first tick inside the window after a holiday hold-over)
   if(have && InWindow(nowM, gExitM))
   {
      if(trade.PositionClose(tk))
         Print("ON4 EXIT at cash open");
      return;
   }

   // ENTRY: just before the cash close
   if(!have && InWindow(nowM, gEntryM))
   {
      if(SkipFridayEntry && dt.day_of_week == 5) return;
      double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      if(bid <= 0 || ask <= 0) return;
      if(MaxSpreadBp > 0 && 1e4*(ask-bid)/bid > MaxSpreadBp) return;   // abnormal spread (news) -> skip tonight
      double cs  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_CONTRACT_SIZE);
      double bal = AccountInfoDouble(ACCOUNT_BALANCE);
      double lots = NotionalPct/100.0 * bal / (bid * cs);
      double minL = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
      double stp  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
      if(stp > 0) lots = MathFloor(lots/stp)*stp;
      if(lots < minL) lots = minL;
      double maxL = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
      if(maxL > 0 && lots > maxL) lots = maxL;
      if(trade.Buy(lots, _Symbol, ask, 0, 0, "ON4"))
         Print("ON4 ENTRY at cash close: ", DoubleToString(lots,2), " lots (notional ",
               DoubleToString(lots*bid*cs,0), " = ", DoubleToString(100.0*lots*bid*cs/bal,0), "% of balance)");
   }
}

//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &trans, const MqlTradeRequest &req, const MqlTradeResult &res)
{
   if(!UseTradeLog) return;
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD) return;
   if(!HistoryDealSelect(trans.deal)) return;
   if(HistoryDealGetInteger(trans.deal, DEAL_MAGIC) != MagicNumber) return;
   if(HistoryDealGetInteger(trans.deal, DEAL_ENTRY) != DEAL_ENTRY_OUT) return;
   double p = HistoryDealGetDouble(trans.deal, DEAL_PROFIT) + HistoryDealGetDouble(trans.deal, DEAL_SWAP)
            + HistoryDealGetDouble(trans.deal, DEAL_COMMISSION);
   int fh = FileOpen("on4_trades.csv", FILE_READ|FILE_WRITE|FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_CSV|FILE_COMMON|FILE_ANSI, ',');
   if(fh == INVALID_HANDLE) return;
   FileSeek(fh, 0, SEEK_END);
   if(FileTell(fh) == 0) FileWrite(fh, "close_time","symbol","volume","net_profit");
   FileWrite(fh, TimeToString(TimeCurrent(), TIME_DATE|TIME_MINUTES), _Symbol,
             DoubleToString(HistoryDealGetDouble(trans.deal, DEAL_VOLUME),2), DoubleToString(p,2));
   FileClose(fh);
}
//+------------------------------------------------------------------+
