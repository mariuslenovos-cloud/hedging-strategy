//+------------------------------------------------------------------+
//|  Marius FadeGrid MT5 v1.0  --  REVERSION grid for mean-reverters  |
//|  The GridStat engine with a FADE trigger instead of momentum.     |
//|  Built for EURGBP (variance ratio 0.67 = hardest-reverting cheap  |
//|  single leg; a range-bound EUR/GBP cross). GridStat's Goldminer   |
//|  is MOMENTUM and barely fires on a reverter (10 sigs/6mo) -> wrong |
//|  tool. This FADES the extension instead.                          |
//|                                                                   |
//|  ENTRY:  rolling z = (close - SMA)/STD over ZLookback. Open a unit |
//|          FADING when |z|>=EntryZ (z>0 price-high -> SELL; z<0 ->   |
//|          BUY). LADDER: add a unit each |z|>=EntryZ+k*LadderStepZ   |
//|          (avg the entry), up to MaxUnits, lots x LotLadderMult^k.  |
//|  HARVEST: close the WHOLE basket at +ProfitTargetUSD (GridStat's   |
//|          real exit -- the averaged basket greens on a small bounce)|
//|  FLOOR:  cut basket if |z|>=ZFloor (regime break) OR float <=      |
//|          -BasketMaxLossPct% balance (catastrophe).                |
//|  No per-unit stop (the grid waits for EURGBP's reliable reversion).|
//|  Needs a HEDGING account (each unit = its own position). Own magic.|
//+------------------------------------------------------------------+
#property copyright "Marius"
#property version   "1.00"
#include <Trade/Trade.mqh>
CTrade trade;

#define BUILD "FADEGRID-2026-06-22-B"

//--- entry / ladder
input int    ZLookback        = 200;     // rolling window for mean+std (bars)
input double EntryZ           = 2.0;      // open first fade unit at |z|>= this
input double LadderStepZ      = 1.0;      // add a unit each additional this much |z|
input int    MaxUnits         = 5;        // max ladder depth per basket
//--- sizing
input double LotSize          = 0.10;     // base lot (unit 1); EURGBP needs size for small moves
input double LotLadderMult    = 1.5;      // deeper unit k lot = LotSize * this^k (1.0 = uniform)
//--- exits
input double ProfitTargetUSD  = 20.0;     // harvest whole basket at this $ float (GridStat mechanism)
input double ZFloor           = 6.0;      // regime-break: cut basket if |z|>= this
input bool   UseBasketStop    = true;     // catastrophe floor
input double BasketMaxLossPct = 20.0;     // ...close basket if float <= -this% of balance
//--- TAIL-KILLERS (the fade strategy's enemy = a TREND. Block fading when a trend is underway.)
input bool   UseRangingFilter = false;    // only open/add fade units when NOT trending (ADX < ADX_RangeMax)
input ENUM_TIMEFRAMES ADX_TF  = PERIOD_H1;// timeframe for the trend gauge (H1 = robust, less M5 noise)
input int    ADX_Period       = 14;
input double ADX_RangeMax      = 25.0;    // ranging when ADX < this; block new fade units when ADX >= this
input bool   UseHTFTrendFilter = false;   // also: don't fade AGAINST the higher-TF trend (only fade-buy below / fade-sell above the HTF mean)
input ENUM_TIMEFRAMES HTF_TF  = PERIOD_D1;
input int    HTF_MA_Period     = 50;
//--- misc
input bool   UseSessionFilter = false;
input int    SessionStartHour = 0;
input int    SessionEndHour   = 24;
input int    MagicSeed        = 0;
input string CommentText      = "FadeGrid";
input bool   UseEquityLog     = false;    // research: per-bar balance+equity -> EquityLogFile
input string EquityLogFile    = "fadegrid_equity.csv";

long     MagicNumber=0;
datetime lastBar=0, lastEqBar=0;
int      gEqHandle=INVALID_HANDLE;
int      hADX=INVALID_HANDLE, hHTF=INVALID_HANDLE;

