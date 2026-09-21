//+------------------------------------------------------------------+
//|  Marius SessionDrift GOLD  v0.1  (2026-08-23)                     |
//|  fib C REPLACEMENT candidate = a TIME edge, uncorrelated to the   |
//|  signal-driven grids. 11y XM + 5y PEP: gold accumulates in the    |
//|  Asian/early-London window (01:00 server peak, t-stat 3.7-6.0,    |
//|  positive 11/12 years) and gives back in the US afternoon.        |
//|  STRATEGY: one intraday LONG per day, EntryHour->ExitHour (server),|
//|  risk-normalized lots, ATR catastrophe stop, NO overnight hold    |
//|  (no swap). Optional SHORT of the give-back window.               |
//+------------------------------------------------------------------+
#property copyright "Marius"
#property version   "0.20"
#include <Trade/Trade.mqh>
CTrade trade;

input int    EntryHour       = 1;      // server hour to OPEN the long (Asian/London accumulation start)
input int    ExitHour        = 4;      // server hour to CLOSE. 04:00 is PF-optimal (measured: exit 04 = PF 1.53/DD 9.1% vs exit 05 = PF 1.28/DD 13.3%; hr 04->05 is noise). Was 5.
input bool   UseGiveBackShort= false;  // also SHORT the US give-back window
input int    ShortEntryHour  = 16;     // give-back short open
input int    ShortExitHour   = 20;     // give-back short close
input double FixedLots       = 0.01;   // v0.2 DEFAULT 0.01 = validated sleeve size (MC: DD p90 ~11%, ruin 0%).
                                       // 0 = risk-based. NOTE: at ~$3k the risk path floors to the
                                       // broker minimum anyway, so set this explicitly to control size.
input double RiskPctPerTrade = 2.0;    // % of balance risked to the ATR stop
input double StopATRMult     = 1.5;    // catastrophe stop = this x ATR(D1); time-exit normally fires first
input double TargetATRMult   = 0.0;    // >0 = take-profit at this x ATR(D1) (banks the drift before it
                                       // fades; sim 2026-08-23: 0.5/0.5 with the stop = PF 1.55->1.65,
                                       // DD 8.1%->5.8%). 0 = clock exit only (validated baseline).
input int    ATRPeriod       = 14;     // ATR(D1) period for sizing/stop
input double MaxLots         = 5.0;    // hard lot cap
input int    MagicNumber     = 88231;  // SessionDrift gold
input string CommentText     = "SessDrift";

int    atrHandle;
double g_atrBuf[];

int OnInit()
{
   atrHandle = iATR(_Symbol, PERIOD_D1, ATRPeriod);
   if(atrHandle == INVALID_HANDLE){ Print("ATR handle fail"); return INIT_FAILED; }
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(30);
   Print("SessionDrift GOLD v0.2 FWD (validated cell 2026-08-23): long ", EntryHour, ":00->", ExitHour,
         ":00 server, giveback-short=", UseGiveBackShort);
   Print("CONFIG | EXITS = clock ", ExitHour, ":00 + stop ", DoubleToString(StopATRMult,2),
         "xATR", (TargetATRMult > 0 ? " + target " + DoubleToString(TargetATRMult,2) + "xATR" : " (no target)"));
   if(FixedLots > 0.0)
      Print("CONFIG | SIZING = FIXED ", DoubleToString(FixedLots,2), " lots (RiskPctPerTrade ignored)");
   else
      Print("CONFIG | SIZING = RISK ", DoubleToString(RiskPctPerTrade,1),
            "% to a ", DoubleToString(StopATRMult,2), "xATR(D1) stop"
            " -- WARNING: at small balances this floors to the broker minimum lot");
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason){ IndicatorRelease(atrHandle); }

double AtrD1()
{
   if(CopyBuffer(atrHandle, 0, 1, 1, g_atrBuf) < 1) return 0.0;
   return g_atrBuf[0];
}

// my open position on this symbol/magic (-1 none, else ticket)
bool HasPosition(long &type)
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(PositionSelectByTicket(tk) && PositionGetString(POSITION_SYMBOL) == _Symbol
         && PositionGetInteger(POSITION_MAGIC) == MagicNumber)
      { type = PositionGetInteger(POSITION_TYPE); return true; }
   }
   return false;
}

double SizeLots(double stopDist)
{
   double vstep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double vmin_ = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vmax_ = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   if(FixedLots > 0.0)                                   // explicit size wins outright
   {
      double fl = FixedLots;
      if(vstep > 0) fl = MathRound(fl / vstep) * vstep;
      if(vmax_ > 0) fl = MathMin(fl, vmax_);
      return MathMax(vmin_, MathMin(fl, MaxLots));
   }
   if(stopDist <= 0) return 0.0;
   double bal   = AccountInfoDouble(ACCOUNT_BALANCE);
   double tickV = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickS = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tickV <= 0 || tickS <= 0) return 0.0;
   double riskMoney  = RiskPctPerTrade / 100.0 * bal;
   double lossPerLot = stopDist / tickS * tickV;           // $ lost per 1.0 lot at the stop
   double lots = (lossPerLot > 0) ? riskMoney / lossPerLot : 0.0;
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double vmin = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   if(step > 0) lots = MathFloor(lots / step) * step;
   lots = MathMax(vmin, MathMin(lots, MaxLots));
   return lots;
}

void OpenDir(bool isBuy)
{
   double atr = AtrD1();
   if(atr <= 0) return;
   double stopDist = StopATRMult * atr;
   double lots = SizeLots(stopDist);
   if(lots <= 0) return;
   double px  = isBuy ? SymbolInfoDouble(_Symbol, SYMBOL_ASK) : SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double sl  = isBuy ? px - stopDist : px + stopDist;
   double tp  = 0.0;
   if(TargetATRMult > 0)
      tp = isBuy ? px + TargetATRMult * atr : px - TargetATRMult * atr;
   if(isBuy) trade.Buy(lots, _Symbol, px, sl, tp, CommentText);
   else      trade.Sell(lots, _Symbol, px, sl, tp, CommentText);
}

void CloseMine()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(PositionSelectByTicket(tk) && PositionGetString(POSITION_SYMBOL) == _Symbol
         && PositionGetInteger(POSITION_MAGIC) == MagicNumber)
         trade.PositionClose(tk);
   }
}

datetime g_lastBar = 0;

void OnTick()
{
   // act once per M5 bar (enough granularity for hour transitions)
   datetime bt = iTime(_Symbol, PERIOD_M5, 0);
   if(bt == g_lastBar) return;
   g_lastBar = bt;

   MqlDateTime st; TimeToStruct(TimeCurrent(), st);
   int h = st.hour;
   long type;
   bool have = HasPosition(type);

   // --- LONG accumulation window ---
   if(!have && h == EntryHour)            { OpenDir(true); return; }
   if(have && type == POSITION_TYPE_BUY && h >= ExitHour && h < ExitHour + 4) { CloseMine(); return; }

   // --- optional SHORT give-back window ---
   if(UseGiveBackShort)
   {
      if(!have && h == ShortEntryHour)    { OpenDir(false); return; }
      if(have && type == POSITION_TYPE_SELL && h >= ShortExitHour && h < ShortExitHour + 4) { CloseMine(); return; }
   }
}
//+------------------------------------------------------------------+
