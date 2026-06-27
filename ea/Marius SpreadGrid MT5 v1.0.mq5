//+------------------------------------------------------------------+
//|  Marius SpreadGrid MT5 v1.0  --  COINTEGRATION SPREAD GRID         |
//|  The synthesis: GridStat's grid-harvest engine run on a            |
//|  STRUCTURALLY-cointegrated SPREAD (WTI-Brent) instead of a single  |
//|  instrument. The spread mean-reverts BY CONSTRUCTION (same         |
//|  commodity) -> bounded, no one-way blow-up -> ideal grid substrate.|
//|  MARKET-NEUTRAL (uncorrelated to the directional gold/oil book).   |
//|                                                                    |
//|  spread s = log(A) - beta*log(B), beta = rolling cointegration     |
//|  hedge ratio; z = rolling z-score of s.                            |
//|  ENTRY:   |z|>=EntryZ -> open a 2-leg unit FADING the spread       |
//|           (z>0 spread rich -> SELL A / BUY B ; z<0 -> BUY A/SELL B).|
//|  LADDER:  add a unit each time |z| extends by LadderStepZ (max N).  |
//|  HARVEST: close the whole basket at +ProfitTargetUSD (GridStat).    |
//|  FLOOR:   close (loss) if |z|>=ZFloor (cointegration break) OR      |
//|           basket float <= -BasketMaxLossPct% (the rare tail).       |
//|  Sizing:  dollar-neutral via beta (lotB = beta*notional-matched).   |
//|  Python feasibility: PT-harvest -> 97-99% win, PF 3.5-4.0, ~4       |
//|  floor-hits/14mo (bounded). Validate EVERY-TICK (grid path-sens.).  |
//|  Needs a HEDGING account (both legs + ladder stack).               |
//+------------------------------------------------------------------+
#property copyright "Marius"
#property version   "1.00"
#include <Trade/Trade.mqh>
CTrade trade;

#define BUILD "SPREADGRID-2026-06-21-A"

input string SymbolA          = "OILCash";    // leg A (WTI)
input string SymbolB          = "BRENTCash";   // leg B (Brent)
input ENUM_TIMEFRAMES TF      = PERIOD_H1;
input int    BetaLookback     = 300;           // rolling cointegration hedge-ratio window (bars)
input int    ZLookback        = 150;           // rolling z-score window (bars)
input double EntryZ           = 1.5;           // open first unit when |z|>=this
input double LadderStepZ      = 1.0;           // add a unit each +this z beyond entry
input int    MaxUnits         = 5;             // max laddered units per basket
input double ProfitTargetUSD  = 50.0;          // HARVEST the basket at +$ (GridStat mechanism)
input double ZFloor           = 6.0;           // cointegration-break exit (loss)
input double BasketMaxLossPct = 15.0;          // $-backstop floor (% of balance)
input double LotA             = 0.10;          // base lot on leg A per unit
input bool   AutoHedgeLot     = true;          // lotB = beta * notional-matched (dollar-neutral); else FixedLotB
input double FixedLotB        = 0.10;
input int    MagicSeed        = 0;
input string CommentText      = "SpreadGrid";

long     MagicNumber=0;
datetime lastBarTime=0;
double   g_beta=1.0, g_z=0.0;
bool     g_calcOK=false;

//+------------------------------------------------------------------+
int OnInit()
{
   if(!SymbolSelect(SymbolA,true) || !SymbolSelect(SymbolB,true))
   { Print("Leg symbol(s) not found: ",SymbolA,",",SymbolB); return(INIT_FAILED); }
   MagicNumber=(MagicSeed!=0)?MagicSeed:GenMagic("SpreadGrid",SymbolA);
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(20);
   Print("============================================================");
   Print("MARIUS SPREADGRID ",BUILD," | ",SymbolA," vs ",SymbolB," | Magic=",MagicNumber);
   Print("CONFIG | TF=",EnumToString(TF)," betaLB=",BetaLookback," zLB=",ZLookback,
         " EntryZ=",DoubleToString(EntryZ,2)," LadderZ=",DoubleToString(LadderStepZ,2),
         " MaxUnits=",MaxUnits," PT=$",DoubleToString(ProfitTargetUSD,2),
         " ZFloor=",DoubleToString(ZFloor,1)," LotA=",DoubleToString(LotA,2)," AutoHedge=",AutoHedgeLot);
   Print("============================================================");
   int fh=FileOpen("spreadgrid_trades.csv",FILE_WRITE|FILE_CSV|FILE_COMMON|FILE_ANSI,',');
   if(fh!=INVALID_HANDLE){ FileWrite(fh,"time","event","units","z","beta","floatUSD","reason"); FileClose(fh); }
   return(INIT_SUCCEEDED);
}
int GenMagic(string a,string b){ int h=0; string s=a+b; for(int i=0;i<StringLen(s);i++) h+=StringGetCharacter(s,i)*(i+1); return h%100000+90000; }

