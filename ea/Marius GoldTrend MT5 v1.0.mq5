//+------------------------------------------------------------------+
//|  Marius GoldTrend MT5 v1.0  --  TREND-FOLLOWER (the runner engine)|
//|  PURPOSE: capture the 12% of gold moves that RUN, which the        |
//|  GridStat harvester banks at +$100 and lets go. OPPOSITE profile   |
//|  to the harvester by design -> negatively correlated -> ideal as a |
//|  second HRP portfolio stream (AFML Ch.16). Don't judge by win% --  |
//|  judge by whether the few big-R winners pay for the many small     |
//|  stops (Recovery Factor / PF / netR), the trend-follower's law.    |
//|                                                                    |
//|  Entry:  Donchian breakout -- close[1] breaks the prior N-bar      |
//|          high (long) / low (short), optional ADX + D1-trend filter.|
//|  Exit:   ATR CHANDELIER trailing stop (let winners run, no TP);    |
//|          initial 1R stop = InitStopATR x ATR(D1).                  |
//|  Sizing: risk-normalized (1R = stop distance = RiskPct% balance).  |
//|  One position per symbol (no grid/martingale). Own magic.          |
//+------------------------------------------------------------------+
#property copyright "Marius"
#property version   "1.00"
#include <Trade/Trade.mqh>
CTrade trade;

#define BUILD "GOLDTREND-2026-06-22-C"

input string Symbols          = "US100Cash,US500Cash,US30Cash,GOLD"; // trend book (one-way trenders; comma list, verify Market-Watch names)
input ENUM_TIMEFRAMES TF      = PERIOD_H1;     // H1 = cleaner trends, less M5 false-breakout noise (the bigger lever)
input int    DonchianN        = 20;           // breakout lookback (prior N-bar high/low)
input bool   UseADXFilter     = true;         // only break when trend strength present
input double ADX_Threshold    = 20.0;
input int    ADX_Period       = 14;
input bool   UseDailyTrendFilter = true;      // only break WITH the D1 trend
input int    DailyMA_Period   = 50;
input double InitStopATR      = 1.5;          // initial stop = this x ATR = 1R
input double ChandelierATR    = 3.0;          // trail = highest-high-since-entry - this x ATR
input ENUM_TIMEFRAMES StopATR_TF = PERIOD_D1; // timeframe for the stop/trail ATR (D1 = wide/positional; set = TF for tighter/responsive on H1)
input int    ATR_Period       = 14;
input double BreakoutBufferATR = 0.0;         // require breakout to EXCEED the Donchian level by this x ATR (0 = touch; >0 = fewer false breaks)
input bool   UseSessionFilter = true;
input int    SessionStartHour = 9;
input int    SessionEndHour   = 23;
input bool   UseRiskNorm      = true;
input double RiskPctPerTrade  = 1.0;
input double MaxRiskPctSkip   = 8.0;
input double FixedLot         = 0.01;
input int    MagicSeed        = 0;
input string CommentText      = "GoldTrend";
//--- TWO-ENGINE LAB: per-bar floating-equity log (the trend-rider half). DEFAULT OFF -> no files in live.
input bool   UseEquityLog     = false;            // research: write time,balance,equity per chart bar to EquityLogFile (Common\Files)
input string EquityLogFile    = "goldtrend_equity.csv";

string Sym[]; int NSym=0;
int    hADX[], hATRstop[], hMAd1[];
datetime symLast[];
bool   symOK[];
long   MagicNumber=0;
int    gEqHandle=INVALID_HANDLE; datetime gLastEqBar=0;
int    sigCnt[], skipCnt[], failCnt[];   // diagnostics: breakout signals / vol-skips / order-fails per symbol

