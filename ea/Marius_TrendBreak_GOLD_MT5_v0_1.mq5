//+------------------------------------------------------------------+
//|  Marius TrendBreak GOLD  --  MT5 v0.1  (2026-08-17)               |
//|  The COMPLEMENT to GridStat / fib C: a volatility-breakout trend  |
//|  follower that bleeds small in chop and gets paid on the handful  |
//|  of real legs the grids cap at +$100 or sit out (VolBlockAll).    |
//|                                                                   |
//|  ENTRY  (new bar, H1 recommended):                                |
//|    close[1] breaks the prior N-bar Donchian high/low + buffer      |
//|    AND H4 EMA(50) slope agrees (skippable in a CrashGuard regime) |
//|    AND ATR(D1,5)/ATR(D1,60) >= VolExpandMin  (vol EXPANDING = go) |
//|    AND session / spread / cooldown / one-position-per-symbol       |
//|  EXIT: hard SL = StopATR x ATR; break-even at +BreakEvenATR;       |
//|    chandelier trail = TrailATR x ATR from best close; time-stop    |
//|    if no progress after TimeStopHours; optional Friday flat.       |
//|  SIZE: RiskPct of balance / stop distance (tick-value based).      |
//|                                                                   |
//|  CROSS-TALK (GlobalVariables, both optional):                      |
//|    reads  GS_CRASH_<SYMBOL>  (-1 down / 0 none / +1 up)            |
//|           written by GridStat CrashGuard (see upgrade notes)       |
//|    writes TB_DIR_<SYMBOL>    (-1 short / 0 flat / +1 long)         |
//|           so GridStat/fib C can refuse a fresh counter-trend basket|
//|  Needs nothing else. Own magic. Own comment. Own equity log.       |
//+------------------------------------------------------------------+
#property copyright "Marius"
#property version   "0.10"
#property strict
#include <Trade/Trade.mqh>
CTrade trade;

#define BUILD "TRENDBREAK-GOLD-MT5-2026-08-17-v0.1"

//--- signal
input int    DonchianPeriod    = 20;      // prior N bars high/low (bar 1 must CLOSE beyond it)
input double BreakoutBufferATR = 0.10;    // extra x ATR the close must clear (cuts hair-trigger breaks)
input int    ATRPeriod         = 14;      // ATR on the chart TF (stops, trail, sizing)
input ENUM_TIMEFRAMES HTF      = PERIOD_H4;
input int    HTF_EMA_Period    = 50;
input int    HTF_SlopeBars     = 3;       // EMA[1] vs EMA[1+this] = slope direction
input bool   UseHTFFilter      = true;
//--- volatility regime (the vol-expansion fib C HIDES from = this EA's GO signal)
input bool   UseVolExpandFilter = true;
input int    VolATRFast        = 5;
input int    VolATRSlow        = 60;
input double VolExpandMin      = 1.20;    // ATR(D1,fast)/ATR(D1,slow) >= this
//--- risk / exits
input double RiskPct           = 0.75;    // % of balance risked per trade (keep SMALL: this is the payoff engine, not the hit-rate engine)
input double MaxLots           = 1.00;
input double StopATR           = 1.50;    // initial SL distance x ATR
input double BreakEvenATR      = 1.00;    // move SL to BE (+spread) once price is this x ATR in profit
input double TrailATR          = 3.00;    // chandelier: SL = best close -/+ this x ATR (only after BE)
input int    TimeStopHours     = 72;      // close if open > this AND
input double TimeStopProgressATR = 0.50;  // ...profit still < this x ATR (dead trade)
input bool   FridayFlat        = false;   // close everything on Friday >= FridayFlatHour (gold gaps: usually leave OFF, SL handles it)
input int    FridayFlatHour    = 22;
//--- session / hygiene
input bool   UseSessionFilter  = true;
input int    SessionStartHour  = 9;       // server time; London-NY for gold
input int    SessionEndHour    = 22;
input int    MaxSpreadPoints   = 350;     // skip entries if spread wider (gold ~ 35 pips at 3-digit brokers)
input int    CooldownBars      = 6;       // bars to wait after a STOPPED trade before re-entering same direction
input int    MaxTradesPerDay   = 2;
//--- cross-talk with the grids
input bool   UseRegimeGV       = true;    // read GS_CRASH_<sym>: block counter-regime entries, skip HTF filter for aligned ones
input bool   WriteDirGV        = true;    // write TB_DIR_<sym> for the grids to read
//--- misc
input long   MagicNumber       = 260817;
input string CommentText       = "TrendBreak";
input bool   UseEquityLog      = false;   // research: time,balance,equity per bar -> Common\Files
input string EquityLogFile     = "trendbreak_gold_equity.csv";