double LClose(string sym,int sh){ double c=iClose(sym,TF,sh); return (c>0)?MathLog(c):0.0; }

// rolling beta (hedge ratio) + z of spread = logA - beta*logB, on last-closed bars
bool ComputeBetaZ(double &beta,double &z)
{
   int need=MathMax(BetaLookback,ZLookback)+2;
   if(Bars(SymbolA,TF)<need || Bars(SymbolB,TF)<need) return(false);
   // beta = cov(logA,logB)/var(logB) over BetaLookback (shifts 1..BetaLookback)
   double sa=0,sb=0,sbb=0,sab=0; int N=BetaLookback;
   for(int k=1;k<=N;k++){ double la=LClose(SymbolA,k), lb=LClose(SymbolB,k); sa+=la; sb+=lb; sbb+=lb*lb; sab+=la*lb; }
   double ma=sa/N, mb=sb/N;
   double cov=sab/N-ma*mb, var=sbb/N-mb*mb;
   if(var<=0) return(false);
   beta=cov/var;
   // z over ZLookback
   int M=ZLookback; double ss=0,ss2=0;
   for(int k=1;k<=M;k++){ double sp=LClose(SymbolA,k)-beta*LClose(SymbolB,k); ss+=sp; ss2+=sp*sp; }
   double mu=ss/M, sd=MathSqrt(MathMax(0.0,ss2/M-mu*mu));
   if(sd<=0) return(false);
   double cur=LClose(SymbolA,1)-beta*LClose(SymbolB,1);
   z=(cur-mu)/sd;
   return(true);
}

//--- basket state from open positions (one basket at a time) -------------------
int  BasketUnits(){ int c=0; for(int i=PositionsTotal()-1;i>=0;i--){ ulong t=PositionGetTicket(i); if(t==0||!PositionSelectByTicket(t))continue; if(PositionGetInteger(POSITION_MAGIC)!=MagicNumber)continue; if(PositionGetString(POSITION_SYMBOL)==SymbolA) c++; } return c; }
int  BasketDir() // +1 spread-long (A long), -1 spread-short (A short), 0 none -- from leg A
{
   for(int i=PositionsTotal()-1;i>=0;i--){ ulong t=PositionGetTicket(i); if(t==0||!PositionSelectByTicket(t))continue;
      if(PositionGetInteger(POSITION_MAGIC)!=MagicNumber)continue;
      if(PositionGetString(POSITION_SYMBOL)!=SymbolA)continue;
      return (PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY)?+1:-1; }
   return 0;
}
double BasketFloat(){ double f=0; for(int i=PositionsTotal()-1;i>=0;i--){ ulong t=PositionGetTicket(i); if(t==0||!PositionSelectByTicket(t))continue; if(PositionGetInteger(POSITION_MAGIC)!=MagicNumber)continue; string sym=PositionGetString(POSITION_SYMBOL); if(sym!=SymbolA&&sym!=SymbolB)continue; f+=PositionGetDouble(POSITION_PROFIT)+PositionGetDouble(POSITION_SWAP); } return f; }

double NotionalPerLot(string sym){ return SymbolInfoDouble(sym,SYMBOL_TRADE_CONTRACT_SIZE)*SymbolInfoDouble(sym,SYMBOL_BID); }

double NormLot(string sym,double lot){ double st=SymbolInfoDouble(sym,SYMBOL_VOLUME_STEP), mn=SymbolInfoDouble(sym,SYMBOL_VOLUME_MIN), mx=SymbolInfoDouble(sym,SYMBOL_VOLUME_MAX);
   if(st>0) lot=MathRound(lot/st)*st; if(lot<mn)lot=mn; if(mx>0&&lot>mx)lot=mx; return lot; }

