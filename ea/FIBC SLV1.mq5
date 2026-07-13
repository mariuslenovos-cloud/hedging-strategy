//| GENERATED TEST CELL SLV1 -- do not edit; regen via fibc_make_cells.py |
//+------------------------------------------------------------------+
//|  Marius Hedger M5 fib C  --  MT5 PORT (v1.0)                      |
//|  Faithful MT5 equivalent of the LIVE MT4 fib C that made ~$1,400  |
//|  in 10 days. Two-sided Goldminer hedge: BUY on green / SELL on    |
//|  red; Fibonacci ladder per direction (1,1,2,3,5,8.. x base, max   |
//|  MaxSameTrades); compounding (base lot x floor(bal/CompBase));    |
//|  session filter; trend gate (ADX + MA-angle). EXITS: basket-trail |
//|  (activate at +MinFloatToActivate, close all on BasketTrailAmount |
//|  give-back from peak, both x compound-scale) + same-direction     |
//|  quick-harvest (close a side when 2+ in that dir and in profit).  |
//|  Goldminer is EMBEDDED natively (validated 50/50 vs MT4).         |
//|                                                                   |
//|  RISK-SAFE levers are DEFAULT-OFF so the base == live behaviour:  |
//|  UseBasketStop (catastrophe floor), UseDailyTrendFilter,          |
//|  UseImbalanceLock. We A/B these on together to harden it.         |
//|  Needs a HEDGING account.                                          |
//+------------------------------------------------------------------+
#property copyright "Marius"
#property version   "1.00"
#include <Trade/Trade.mqh>
CTrade trade;

#define BUILD "FIBC-CELL-SLV1-2026-07-13"