//+------------------------------------------------------------------+
int OnInit()
{
   MagicNumber = (MagicSeed!=0) ? MagicSeed : GenMagic("FadeGrid");
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(20);
   trade.SetTypeFillingBySymbol(_Symbol);
   hADX = iADX(_Symbol, ADX_TF, ADX_Period);
   hHTF = iMA(_Symbol, HTF_TF, HTF_MA_Period, 0, MODE_EMA, PRICE_CLOSE);
   if(hADX==INVALID_HANDLE||hHTF==INVALID_HANDLE){ Print("handle fail"); return(INIT_FAILED); }
   Print("============================================================");
   Print("MARIUS FADEGRID ",BUILD," | ",_Symbol," | Magic=",MagicNumber);
   Print("CONFIG | Zlb=",ZLookback," EntryZ=",EntryZ," step=",LadderStepZ," maxU=",MaxUnits,
         " lot=",LotSize," ladderMult=",LotLadderMult);
   Print("CONFIG | PT$=",ProfitTargetUSD," Zfloor=",ZFloor," BasketStop=",UseBasketStop,"/",BasketMaxLossPct,"%");
   Print("CONFIG | TAIL-KILLERS: RangingFilter=",UseRangingFilter,"/ADX<",ADX_RangeMax,"@",EnumToString(ADX_TF),
         " HTFTrendFilter=",UseHTFTrendFilter,"@",EnumToString(HTF_TF));
   Print("============================================================");
   int fh=FileOpen("fadegrid_trades.csv",FILE_WRITE|FILE_CSV|FILE_COMMON|FILE_ANSI,',');
   if(fh!=INVALID_HANDLE){ FileWrite(fh,"time","symbol","reason","units","profit","z"); FileClose(fh); }
   if(UseEquityLog){
      gEqHandle=FileOpen(EquityLogFile,FILE_WRITE|FILE_CSV|FILE_COMMON|FILE_ANSI,',');
      if(gEqHandle!=INVALID_HANDLE) FileWrite(gEqHandle,"time","balance","equity");
   }
   return(INIT_SUCCEEDED);
}
void OnDeinit(const int reason){ if(gEqHandle!=INVALID_HANDLE){ FileClose(gEqHandle); gEqHandle=INVALID_HANDLE; } }
int GenMagic(string n){ int h=0; for(int i=0;i<StringLen(n);i++) h+=StringGetCharacter(n,i)*(i+1); return h%100000+60000; }

int BarHour(datetime t){ MqlDateTime d; TimeToStruct(t,d); return d.hour; }
double RB(int hd,int sh){ double a[]; if(CopyBuffer(hd,0,sh,1,a)<=0) return 0; return a[0]; }
bool Ranging(){ return !UseRangingFilter || RB(hADX,0) < ADX_RangeMax; }   // tail-killer 1: no fading in a trend
bool HTFok(int fadeDir){                                                   // tail-killer 2: don't fade against the HTF trend
   if(!UseHTFTrendFilter) return true;
   bool bull = RB(hHTF,0) > RB(hHTF,1);
   if(fadeDir<0 && bull) return false;    // don't fade-SELL in an uptrend
   if(fadeDir>0 && !bull) return false;   // don't fade-BUY in a downtrend
   return true;
}

//--- rolling z of close[1] over ZLookback (uses CLOSED bars) -----------------
double ZScore()
{
   double cl[]; int got=CopyClose(_Symbol,PERIOD_CURRENT,1,ZLookback,cl);
   if(got<ZLookback) return 0;
   double sum=0; for(int i=0;i<got;i++) sum+=cl[i];
   double mean=sum/got, var=0;
   for(int i=0;i<got;i++) var+=(cl[i]-mean)*(cl[i]-mean);
   double sd=MathSqrt(var/got);
   if(sd<=0) return 0;
   return (cl[got-1]-mean)/sd;          // cl[got-1] = most recent CLOSED bar (shift 1)
}

int    BasketUnits(){ int c=0; for(int i=PositionsTotal()-1;i>=0;i--){ ulong t=PositionGetTicket(i); if(t==0||!PositionSelectByTicket(t))continue; if(PositionGetInteger(POSITION_MAGIC)==MagicNumber&&PositionGetString(POSITION_SYMBOL)==_Symbol) c++; } return c; }
double BasketFloat(){ double p=0; for(int i=PositionsTotal()-1;i>=0;i--){ ulong t=PositionGetTicket(i); if(t==0||!PositionSelectByTicket(t))continue; if(PositionGetInteger(POSITION_MAGIC)==MagicNumber&&PositionGetString(POSITION_SYMBOL)==_Symbol) p+=PositionGetDouble(POSITION_PROFIT)+PositionGetDouble(POSITION_SWAP); } return p; }
int    BasketDir(){ for(int i=PositionsTotal()-1;i>=0;i--){ ulong t=PositionGetTicket(i); if(t==0||!PositionSelectByTicket(t))continue; if(PositionGetInteger(POSITION_MAGIC)==MagicNumber&&PositionGetString(POSITION_SYMBOL)==_Symbol) return (PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY)?1:-1; } return 0; }

