//+------------------------------------------------------------------+
//|  Marius CusumRev MT5 v1.0  --  MULTI-SYMBOL CUSUM-REVERSION TRADER|
//|  Second engine (uncorrelated to the gold momentum book).         |
//|  Entry: FADE a CUSUM cumulative-drift breach (up-breach -> SELL,  |
//|         down-breach -> BUY), in a ranging regime (ADX<thr).       |
//|  Exit:  protective SL + optional TP + time exit (HoldBars).       |
//|  No grid (reversion-martingale = tail risk); single position/sym. |
//|  Validated CUSUM-rev symbols (scan + plateau + time-split):       |
//|     EURGBP, GBPJPY, OILCash (REAL). Marginals can be added but    |
//|     capital should sit on the validated three.                   |
//|  Sizing: risk-normalized (1R = SL distance = RiskPct% of balance).|
//+------------------------------------------------------------------+
#property copyright "Marius"
#property version   "1.00"
#include <Trade/Trade.mqh>
CTrade trade;

#define BUILD "CUSUMREV-2026-06-07-A"

input string Symbols        = "GBPJPY,EURGBP,OILCash";  // validated CUSUM-rev set (configurable)
input ENUM_TIMEFRAMES TF    = PERIOD_M5;
input double CUSUM_H        = 5.0;     // breach threshold = this x ATR(TF) (validated h~5)
input int    HoldBars       = 288;     // time exit (M5 bars; 288 = 24h)
input double SL_ATR         = 1.5;     // wide catastrophe stop x ATR(D1) (MAE 90p ~0.98 -> rarely hit)
input double TP_ATR         = 0.0;     // 0 = no TP (edge is a TIME-drift; symmetric MFE/MAE = brackets don't help)
input bool   RequireRanging = true;    // only enter when ADX < ADX_Threshold
input double ADX_Threshold  = 25.0;
input int    ADX_Period     = 14;
input bool   UseSessionFilter = true;
input int    SessionStartHour = 9;
input int    SessionEndHour   = 23;
input bool   UseRiskNorm     = true;   // size so 1R = RiskPct% of balance
input double RiskPctPerTrade = 1.0;    // small risk for the newer engine
input double MaxRiskPctSkip  = 8.0;
input double FixedLot        = 0.01;   // used when UseRiskNorm = false
input int    MagicSeed       = 0;
input string CommentText     = "CusumRev";

string   Sym[]; int NSym=0;
int      hADX[], hATRtf[], hATRd1[];
datetime symLast[];
double   cusPos[], cusNeg[];
bool     symOK[];
long     MagicNumber=0;