//+------------------------------------------------------------------+
int OnInit()
{
   ushort sep=StringGetCharacter(",",0);
   NSym=StringSplit(Symbols,sep,Sym);
   if(NSym<=0){ Print("No symbols"); return(INIT_FAILED); }
   ArrayResize(hADX,NSym);ArrayResize(hATRstop,NSym);ArrayResize(hMAd1,NSym);
   ArrayResize(symLast,NSym);ArrayResize(symOK,NSym);
   ArrayResize(sigCnt,NSym);ArrayResize(skipCnt,NSym);ArrayResize(failCnt,NSym);
   ArrayInitialize(sigCnt,0);ArrayInitialize(skipCnt,0);ArrayInitialize(failCnt,0);
   int good=0;
   for(int s=0;s<NSym;s++)
   {
      StringTrimLeft(Sym[s]);StringTrimRight(Sym[s]); symOK[s]=false; symLast[s]=0;
      if(!SymbolSelect(Sym[s],true)){ Print("Symbol not found: ",Sym[s]); continue; }
      hADX[s]=iADX(Sym[s],TF,ADX_Period);
      hATRstop[s]=iATR(Sym[s],StopATR_TF,ATR_Period);
      hMAd1[s]=iMA(Sym[s],PERIOD_D1,DailyMA_Period,0,MODE_EMA,PRICE_CLOSE);
      if(hADX[s]==INVALID_HANDLE||hATRstop[s]==INVALID_HANDLE||hMAd1[s]==INVALID_HANDLE){ Print("Handle fail: ",Sym[s]); continue; }
      symOK[s]=true; good++;
   }
   MagicNumber=(MagicSeed!=0)?MagicSeed:GenMagic("GoldTrend");
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(10);
   Print("============================================================");
   Print("MARIUS GOLDTREND ",BUILD," | symbols OK:",good,"/",NSym," | Magic=",MagicNumber);
   Print("CONFIG | TF=",EnumToString(TF)," DonchianN=",DonchianN," ADXfilt=",UseADXFilter,"/",ADX_Threshold,
         " D1filt=",UseDailyTrendFilter," InitStopATR=",InitStopATR," ChandelierATR=",ChandelierATR,
         " StopATR_TF=",EnumToString(StopATR_TF),"/",ATR_Period," BreakoutBufATR=",BreakoutBufferATR,
         " riskNorm=",UseRiskNorm,"/",RiskPctPerTrade,"%");
   Print("============================================================");
   int fh=FileOpen("goldtrend_trades.csv",FILE_WRITE|FILE_CSV|FILE_COMMON|FILE_ANSI,',');
   if(fh!=INVALID_HANDLE){ FileWrite(fh,"time","symbol","type","lots","price","profit","reason"); FileClose(fh); }
   if(UseEquityLog){
      gEqHandle=FileOpen(EquityLogFile,FILE_WRITE|FILE_CSV|FILE_COMMON|FILE_ANSI,',');
      if(gEqHandle!=INVALID_HANDLE) FileWrite(gEqHandle,"time","balance","equity");
      else Print("EquityLog open FAILED: ",EquityLogFile);
   }
   return(INIT_SUCCEEDED);
}
void OnDeinit(const int reason)
{
   if(gEqHandle!=INVALID_HANDLE){ FileClose(gEqHandle); gEqHandle=INVALID_HANDLE; }
   Print("--- GOLDTREND DIAGNOSTICS (signals / vol-skips / order-fails per symbol) ---");
   for(int s=0;s<NSym;s++)
      if(symOK[s])
         Print("   ",Sym[s],": signals=",sigCnt[s]," volSkips=",skipCnt[s]," orderFails=",failCnt[s],
               (sigCnt[s]>0 && skipCnt[s]==sigCnt[s] ? "  <== ALL skipped (raise MaxRiskPctSkip or deposit)" :
                sigCnt[s]==0 ? "  <== NO signal fired" : ""));
}
void LogEquity(){
   if(!UseEquityLog || gEqHandle==INVALID_HANDLE) return;
   datetime cur=iTime(_Symbol,PERIOD_CURRENT,0); if(cur==gLastEqBar) return; gLastEqBar=cur;
   FileWrite(gEqHandle,TimeToString(TimeCurrent(),TIME_DATE|TIME_SECONDS),
             DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE),2),
             DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY),2));
   FileFlush(gEqHandle);
}
int GenMagic(string n){ int h=0; for(int i=0;i<StringLen(n);i++) h+=StringGetCharacter(n,i)*(i+1); return h%100000+70000; }
double RB(int hd,int b,int sh){ double a[]; if(CopyBuffer(hd,b,sh,1,a)<=0) return(0); return(a[0]); }
int BarHour(datetime t){ MqlDateTime d; TimeToStruct(t,d); return(d.hour); }
double HiHigh(int s,int count,int start){ int i=iHighest(Sym[s],TF,MODE_HIGH,count,start); return (i<0)?0:iHigh(Sym[s],TF,i); }
double LoLow(int s,int count,int start){ int i=iLowest(Sym[s],TF,MODE_LOW,count,start); return (i<0)?0:iLow(Sym[s],TF,i); }

