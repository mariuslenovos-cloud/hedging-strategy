//+------------------------------------------------------------------+
//|  Marius FXFade MT5 v1.0  --  ROLLOVER MEAN-REVERSION FADE          |
//|  PATH A engine (uncorrelated to the metals/oil momentum-grid book).|
//|                                                                    |
//|  Validated in Python (afml_engine.py + fxfade_tree.py, 109,826     |
//|  events, 11 FX): CUSUM over-extension events faded in the FX        |
//|  rollover window. Survived CPCV (DSR 100%), TRUE forward holdout    |
//|  (+0.475R, 81% win, 11/11 symbols), cost-stress to 0.30R, breadth.  |
//|  A depth-3 tree on portable features collapsed to TWO rules         |
//|  (no ONNX needed -- hand-coded below):                              |
//|    * hours 22-23 (server) + momentum UP  -> SELL (fade the up-move) |
//|    * hour   0    (server) + momentum DOWN -> BUY  (fade the down)   |
//|  Exit: vol triple-barrier (PT/SL = BarrierVolMult x bar-vol,        |
//|        time = HoldBars) + risk-normalized sizing. 1 position/symbol.|
//|                                                                    |
//|  NOTE (parity): research 'hour' = copy_rates time = BROKER-SERVER   |
//|  time (NOT UTC); the EA's iTime is the SAME clock -> no conversion.  |
//|  research 'side' used frac-diff momentum; the EA uses simple        |
//|  close-momentum sign (portable). The MT5 every-tick backtest is the |
//|  parity arbiter -- it should reproduce ~+0.37R/trade, ~76% win.     |
//+------------------------------------------------------------------+
#property copyright "Marius"
#property version   "1.00"
#include <Trade/Trade.mqh>
CTrade trade;

#define BUILD "FXFADE-2026-06-20-B"

input string Symbols          = "EURUSD,USDJPY,GBPUSD,USDCHF,AUDUSD,NZDUSD,USDCAD,EURJPY,GBPJPY,EURGBP,AUDJPY"; // 11 validated FX
input ENUM_TIMEFRAMES TF      = PERIOD_M5;
//--- CUSUM over-extension event trigger (on log-returns; threshold = K x realized vol)
input double CUSUM_K          = 3.0;     // breach threshold = this x realized vol (research CUSUM_K=3)
input int    VolLookback      = 100;     // bars for realized vol (std of log-returns; research ewma span 100)
input int    MomLookback      = 12;      // momentum lookback for the FADE side (research MOM_LB=12)
//--- the two rollover-fade rules (SERVER hours = research hours, same XM clock -> no UTC convert)
input int    SellHour1        = 22;      // fade UP-moves (SELL) in this server hour ...
input int    SellHour2        = 23;      // ... and this one
input int    BuyHour          = 0;       // fade DOWN-moves (BUY) in this server hour
//--- exit: vol triple-barrier + time
input double BarrierVolMult   = 4.0;     // PT and SL distance = this x bar-vol x price (research PT/SL_MULT=4)
input int    HoldBars         = 96;      // time exit (M5 bars; 96 = 8h, research MAX_H)
//--- spread protection (the rollover-spread killer: see backtest 2026-06-20, win% 3-16% at 22-00h).
//    The edge is real in MID-price but the hard SL sits inside the rollover spread -> instant stop.
input double MaxSpreadToBarrier = 0.0;   // >0: SKIP entry if current spread > this x SL distance (e.g. 0.25). 0 = off
input bool   UseHardSL          = true;  // false: NO hard SL (time-exit only) -> avoid spread-triggered instant stops
//--- LIMIT/MAKER entry (the aligned fix: reversion = PROVIDE liquidity, pay LESS spread).
//    Python real-spread model: market(pay 100%)=-0.106R but pay<=50%=+0.22R. Limit posts a passive fade.
//    CAVEAT: adverse selection + non-fills -> realized < the clean model; MT5 limit-fill is optimistic; demo is arbiter.
input bool   UseLimitEntry      = false; // true: post a LIMIT fade instead of market
input double LimitOffsetSpreads = 0.5;   // limit price = this many spreads BETTER than market (0=touch, 0.5=mid, 1=earn full spread)
input int    LimitExpiryBars    = 2;     // cancel an unfilled limit after N bars (the over-extension moment passed)
//--- sizing
input bool   UseRiskNorm      = true;    // 1R = SL distance = RiskPct% of balance
input double RiskPctPerTrade  = 1.0;
input double MaxRiskPctSkip   = 8.0;
input double FixedLot         = 0.01;    // used when UseRiskNorm = false
//--- misc
input int    MagicSeed        = 0;
input string CommentText      = "FXFade";

