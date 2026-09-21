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

#define BUILD "FIBC-MT5-2026-08-24-P-STATEREL"

//--- sizing
input double LotSize            = 0.02;
input bool   UseFibonacci       = true;     // 1,1,2,3,5,8.. per direction (else martingale x LotMultiplier)
input int    LotMultiplier      = 2;
input bool   UseCompounding     = true;
input double CompoundingBase    = 3000.0;   // base lot scales with floor(balance/this)
input int    MaxSameTrades      = 5;        // max ladder depth per direction
input int    MaxFibMult         = 0;        // GENTLER LADDER: cap per-leg fib multiplier (0=uncapped 1,1,2,3,5,8..; e.g. 3 -> 1,1,2,3,3,3 = smaller deep legs = smaller floating basket = smaller floor loss, lower PF in chop. The DD dial that works regardless of where legs were placed.)
input int    MaxCompoundScale   = 3;        // [curb-give-back] cap the compounding multiplier floor(bal/CompoundingBase). 0=uncapped (current). e.g. 3 = base lot never grows past 3x -> baskets stay SMALL relative to a grown account -> the recovery keeps the rescue headroom it has at $3k -> fewer/smaller floor-hits. Trade-off: less compounding upside.
//--- RECOVERY SIZING MODE (zone-recovery "break-even guarantee" math vs Fibonacci). A/B lever.
input int    RecoverySizeMode   = 1;        // 0 = Fibonacci (default, UNCHANGED). 1 = BREAK-EVEN formula: each recovery leg = (RR+1)/RR x (opposite-side lots - same-side lots) x CostBuffer = the MINIMAL leg that makes the basket net-positive at the next favourable move, cost included. Leaner/more principled than Fibonacci -> smaller per-basket tail. (Derived from zone-recovery math; in a one-sided trend it floors to base = uniform lots.)
input double RecoveryRR         = 3.0;      // mode 1 R:R (higher = gentler leg growth)
input double RecoveryCostBuffer = 1.1;      // mode 1: size up x this to clear spread+commission+swap (1.1 = +10%)
//--- entry signal (Goldminer embedded + trend gate)
input int    grisk              = 7;        // fib C value (drives auto period/bands)
input int    GM_Period          = 0;        // 0 = auto (grisk*2+3)
input double GM_UpperBand        = 0;       // 0 = auto (grisk+67)
input double GM_LowerBand        = 0;       // 0 = auto (33-grisk)
input double GM_GapMult          = 2.0;
input int    GM_GapMode          = 0;
input double GM_FastMult         = 4.6;
input int    goldminershift      = 1;
input int    MA_Period           = 20;
input double MA_Angle_Threshold  = 20.0;
input int    ADX_Period          = 14;
input double ADX_Threshold       = 25.0;
input int    tradesperbar        = 1;
//--- session
input bool   UseSessionFilter    = true;
input int    SessionStartHour     = 9;
input int    SessionEndHour       = 23;
//--- exits
input bool   UseBasketTrail       = true;
input double MinFloatToActivate   = 80.0;
input double BasketTrailAmount     = 15.0;
input bool   UseBuySellProfitThreshold = true;  // same-dir quick harvest
input double BuySellProfitThreshold     = 50.0; // in POINTS*point (gold ~ $0.50) -- faithful to live
input double BuySellProfitThresholdInCurrency = 0; // >0 overrides to a $ threshold
//=== RISK-SAFE levers (DEFAULT OFF -> base == live; we A/B these on) ===
input bool   UseBasketStop        = true;  // catastrophe floor: close ALL if book float <= -BasketMaxLossPct% balance
input double BasketMaxLossPct     = 20.0;
//--- build L (2026-07-14): fib C's $10k autopsy = ONE deep book realized -$3,516 AT the 20%
//    floor of the grown balance (Apr-14, 11 legs) = gold's exact pre-SF12 anatomy. Two levers:
input bool   UseStagedFloor       = false; // gold SF12 port: book <= -StagedFloorPct% -> close the WORST leg (once/bar) BEFORE the floor
input double StagedFloorPct       = 12.0;
input double ScaleAnchorBalance   = 0;     // cold-start protection: >0 -> compounding scale counts only balance ABOVE this
                                           //   (a cold $10k deposit trades like a fresh $3k until it has EARNED its scale;
                                           //   fixes the sequencing disease WITHOUT breaking fib C's lot/threshold proportions
                                           //   -- the mistake a plain tighter cap makes: CAP2@10k = RF 0.58, 11-leg clusters)