bool HasPosition(int s)
{
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong tk=PositionGetTicket(i); if(tk==0||!PositionSelectByTicket(tk)) continue;
      if(PositionGetInteger(POSITION_MAGIC)==MagicNumber && PositionGetString(POSITION_SYMBOL)==Sym[s]) return(true);
   }
   return(false);
}
double CalcLot(int s,double slDist)
{
   if(!UseRiskNorm) return(FixedLot);
   double ts=SymbolInfoDouble(Sym[s],SYMBOL_TRADE_TICK_SIZE), tv=SymbolInfoDouble(Sym[s],SYMBOL_TRADE_TICK_VALUE);
   double dppl=(ts>0)?tv/ts:0;
   double minLot=SymbolInfoDouble(Sym[s],SYMBOL_VOLUME_MIN), maxLot=SymbolInfoDouble(Sym[s],SYMBOL_VOLUME_MAX);
   if(slDist<=0||dppl<=0) return(minLot);
   double riskMin=slDist*dppl*minLot;
   if(riskMin>MaxRiskPctSkip/100.0*AccountInfoDouble(ACCOUNT_BALANCE)) return(-1);
   double lot=NormalizeDouble((RiskPctPerTrade/100.0*AccountInfoDouble(ACCOUNT_BALANCE))/(slDist*dppl),2);
   if(lot<minLot) lot=minLot; if(maxLot>0&&lot>maxLot) lot=maxLot;
   return(lot);
}
bool D1Bull(int s){ return RB(hMAd1[s],0,0) > RB(hMAd1[s],0,1); }

// ATR chandelier trailing stop: ratchet the SL toward the extreme since entry
void ManageTrail(int s)
{
   double atrD1=RB(hATRstop[s],0,1); if(atrD1<=0) return;
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong tk=PositionGetTicket(i); if(tk==0||!PositionSelectByTicket(tk)) continue;
      if(PositionGetInteger(POSITION_MAGIC)!=MagicNumber||PositionGetString(POSITION_SYMBOL)!=Sym[s]) continue;
      datetime pt=(datetime)PositionGetInteger(POSITION_TIME);
      int bars=(int)((TimeCurrent()-pt)/PeriodSeconds(TF))+1; if(bars<1) bars=1;
      long type=PositionGetInteger(POSITION_TYPE);
      double curSL=PositionGetDouble(POSITION_SL), tp=PositionGetDouble(POSITION_TP);
      int dig=(int)SymbolInfoInteger(Sym[s],SYMBOL_DIGITS);
      if(type==POSITION_TYPE_BUY)
      {
         double newSL=NormalizeDouble(HiHigh(s,bars,0)-ChandelierATR*atrD1,dig);
         if(newSL>curSL && newSL<SymbolInfoDouble(Sym[s],SYMBOL_BID)) trade.PositionModify(tk,newSL,tp);
      }
      else if(type==POSITION_TYPE_SELL)
      {
         double newSL=NormalizeDouble(LoLow(s,bars,0)+ChandelierATR*atrD1,dig);
         if((curSL==0||newSL<curSL) && newSL>SymbolInfoDouble(Sym[s],SYMBOL_ASK)) trade.PositionModify(tk,newSL,tp);
      }
   }
}
void OpenBreakout(int s,int dir)
{
   double atrD1=RB(hATRstop[s],0,1); if(atrD1<=0) return;
   double slDist=atrD1*InitStopATR;
   double lot=CalcLot(s,slDist); if(lot<0){ skipCnt[s]++; return; }   // vol-skip (min-lot risk > MaxRiskPctSkip%)
   double ask=SymbolInfoDouble(Sym[s],SYMBOL_ASK), bid=SymbolInfoDouble(Sym[s],SYMBOL_BID);
   trade.SetTypeFillingBySymbol(Sym[s]);
   bool ok = (dir==ORDER_TYPE_BUY) ? trade.Buy(lot,Sym[s],ask,ask-slDist,0,CommentText)
                                   : trade.Sell(lot,Sym[s],bid,bid+slDist,0,CommentText);
   if(!ok) failCnt[s]++;
}