//--- sizing
const double LotSize            = 0.02;  // CELL-LOCKED
const bool UseFibonacci       = true;     // 1,1,2,3,5,8.. per direction (else martingale x LotMultiplier)  // CELL-LOCKED
const int LotMultiplier      = 2;  // CELL-LOCKED
const bool UseCompounding     = true;  // CELL-LOCKED
const double CompoundingBase    = 3000.0;   // base lot scales with floor(balance/this)  // CELL-LOCKED
const int MaxSameTrades      = 5;        // max ladder depth per direction  // CELL-LOCKED
const int MaxFibMult         = 0;        // GENTLER LADDER: cap per-leg fib multiplier (0=uncapped 1,1,2,3,5,8..; e.g. 3 -> 1,1,2,3,3,3 = smaller deep legs = smaller floating basket = smaller floor loss, lower PF in chop. The DD dial that works regardless of where legs were placed.)  // CELL-LOCKED
const int MaxCompoundScale   = 3;        // [curb-give-back] cap the compounding multiplier floor(bal/CompoundingBase). 0=uncapped (current). e.g. 3 = base lot never grows past 3x -> baskets stay SMALL relative to a grown account -> the recovery keeps the rescue headroom it has at $3k -> fewer/smaller floor-hits. Trade-off: less compounding upside.  // CELL-LOCKED
//--- RECOVERY SIZING MODE (zone-recovery "break-even guarantee" math vs Fibonacci). A/B lever.
const int RecoverySizeMode   = 1;        // 0 = Fibonacci (default, UNCHANGED). 1 = BREAK-EVEN formula: each recovery leg = (RR+1)/RR x (opposite-side lots - same-side lots) x CostBuffer = the MINIMAL leg that makes the basket net-positive at the next favourable move, cost included. Leaner/more principled than Fibonacci -> smaller per-basket tail. (Derived from zone-recovery math; in a one-sided trend it floors to base = uniform lots.)  // CELL-LOCKED
const double RecoveryRR         = 3.0;      // mode 1 R:R (higher = gentler leg growth)  // CELL-LOCKED
const double RecoveryCostBuffer = 1.1;      // mode 1: size up x this to clear spread+commission+swap (1.1 = +10%)  // CELL-LOCKED
//--- entry signal (Goldminer embedded + trend gate)
const int grisk              = 7;        // fib C value (drives auto period/bands)  // CELL-LOCKED
const int GM_Period          = 0;        // 0 = auto (grisk*2+3)  // CELL-LOCKED
const double GM_UpperBand        = 0;       // 0 = auto (grisk+67)  // CELL-LOCKED
const double GM_LowerBand        = 0;       // 0 = auto (33-grisk)  // CELL-LOCKED
const double GM_GapMult          = 2.0;  // CELL-LOCKED
const int GM_GapMode          = 0;  // CELL-LOCKED
const double GM_FastMult         = 4.6;  // CELL-LOCKED
const int goldminershift      = 1;  // CELL-LOCKED
const int MA_Period           = 20;  // CELL-LOCKED
const double MA_Angle_Threshold  = 20.0;  // CELL-LOCKED
const int ADX_Period          = 14;  // CELL-LOCKED
const double ADX_Threshold       = 25.0;  // CELL-LOCKED
const int tradesperbar        = 1;  // CELL-LOCKED
//--- session
const bool UseSessionFilter    = true;  // CELL-LOCKED
const int SessionStartHour     = 9;  // CELL-LOCKED
const int SessionEndHour       = 23;  // CELL-LOCKED
//--- exits
const bool UseBasketTrail       = true;  // CELL-LOCKED
const double MinFloatToActivate   = 80.0;  // CELL-LOCKED
const double BasketTrailAmount     = 15.0;  // CELL-LOCKED
const bool UseBuySellProfitThreshold = true;  // same-dir quick harvest  // CELL-LOCKED
const double BuySellProfitThreshold     = 50.0; // in POINTS*point (gold ~ $0.50) -- faithful to live  // CELL-LOCKED
const double BuySellProfitThresholdInCurrency = 0; // >0 overrides to a $ threshold  // CELL-LOCKED
//=== RISK-SAFE levers (DEFAULT OFF -> base == live; we A/B these on) ===
const bool UseBasketStop        = true;  // catastrophe floor: close ALL if book float <= -BasketMaxLossPct% balance  // CELL-LOCKED
const double BasketMaxLossPct     = 20.0;  // CELL-LOCKED
const bool UseDailyTrendFilter  = true;  // only enter WITH the D1 trend (cuts counter-trend tax)  // CELL-LOCKED
const int DailyMA_Period       = 50;  // CELL-LOCKED
const bool UseImbalanceLock     = true;  // stop adding to a side that outnumbers the other by >= ImbalanceThreshold AND is in loss  // CELL-LOCKED
const int ImbalanceThreshold   = 2;  // CELL-LOCKED
const bool UseMaxBasketLots     = false;  // cap TOTAL open lots -> bounds the Fibonacci martingale = caps the max basket loss (the DD tail)  // CELL-LOCKED
const double MaxBasketLotsTotal    = 0.30;  // CELL-LOCKED
//--- VOL-REGIME filter (AFML Ch.17; the proven MT4 DD-cut: (a)+(c) cut fib C DD 59%->38%, session 19k). DEFAULT OFF.
const bool UseVolRegimeFilter   = true;  // master switch  // CELL-LOCKED
const int VolATRFastPeriod     = 5;      // fast ATR(D1) = current regime  // CELL-LOCKED
const int VolATRSlowPeriod     = 60;     // slow ATR(D1) = baseline regime  // CELL-LOCKED
const double VolRegimeMult         = 2.5;   // HOT when ATR_fast/ATR_slow >= this  // CELL-LOCKED
const bool VolBlockAllEntries    = true;  // (a) HOT: block ALL new entries (sit out the storm)  // CELL-LOCKED
const bool VolBlockStacking      = false; // (b) HOT: block only ADDS (allow 1st entry/dir)  // CELL-LOCKED
const bool VolScaledFloor        = false;  // (c) HOT: WIDEN the catastrophe floor so baskets ride to recovery  // CELL-LOCKED
const double VolFloorMaxMult        = 2.0;  // (c) cap: floor% widens up to this x BasketMaxLossPct (30%->60%)  // CELL-LOCKED
//--- OVEREXTENSION filter (AFML Ch.17; the DIRECTIONAL-DRIFT analog of the vol filter -- catches the slow-drift
//    structural break the vol-EXPANSION filter MISSES. gridregime.py (19o): dist=|close-D1EMA|/ATR(D1,60) corr
//    -0.61 with gold deep-MAE. Stops growing the fib ladder into the extreme = caps the deep-leg tail WITHOUT
//    cutting recoverable baskets. DEFAULT OFF -> base unchanged.)
const bool UseOverextFilter     = false;   // CELL-LOCKED
const double OverextATRMult        = 4.5;   // HOT when |close - D1EMA(DailyMA_Period)| / ATR(D1,VolATRSlowPeriod) >= this (gold ~90th pctile)  // CELL-LOCKED
const bool OverextBlockAdds      = true;  // true: block only ADDS when stretched (cap the deep fib legs, keep base flow); false: block ALL entries  // CELL-LOCKED
//--- TWO-ENGINE LAB: per-bar floating-equity log (the harvester half of the harvester+trend pairing). DEFAULT OFF -> no files in live.
const bool UseEquityLog         = false;          // research: write time,balance,equity per bar to EquityLogFile (Common\Files)  // CELL-LOCKED
const string EquityLogFile        = "fibc_equity.csv";  // CELL-LOCKED
//--- FIRST-ENTRY PROBABILITY GATE (the GridStat selectivity = source of its 20% DD vs fib C's 50%).
//    Only START a basket (first leg on a side) when the entry fingerprint DIR|SESSION|ATR-regime has
//    historical win-rate >= threshold in the stats DB. Recovery legs (adds) BYPASS it. DEFAULT OFF.
//    Attacks the tail AT SOURCE (don't start bad baskets) -> preserves the recovery edge (vs floor-cuts).
const bool UseFirstEntryGate    = true;  // CELL-LOCKED
const string FirstGateStatsCSV    = "gridstat_setups_silver_mt5.csv";  // GridStat shadow DB (Common\Files); same fingerprint  // CELL-LOCKED
const double FirstGateMinWinRate  = 0.55;   // win-rate threshold for BUY starts  // CELL-LOCKED
const double FirstGateSellMinWinRate = 0.65; // SELL-only threshold (0 = use FirstGateMinWinRate). Gold longs >> shorts -> set this higher (e.g. 0.65) to cut weak shorts.  // CELL-LOCKED
const int FirstGateMinSamples  = 10;  // CELL-LOCKED
//--- RECOVERY HEDGE (the validated MT4 win, session 19v): when the book is deep underwater,
//    STOP feeding the loser and RIDE the winning (trend) side on every Goldminer signal until
//    the whole book recovers to +target. Averaging-in recovers mean-reversion; riding the winner
//    recovers sustained trends (the deep-basket cause). Overrides D1/session/imbalance/MaxSameTrades
//    for the WINNING side only. Catastrophe floor stays the backstop. DEFAULT OFF -> base unchanged.
const bool UseRecoveryHedge     = true;  // CELL-LOCKED
const double HedgeTriggerLoss     = 0.0;  // arm when book float <= -this ($)  // CELL-LOCKED
const double HedgeTriggerPctBal   = 3.0;    // >0: arm when book float <= -this%% of balance (overrides HedgeTriggerLoss; deposit-portable). Validated 3.  // CELL-LOCKED
const double RecoveryTargetUSD    = 40.0;   // close the WHOLE book once it recovers to +this ($)  // CELL-LOCKED
const bool UseRecoveryTrail     = true;  // [opt1] once recovered to +target, TRAIL the winner instead of flat-closing (+4%% on gold)  // CELL-LOCKED
const double RecoveryTrailGiveback = 20.0;  // give-back ($) from the recovery peak that closes (locks >= effective target)  // CELL-LOCKED
const double RecoveryTargetPct    = 10.0;    // [opt2] >0: scale target to this %% of the DEEPEST loss rescued (max w/ RecoveryTargetUSD). +3%% on gold at 10.  // CELL-LOCKED
const bool RecoveryRespectBreakFilters = false; // [curb] while rescuing, DON'T add a recovery leg when vol-regime HOT or price OVEREXTENDED (structural-break filters) -> stops piling into a stretched move about to whipsaw (the floor-hit cause). Needs UseVolRegimeFilter/UseOverextFilter on.  // CELL-LOCKED
const bool RecoveryScaleByLots  = false; // [curb-size] scale the recovery $ levers (RecoveryTargetUSD/RecoveryTrailGiveback/HedgeTriggerLoss) by the compounding lotScale=floor(bal/CompoundingBase) so they TRACK lot size as the account grows (the basket-trail already does this). Fixes the floor-hits that appear only on grown accounts.  // CELL-LOCKED
//--- misc
const string CommentText          = "FIB C";  // CELL-LOCKED
const int MagicSeed            = 0;  // CELL-LOCKED