input bool   UseDailyTrendFilter  = true;  // only enter WITH the D1 trend (cuts counter-trend tax)
input int    DailyMA_Period       = 50;
input bool   UseImbalanceLock     = true;  // stop adding to a side that outnumbers the other by >= ImbalanceThreshold AND is in loss
input int    ImbalanceThreshold   = 2;
input bool   UseMaxBasketLots     = false;  // cap TOTAL open lots -> bounds the Fibonacci martingale = caps the max basket loss (the DD tail)
input double MaxBasketLotsTotal    = 0.30;
//--- VOL-REGIME filter (AFML Ch.17; the proven MT4 DD-cut: (a)+(c) cut fib C DD 59%->38%, session 19k). DEFAULT OFF.
input bool   UseVolRegimeFilter   = true;  // master switch
input int    VolATRFastPeriod     = 5;      // fast ATR(D1) = current regime
input int    VolATRSlowPeriod     = 60;     // slow ATR(D1) = baseline regime
input double VolRegimeMult         = 2.5;   // HOT when ATR_fast/ATR_slow >= this
input bool   VolBlockAllEntries    = true;  // (a) HOT: block ALL new entries (sit out the storm)
input bool   VolBlockStacking      = false; // (b) HOT: block only ADDS (allow 1st entry/dir)
input bool   VolScaledFloor        = false;  // (c) HOT: WIDEN the catastrophe floor so baskets ride to recovery
input double VolFloorMaxMult        = 2.0;  // (c) cap: floor% widens up to this x BasketMaxLossPct (30%->60%)
//--- OVEREXTENSION filter (AFML Ch.17; the DIRECTIONAL-DRIFT analog of the vol filter -- catches the slow-drift
//    structural break the vol-EXPANSION filter MISSES. gridregime.py (19o): dist=|close-D1EMA|/ATR(D1,60) corr
//    -0.61 with gold deep-MAE. Stops growing the fib ladder into the extreme = caps the deep-leg tail WITHOUT
//    cutting recoverable baskets. DEFAULT OFF -> base unchanged.)
input bool   UseOverextFilter     = false; 
input double OverextATRMult        = 4.5;   // HOT when |close - D1EMA(DailyMA_Period)| / ATR(D1,VolATRSlowPeriod) >= this (gold ~90th pctile)
input bool   OverextBlockAdds      = true;  // true: block only ADDS when stretched (cap the deep fib legs, keep base flow); false: block ALL entries
//--- TWO-ENGINE LAB: per-bar floating-equity log (the harvester half of the harvester+trend pairing). DEFAULT OFF -> no files in live.
input bool   UseEquityLog         = false;          // research: write time,balance,equity per bar to EquityLogFile (Common\Files)
input string EquityLogFile        = "fibc_equity.csv";
//--- FIRST-ENTRY PROBABILITY GATE (the GridStat selectivity = source of its 20% DD vs fib C's 50%).
//    Only START a basket (first leg on a side) when the entry fingerprint DIR|SESSION|ATR-regime has
//    historical win-rate >= threshold in the stats DB. Recovery legs (adds) BYPASS it. DEFAULT OFF.
//    Attacks the tail AT SOURCE (don't start bad baskets) -> preserves the recovery edge (vs floor-cuts).
input bool   UseFirstEntryGate    = true;
input string FirstGateStatsCSV    = "gridstat_setups_gold.csv";  // GridStat shadow DB (Common\Files); same fingerprint
input double FirstGateMinWinRate  =    0.55;   // win-rate threshold for BUY starts
input double FirstGateSellMinWinRate = 0.65; // SELL-only threshold (0 = use FirstGateMinWinRate). Gold longs >> shorts -> set this higher (e.g. 0.65) to cut weak shorts.
input int    FirstGateMinSamples  = 10;
//--- RECOVERY HEDGE (the validated MT4 win, session 19v): when the book is deep underwater,
//    STOP feeding the loser and RIDE the winning (trend) side on every Goldminer signal until
//    the whole book recovers to +target. Averaging-in recovers mean-reversion; riding the winner
//    recovers sustained trends (the deep-basket cause). Overrides D1/session/imbalance/MaxSameTrades
//    for the WINNING side only. Catastrophe floor stays the backstop. DEFAULT OFF -> base unchanged.
input bool   UseRecoveryHedge     = true;
input double HedgeTriggerLoss     = 0.0;  // arm when book float <= -this ($)
input double HedgeTriggerPctBal   = 3.0;    // >0: arm when book float <= -this%% of balance (overrides HedgeTriggerLoss; deposit-portable). Validated 3.
input double RecoveryTargetUSD    = 40.0;   // close the WHOLE book once it recovers to +this ($)
input bool   UseRecoveryTrail     = true;  // [opt1] once recovered to +target, TRAIL the winner instead of flat-closing (+4%% on gold)
input double RecoveryTrailGiveback = 20.0;  // give-back ($) from the recovery peak that closes (locks >= effective target)
input double RecoveryTargetPct    = 10.0;    // [opt2] >0: scale target to this %% of the DEEPEST loss rescued (max w/ RecoveryTargetUSD). +3%% on gold at 10.
input bool   RecoveryRespectBreakFilters = false; // [curb] while rescuing, DON'T add a recovery leg when vol-regime HOT or price OVEREXTENDED (structural-break filters) -> stops piling into a stretched move about to whipsaw (the floor-hit cause). Needs UseVolRegimeFilter/UseOverextFilter on.
input bool   RecoveryScaleByLots  = false; // [curb-size] scale the recovery $ levers (RecoveryTargetUSD/RecoveryTrailGiveback/HedgeTriggerLoss) by the compounding lotScale=floor(bal/CompoundingBase) so they TRACK lot size as the account grows (the basket-trail already does this). Fixes the floor-hits that appear only on grown accounts.
//--- WHIPSAW RECALIBRATION (build N, 2026-08-07 — the Aug-5/6 V-reversal floor autopsy; XM floored -$451
//    while the identical PEP episode rescued +$103 = capital bought time, but the defects are real).
//    ALL default-OFF -> base byte-identical. Kill-test window Dec-01->Aug-07 CONTAINS both episodes:
//    the ep1 rescue-win must STAY green; the ep2 whipsaw floor must flip to small/no loss.
input double HedgeTriggerATRMult  = 0.0;   // >0: arm threshold = max(%%-bal trigger, this x ATR(D1,fast) x sideLots x contract $). Denominates the trigger in the THREAT's units (vol): the 3%%-bal trigger armed at ~0.3 daily-ATR post-melt-up = ordinary noise = systematic top-buying. Sweep {0.5,0.75,1.0}.
input bool   UseRideBrake         = false; // skip a ride add while the ride side's NEWEST leg is underwater (the ride is no longer winning). Would have blocked the Aug-6 top-adds (legs 3-6 @4262-4270, all AFTER the 4297 peak).
input int    MaxRideLegs          = 0;     // >0: hard cap on winning-side legs while rescuing (the ride overrides MaxSameTrades: XM stacked 6, PEP 11)
input double RecoveryPeakBankPct  = 0.0;   // >0: arm the recovery trail once the book claws back this %% of the deepest->target distance (bank partial progress below +target: the Aug-6 book peaked -$35, $75 short of target, then floored -$451). e.g. 75.
//--- STATE-RELEASE (build P, 2026-08-24 -- the adaptive rework's first lever; pilots fibc_inflight*/fibc_policy_sim*).
//    IN-FLIGHT state study (5.25y PEP, perm p=0.000, halves stable): a ride pulled back >=0.3 x ATR(D1,14)
//    off its post-arm extreme AND stale (no new extreme for hours) -- or under water vs its arm price while
//    pulled back -- whipsaws 2-3x more often than it rescues. Specimen replay: releases the Aug-19 demo
//    floor at -$233 instead of -$1,306 (trigger fired 6h before the floor); clean rescues untouched.
//    ACTION: realize the WHOLE book at market at the first bad-state moment. DEFAULT OFF -> base unchanged.
input bool   UseStateRelease      = false;
input double SR_PullATR           = 0.30;  // pullback from post-arm extreme, x ATR(D1,14) (pilot q66)
input double SR_StaleHours        = 7.0;   // hours without a new post-arm extreme (pilot q66)
input double StateReleaseMinMark  = 0.0;   // <0: release ONLY while book float >= this $ (caps the realized loss; 0 = always)
input bool   SR_UsePosLeg         = true;  // false: drop the (pos<=0 & pull) leg -- release only on pull+stale (the pos leg fires on transient wobbles)
input double SR_MinAgeHours       = 0.0;   // >0: no release before the rescue is this old (protects fast ordinary rescues; disasters run 16h+)
input double SR_ConfirmMins       = 0.0;   // >0: the bad state must persist this many minutes before releasing (kills one-tick triggers)
//--- INTELLIGENT WEEKEND FLAT/FREEZE (2026-08-11 spec; user: "must not close a huge open position
//    that puts the account back"). State-aware at the Friday cutoff: book green/shallow -> FLATTEN
//    & bank (zero gap risk); book DEEP -> 1:1 NET HEDGE for the weekend (gap-IMMUNE: long+short
//    cancel whatever Monday gaps) held frozen, released Monday -> the recovery continues untouched.
//    Never realizes a deep recoverable float. DEFAULT OFF -> base byte-identical.
input bool   UseWeekendFlat        = false;
input int    WeekendNoNewHour      = 20;   // Friday server hour: stop NEW entries (never open a basket just to decide about it at the close)
input int    WeekendFlatHour       = 22;   // Friday server hour: act on the book (flatten or freeze)
input double WeekendFlatMaxLossPct = 1.0;  // book better than -this% of ScaleBal -> FLATTEN/bank; deeper -> freeze
input bool   WeekendFreezeDeep     = true; // deep book -> weekend net-hedge (false = deep books just HOLD unhedged)
input int    MondayReleaseHour     = 2;    // Monday server hour: close WKND hedge legs, resume normal ops
//--- misc
input string CommentText          = "FIB C";
input int    MagicSeed            = 0;