//+------------------------------------------------------------------+
void OnTick()
{
   LogEquity();
   for(int s=0;s<NSym;s++)
   {
      if(!symOK[s]) continue;
      ManageTrail(s);                          // trail every tick

      datetime t0=iTime(Sym[s],TF,0);
      if(t0==0||t0==symLast[s]) continue;      // new bar only for entries
      symLast[s]=t0;

      if(HasPosition(s)) continue;             // one position per symbol
      if(UseSessionFilter){ int hr=BarHour(t0); if(!(hr>=SessionStartHour&&hr<SessionEndHour)) continue; }
      if(UseADXFilter && RB(hADX[s],0,0)<ADX_Threshold) continue;

      double priorHigh=HiHigh(s,DonchianN,2);  // prior N-bar high (exclude breakout bar[1] & current[0])
      double priorLow =LoLow(s,DonchianN,2);
      double close1=iClose(Sym[s],TF,1);
      if(priorHigh<=0||priorLow<=0) continue;
      double buf=BreakoutBufferATR*RB(hATRstop[s],0,1);   // require break to exceed the level by buf (false-break filter)

      bool d1Bull = !UseDailyTrendFilter || D1Bull(s);
      bool d1Bear = !UseDailyTrendFilter || !D1Bull(s);
      if(close1>priorHigh+buf && d1Bull)      { sigCnt[s]++; OpenBreakout(s,ORDER_TYPE_BUY); }
      else if(close1<priorLow-buf && d1Bear)  { sigCnt[s]++; OpenBreakout(s,ORDER_TYPE_SELL); }
   }
}
//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &trans,const MqlTradeRequest &req,const MqlTradeResult &res)
{
   if(trans.type!=TRADE_TRANSACTION_DEAL_ADD) return;
   ulong d=trans.deal; if(!HistoryDealSelect(d)) return;
   if(HistoryDealGetInteger(d,DEAL_MAGIC)!=MagicNumber) return;
   if(HistoryDealGetInteger(d,DEAL_ENTRY)!=DEAL_ENTRY_OUT) return;
   double profit=HistoryDealGetDouble(d,DEAL_PROFIT)+HistoryDealGetDouble(d,DEAL_SWAP)+HistoryDealGetDouble(d,DEAL_COMMISSION);
   long rs=HistoryDealGetInteger(d,DEAL_REASON);
   string rsn=(rs==DEAL_REASON_SL)?"SL/trail":(rs==DEAL_REASON_TP)?"TP":(rs==DEAL_REASON_EXPERT)?"EA":"OTHER";
   int fh=FileOpen("goldtrend_trades.csv",FILE_READ|FILE_WRITE|FILE_CSV|FILE_COMMON|FILE_ANSI,',');
   if(fh==INVALID_HANDLE) return;
   FileSeek(fh,0,SEEK_END);
   FileWrite(fh,TimeToString((datetime)HistoryDealGetInteger(d,DEAL_TIME),TIME_DATE|TIME_MINUTES),
      HistoryDealGetString(d,DEAL_SYMBOL),
      (HistoryDealGetInteger(d,DEAL_TYPE)==DEAL_TYPE_BUY)?"close_buy":"close_sell",
      DoubleToString(HistoryDealGetDouble(d,DEAL_VOLUME),2),
      DoubleToString(HistoryDealGetDouble(d,DEAL_PRICE),(int)SymbolInfoInteger(HistoryDealGetString(d,DEAL_SYMBOL),SYMBOL_DIGITS)),
      DoubleToString(profit,2), rsn);
   FileClose(fh);
}
//+------------------------------------------------------------------+