//+------------------------------------------------------------------+
int OnInit()
{
   ushort sep=StringGetCharacter(",",0);
   NSym=StringSplit(Symbols,sep,Sym);
   if(NSym<=0){ Print("No symbols"); return(INIT_FAILED); }
   ArrayResize(hADX,NSym);ArrayResize(hATRtf,NSym);ArrayResize(hATRd1,NSym);
   ArrayResize(symLast,NSym);ArrayResize(cusPos,NSym);ArrayResize(cusNeg,NSym);ArrayResize(symOK,NSym);
   ArrayInitialize(cusPos,0);ArrayInitialize(cusNeg,0);
   int good=0;
   for(int s=0;s<NSym;s++)
   {
      StringTrimLeft(Sym[s]);StringTrimRight(Sym[s]); symOK[s]=false; symLast[s]=0;
      if(!SymbolSelect(Sym[s],true)){ Print("Symbol not found: ",Sym[s]); continue; }
      hADX[s]=iADX(Sym[s],TF,ADX_Period);
      hATRtf[s]=iATR(Sym[s],TF,20);
      hATRd1[s]=iATR(Sym[s],PERIOD_D1,14);
      if(hADX[s]==INVALID_HANDLE||hATRtf[s]==INVALID_HANDLE||hATRd1[s]==INVALID_HANDLE){ Print("Handle fail: ",Sym[s]); continue; }
      symOK[s]=true; good++;
   }
   MagicNumber=(MagicSeed!=0)?MagicSeed:GenMagic("CusumRev");
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(10);
   Print("============================================================");
   Print("MARIUS CUSUMREV ",BUILD," | symbols OK:",good,"/",NSym," | Magic=",MagicNumber);
   Print("============================================================");
   int fh=FileOpen("cusumrev_trades.csv",FILE_WRITE|FILE_CSV|FILE_COMMON|FILE_ANSI,',');
   if(fh!=INVALID_HANDLE){ FileWrite(fh,"time","symbol","type","lots","price","profit","reason"); FileClose(fh); }
   return(INIT_SUCCEEDED);
}
int GenMagic(string n){ int h=0; for(int i=0;i<StringLen(n);i++) h+=StringGetCharacter(n,i)*(i+1); return h%100000+60000; }
double RB(int hd,int b,int sh){ double a[]; if(CopyBuffer(hd,b,sh,1,a)<=0) return(0); return(a[0]); }
int BarHour(datetime t){ MqlDateTime d; TimeToStruct(t,d); return(d.hour); }

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
void CloseSymbolPositions(int s,string reason)
{
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong tk=PositionGetTicket(i); if(tk==0||!PositionSelectByTicket(tk)) continue;
      if(PositionGetInteger(POSITION_MAGIC)!=MagicNumber||PositionGetString(POSITION_SYMBOL)!=Sym[s]) continue;
      trade.PositionClose(tk);
   }
}
// time-exit: close positions older than HoldBars
void ManageExits(int s)
{
   datetime cut=TimeCurrent()-HoldBars*PeriodSeconds(TF);
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong tk=PositionGetTicket(i); if(tk==0||!PositionSelectByTicket(tk)) continue;
      if(PositionGetInteger(POSITION_MAGIC)!=MagicNumber||PositionGetString(POSITION_SYMBOL)!=Sym[s]) continue;
      if((datetime)PositionGetInteger(POSITION_TIME)<=cut) trade.PositionClose(tk);
   }
}
int CusumStep(int s,double h)
{
   double r=iClose(Sym[s],TF,1)-iClose(Sym[s],TF,2);
   cusPos[s]=MathMax(0.0,cusPos[s]+r);
   cusNeg[s]=MathMin(0.0,cusNeg[s]+r);
   if(cusPos[s]>=h){ cusPos[s]=0; return(1); }
   if(cusNeg[s]<=-h){ cusNeg[s]=0; return(-1); }
   return(0);
}
void OpenFade(int s,int dir)
{
   double atrD1=RB(hATRd1[s],0,1); if(atrD1<=0) return;
   double slDist=atrD1*SL_ATR, tpDist=atrD1*TP_ATR;
   double lot=CalcLot(s,slDist); if(lot<0) return;
   double ask=SymbolInfoDouble(Sym[s],SYMBOL_ASK), bid=SymbolInfoDouble(Sym[s],SYMBOL_BID);
   trade.SetTypeFillingBySymbol(Sym[s]);
   if(dir==ORDER_TYPE_BUY)
   {
      double sl=ask-slDist, tp=(TP_ATR>0)?ask+tpDist:0;
      trade.Buy(lot,Sym[s],ask,sl,tp,CommentText);
   }
   else
   {
      double sl=bid+slDist, tp=(TP_ATR>0)?bid-tpDist:0;
      trade.Sell(lot,Sym[s],bid,sl,tp,CommentText);
   }
}

//+------------------------------------------------------------------+
void OnTick()
{
   for(int s=0;s<NSym;s++)
   {
      if(!symOK[s]) continue;
      datetime t0=iTime(Sym[s],TF,0);
      if(t0==0||t0==symLast[s]) continue;
      symLast[s]=t0;

      ManageExits(s);                         // time exit first
      double br=CusumStep(s, CUSUM_H*RB(hATRtf[s],0,1));  // always accumulate

      if(UseSessionFilter){ int hr=BarHour(t0); if(!(hr>=SessionStartHour&&hr<SessionEndHour)) continue; }
      if(br==0) continue;
      if(HasPosition(s)) continue;            // one position per symbol
      if(RequireRanging && RB(hADX[s],0,0)>=ADX_Threshold) continue;
      // FADE the breach: up-breach -> SELL, down-breach -> BUY
      OpenFade(s, br>0 ? ORDER_TYPE_SELL : ORDER_TYPE_BUY);
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
   string rsn=(rs==DEAL_REASON_SL)?"SL":(rs==DEAL_REASON_TP)?"TP":(rs==DEAL_REASON_EXPERT)?"TIME/EA":"OTHER";
   int fh=FileOpen("cusumrev_trades.csv",FILE_READ|FILE_WRITE|FILE_CSV|FILE_COMMON|FILE_ANSI,',');
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