double   point;
long     MagicNumber=0;
datetime lastBarTime=0;
int      tradesThisBar=0;
bool     g_recovering=false;
int      g_recoverWinDir=-1;     // POSITION_TYPE_BUY / _SELL = the side we ride to recover
bool     g_recoverArmed=false;
double   g_recoverPeak=0;
double   g_recoverDeepest=0;
double   peakBasketFloat=0;
int      hMA, hADX, hMA_D1, hATRfast, hATRslow;
int      hATR_cur, hATR_avg;   // for the first-entry fingerprint (match GridStat: M5 ATR 20 / 100)
int      gEqHandle=INVALID_HANDLE;

//+------------------------------------------------------------------+
int OnInit()
{

   Print("FIBC TEST CELL SLV1 -- zero-input build; deltas: FirstGateStatsCSV='gridstat_setups_silver_mt5.csv'");
   point = (_Digits==3 || _Digits==5) ? _Point*10 : _Point;
   hMA   = iMA(_Symbol, PERIOD_CURRENT, MA_Period, 0, MODE_EMA, PRICE_CLOSE);
   hADX  = iADX(_Symbol, PERIOD_CURRENT, ADX_Period);
   hMA_D1= iMA(_Symbol, PERIOD_D1, DailyMA_Period, 0, MODE_EMA, PRICE_CLOSE);
   hATRfast= iATR(_Symbol, PERIOD_D1, VolATRFastPeriod);
   hATRslow= iATR(_Symbol, PERIOD_D1, VolATRSlowPeriod);
   hATR_cur= iATR(_Symbol, PERIOD_CURRENT, 20);   // fingerprint ATR (match GridStat)
   hATR_avg= iATR(_Symbol, PERIOD_CURRENT, 100);
   if(hMA==INVALID_HANDLE||hADX==INVALID_HANDLE||hMA_D1==INVALID_HANDLE||hATRfast==INVALID_HANDLE||hATRslow==INVALID_HANDLE||hATR_cur==INVALID_HANDLE||hATR_avg==INVALID_HANDLE){ Print("handle fail"); return(INIT_FAILED); }
   MagicNumber = (MagicSeed!=0)?MagicSeed:GenMagic("MyEA",_Symbol,(int)Period());
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(20);
   Print("============================================================");
   Print("MARIUS HEDGER FIB C ",BUILD," | ",_Symbol," | Magic=",MagicNumber);
   Print("CONFIG | RecoverySizeMode=",RecoverySizeMode,(RecoverySizeMode==1?" (BREAK-EVEN RR="+DoubleToString(RecoveryRR,1)+"/buf"+DoubleToString(RecoveryCostBuffer,2)+")":" (Fibonacci)"));
   Print("CONFIG | FirstEntryGate=",UseFirstEntryGate,(UseFirstEntryGate?" (BUY>="+DoubleToString(FirstGateMinWinRate,2)+" SELL>="+DoubleToString(FirstGateSellMinWinRate>0?FirstGateSellMinWinRate:FirstGateMinWinRate,2)+" n>="+IntegerToString(FirstGateMinSamples)+" DB="+FirstGateStatsCSV+")":""));
   Print("CONFIG | grisk=",grisk," Fib=",UseFibonacci,"/MaxFibMult=",MaxFibMult," Compound=",UseCompounding,
         " MaxSame=",MaxSameTrades," Trail=",UseBasketTrail,"/",DoubleToString(MinFloatToActivate,0),
         "/",DoubleToString(BasketTrailAmount,0)," QuickHarvest=",UseBuySellProfitThreshold);
   Print("CONFIG | SAFETY: BasketStop=",UseBasketStop,"/",DoubleToString(BasketMaxLossPct,0),
         "% D1filter=",UseDailyTrendFilter," ImbalanceLock=",UseImbalanceLock,"/",ImbalanceThreshold,
         " MaxLots=",UseMaxBasketLots,"/",DoubleToString(MaxBasketLotsTotal,2));
   Print("CONFIG | BREAK-DEFENSE: VolFilter=",UseVolRegimeFilter,"/",DoubleToString(VolRegimeMult,1),
         " (blockAll=",VolBlockAllEntries," scaledFloor=",VolScaledFloor,") | OverextFilter=",UseOverextFilter,
         "/",DoubleToString(OverextATRMult,1)," (blockAdds=",OverextBlockAdds,")");
   Print("============================================================");
   if(UseEquityLog){
      gEqHandle=FileOpen(EquityLogFile,FILE_WRITE|FILE_CSV|FILE_COMMON|FILE_ANSI,',');
      if(gEqHandle!=INVALID_HANDLE) FileWrite(gEqHandle,"time","balance","equity");
      else Print("EquityLog open FAILED: ",EquityLogFile);
   }
   return(INIT_SUCCEEDED);
}
void OnDeinit(const int reason){ if(gEqHandle!=INVALID_HANDLE){ FileClose(gEqHandle); gEqHandle=INVALID_HANDLE; } }
void LogEquity(){
   if(!UseEquityLog || gEqHandle==INVALID_HANDLE) return;
   FileWrite(gEqHandle,TimeToString(TimeCurrent(),TIME_DATE|TIME_SECONDS),
             DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE),2),
             DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY),2));
   FileFlush(gEqHandle);
}
int GenMagic(string ea,string sym,int tf){ int h=0; string s=ea+sym+IntegerToString(tf); for(int i=0;i<StringLen(s);i++) h+=StringGetCharacter(s,i)*(i+1); return h%100000; }