double   point;
long     MagicNumber=0;
datetime g_lastStageBar=0;   // staged floor (build L): one worst-leg cut per bar
datetime lastBarTime=0;
int      tradesThisBar=0;
bool     g_recovering=false;
int      g_recoverWinDir=-1;     // POSITION_TYPE_BUY / _SELL = the side we ride to recover
bool     g_recoverArmed=false;
double   g_recoverPeak=0;
double   g_recoverDeepest=0;
double   g_srArmPrice=0, g_srExt=0;   // state-release (build P): post-arm extreme tracking
datetime g_srExtTime=0;
datetime g_srArmTime=0, g_srBadSince=0;   // state-release refinements: rescue age + persistence
double   peakBasketFloat=0;
int      hMA, hADX, hMA_D1, hATRfast, hATRslow;
int      hATR_cur, hATR_avg;   // for the first-entry fingerprint (match GridStat: M5 ATR 20 / 100)
int      hATR_D1_14;           // state-release ATR unit (matches the pilot: ATR(D1,14))
int      gEqHandle=INVALID_HANDLE;

//+------------------------------------------------------------------+
int OnInit()
{
   point = (_Digits==3 || _Digits==5) ? _Point*10 : _Point;
   hMA   = iMA(_Symbol, PERIOD_CURRENT, MA_Period, 0, MODE_EMA, PRICE_CLOSE);
   hADX  = iADX(_Symbol, PERIOD_CURRENT, ADX_Period);
   hMA_D1= iMA(_Symbol, PERIOD_D1, DailyMA_Period, 0, MODE_EMA, PRICE_CLOSE);
   hATRfast= iATR(_Symbol, PERIOD_D1, VolATRFastPeriod);
   hATRslow= iATR(_Symbol, PERIOD_D1, VolATRSlowPeriod);
   hATR_cur= iATR(_Symbol, PERIOD_CURRENT, 20);   // fingerprint ATR (match GridStat)
   hATR_avg= iATR(_Symbol, PERIOD_CURRENT, 100);
   hATR_D1_14= iATR(_Symbol, PERIOD_D1, 14);   // state-release (build P)
   if(hMA==INVALID_HANDLE||hADX==INVALID_HANDLE||hMA_D1==INVALID_HANDLE||hATRfast==INVALID_HANDLE||hATRslow==INVALID_HANDLE||hATR_cur==INVALID_HANDLE||hATR_avg==INVALID_HANDLE||hATR_D1_14==INVALID_HANDLE){ Print("handle fail"); return(INIT_FAILED); }
   MagicNumber = (MagicSeed!=0)?MagicSeed:GenMagic("MyEA",_Symbol,(int)Period());
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(20);
   Print("============================================================");
   Print("MARIUS HEDGER FIB C ",BUILD," | ",_Symbol," | Magic=",MagicNumber);
   Print("CONFIG | RecoverySizeMode=",RecoverySizeMode,(RecoverySizeMode==1?" (BREAK-EVEN RR="+DoubleToString(RecoveryRR,1)+"/buf"+DoubleToString(RecoveryCostBuffer,2)+")":" (Fibonacci)"));
   Print("CONFIG | FirstEntryGate=",UseFirstEntryGate,(UseFirstEntryGate?" (BUY>="+DoubleToString(FirstGateMinWinRate,2)+" SELL>="+DoubleToString(FirstGateSellMinWinRate>0?FirstGateSellMinWinRate:FirstGateMinWinRate,2)+" n>="+IntegerToString(FirstGateMinSamples)+" DB="+FirstGateStatsCSV+")":""));
   Print("CONFIG | WHIPSAW-RECAL | HedgeTriggerATRMult=",DoubleToString(HedgeTriggerATRMult,2)," RideBrake=",UseRideBrake," MaxRideLegs=",MaxRideLegs," PeakBankPct=",DoubleToString(RecoveryPeakBankPct,0));
   Print("CONFIG | STATE-RELEASE | UseStateRelease=",UseStateRelease,(UseStateRelease?" (pull>="+DoubleToString(SR_PullATR,2)+"xATR14 stale>="+DoubleToString(SR_StaleHours,1)+"h minMark="+DoubleToString(StateReleaseMinMark,0)+" posLeg="+(string)SR_UsePosLeg+" minAge="+DoubleToString(SR_MinAgeHours,0)+"h confirm="+DoubleToString(SR_ConfirmMins,0)+"m)":""));
   Print("CONFIG | WEEKEND | UseWeekendFlat=",UseWeekendFlat,(UseWeekendFlat?" (noNew Fri "+IntegerToString(WeekendNoNewHour)+"h, act "+IntegerToString(WeekendFlatHour)+"h: flatten>-"+DoubleToString(WeekendFlatMaxLossPct,1)+"% else "+(WeekendFreezeDeep?"FREEZE":"hold")+", release Mon "+IntegerToString(MondayReleaseHour)+"h)":""));
   // weekend restart-safety: a WKND hedge leg on the book = we are frozen (e.g. terminal restart Sat/Sun)
   for(int wi=PositionsTotal()-1; wi>=0; wi--){
      ulong wt=PositionGetTicket(wi);
      if(wt==0||!PositionSelectByTicket(wt)) continue;
      if(PositionGetInteger(POSITION_MAGIC)!=MagicNumber||PositionGetString(POSITION_SYMBOL)!=_Symbol) continue;
      if(StringFind(PositionGetString(POSITION_COMMENT),"WKND")>=0){ g_wkndFrozen=true; Print("WEEKEND: frozen state re-adopted from open WKND hedge"); break; }
   }
   Print("CONFIG | grisk=",grisk," Fib=",UseFibonacci,"/MaxFibMult=",MaxFibMult," Compound=",UseCompounding,
         " MaxSame=",MaxSameTrades," Trail=",UseBasketTrail,"/",DoubleToString(MinFloatToActivate,0),
         "/",DoubleToString(BasketTrailAmount,0)," QuickHarvest=",UseBuySellProfitThreshold);
   Print("CONFIG | StagedFloor=",UseStagedFloor,"/",DoubleToString(StagedFloorPct,1),
         "% ScaleAnchorBalance=",DoubleToString(ScaleAnchorBalance,0)," (build L levers)");
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

double ScaleBal(){ double b=AccountInfoDouble(ACCOUNT_BALANCE);
   // cold-start anchor (build L): only EARNED balance above the anchor drives the scale
   if(ScaleAnchorBalance>0) b = CompoundingBase + MathMax(0.0, b - ScaleAnchorBalance);
   return b; }
double LotScaleInt(){ if(!UseCompounding||CompoundingBase<=0) return 1.0; double sc=MathFloor(ScaleBal()/CompoundingBase); if(MaxCompoundScale>0) sc=MathMin(sc,(double)MaxCompoundScale); return MathMax(1.0,sc); }
double CalculateLot(int dir)
{
   double baseLot=LotSize;
   if(UseCompounding && CompoundingBase>0){
      double mult=ScaleBal()/CompoundingBase;
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

//--- WEEKEND FLAT/FREEZE machinery -------------------------------------------------
bool g_wkndFrozen = false;

bool IsWkndLeg(ulong tk)
{
   if(!PositionSelectByTicket(tk)) return false;
   return StringFind(PositionGetString(POSITION_COMMENT), "WKND") >= 0;
}

bool WkndBlockNew()   // Friday pre-close: no NEW entries; frozen book: nothing new either
{
   if(!UseWeekendFlat) return false;
   if(g_wkndFrozen) return true;
   MqlDateTime dt; TimeToStruct(TimeCurrent(), dt);
   return (dt.day_of_week == 5 && dt.hour >= WeekendNoNewHour);
}

void WeekendCheck()
{
   if(!UseWeekendFlat) return;
   MqlDateTime dt; TimeToStruct(TimeCurrent(), dt);
   // FRIDAY cutoff: state-aware action on the open book
   if(!g_wkndFrozen && dt.day_of_week == 5 && dt.hour >= WeekendFlatHour)
   {
      int n = CountOpen(POSITION_TYPE_BUY) + CountOpen(POSITION_TYPE_SELL);
      if(n > 0)
      {
         double book = BookFloat();
         if(book >= -WeekendFlatMaxLossPct/100.0 * ScaleBal())
         {
            Print("WEEKEND FLAT: banking/flattening book ", DoubleToString(book,2),
                  " (better than -", DoubleToString(WeekendFlatMaxLossPct,1), "% -> cheap insurance)");
            CloseAll(); peakBasketFloat = 0;
         }
         else if(WeekendFreezeDeep)
         {
            double net = SideLots(POSITION_TYPE_BUY) - SideLots(POSITION_TYPE_SELL);
            double vol = NormalizeDouble(MathAbs(net), 2);
            double minv = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
            if(vol >= minv)
            {
               bool ok = (net > 0) ? trade.Sell(vol, _Symbol, 0, 0, 0, CommentText + " WKND")
                                   : trade.Buy(vol, _Symbol, 0, 0, 0, CommentText + " WKND");
               Print("WEEKEND FREEZE: book ", DoubleToString(book,2), " too deep to realize -> net-hedged ",
                     DoubleToString(vol,2), (net>0?" SELL":" BUY"), ok?" OK":" FAILED");
               if(ok) g_wkndFrozen = true;
            }
            else { g_wkndFrozen = true; Print("WEEKEND FREEZE: net ~0, book already balanced"); }
         }
      }
   }
   // MONDAY release: close ONLY the WKND hedge legs, recovery/trail resume where they left off
   if(g_wkndFrozen && dt.day_of_week == 1 && dt.hour >= MondayReleaseHour)
   {
      for(int i = PositionsTotal()-1; i >= 0; i--)
      {
         ulong tk = PositionGetTicket(i);
         if(tk == 0 || !PositionSelectByTicket(tk)) continue;
         if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
         if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
         if(StringFind(PositionGetString(POSITION_COMMENT), "WKND") >= 0) trade.PositionClose(tk);
      }
      g_wkndFrozen = false;
      Print("WEEKEND RELEASE: hedge closed, normal operations resume");
   }
}

//--- [build N] ride-brake: is the ride side's NEWEST leg underwater? (= the ride stopped winning;
//    adding here is top-buying — the Aug-6 legs 3-6 anatomy)
bool RideSideDrowning(int dir)
{
   datetime newest=0; double pnl=0; bool found=false;
   for(int i=PositionsTotal()-1;i>=0;i--){ ulong t=PositionGetTicket(i); if(t==0||!PositionSelectByTicket(t))continue;
      if(PositionGetInteger(POSITION_MAGIC)!=MagicNumber||PositionGetString(POSITION_SYMBOL)!=_Symbol)continue;
      if((int)PositionGetInteger(POSITION_TYPE)!=dir)continue;
      datetime pt=(datetime)PositionGetInteger(POSITION_TIME);
      if(pt>=newest){ newest=pt; pnl=PositionGetDouble(POSITION_PROFIT)+PositionGetDouble(POSITION_SWAP); found=true; }
   }
   return(found && pnl<0);
}

//--- RECOVERY HEDGE: arm when deep underwater, ride the winning side, exit the whole book in profit.
//    Sets g_recovering. The catastrophe floor (in CheckBasketTrail) stays the backstop.
void CheckRecoveryHedge()
{
   if(!UseRecoveryHedge){ g_recovering=false; return; }
   double bal=ScaleBal();   // virtual balance (build M): hedge arms at the VIRTUAL account's -3%
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
      // [build P] STATE-RELEASE: track the ride's post-arm extreme; at the first bad-state
      // moment (pulled back off the extreme AND stale, or under water vs arm while pulled back)
      // realize the WHOLE book at market. Skipped once the recovery trail is armed (trail exits better).
      if(UseStateRelease)
      {
         int srSign=(g_recoverWinDir==POSITION_TYPE_BUY)?1:-1;
         double srPx=SymbolInfoDouble(_Symbol,SYMBOL_BID);
         if(g_srArmPrice<=0){ g_srArmPrice=srPx; g_srExt=srPx; g_srExtTime=TimeCurrent(); }  // restart-mid-rescue fallback
         if((srPx-g_srExt)*srSign>0){ g_srExt=srPx; g_srExtTime=TimeCurrent(); }
         double srAtr[1];
         if(!g_recoverArmed && CopyBuffer(hATR_D1_14,0,1,1,srAtr)==1 && srAtr[0]>0)
         {
            double srPull =(g_srExt-srPx)*srSign/srAtr[0];
            double srPos  =(srPx-g_srArmPrice)*srSign/srAtr[0];
            double srStale=(double)(TimeCurrent()-g_srExtTime)/3600.0;
            bool srBad=(srPull>=SR_PullATR && srStale>=SR_StaleHours) || (SR_UsePosLeg && srPos<=0.0 && srPull>=SR_PullATR);
            if(SR_MinAgeHours>0 && (double)(TimeCurrent()-g_srArmTime)/3600.0 < SR_MinAgeHours) srBad=false;
            if(srBad){ if(g_srBadSince==0) g_srBadSince=TimeCurrent(); } else g_srBadSince=0;
            if(srBad && SR_ConfirmMins>0 && (double)(TimeCurrent()-g_srBadSince)/60.0 < SR_ConfirmMins) srBad=false;
            if(srBad && (StateReleaseMinMark>=0.0 || bookFloat>=StateReleaseMinMark))
            {
               Print("STATE RELEASE: book=",DoubleToString(bookFloat,2)," pull=",DoubleToString(srPull,2),
                     " stale=",DoubleToString(srStale,1),"h pos=",DoubleToString(srPos,2),
                     " (arm ",DoubleToString(g_srArmPrice,2)," ext ",DoubleToString(g_srExt,2),")");
               CloseAll(); g_recovering=false; g_recoverWinDir=-1; g_recoverArmed=false; g_recoverPeak=0; g_recoverDeepest=0; peakBasketFloat=0;
               g_srArmPrice=0; g_srExt=0; g_srExtTime=0; g_srBadSince=0;
               return;
            }
         }
      }
      if(UseRecoveryTrail)
      {
         // [build N] peak-banking: arm the trail once the book claws back RecoveryPeakBankPct% of the
         // deepest->target distance (default 0 = arm only at +target, byte-identical to build M).
         double armLvl=effTarget;
         if(RecoveryPeakBankPct>0 && g_recoverDeepest<0)
            armLvl=MathMin(effTarget, g_recoverDeepest + (RecoveryPeakBankPct/100.0)*(effTarget-g_recoverDeepest));
         if(bookFloat>=armLvl){ if(!g_recoverArmed) g_recoverArmed=true; if(bookFloat>g_recoverPeak) g_recoverPeak=bookFloat; }
         if(g_recoverArmed){
            double exitLvl=MathMax(armLvl, g_recoverPeak-giveback);
            if(bookFloat<=exitLvl && bookFloat<g_recoverPeak){
               Print("RECOVERY TRAIL exit: book=",DoubleToString(bookFloat,2)," peak ",DoubleToString(g_recoverPeak,2)," tgt ",DoubleToString(effTarget,0)," arm ",DoubleToString(armLvl,0));
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
   // [build N] ATR-denominated floor on the trigger: never arm inside ordinary noise. The $-trigger is
   // static while gold's ATR moves; post-melt-up 3%-bal = ~0.3 daily-ATR -> armed on noise -> top-bought.
   if(HedgeTriggerATRMult>0 && trigger>0){
      double atrb[1];
      if(CopyBuffer(hATRfast,0,1,1,atrb)==1 && atrb[0]>0){
         double sideLots=MathMax(SideLots(POSITION_TYPE_BUY),SideLots(POSITION_TYPE_SELL));
         double contract=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_CONTRACT_SIZE);
         double atrUSD=HedgeTriggerATRMult*atrb[0]*contract*sideLots;
         if(atrUSD>trigger) trigger=atrUSD;
      }
   }
   if(trigger>0 && bookFloat<=-trigger)
   {
      double bp=SideProfit(POSITION_TYPE_BUY), sp=SideProfit(POSITION_TYPE_SELL);
      g_recoverWinDir = (bp>=sp) ? POSITION_TYPE_BUY : POSITION_TYPE_SELL;  // ride the LESS-negative (trend) side
      g_recovering=true; g_recoverArmed=false; g_recoverPeak=0; g_recoverDeepest=bookFloat;
      g_srArmPrice=SymbolInfoDouble(_Symbol,SYMBOL_BID); g_srExt=g_srArmPrice; g_srExtTime=TimeCurrent();   // state-release (build P)
      g_srArmTime=TimeCurrent(); g_srBadSince=0;
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
      if(tot <= -floorPct/100.0*ScaleBal()){   // virtual balance (build M)
         Print("BASKET STOP fired float=",DoubleToString(tot,2)," floorPct=",DoubleToString(floorPct,1)); CloseAll(); peakBasketFloat=0;
         g_recovering=false; g_recoverWinDir=-1; g_recoverArmed=false; g_recoverPeak=0; g_recoverDeepest=0; return;
      }
   }
   // ---- STAGED FLOOR (build L, gold SF12 port): book deep -> cut the single WORST leg
   // BEFORE the -20% floor realizes the whole ladder (the $10k Apr-14 -$3,516 anatomy).
   // Runs during recovery too (lightening the loser complements the hedge). Once per bar.
   if(UseStagedFloor && iTime(_Symbol,PERIOD_CURRENT,0)!=g_lastStageBar &&
      tot <= -StagedFloorPct/100.0*ScaleBal()){   // virtual balance (build M)
      ulong worst=0; double wp=0;
      for(int si=PositionsTotal()-1; si>=0; si--){
         ulong tk=PositionGetTicket(si);
         if(tk==0 || !PositionSelectByTicket(tk)) continue;
         if(PositionGetInteger(POSITION_MAGIC)!=MagicNumber) continue;
         if(PositionGetString(POSITION_SYMBOL)!=_Symbol) continue;
         double p=PositionGetDouble(POSITION_PROFIT)+PositionGetDouble(POSITION_SWAP);
         if(worst==0 || p<wp){ worst=tk; wp=p; }
      }
      if(worst>0){
         if(trade.PositionClose(worst))
            Print("STAGED FLOOR: closed worst leg #",worst," pnl=",DoubleToString(wp,2),
                  " (book was ",DoubleToString(tot,2),")");
         else Print("STAGED FLOOR: close failed #",worst," err=",GetLastError());
         g_lastStageBar=iTime(_Symbol,PERIOD_CURRENT,0);
         return;   // re-evaluate the lightened book next tick
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

   WeekendCheck();                // Friday flatten/freeze + Monday release (state-aware, spec 08-11)
   if(g_wkndFrozen) return;       // frozen book crosses the weekend untouched: no trail/harvest/rescue/entries

   CheckRecoveryHedge();          // arm/exit the deep-basket rescue -> sets g_recovering
   CheckBasketTrail(g_recovering);// catastrophe floor always; basket-trail skipped while rescuing

   if(!g_recovering && UseSessionFilter){
      int hr=BarHour(TimeCurrent());
      bool inS=(SessionStartHour<SessionEndHour)?(hr>=SessionStartHour&&hr<SessionEndHour):(hr>=SessionStartHour||hr<SessionEndHour);
      if(!inS) return;
   }
   if(tradesThisBar>=tradesperbar) return;
   if(WkndBlockNew()) return;     // Friday pre-close: manage what's open, start nothing new

   int sig=GoldminerSignal();
   if(sig==0) return;

   // RECOVERY: ride ONLY the winning (trend) side, bypassing D1/session/imbalance/MaxSameTrades
   if(g_recovering){
      int winSig=(g_recoverWinDir==POSITION_TYPE_BUY)?1:-1;
      bool blockAdd = RecoveryRespectBreakFilters &&
                      ( (UseVolRegimeFilter && IsVolRegimeHot()) || (UseOverextFilter && IsOverextended()) );
      // [build N] ride-brake: no adds while the ride's newest leg is red (the ride stopped winning);
      // + optional hard cap on ride legs (the ride path ignores MaxSameTrades by design).
      if(UseRideBrake && RideSideDrowning(g_recoverWinDir)) blockAdd=true;
      if(MaxRideLegs>0 && CountOpen(g_recoverWinDir)>=MaxRideLegs) blockAdd=true;
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