void LogClose(string reason,int units,double profit,double z)
{
   int fh=FileOpen("fadegrid_trades.csv",FILE_READ|FILE_WRITE|FILE_CSV|FILE_COMMON|FILE_ANSI,',');
   if(fh==INVALID_HANDLE) return; FileSeek(fh,0,SEEK_END);
   FileWrite(fh,TimeToString(TimeCurrent(),TIME_DATE|TIME_MINUTES),_Symbol,reason,
             IntegerToString(units),DoubleToString(profit,2),DoubleToString(z,2));
   FileClose(fh);
}
void CloseBasket(string reason,double z)
{
   int u=BasketUnits(); double pf=BasketFloat();
   for(int i=PositionsTotal()-1;i>=0;i--){ ulong t=PositionGetTicket(i); if(t==0||!PositionSelectByTicket(t))continue;
      if(PositionGetInteger(POSITION_MAGIC)==MagicNumber&&PositionGetString(POSITION_SYMBOL)==_Symbol) trade.PositionClose(t); }
   LogClose(reason,u,pf,z);
}
void OpenUnit(int dir,double lot)
{
   double ask=SymbolInfoDouble(_Symbol,SYMBOL_ASK), bid=SymbolInfoDouble(_Symbol,SYMBOL_BID);
   if(dir>0) trade.Buy(lot,_Symbol,ask,0,0,CommentText);
   else      trade.Sell(lot,_Symbol,bid,0,0,CommentText);
}
double UnitLot(int k)
{
   double l=LotSize*MathPow(LotLadderMult,k);
   double minl=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN), step=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
   double maxl=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX);
   if(step>0) l=MathRound(l/step)*step;
   if(l<minl) l=minl; if(maxl>0&&l>maxl) l=maxl;
   return l;
}

//+------------------------------------------------------------------+
void OnTick()
{
   // equity log (per bar)
   if(UseEquityLog && gEqHandle!=INVALID_HANDLE){
      datetime cb=iTime(_Symbol,PERIOD_CURRENT,0);
      if(cb!=lastEqBar){ lastEqBar=cb;
         FileWrite(gEqHandle,TimeToString(TimeCurrent(),TIME_DATE|TIME_SECONDS),
                   DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE),2),
                   DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY),2)); FileFlush(gEqHandle); }
   }

   // --- manage open basket EVERY TICK (harvest / floor) ---
   int units=BasketUnits();
   if(units>0){
      double fl=BasketFloat();
      if(fl>=ProfitTargetUSD){ CloseBasket("harvest",ZScore()); return; }
      double z=ZScore();
      if(MathAbs(z)>=ZFloor){ CloseBasket("zfloor",z); return; }
      if(UseBasketStop && fl<=-BasketMaxLossPct/100.0*AccountInfoDouble(ACCOUNT_BALANCE)){ CloseBasket("basketstop",z); return; }
   }

   // --- entries on NEW BAR only ---
   datetime bt=iTime(_Symbol,PERIOD_CURRENT,0);
   if(bt==lastBar) return;
   lastBar=bt;

   if(UseSessionFilter){ int hr=BarHour(TimeCurrent()); if(!(hr>=SessionStartHour && hr<SessionEndHour)) return; }

   double z=ZScore();
   if(z==0) return;
   // how many ladder units does the current |z| justify?
   int target=0; for(int k=0;k<MaxUnits;k++) if(MathAbs(z)>=EntryZ+k*LadderStepZ) target=k+1;
   if(target<=units) return;                          // no new unit warranted

   int fadeDir=(z>0)?-1:1;                             // fade: high->SELL, low->BUY
   if(units>0 && BasketDir()!=fadeDir) return;         // never add against an open basket (z sign stable; guard anyway)
   if(!Ranging()) return;                              // TAIL-KILLER 1: don't fade while trending (ADX high)
   if(!HTFok(fadeDir)) return;                         // TAIL-KILLER 2: don't fade against the higher-TF trend

   for(int k=units; k<target; k++) OpenUnit(fadeDir,UnitLot(k));
}
//+------------------------------------------------------------------+