//--- globals
int      hATR, hHTF, hATR_D1_fast, hATR_D1_slow;
datetime g_lastBar = 0;
double   g_point;
int      g_digits;
datetime g_lastStopTime[2];   // [0]=buy [1]=sell : time of last stopped-out trade per side
int      g_tradesToday = 0;
int      g_today = -1;
double   g_bestClose = 0;     // best close since entry (chandelier anchor)
bool     g_beDone = false;

//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(50);
   trade.SetTypeFillingBySymbol(_Symbol);
   g_point  = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   g_digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);

   hATR         = iATR(_Symbol, PERIOD_CURRENT, ATRPeriod);
   hHTF         = iMA(_Symbol, HTF, HTF_EMA_Period, 0, MODE_EMA, PRICE_CLOSE);
   hATR_D1_fast = iATR(_Symbol, PERIOD_D1, VolATRFast);
   hATR_D1_slow = iATR(_Symbol, PERIOD_D1, VolATRSlow);
   if(hATR==INVALID_HANDLE || hHTF==INVALID_HANDLE || hATR_D1_fast==INVALID_HANDLE || hATR_D1_slow==INVALID_HANDLE)
   { Print("indicator handle failed"); return(INIT_FAILED); }

   g_lastStopTime[0]=0; g_lastStopTime[1]=0;
   Print(BUILD, " | ", _Symbol, " ", EnumToString(Period()),
         " | Donchian=", DonchianPeriod, " StopATR=", StopATR, " TrailATR=", TrailATR,
         " Risk%=", RiskPct, " VolMin=", VolExpandMin, " HTF=", EnumToString(HTF));
   if(WriteDirGV) GlobalVariableSet("TB_DIR_"+_Symbol, 0);
   return(INIT_SUCCEEDED);
}
void OnDeinit(const int reason)
{
   if(WriteDirGV) GlobalVariableSet("TB_DIR_"+_Symbol, 0);
}

//+------------------------------------------------------------------+
double Buf(int h, int shift)
{
   double b[1];
   if(CopyBuffer(h, 0, shift, 1, b) != 1) return(0);
   return(b[0]);
}
int BarHour(datetime t){ MqlDateTime s; TimeToStruct(t,s); return(s.hour); }
int BarDOW (datetime t){ MqlDateTime s; TimeToStruct(t,s); return(s.day_of_week); }
int BarDay (datetime t){ MqlDateTime s; TimeToStruct(t,s); return(s.day_of_year); }

// our open position on this symbol (ticket or 0)
ulong OurPosition(int &type)
{
   type = -1;
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(tk==0) continue;
      if(PositionGetString(POSITION_SYMBOL)!=_Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC)!=MagicNumber) continue;
      type = (int)PositionGetInteger(POSITION_TYPE);
      return(tk);
   }
   return(0);
}
int RegimeGV()
{
   if(!UseRegimeGV) return(0);
   string n = "GS_CRASH_"+_Symbol;
   if(!GlobalVariableCheck(n)) return(0);
   return((int)GlobalVariableGet(n));
}
void SetDirGV(int v){ if(WriteDirGV) GlobalVariableSet("TB_DIR_"+_Symbol, v); }

//+------------------------------------------------------------------+
double LotsForRisk(double stopDist)
{
   double bal   = AccountInfoDouble(ACCOUNT_BALANCE);
   double riskUSD = bal * RiskPct / 100.0;
   double tickVal = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSz  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tickVal<=0 || tickSz<=0 || stopDist<=0) return(0);
   double lossPerLot = (stopDist / tickSz) * tickVal;
   double lots = riskUSD / lossPerLot;
   double minL = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxL = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   lots = MathFloor(lots/step)*step;
   if(lots > MaxLots) lots = MaxLots;
   if(lots > maxL) lots = maxL;
   if(lots < minL) return(0);   // stop too wide for the risk budget -> skip rather than over-risk
   return(NormalizeDouble(lots,2));
}