string   Sym[]; int NSym=0;
int      hATRd1[];           // only used as a sizing fallback / diagnostics
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
   ArrayResize(hATRd1,NSym); ArrayResize(symLast,NSym);
   ArrayResize(cusPos,NSym); ArrayResize(cusNeg,NSym); ArrayResize(symOK,NSym);
   ArrayInitialize(cusPos,0); ArrayInitialize(cusNeg,0);
   int good=0;
   for(int s=0;s<NSym;s++)
   {
      StringTrimLeft(Sym[s]); StringTrimRight(Sym[s]); symOK[s]=false; symLast[s]=0;
      if(!SymbolSelect(Sym[s],true)){ Print("Symbol not found: ",Sym[s]); continue; }
      hATRd1[s]=iATR(Sym[s],PERIOD_D1,14);
      symOK[s]=true; good++;
   }
   MagicNumber=(MagicSeed!=0)?MagicSeed:GenMagic("FXFade");
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(20);
   Print("============================================================");
   Print("MARIUS FXFADE ",BUILD," | symbols OK:",good,"/",NSym," | Magic=",MagicNumber);
   Print("CONFIG | CUSUM_K=",DoubleToString(CUSUM_K,1)," BarrierVolMult=",DoubleToString(BarrierVolMult,1),
         " HoldBars=",HoldBars," SELL-fade hrs=",SellHour1,"/",SellHour2," BUY-fade hr=",BuyHour,
         " (SERVER time) RiskNorm=",UseRiskNorm," Risk%=",DoubleToString(RiskPctPerTrade,2));
   Print("CONFIG | UseLimitEntry=",UseLimitEntry," LimitOffsetSpreads=",DoubleToString(LimitOffsetSpreads,2),
         " LimitExpiryBars=",LimitExpiryBars," UseHardSL=",UseHardSL," MaxSpreadToBarrier=",DoubleToString(MaxSpreadToBarrier,2));
   Print("CONFIG | sample bar server time now = ",TimeToString(TimeCurrent(),TIME_DATE|TIME_MINUTES),
         "  (verify rollover window: research used server hours 22,23,0)");
   Print("============================================================");
   int fh=FileOpen("fxfade_trades.csv",FILE_WRITE|FILE_CSV|FILE_COMMON|FILE_ANSI,',');
   if(fh!=INVALID_HANDLE){ FileWrite(fh,"time","symbol","type","lots","price","profit","reason"); FileClose(fh); }
   return(INIT_SUCCEEDED);
}
int GenMagic(string n){ int h=0; for(int i=0;i<StringLen(n);i++) h+=StringGetCharacter(n,i)*(i+1); return h%100000+80000; }
int BarHour(datetime t){ MqlDateTime d; TimeToStruct(t,d); return(d.hour); }

double LogRet(int s,int shift)
{
   double a=iClose(Sym[s],TF,shift), b=iClose(Sym[s],TF,shift+1);
   return (a>0 && b>0) ? MathLog(a/b) : 0.0;
}
// realized vol = std of last VolLookback log-returns (fractional)
double RealizedVol(int s)
{
   int n=VolLookback; if(n<2) n=2;
   double sum=0,sum2=0;
   for(int k=1;k<=n;k++){ double r=LogRet(s,k); sum+=r; sum2+=r*r; }
   double mean=sum/n, var=sum2/n-mean*mean;
   return (var>0)?MathSqrt(var):0.0;
}
// CUSUM on log-returns; reset only the breached side (research). +1 up-breach, -1 down-breach, 0 none.
int CusumStep(int s,double vol)
{
   double r=LogRet(s,1);
   cusPos[s]=MathMax(0.0,cusPos[s]+r);
   cusNeg[s]=MathMin(0.0,cusNeg[s]+r);
   double h=CUSUM_K*vol;
   if(h<=0) return(0);
   if(cusPos[s]>=h){ cusPos[s]=0; return(1); }
   if(cusNeg[s]<=-h){ cusNeg[s]=0; return(-1); }
   return(0);
}
// FADE side: momentum over MomLookback. momentum UP -> we FADE by SELLING; momentum DOWN -> BUY.
bool MomentumUp(int s){ return( (iClose(Sym[s],TF,1)-iClose(Sym[s],TF,1+MomLookback)) > 0 ); }