double RB(int hd,int b,int sh){ double a[]; if(CopyBuffer(hd,b,sh,1,a)<=0) return(0); return(a[0]); }
int BarHour(datetime t){ MqlDateTime d; TimeToStruct(t,d); return(d.hour); }

//--- FIRST-ENTRY GATE: fingerprint + win-rate lookup (ported from GridStat -> same DB/fingerprint) ---
string ClassifySetup(int dir)
{
   string d   = (dir==POSITION_TYPE_BUY) ? "BUY" : "SELL";
   int    hr  = BarHour(TimeCurrent());
   string hrB = (hr<9)?"HR_ASIA":(hr<14)?"HR_LDN":(hr<18)?"HR_OVL":"HR_NY";
   double an  = RB(hATR_cur,0,1), aa = RB(hATR_avg,0,1);
   string atrB= (aa==0)?"ATR_NA":(an>aa*1.3)?"ATR_EXP":(an<aa*0.7)?"ATR_COMP":"ATR_NORM";
   return(d+"|"+hrB+"|"+atrB);
}
bool LookupFirstGateStats(string setupKey, double &winRate, int &samples)
{
   int fh=FileOpen(FirstGateStatsCSV, FILE_READ|FILE_CSV|FILE_COMMON|FILE_ANSI, ',');
   if(fh==INVALID_HANDLE){ winRate=0; samples=0; return false; }
   int ncol=0, rIdx=-1;
   while(!FileIsEnding(fh)){ string c=FileReadString(fh); if(c=="r_multiple") rIdx=ncol; ncol++; if(FileIsLineEnding(fh)) break; }
   if(rIdx<0||ncol<=0){ FileClose(fh); winRate=0; samples=0; return false; }
   int wins=0,total=0;
   while(!FileIsEnding(fh)){
      string key=""; double r=0; bool any=false;
      for(int c=0;c<ncol && !FileIsEnding(fh);c++){ string cell=FileReadString(fh); any=true; if(c==0) key=cell; if(c==rIdx) r=StringToDouble(cell); }
      if(!any) break;
      if(key==setupKey){ total++; if(r>0) wins++; }
   }
   FileClose(fh);
   samples=total; winRate=(total>0)?(double)wins/total:0.0;
   return(total>0);
}