//+------------------------------------------------------------------+
void ManagePosition()
{
   int type; ulong tk = OurPosition(type);
   if(tk==0){ g_bestClose=0; g_beDone=false; SetDirGV(0); return; }
   if(!PositionSelectByTicket(tk)) return;

   double atr   = Buf(hATR,1);
   if(atr<=0) return;
   double open  = PositionGetDouble(POSITION_PRICE_OPEN);
   double sl    = PositionGetDouble(POSITION_SL);
   datetime t0  = (datetime)PositionGetInteger(POSITION_TIME);
   double bid   = SymbolInfoDouble(_Symbol,SYMBOL_BID), ask = SymbolInfoDouble(_Symbol,SYMBOL_ASK);
   double spread = ask-bid;
   double c1    = iClose(_Symbol,PERIOD_CURRENT,1);
   bool   isBuy = (type==POSITION_TYPE_BUY);
   double px    = isBuy ? bid : ask;
   double profitDist = isBuy ? (px-open) : (open-px);
   long   stopsLvl = SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL);
   double minDist  = stopsLvl*g_point;

   // Friday flat
   if(FridayFlat && BarDOW(TimeCurrent())==5 && BarHour(TimeCurrent())>=FridayFlatHour)
   { trade.PositionClose(tk); Print("TB: Friday flat close"); return; }

   // time-stop: dead trade
   if(TimeStopHours>0 && (TimeCurrent()-t0) > TimeStopHours*3600 && profitDist < TimeStopProgressATR*atr)
   { trade.PositionClose(tk); Print("TB: time-stop (no progress)"); return; }

   // chandelier anchor = best CLOSE since entry (evaluated on closed bars = less noise than ticks)
   if(g_bestClose==0) g_bestClose = c1;
   if(isBuy && c1>g_bestClose) g_bestClose=c1;
   if(!isBuy && c1<g_bestClose) g_bestClose=c1;

   double newSL = sl;
   // 1) break-even
   if(!g_beDone && profitDist >= BreakEvenATR*atr)
   {
      newSL = isBuy ? (open + spread + 2*g_point) : (open - spread - 2*g_point);
      g_beDone = true;
   }
   // 2) trail (only once BE is locked -> a triggered winner can never become a loss)
   if(g_beDone)
   {
      double trail = isBuy ? (g_bestClose - TrailATR*atr) : (g_bestClose + TrailATR*atr);
      if(isBuy && trail>newSL) newSL=trail;
      if(!isBuy && (newSL==0 || trail<newSL)) newSL=trail;
   }
   newSL = NormalizeDouble(newSL, g_digits);
   bool improves = isBuy ? (newSL > sl + g_point) : (sl==0 || newSL < sl - g_point);
   bool legal    = isBuy ? (bid - newSL >= minDist) : (newSL - ask >= minDist);
   if(improves && legal)
   {
      if(!trade.PositionModify(tk, newSL, 0.0))
         Print("TB: modify failed err=", GetLastError());
   }
}