bool HasPosition(int s)
{
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong tk=PositionGetTicket(i); if(tk==0||!PositionSelectByTicket(tk)) continue;
      if(PositionGetInteger(POSITION_MAGIC)==MagicNumber && PositionGetString(POSITION_SYMBOL)==Sym[s]) return(true);
   }
   return(false);
}
// positions OR working pending limit orders for this symbol (so we don't double-post)
bool HasPendingOrPosition(int s)
{
   if(HasPosition(s)) return(true);
   for(int i=OrdersTotal()-1;i>=0;i--)
   {
      ulong tk=OrderGetTicket(i); if(tk==0||!OrderSelect(tk)) continue;
      if(OrderGetInteger(ORDER_MAGIC)==MagicNumber && OrderGetString(ORDER_SYMBOL)==Sym[s]) return(true);
   }
   return(false);
}
// cancel unfilled limit orders older than LimitExpiryBars (backup to the order's own expiration)
void CancelStalePendings(int s)
{
   datetime cut=TimeCurrent()-LimitExpiryBars*PeriodSeconds(TF);
   for(int i=OrdersTotal()-1;i>=0;i--)
   {
      ulong tk=OrderGetTicket(i); if(tk==0||!OrderSelect(tk)) continue;
      if(OrderGetInteger(ORDER_MAGIC)!=MagicNumber||OrderGetString(ORDER_SYMBOL)!=Sym[s]) continue;
      if((datetime)OrderGetInteger(ORDER_TIME_SETUP)<=cut) trade.OrderDelete(tk);
   }
}
double CalcLot(int s,double slDist)
{
   if(!UseRiskNorm) return(FixedLot);
   double ts=SymbolInfoDouble(Sym[s],SYMBOL_TRADE_TICK_SIZE), tv=SymbolInfoDouble(Sym[s],SYMBOL_TRADE_TICK_VALUE);
   double dppl=(ts>0)?tv/ts:0;
   double minLot=SymbolInfoDouble(Sym[s],SYMBOL_VOLUME_MIN), maxLot=SymbolInfoDouble(Sym[s],SYMBOL_VOLUME_MAX);
   if(slDist<=0||dppl<=0) return(minLot);
   double riskMin=slDist*dppl*minLot;
   if(riskMin>MaxRiskPctSkip/100.0*AccountInfoDouble(ACCOUNT_BALANCE)) return(-1);  // vol-skip
   double lot=NormalizeDouble((RiskPctPerTrade/100.0*AccountInfoDouble(ACCOUNT_BALANCE))/(slDist*dppl),2);
   if(lot<minLot) lot=minLot; if(maxLot>0&&lot>maxLot) lot=maxLot;
   return(lot);
}
// time exit
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
void OpenFade(int s,int dir,double vol)
{
   double ask=SymbolInfoDouble(Sym[s],SYMBOL_ASK), bid=SymbolInfoDouble(Sym[s],SYMBOL_BID);
   double mkt=(dir==ORDER_TYPE_BUY)?ask:bid;
   double slDist=BarrierVolMult*vol*mkt;   // barrier in price = mult x bar-vol(fractional) x price
   if(slDist<=0) return;
   double spread=ask-bid;
   if(MaxSpreadToBarrier>0 && spread > MaxSpreadToBarrier*slDist) return;  // skip toxic-spread (rollover) entries
   double lot=CalcLot(s,slDist); if(lot<0) return;   // vol-skip
   trade.SetTypeFillingBySymbol(Sym[s]);
   if(!UseLimitEntry)
   {
      // MARKET entry (pays the full spread = the dead config; kept for the raw-spread-account test)
      double sl=UseHardSL?slDist:0.0;
      if(dir==ORDER_TYPE_BUY) trade.Buy (lot,Sym[s],ask,(sl>0?ask-sl:0),ask+slDist,CommentText);
      else                    trade.Sell(lot,Sym[s],bid,(sl>0?bid+sl:0),bid-slDist,CommentText);
   }
   else
   {
      // LIMIT/MAKER entry: post a passive fade LimitOffsetSpreads better than market -> pay less spread.
      datetime exp=TimeCurrent()+LimitExpiryBars*PeriodSeconds(TF);
      if(dir==ORDER_TYPE_BUY)
      {
         double lp=ask-LimitOffsetSpreads*spread;            // buy limit below market
         double sl=UseHardSL?lp-slDist:0.0;
         trade.BuyLimit(lot,lp,Sym[s],sl,lp+slDist,ORDER_TIME_SPECIFIED,exp,CommentText);
      }
      else
      {
         double lp=bid+LimitOffsetSpreads*spread;            // sell limit above market
         double sl=UseHardSL?lp+slDist:0.0;
         trade.SellLimit(lot,lp,Sym[s],sl,lp-slDist,ORDER_TIME_SPECIFIED,exp,CommentText);
      }
   }
}

//+------------------------------------------------------------------+
void OnTick()
{
   for(int s=0;s<NSym;s++)
   {
      if(!symOK[s]) continue;
      datetime t0=iTime(Sym[s],TF,0);
      if(t0==0||t0==symLast[s]) continue;     // new bar only
      symLast[s]=t0;

      ManageExits(s);                          // time exit first
      if(UseLimitEntry) CancelStalePendings(s); // expire unfilled limit fades

      double vol=RealizedVol(s);
      int br=CusumStep(s,vol);                 // always accumulate the CUSUM
      if(br==0) continue;                      // no over-extension event this bar
      if(HasPendingOrPosition(s)) continue;    // one position/pending per symbol

      // rollover-fade rules (server hour of the EVENT bar = shift 1)
      int hr=BarHour(iTime(Sym[s],TF,1));
      bool momUp=MomentumUp(s);
      int dir=-1;
      if((hr==SellHour1||hr==SellHour2) && momUp)  dir=ORDER_TYPE_SELL;   // fade an up-move
      else if(hr==BuyHour && !momUp)               dir=ORDER_TYPE_BUY;    // fade a down-move
      if(dir<0) continue;                      // no rule fires this event
      OpenFade(s,dir,vol);
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
   int fh=FileOpen("fxfade_trades.csv",FILE_READ|FILE_WRITE|FILE_CSV|FILE_COMMON|FILE_ANSI,',');
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