//--- EMBEDDED GOLDMINER (native MQL5, validated 50/50 vs MT4) -------------------
double WprValue(int period,int shift)
{
   int hhs=iHighest(_Symbol,PERIOD_CURRENT,MODE_HIGH,period,shift);
   int lls=iLowest(_Symbol,PERIOD_CURRENT,MODE_LOW,period,shift);
   if(hhs<0||lls<0) return(50);
   double hh=iHigh(_Symbol,PERIOD_CURRENT,hhs), ll=iLow(_Symbol,PERIOD_CURRENT,lls), cl=iClose(_Symbol,PERIOD_CURRENT,shift);
   double wpr=(hh-ll!=0)? -100.0*(hh-cl)/(hh-ll) : 0;
   return(100.0-MathAbs(wpr));
}
double GMValueAt(int j)
{
   double avg=0; for(int k=j;k<=j+9;k++) avg+=MathAbs(iHigh(_Symbol,PERIOD_CURRENT,k)-iLow(_Symbol,PERIOD_CURRENT,k)); avg/=10.0;
   bool gap=false,fast=false;
   for(int k=j;k<j+9 && !gap;k++){ double jp=(GM_GapMode==1)?MathAbs(iClose(_Symbol,PERIOD_CURRENT,k)-iClose(_Symbol,PERIOD_CURRENT,k+1)):MathAbs(iOpen(_Symbol,PERIOD_CURRENT,k)-iClose(_Symbol,PERIOD_CURRENT,k+1)); if(jp>=GM_GapMult*avg) gap=true; }
   for(int k=j;k<j+6 && !fast;k++) if(MathAbs(iClose(_Symbol,PERIOD_CURRENT,k+3)-iClose(_Symbol,PERIOD_CURRENT,k))>=GM_FastMult*avg) fast=true;
   int period=(GM_Period>0)?GM_Period:(grisk*2+3); if(gap) period=3; if(fast) period=4;
   return(WprValue(period,j));
}
// returns +1 BUY (green), -1 SELL (red), 0 none
int GoldminerSignal()
{
   double upper=(GM_UpperBand>0)?GM_UpperBand:(grisk+67);
   double lower=(GM_LowerBand>0)?GM_LowerBand:(33-grisk);
   int LB=40; double val[]; ArrayResize(val,LB);
   for(int k=0;k<LB;k++) val[k]=GMValueAt(goldminershift+k);
   int li=1;
   if(val[0]>upper){ while(li<LB-1 && val[li]>=lower && val[li]<=upper) li++; if(val[li]<lower) return(+1); }
   else if(val[0]<lower){ while(li<LB-1 && val[li]>=lower && val[li]<=upper) li++; if(val[li]>upper) return(-1); }
   return(0);
}

double VolRegimeRatio(){ double f=RB(hATRfast,0,0), s=RB(hATRslow,0,0); return (s>0)? f/s : 1.0; }
bool   IsVolRegimeHot(){ return UseVolRegimeFilter && VolRegimeRatio()>=VolRegimeMult; }
double DistD1MA(){ double ema=RB(hMA_D1,0,0), atr=RB(hATRslow,0,0); if(atr<=0) return 0; return MathAbs(iClose(_Symbol,PERIOD_CURRENT,0)-ema)/atr; }
bool   IsOverextended(){ return UseOverextFilter && DistD1MA()>=OverextATRMult; }
double GetMAAngle(){ double m0=RB(hMA,0,0), m1=RB(hMA,0,5); double slope=(m0-m1)/(5*point); return(MathArctan(slope)*180.0/M_PI); }
bool IsTrendDetected(){ double adx=RB(hADX,0,0); return(adx>ADX_Threshold && MathAbs(GetMAAngle())>MA_Angle_Threshold); }
bool D1Bull(){ return RB(hMA_D1,0,0)>RB(hMA_D1,0,1); }