//+------------------------------------------------------------------+
void OnTick()
{
   ManagePosition();

   bool newBar = (iTime(_Symbol,PERIOD_CURRENT,0) != g_lastBar);
   if(!newBar) return;
   g_lastBar = iTime(_Symbol,PERIOD_CURRENT,0);

   // per-bar research log
   if(UseEquityLog)
   {
      int fh = FileOpen(EquityLogFile, FILE_READ|FILE_WRITE|FILE_CSV|FILE_COMMON|FILE_ANSI, ',');
      if(fh!=INVALID_HANDLE){ FileSeek(fh,0,SEEK_END);
         FileWrite(fh, TimeToString(TimeCurrent(),TIME_DATE|TIME_MINUTES), AccountInfoDouble(ACCOUNT_BALANCE), AccountInfoDouble(ACCOUNT_EQUITY)); FileClose(fh); }
   }

   // reset daily counter
   int today = BarDay(TimeCurrent());
   if(today!=g_today){ g_today=today; g_tradesToday=0; }

   int type; if(OurPosition(type)!=0) return;               // one position per symbol
   if(g_tradesToday >= MaxTradesPerDay) return;
   if(UseSessionFilter){ int hr=BarHour(TimeCurrent()); if(!(hr>=SessionStartHour && hr<SessionEndHour)) return; }
   if(FridayFlat && BarDOW(TimeCurrent())==5 && BarHour(TimeCurrent())>=FridayFlatHour) return;

   long spreadPts = SymbolInfoInteger(_Symbol,SYMBOL_SPREAD);
   if(spreadPts > MaxSpreadPoints) return;

   double atr = Buf(hATR,1);
   if(atr<=0) return;

   // vol regime: expanding = go
   if(UseVolExpandFilter)
   {
      double f=Buf(hATR_D1_fast,1), s=Buf(hATR_D1_slow,1);
      if(s<=0 || f/s < VolExpandMin) return;
   }

   // Donchian of the PRIOR N bars (2..N+1), broken by the just-closed bar 1
   int hi = iHighest(_Symbol,PERIOD_CURRENT,MODE_HIGH,DonchianPeriod,2);
   int lo = iLowest (_Symbol,PERIOD_CURRENT,MODE_LOW, DonchianPeriod,2);
   if(hi<0 || lo<0) return;
   double chHigh = iHigh(_Symbol,PERIOD_CURRENT,hi), chLow = iLow(_Symbol,PERIOD_CURRENT,lo);
   double c1 = iClose(_Symbol,PERIOD_CURRENT,1);
   double buf = BreakoutBufferATR*atr;

   int dir = -1;
   if(c1 > chHigh + buf) dir = ORDER_TYPE_BUY;
   else if(c1 < chLow - buf) dir = ORDER_TYPE_SELL;
   if(dir<0) return;

   // regime cross-talk from GridStat CrashGuard
   int regime = RegimeGV();                       // -1 down, +1 up, 0 none
   if(regime==-1 && dir==ORDER_TYPE_BUY)  return; // don't buy the falling knife the grid already flagged
   if(regime== 1 && dir==ORDER_TYPE_SELL) return;
   bool regimeAligned = (regime==-1 && dir==ORDER_TYPE_SELL) || (regime==1 && dir==ORDER_TYPE_BUY);

   // HTF slope (skipped when the crash regime already confirms direction -- the D1 EMA lags exactly there)
   if(UseHTFFilter && !regimeAligned)
   {
      double e0=Buf(hHTF,1), e1=Buf(hHTF,1+HTF_SlopeBars);
      if(e0==0 || e1==0) return;
      if(dir==ORDER_TYPE_BUY  && !(e0>e1)) return;
      if(dir==ORDER_TYPE_SELL && !(e0<e1)) return;
   }

   // cooldown after a stop-out in the same direction
   int side = (dir==ORDER_TYPE_BUY)?0:1;
   if(g_lastStopTime[side]>0 && (TimeCurrent()-g_lastStopTime[side]) < CooldownBars*PeriodSeconds(PERIOD_CURRENT)) return;

   // sizing & orders
   double stopDist = StopATR*atr;
   double lots = LotsForRisk(stopDist);
   if(lots<=0){ Print("TB: skip, stop too wide for risk budget (", DoubleToString(stopDist,g_digits), ")"); return; }
   double ask=SymbolInfoDouble(_Symbol,SYMBOL_ASK), bid=SymbolInfoDouble(_Symbol,SYMBOL_BID);
   double sl = (dir==ORDER_TYPE_BUY) ? NormalizeDouble(ask-stopDist,g_digits) : NormalizeDouble(bid+stopDist,g_digits);
   bool ok = (dir==ORDER_TYPE_BUY) ? trade.Buy(lots,_Symbol,ask,sl,0.0,CommentText)
                                   : trade.Sell(lots,_Symbol,bid,sl,0.0,CommentText);
   if(ok)
   {
      g_tradesToday++; g_bestClose=c1; g_beDone=false;
      SetDirGV(dir==ORDER_TYPE_BUY?1:-1);
      Print("TB: ", (dir==ORDER_TYPE_BUY?"BUY":"SELL"), " ", lots, " @", (dir==ORDER_TYPE_BUY?ask:bid),
            " sl=", sl, " atr=", DoubleToString(atr,g_digits), " regime=", regime);
   }
   else Print("TB: order failed err=", GetLastError(), " ret=", trade.ResultRetcode());
}

//+------------------------------------------------------------------+
//| record stop-outs for the cooldown (deal history events)          |
//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &trans, const MqlTradeRequest &req, const MqlTradeResult &res)
{
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD) return;
   if(!HistoryDealSelect(trans.deal)) return;
   if(HistoryDealGetString(trans.deal, DEAL_SYMBOL) != _Symbol) return;
   if(HistoryDealGetInteger(trans.deal, DEAL_MAGIC) != MagicNumber) return;
   if(HistoryDealGetInteger(trans.deal, DEAL_ENTRY) != DEAL_ENTRY_OUT) return;
   double pnl = HistoryDealGetDouble(trans.deal, DEAL_PROFIT);
   long   dtype = HistoryDealGetInteger(trans.deal, DEAL_TYPE);   // closing deal: SELL closes a BUY
   int side = (dtype==DEAL_TYPE_SELL) ? 0 : 1;
   if(pnl < 0) g_lastStopTime[side] = TimeCurrent();
   SetDirGV(0);
   Print("TB: closed side=", (side==0?"BUY":"SELL"), " pnl=", DoubleToString(pnl,2));
}
//+------------------------------------------------------------------+