void LegLots(double &lotA,double &lotB)
{
   lotA=NormLot(SymbolA,LotA);
   if(!AutoHedgeLot){ lotB=NormLot(SymbolB,FixedLotB); return; }
   double nA=NotionalPerLot(SymbolA), nB=NotionalPerLot(SymbolB);
   double lb=(nB>0)? g_beta*lotA*nA/nB : lotA;
   lotB=NormLot(SymbolB,lb);
}

// open a 2-leg unit. dir=+1 spread-long (BUY A / SELL B); dir=-1 spread-short (SELL A / BUY B)
void OpenUnit(int dir)
{
   double lotA,lotB; LegLots(lotA,lotB);
   trade.SetTypeFillingBySymbol(SymbolA);
   if(dir>0) trade.Buy (lotA,SymbolA,0,0,0,CommentText);
   else      trade.Sell(lotA,SymbolA,0,0,0,CommentText);
   trade.SetTypeFillingBySymbol(SymbolB);
   if(dir>0) trade.Sell(lotB,SymbolB,0,0,0,CommentText);
   else      trade.Buy (lotB,SymbolB,0,0,0,CommentText);
}
void CloseBasket(string reason)
{
   double fl=BasketFloat(); int u=BasketUnits();
   for(int i=PositionsTotal()-1;i>=0;i--){ ulong t=PositionGetTicket(i); if(t==0||!PositionSelectByTicket(t))continue;
      if(PositionGetInteger(POSITION_MAGIC)!=MagicNumber)continue; string sym=PositionGetString(POSITION_SYMBOL);
      if(sym!=SymbolA&&sym!=SymbolB)continue; trade.PositionClose(t); }
   LogEvent("CLOSE",u,fl,reason);
}
void LogEvent(string ev,int units,double fl,string reason)
{
   int fh=FileOpen("spreadgrid_trades.csv",FILE_READ|FILE_WRITE|FILE_CSV|FILE_COMMON|FILE_ANSI,',');
   if(fh==INVALID_HANDLE) return; FileSeek(fh,0,SEEK_END);
   FileWrite(fh,TimeToString(TimeCurrent(),TIME_DATE|TIME_MINUTES),ev,IntegerToString(units),
             DoubleToString(g_z,2),DoubleToString(g_beta,4),DoubleToString(fl,2),reason);
   FileClose(fh);
}

//+------------------------------------------------------------------+
void OnTick()
{
   bool newBar=(iTime(SymbolA,TF,0)!=lastBarTime);
   if(newBar) lastBarTime=iTime(SymbolA,TF,0);

   g_calcOK=ComputeBetaZ(g_beta,g_z);
   int units=BasketUnits();

   // --- manage open basket every tick ---
   if(units>0)
   {
      double fl=BasketFloat();
      if(fl>=ProfitTargetUSD){ CloseBasket("harvest +PT"); return; }          // GridStat harvest
      if(g_calcOK && MathAbs(g_z)>=ZFloor){ CloseBasket("z-floor (coint break)"); return; }
      if(fl<=-BasketMaxLossPct/100.0*AccountInfoDouble(ACCOUNT_BALANCE)){ CloseBasket("$-floor"); return; }
   }
   if(!newBar || !g_calcOK) return;

   // --- entry / ladder on new bar ---
   if(units==0)
   {
      if(MathAbs(g_z)>=EntryZ){ int dir=(g_z>0)?-1:+1; OpenUnit(dir); LogEvent("OPEN",1,0,(dir>0?"spread-long":"spread-short")); }
   }
   else if(units<MaxUnits)
   {
      int bdir=BasketDir();
      bool sameSide=((bdir<0 && g_z>0) || (bdir>0 && g_z<0));   // z still extended in the basket's fade direction
      double need=EntryZ+units*LadderStepZ;
      if(sameSide && MathAbs(g_z)>=need){ OpenUnit(bdir); LogEvent("LADDER",units+1,BasketFloat(),"add unit"); }
   }
}
//+------------------------------------------------------------------+