int CountOpen(int dir)  // dir: POSITION_TYPE_BUY / _SELL
{
   int c=0; for(int i=PositionsTotal()-1;i>=0;i--){ ulong t=PositionGetTicket(i); if(t==0||!PositionSelectByTicket(t))continue;
      if(PositionGetInteger(POSITION_MAGIC)!=MagicNumber||PositionGetString(POSITION_SYMBOL)!=_Symbol)continue;
      if(PositionGetInteger(POSITION_TYPE)==dir) c++; }
   return c;
}
double SideProfit(int dir)
{
   double p=0; for(int i=PositionsTotal()-1;i>=0;i--){ ulong t=PositionGetTicket(i); if(t==0||!PositionSelectByTicket(t))continue;
      if(PositionGetInteger(POSITION_MAGIC)!=MagicNumber||PositionGetString(POSITION_SYMBOL)!=_Symbol)continue;
      if(PositionGetInteger(POSITION_TYPE)==dir) p+=PositionGetDouble(POSITION_PROFIT)+PositionGetDouble(POSITION_SWAP); }
   return p;
}
double SideLots(int dir)  // sum of OPEN lots on one side (for break-even recovery sizing)
{
   double l=0; for(int i=PositionsTotal()-1;i>=0;i--){ ulong t=PositionGetTicket(i); if(t==0||!PositionSelectByTicket(t))continue;
      if(PositionGetInteger(POSITION_MAGIC)!=MagicNumber||PositionGetString(POSITION_SYMBOL)!=_Symbol)continue;
      if(PositionGetInteger(POSITION_TYPE)==dir) l+=PositionGetDouble(POSITION_VOLUME); }
   return l;
}
double BookFloat(){ return SideProfit(POSITION_TYPE_BUY)+SideProfit(POSITION_TYPE_SELL); }
double TotalOpenLots(){ double l=0; for(int i=PositionsTotal()-1;i>=0;i--){ ulong t=PositionGetTicket(i); if(t==0||!PositionSelectByTicket(t))continue; if(PositionGetInteger(POSITION_MAGIC)!=MagicNumber||PositionGetString(POSITION_SYMBOL)!=_Symbol)continue; l+=PositionGetDouble(POSITION_VOLUME); } return l; }

double LotScaleInt(){ if(!UseCompounding||CompoundingBase<=0) return 1.0; double sc=MathFloor(AccountInfoDouble(ACCOUNT_BALANCE)/CompoundingBase); if(MaxCompoundScale>0) sc=MathMin(sc,(double)MaxCompoundScale); return MathMax(1.0,sc); }
double CalculateLot(int dir)
{
   double baseLot=LotSize;
   if(UseCompounding && CompoundingBase>0){
      double mult=AccountInfoDouble(ACCOUNT_BALANCE)/CompoundingBase;
      if(MaxCompoundScale>0) mult=MathMin(mult,(double)MaxCompoundScale);
      double scaled=MathFloor(mult*LotSize/0.01)*0.01;
      baseLot=MathMax(LotSize,scaled);
   }
   int cnt=CountOpen(dir);
   if(cnt<=0) return NormalizeDouble(baseLot,2);          // first leg = base (both modes)

   if(RecoverySizeMode==1)
   {
      // BREAK-EVEN GUARANTEE (zone-recovery math): minimal leg that makes the basket net-positive
      // at the next favourable move, cost included. = (RR+1)/RR x (oppositeLots - sameLots) x buffer.
      int opp = (dir==POSITION_TYPE_BUY) ? POSITION_TYPE_SELL : POSITION_TYPE_BUY;
      double factor = (RecoveryRR + 1.0) / MathMax(0.1, RecoveryRR);
      double lot = factor * (SideLots(opp) - SideLots(dir)) * RecoveryCostBuffer;
      if(lot < baseLot) lot = baseLot;                    // one-sided / low-imbalance -> base (gentlest)
      return NormalizeDouble(lot,2);
   }

   // FIBONACCI (default, unchanged)
   if(UseFibonacci){ int fib[10]={1,1,2,3,5,8,13,21,34,55}; int idx=(int)MathMin(cnt,9); int m=fib[idx]; if(MaxFibMult>0) m=(int)MathMin(m,MaxFibMult); return NormalizeDouble(baseLot*m,2); }
   return NormalizeDouble(baseLot*MathPow(LotMultiplier,cnt),2);
}

void CloseSide(int dir)
{
   for(int i=PositionsTotal()-1;i>=0;i--){ ulong t=PositionGetTicket(i); if(t==0||!PositionSelectByTicket(t))continue;
      if(PositionGetInteger(POSITION_MAGIC)!=MagicNumber||PositionGetString(POSITION_SYMBOL)!=_Symbol)continue;
      if(PositionGetInteger(POSITION_TYPE)==dir) trade.PositionClose(t); }
}
void CloseAll(){ CloseSide(POSITION_TYPE_BUY); CloseSide(POSITION_TYPE_SELL); }

//--- RECOVERY HEDGE: arm when deep underwater, ride the winning side, exit the whole book in profit.
//    Sets g_recovering. The catastrophe floor (in CheckBasketTrail) stays the backstop.
void CheckRecoveryHedge()
{
   if(!UseRecoveryHedge){ g_recovering=false; return; }
   double bal=AccountInfoDouble(ACCOUNT_BALANCE);
   double bookFloat=BookFloat();

   if(g_recovering)
   {
      // safety: if the whole book got closed elsewhere, end the rescue cleanly
      if(CountOpen(POSITION_TYPE_BUY)==0 && CountOpen(POSITION_TYPE_SELL)==0){
         g_recovering=false; g_recoverWinDir=-1; g_recoverArmed=false; g_recoverPeak=0; g_recoverDeepest=0; return;
      }
      if(bookFloat < g_recoverDeepest) g_recoverDeepest=bookFloat;        // track deepest loss this rescue
      double lotScale = LotScaleInt();
      double tgtUSD   = RecoveryScaleByLots ? RecoveryTargetUSD*lotScale    : RecoveryTargetUSD;
      double giveback = RecoveryScaleByLots ? RecoveryTrailGiveback*lotScale : RecoveryTrailGiveback;
      double effTarget = (RecoveryTargetPct>0) ? MathMax(tgtUSD,(RecoveryTargetPct/100.0)*(-g_recoverDeepest)) : tgtUSD;
      if(UseRecoveryTrail)
      {
         if(bookFloat>=effTarget){ if(!g_recoverArmed) g_recoverArmed=true; if(bookFloat>g_recoverPeak) g_recoverPeak=bookFloat; }
         if(g_recoverArmed){
            double exitLvl=MathMax(effTarget, g_recoverPeak-giveback);
            if(bookFloat<=exitLvl && bookFloat<g_recoverPeak){
               Print("RECOVERY TRAIL exit: book=+",DoubleToString(bookFloat,2)," peak +",DoubleToString(g_recoverPeak,2)," tgt ",DoubleToString(effTarget,0));
               CloseAll(); g_recovering=false; g_recoverWinDir=-1; g_recoverArmed=false; g_recoverPeak=0; g_recoverDeepest=0; peakBasketFloat=0;
            }
         }
         return;
      }
      if(bookFloat>=effTarget){
         Print("RECOVERY COMPLETE: book=+",DoubleToString(bookFloat,2)," (tgt ",DoubleToString(effTarget,0),")");
         CloseAll(); g_recovering=false; g_recoverWinDir=-1; g_recoverDeepest=0; peakBasketFloat=0;
      }
      return;
   }

   // not recovering -> check the arm trigger
   double trigger = (HedgeTriggerPctBal>0) ? (HedgeTriggerPctBal/100.0)*bal : (RecoveryScaleByLots ? HedgeTriggerLoss*LotScaleInt() : HedgeTriggerLoss);
   if(trigger>0 && bookFloat<=-trigger)
   {
      double bp=SideProfit(POSITION_TYPE_BUY), sp=SideProfit(POSITION_TYPE_SELL);
      g_recoverWinDir = (bp>=sp) ? POSITION_TYPE_BUY : POSITION_TYPE_SELL;  // ride the LESS-negative (trend) side
      g_recovering=true; g_recoverArmed=false; g_recoverPeak=0; g_recoverDeepest=bookFloat;
      Print("RECOVERY ARMED: book=",DoubleToString(bookFloat,2)," trigger=-",DoubleToString(trigger,2)," winDir=",(g_recoverWinDir==POSITION_TYPE_BUY?"BUY":"SELL"));
   }
}

//--- basket trail (every tick) + catastrophe floor (safety, default off) -------
void CheckBasketTrail(bool recovering=false)
{
   double lotScale=LotScaleInt();
   double effMin=MinFloatToActivate*lotScale, effTrail=BasketTrailAmount*lotScale;
   double tot=BookFloat();
   // SAFETY: catastrophe floor (+ vol-scaled widening (c): in a hot regime give baskets room to revert)
   if(UseBasketStop){
      double floorPct=BasketMaxLossPct;
      if(UseVolRegimeFilter && VolScaledFloor){ double r=VolRegimeRatio(); if(r>1.0) floorPct*=MathMax(1.0,MathMin(r,VolFloorMaxMult)); }
      if(tot <= -floorPct/100.0*AccountInfoDouble(ACCOUNT_BALANCE)){
         Print("BASKET STOP fired float=",DoubleToString(tot,2)," floorPct=",DoubleToString(floorPct,1)); CloseAll(); peakBasketFloat=0;
         g_recovering=false; g_recoverWinDir=-1; g_recoverArmed=false; g_recoverPeak=0; g_recoverDeepest=0; return;
      }
   }
   if(recovering) return;   // recovery owns the profit-side close; only the floor above runs while rescuing
   if(UseBasketTrail && tot>=effMin){
      if(tot>peakBasketFloat) peakBasketFloat=tot;
      if(tot<=peakBasketFloat-effTrail){ Print("BasketTrail fired float=",DoubleToString(tot,2)," peak=",DoubleToString(peakBasketFloat,2)); CloseAll(); peakBasketFloat=0; }
      return;
   }
   peakBasketFloat=0;
}
//--- same-direction quick harvest (called after a new entry, like live) --------
void ManageTradeClosures()
{
   double bp=SideProfit(POSITION_TYPE_BUY); int bc=CountOpen(POSITION_TYPE_BUY);
   double sp=SideProfit(POSITION_TYPE_SELL); int sc=CountOpen(POSITION_TYPE_SELL);
   double eff=(BuySellProfitThresholdInCurrency>0)?BuySellProfitThresholdInCurrency:(BuySellProfitThreshold*point);
   if(UseBuySellProfitThreshold && bc>=2 && bp>=eff) CloseSide(POSITION_TYPE_BUY);
   if(UseBuySellProfitThreshold && sc>=2 && sp>=eff) CloseSide(POSITION_TYPE_SELL);
}

void OpenTrade(int dir, bool force=false)  // dir +1 buy / -1 sell; force = recovery ride (bypass gates)
{
   int ptype=(dir>0)?POSITION_TYPE_BUY:POSITION_TYPE_SELL;
   if(!force && CountOpen(ptype)>=MaxSameTrades) return;
   // FIRST-ENTRY PROBABILITY GATE: only START a basket on this side from a high-win-rate fingerprint.
   // Recovery legs (CountOpen>0) bypass -> the recovery edge is preserved; we just refuse bad STARTS.
   if(!force && UseFirstEntryGate && CountOpen(ptype)==0)
   {
      double wr=0; int ns=0; string key=ClassifySetup(ptype);
      if(!LookupFirstGateStats(key, wr, ns)) return;                       // unknown fingerprint -> don't start
      double thr = FirstGateMinWinRate;                                    // per-direction threshold
      if(ptype==POSITION_TYPE_SELL && FirstGateSellMinWinRate>0) thr = FirstGateSellMinWinRate;  // gate weak shorts harder
      if(ns < FirstGateMinSamples || wr < thr) return;                     // low-probability -> don't start
   }
   // SAFETY: imbalance lock -- don't add to a losing side that outnumbers the other
   if(!force && UseImbalanceLock){
      int me=CountOpen(ptype), opp=CountOpen(dir>0?POSITION_TYPE_SELL:POSITION_TYPE_BUY);
      double myP=SideProfit(ptype);
      if(me-opp>=ImbalanceThreshold && myP<0) return;
   }
   double lot=CalculateLot(ptype);
   if(!force && UseMaxBasketLots && TotalOpenLots()+lot > MaxBasketLotsTotal) return;  // cap the Fibonacci ladder = cap the loss tail
   trade.SetTypeFillingBySymbol(_Symbol);
   bool ok=(dir>0)?trade.Buy(lot,_Symbol,0,0,0,CommentText):trade.Sell(lot,_Symbol,0,0,0,CommentText);
   if(ok){ tradesThisBar++; if(!force) ManageTradeClosures(); }
}

//+------------------------------------------------------------------+
void OnTick()
{
   if(iTime(_Symbol,PERIOD_CURRENT,0)!=lastBarTime){ lastBarTime=iTime(_Symbol,PERIOD_CURRENT,0); tradesThisBar=0; LogEquity(); }

   CheckRecoveryHedge();          // arm/exit the deep-basket rescue -> sets g_recovering
   CheckBasketTrail(g_recovering);// catastrophe floor always; basket-trail skipped while rescuing

   if(!g_recovering && UseSessionFilter){
      int hr=BarHour(TimeCurrent());
      bool inS=(SessionStartHour<SessionEndHour)?(hr>=SessionStartHour&&hr<SessionEndHour):(hr>=SessionStartHour||hr<SessionEndHour);
      if(!inS) return;
   }
   if(tradesThisBar>=tradesperbar) return;

   int sig=GoldminerSignal();
   if(sig==0) return;

   // RECOVERY: ride ONLY the winning (trend) side, bypassing D1/session/imbalance/MaxSameTrades
   if(g_recovering){
      int winSig=(g_recoverWinDir==POSITION_TYPE_BUY)?1:-1;
      bool blockAdd = RecoveryRespectBreakFilters &&
                      ( (UseVolRegimeFilter && IsVolRegimeHot()) || (UseOverextFilter && IsOverextended()) );
      if(sig==winSig && !blockAdd) OpenTrade(sig,true);   // ride the winner unless a structural break says wait
      return;
   }

   bool hasOpen=(CountOpen(POSITION_TYPE_BUY)>0||CountOpen(POSITION_TYPE_SELL)>0);
   if(!IsTrendDetected() && !hasOpen) return;
   // SAFETY: D1 trend filter
   if(UseDailyTrendFilter){
      if(sig>0 && !D1Bull()) return;
      if(sig<0 &&  D1Bull()) return;
   }
   // SAFETY: vol-regime filter -- (a) block all entries / (b) block only adds, while regime is HOT
   if(UseVolRegimeFilter && IsVolRegimeHot()){
      if(VolBlockAllEntries) return;
      int ptype=(sig>0)?POSITION_TYPE_BUY:POSITION_TYPE_SELL;
      if(VolBlockStacking && CountOpen(ptype)>0) return;
   }
   // SAFETY: overextension filter -- the slow-drift structural break (vol filter's blind spot).
   // Stop growing the fib ladder when price is stretched far from the D1 mean = where the break catches it.
   if(UseOverextFilter && IsOverextended()){
      if(!OverextBlockAdds) return;                                   // block ALL entries
      int pt=(sig>0)?POSITION_TYPE_BUY:POSITION_TYPE_SELL;
      if(CountOpen(pt)>0) return;                                     // block only ADDS (the deep fib legs)
   }
   OpenTrade(sig);
}
//+------------------------------------------------------------------+
