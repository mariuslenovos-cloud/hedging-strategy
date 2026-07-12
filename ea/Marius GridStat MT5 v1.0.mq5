//+------------------------------------------------------------------+
//|  Marius GridStat MT5 v1.0 -- STAGE 1: SHADOW LOGGER               |
//|  Triple-barrier signal-edge measurement on MT5 (any instrument)   |
//|                                                                   |
//|  Port of the MT4 GridStat shadow engine, with the Goldminer       |
//|  signal EMBEDDED + IMPROVED:                                       |
//|   - DECOUPLED params: period / upper / lower / vol-multipliers     |
//|     are separate inputs (MT4 RISK locked them together)           |
//|   - INSTRUMENTED: logs big_move flag + wpr value per signal so we  |
//|     can test runner/dive hypotheses via feature-importance         |
//|                                                                   |
//|  Stage 1 = SHADOW ONLY (no trades). Use it to measure whether an  |
//|  instrument (oil, etc.) has edge BEFORE building trade execution. |
//|  Stage 2 (later) = CTrade grid/floor/risk-norm for proven symbols.|
//+------------------------------------------------------------------+
#property copyright "Marius"
#property version   "1.00"

#define EA_BUILD_VERSION "MT5-2026-07-12-S20"
#define MAX_PENDING 5000

#include <Trade/Trade.mqh>
CTrade trade;   // Stage 2 execution

//--- Mode
input bool   StatsCollectionMode = false;   // SHADOW: log signals + triple-barrier outcomes (Stage 1 is shadow-only)
input string StatsCSVFile        = "gridstat_setups_gold.csv";  // per-symbol: e.g. gridstat_setups_oil.csv

//--- Triple-barrier
input double BarrierATRMultiplier = 0.8;   // symmetric barrier ATR(D1) mult (used when the asym overrides below = 0)
input double BarrierATRUpper      = 0;     // 0 = symmetric; else UPPER (target) barrier ATR mult -- set > lower to let winners run
input double BarrierATRLower      = 0;     // 0 = symmetric; else LOWER (stop)  barrier ATR mult -- R is measured in units of this (the risk)
input int    TimeBarrierBars      = 288;   // time barrier (M5 bars; 288 = 24h)

//--- Goldminer signal (DECOUPLED -- 0 = auto-derive from grisk like the MT4 original)
input int    grisk        = 4;     // MT5-gold optimum (shadow-swept + trade-validated: +52% net vs 7 at same ~20% equity DD). legacy RISK knob; drives auto bands when overrides=0
input int    GM_Period    = 0;     // 0 = auto (grisk*2+3); else fixed WPR period
input double GM_UpperBand = 0;     // 0 = auto (grisk+67); overbought threshold
input double GM_LowerBand = 0;     // 0 = auto (33-grisk); oversold threshold
input double GM_GapMult   = 2.0;   // gap detector: jump >= this * avgRange -> period 3
input int    GM_GapMode   = 0;     // 0 = original |Open-PrevClose| (MT4-equiv, ~dead on continuous CFDs); 1 = |Close-PrevClose| close-to-close jump (activates the runner detector on gold/oil)
input double GM_FastMult  = 4.6;   // fast-move detector: |Close[i+3]-Close[i]| >= this * avgRange -> period 4
input int    goldminershift = 1;   // evaluate signal on this shift (1 = last closed bar)

//--- Feature-importance instrumentation (UNIVERSAL -- improves gold/silver selection too, not just oil)
//    Logs the features the coarse DIR|SESSION|ATR fingerprint throws away, so feature-importance
//    can find sharper, higher-P&L setup cuts per symbol (run on gold/silver/oil shadow alike).
input int    RunupBars = 12;        // dip-vs-continuation: directional price move over last N bars before entry (/ATR)

//--- Entry filters (so shadow measures only signals that WOULD be tradeable)
input double MA_Angle_Threshold = 20.0;
input int    MA_Period          = 20;
input int    ADX_Period         = 14;
input double ADX_Threshold      = 25.0;
input bool   UseDailyTrendFilter = true;
input int    DailyMA_Period      = 50;
input bool   UseSessionFilter    = true;
input int    SessionStartHour    = 9;
input int    SessionEndHour      = 23;

//=== STAGE 2 -- TRADE EXECUTION (only when StatsCollectionMode = false) ===
//--- Entry win-rate gate (mirrors locked GOLD: reads StatsCSVFile = the shadow DB)
input bool   StatsFilterEnabled    = true;
input double MinWinRate            = 0.55;
input int    MinSamples            = 10;
//--- SIGNAL DIAGNOSTIC LOG (default OFF). Logs EVERY Goldminer fire + each gate's value/pass-fail +
//    the final TRADE/SKIP decision -> gridstat_signals_<symbol>.csv (Common\Files, per-symbol = no clobber).
//    Zero effect on trade behaviour; turn ON to see exactly why a signal was/wasn't taken (e.g. MT4 vs MT5 divergence).
input bool   UseSignalLog          = false;
//--- Overextension regime filter (Ch.17 structural-break; session 19o). Skips entries when price is
//    stretched far from the D1 mean = the overextension regime that breeds deep-DD/blow-up baskets.
//    Python MAE study: gold corr(dist,MAE)=-0.61, silver -0.38 (both SEPARATE); oil -0.20 (NO separation
//    -> leave OFF for oil). DEFAULT OFF = locked configs byte-identical. Trade-mode only (shadow DB untouched).
//    Validate every-tick: does it lower equity DD without killing net? Per-symbol threshold (gold ~4.5, silver ~8).
input bool   UseOverextensionFilter = false;
input double OverextATRMult         = 4.5;   // skip if |close - D1EMA(DailyMA_Period)| / ATR(D1,60) >= this. 0 = off.
//--- Per-setup bet-sizing (AFML): size ∝ edge. DEFAULT OFF = flat lots (unchanged). When ON, reads
//    SizingCSVFile (from gridstat_rigor.py): mult>0 sizes the bet (×base lot), mult==0 / unknown = SKIP.
//    Concentrates capital on high-edge setups (oil: 2× the star BUY|HR_OVL|EXP), zeros negatives.
input bool   UseSizingTable        = false;
input string SizingCSVFile         = "gridstat_sizing_oil.csv";
input double MaxSizeMult           = 2.0;
//--- Lot sizing
input double LotSize               = 0.02;
input bool   UseCompounding        = true;
input double CompoundingBase       = 3000.0;
//--- Grid-ladder shaping (Session 23, ported from MT4 build S): cap the fib multiplier of grid legs.
//    The fib ladder 1,1,2,3,5 is a martingale putting the BIGGEST lots at the WORST prices -- the deep
//    legs carried 40%+ of every observed floor loss (MT4 A/B: MaxFibMult=1 -> zero basket stops, net +86%,
//    PF 1.64->4.66, DD 21.6->11.7%). 0 = original fib (locked configs byte-identical); 1 = FLAT legs
//    (all = base lot; float at the adverse extreme shrinks ~60%; escapes need a slightly deeper retrace);
//    2 = capped ladder 1,1,2,2,2. Validate every-tick per symbol before re-locking.
input int    MaxFibMult            = 0;
input bool   UseRiskNormalizedLots = false;   // OFF for gold; ON for volatile symbols (silver/oil)
input double RiskPctPerTrade       = 3.0;
input double MaxRiskPctSkip        = 8.0;
//--- Hedged grid
input bool   UseATRSpacing         = true;
input double ATRSpacingMultiplier  = 0.5;
input int    GridSpacingMinPoints  = 300;
input int    GridSpacingMaxPoints  = 2000;
input int    MaxGridLevels         = 6;
input int    MaxConcurrentBaskets  = 1;    // 1 = one cluster at a time (gold/silver: UNCHANGED path). >1 = allow N independent baskets so a stuck basket can't starve 200+ signals (trending indices/oil). No time/hard stops.
input bool   UseHedge              = true;
input int    HedgeBreakEvenPoints  = 15000;
input double HedgeRatio            = 1.0;
input double ProfitTargetUSD       = 100.0;   // basket recovery escape + single-position $ cap
input int    MaxDaysOpen           = 30;
//--- Single-position trailing exit (OFF for gold; only used when nLevels<2)
input bool   UseTrailingExit       = false;
input double TrailActivateR        = 1.0;
input double TrailDistanceR        = 0.6;
//--- Lock-and-trail exit (DEFAULT OFF = locked configs unchanged). When ON, a basket that
//    reaches ProfitTargetUSD does NOT close immediately: it LOCKS the target as a guaranteed
//    floor and TRAILS the excess (closes when float retraces LockTrailGiveback $ from peak,
//    but never banks below the locked target). Captures trend continuation past the fixed $
//    target (the chart problem) without the session-16 trailing failure modes (can't reverse
//    into a loss; pair with MaxConcurrentBaskets>1 so holding a runner doesn't starve entries).
input bool   UseLockTrailExit      = false;
input double LockTrailGivebackPct  = 15.0;   // % retrace from PEAK that liquidates (once +ProfitTargetUSD armed the ride); break-even is locked so a triggered winner can't become a loss
//--- Per-entry hard SL toggle. true = SL at the lower barrier (gold-inherited triple-barrier, current).
//    false = NO per-entry stop; rely on grid recovery + the catastrophe basket floor (matches the
//    no-hard-stop hedging philosophy). On pullback-heavy BUY-tilted symbols (oil) the −1R entry stop
//    fires right before the grid would recover; removing it lets those losers recover. TEST per symbol.
input bool   UseEntrySL            = true;
//--- Basket catastrophic floor (the grid has no inherent stop)
input bool   UseBasketStop         = true;
input double BasketMaxLossPct      = 20.0;
//--- STAGED FLOOR (Session 24; user-designed LIVE 2026-07-09, ported from MT4 build T):
//    when a basket floats <= -StagedFloorPct% of balance, close its single WORST leg --
//    lightens the basket (avg entry improves, escape pulls closer, floor pushes away)
//    for the price of one realized leg. Live episode: -$28 vs a near-certain -$388.
//    MT4 156-trade-panel sweep: plateau 12-14, RF 3.74 -> 4.99 at 12. Must be
//    < BasketMaxLossPct or the catastrophic floor fires first. Default OFF = base unchanged.
//    Threshold is PER-SYMBOL ([[exit-rules-per-symbol]]): gold 12; silver/oil need own sweeps.
input bool   UseStagedFloor        = false;    // cut the worst leg early (default OFF)
input double StagedFloorPct        = 12.0;     // ...at basket float <= -this% of balance
//--- PORTFOLIO STAGED FLOOR (2026-07-12): the per-basket staged floor is provably INERT on
//    multi-basket streams whose pain is N shallow ONE-leg baskets drowning together (oil A/B:
//    byte-identical, zero fires -- every deep event was the PORTFOLIO floor, no basket near -8%).
//    This variant = the MT4 original's book-level semantics: TOTAL float <= -this% of balance ->
//    close the single WORST leg anywhere in the book. Multi-basket path only (conc=1 streams
//    use the per-basket lever -- identical there by construction). Default OFF.
input bool   UseStagedFloorPortfolio = false;  // book-level staged cut (oil/silver, conc>1)
input double StagedFloorPortfolioPct = 8.0;    // ...at TOTAL float <= -this% of balance (< BasketMaxLossPct)
//--- equity-DD reducer (default OFF = locked config unchanged): close a LOSING basket when D1 trend flips AGAINST it
//    (the regime change that turns a recoverable dip into a one-way bleed) -> caps the tail before the -20% floor,
//    lowering intraday equity DD so the proven engine can be sized bigger. Validate every-tick vs the $7,908 baseline.
input bool   UseRegimeBasketExit   = false;
//--- Break-even SL + grid guards
input bool   UseBreakEvenSL        = true;
input double BreakEvenTriggerR     = 0.7;
input double MaxBasketLotsTotal     = 0.30;
input bool   SkipGridAfterSL       = true;
input int    SkipGridAfterSLHours  = 4;
//--- Misc
input string CommentText           = "GridStat";
input int    MagicSeed             = 0;       // 0 = auto-hash from symbol+period (matches MT4 scheme)

//--- Globals
double   point;
datetime lastBarTime = 0;
int      hMA, hADX, hMA_D1, hATR_cur, hATR_avg, hATR_D1, hATR_D1_60;

// Pending signal tracking (triple-barrier)
string   pSetup[MAX_PENDING];
int      pDir[MAX_PENDING];
datetime pEntryTime[MAX_PENDING];
double   pEntryPrice[MAX_PENDING];
double   pUpperBarrier[MAX_PENDING];
double   pLowerBarrier[MAX_PENDING];
datetime pTimeBarrier[MAX_PENDING];
double   pAtrAtEntry[MAX_PENDING];
double   pPeakR[MAX_PENDING];
bool     pBigMove[MAX_PENDING];    // did Goldminer's big-move detector fire at entry?
double   pWpr[MAX_PENDING];        // the %R-derived value at entry (extremity)
double   pAdx[MAX_PENDING];        // ADX magnitude at entry (trend strength)
double   pMaAngle[MAX_PENDING];    // MA-angle steepness, directional (+ = MA sloping with the trade)
double   pRunup[MAX_PENDING];      // dip-vs-continuation: directional move into entry /ATR (+cont, -dip)
int      pPeriodUsed[MAX_PENDING]; // adaptive WPR period actually used (3/4 = accelerated, else base)
int      pBarsInBand[MAX_PENDING]; // how many bars the swing took (opposite-extreme breakout -> now)
int      pCount = 0;

double   g_shadowTotalR = 0.0;

// Stage 2 (trade) globals
long     MagicNumber = 0;
string   g_clusterSetup = "";
double   g_clusterSizeMult = 1.0;   // per-setup size multiplier for the active basket (sizing table)
double   g_peakBasketFloat = 0.0;
bool     g_lockArmed = false;   // lock-trail: basket has reached +ProfitTargetUSD and is now riding (Conc<=1 only)
datetime g_lastStageBar = 0;    // staged floor: at most one worst-leg cut per bar (across all baskets)

//+------------------------------------------------------------------+
int OnInit()
{
   point = (_Digits == 3 || _Digits == 5) ? _Point * 10 : _Point;
   hMA      = iMA(_Symbol, PERIOD_CURRENT, MA_Period, 0, MODE_EMA, PRICE_CLOSE);
   hADX     = iADX(_Symbol, PERIOD_CURRENT, ADX_Period);
   hMA_D1   = iMA(_Symbol, PERIOD_D1, DailyMA_Period, 0, MODE_EMA, PRICE_CLOSE);
   hATR_cur = iATR(_Symbol, PERIOD_CURRENT, 20);
   hATR_avg = iATR(_Symbol, PERIOD_CURRENT, 100);
   hATR_D1  = iATR(_Symbol, PERIOD_D1, 14);
   hATR_D1_60 = iATR(_Symbol, PERIOD_D1, 60);   // overextension-filter normalizer (Python study used ATR(D1,60))
   if(hMA==INVALID_HANDLE || hADX==INVALID_HANDLE || hMA_D1==INVALID_HANDLE ||
      hATR_cur==INVALID_HANDLE || hATR_avg==INVALID_HANDLE || hATR_D1==INVALID_HANDLE || hATR_D1_60==INVALID_HANDLE)
   {
      Print("Handle creation failed"); return(INIT_FAILED);
   }
   Print("============================================================");
   Print("MARIUS GRIDSTAT MT5 ", EA_BUILD_VERSION, " | ", _Symbol,
         " | Mode: ", (StatsCollectionMode ? "SHADOW (no trades)" : "TRADE (not in Stage 1)"));
   Print("============================================================");
   if(StatsCollectionMode && !MQLInfoInteger(MQL_OPTIMIZATION))   // skip CSV during optimization (grisk sweep uses OnTester only)
   {
      int fh = FileOpen(StatsCSVFile, FILE_WRITE|FILE_CSV|FILE_COMMON|FILE_ANSI, ',');
      if(fh != INVALID_HANDLE)
      {
         FileWrite(fh, "setup_key","entry_time","entry_price","direction",
                   "upper_barrier","lower_barrier","time_barrier","atr_at_entry",
                   "barrier_hit","r_multiple","outcome_time","mfe_r","big_move","wpr",
                   "adx","ma_angle","runup","period_used","bars_in_band");
         FileClose(fh);
      }
   }
   if(!StatsCollectionMode)
   {
      MagicNumber = (MagicSeed != 0) ? MagicSeed : GenerateMagic("GridStat", _Symbol, (int)Period());
      trade.SetExpertMagicNumber(MagicNumber);
      trade.SetDeviationInPoints(10);
      trade.SetTypeFillingBySymbol(_Symbol);
      Print("TRADE mode | Magic=", MagicNumber);
      Print("CONFIG | StatsFilterEnabled=", StatsFilterEnabled,
            " UseSizingTable=", UseSizingTable, " SizingCSVFile=", SizingCSVFile,
            " MaxConcurrentBaskets=", MaxConcurrentBaskets,
            " UseEntrySL=", UseEntrySL, " UseRiskNormalizedLots=", UseRiskNormalizedLots);
      Print("CONFIG | UseOverextensionFilter=", UseOverextensionFilter,
            " OverextATRMult=", DoubleToString(OverextATRMult,2));
      Print("CONFIG | MaxFibMult=", MaxFibMult, " (0=fib ladder, 1=flat legs, 2=capped)");
      Print("CONFIG | UseStagedFloor=", UseStagedFloor,
            " StagedFloorPct=", DoubleToString(StagedFloorPct,1),
            "% (worst-leg cut; floor=", DoubleToString(BasketMaxLossPct,1), "%)");
      Print("CONFIG | UseStagedFloorPortfolio=", UseStagedFloorPortfolio,
            " StagedFloorPortfolioPct=", DoubleToString(StagedFloorPortfolioPct,1),
            "% (book-level worst-leg cut, conc>1 only)");
      {
         int _szh = FileOpen(SizingCSVFile, FILE_READ|FILE_CSV|FILE_COMMON|FILE_ANSI, ',');
         Print("CONFIG | sizing file '", SizingCSVFile, "' open: ",
               (_szh!=INVALID_HANDLE ? "OK (found)" : "FAILED / NOT FOUND -> flat 1.0x"));
         if(_szh!=INVALID_HANDLE) FileClose(_szh);
      }
      int fh = FileOpen("gridstat_trades_mt5.csv", FILE_WRITE|FILE_CSV|FILE_COMMON|FILE_ANSI, ',');
      if(fh != INVALID_HANDLE)
      { FileWrite(fh,"time","type","volume","price","profit","reason","comment"); FileClose(fh); }
      // signal diagnostic log: per-symbol, created once (NOT truncated on reload -> accumulates)
      if(UseSignalLog && !FileIsExist(SigFile(), FILE_COMMON))
      {
         int sfh = FileOpen(SigFile(), FILE_WRITE|FILE_CSV|FILE_COMMON|FILE_ANSI, ',');
         if(sfh != INVALID_HANDLE)
         { FileWrite(sfh,"time","dir","setup_key","wpr","adx","ma_angle","d1_bull","winrate","n","decision"); FileClose(sfh); }
      }
      Print("CONFIG | UseSignalLog=", UseSignalLog, (UseSignalLog ? " -> "+SigFile() : ""));
   }
   return(INIT_SUCCEEDED);
}
string SigFile() { return "gridstat_signals_" + _Symbol + ".csv"; }
void LogSignal(int dir, string key, double wpr, double adx, double ang, bool bull, double wr, int ns, string decision)
{
   if(!UseSignalLog) return;
   int h = FileOpen(SigFile(), FILE_READ|FILE_WRITE|FILE_CSV|FILE_COMMON|FILE_ANSI, ',');
   if(h == INVALID_HANDLE) return;
   FileSeek(h, 0, SEEK_END);
   FileWrite(h, TimeToString(TimeCurrent(), TIME_DATE|TIME_MINUTES),
             (dir==ORDER_TYPE_BUY ? "BUY" : "SELL"), key,
             DoubleToString(wpr,1), DoubleToString(adx,1), DoubleToString(ang,1),
             (bull ? "1" : "0"), DoubleToString(wr,2), IntegerToString(ns), decision);
   FileClose(h);
}

int GenerateMagic(string eaName, string sym, int tf)
{
   int hash = 0;
   string s = eaName + sym + IntegerToString(tf);
   for(int i=0; i<StringLen(s); i++) hash += StringGetCharacter(s,i) * (i+1);
   return hash % 100000 + 50000;
}

double OnTester() { return(StatsCollectionMode ? g_shadowTotalR : 0); }

// Diagnostic: log every closing deal with its close reason + net profit.
string DealReasonStr(long r)
{
   switch((int)r)
   {
      case DEAL_REASON_CLIENT:   return "CLIENT";
      case DEAL_REASON_EXPERT:   return "EXPERT";   // EA close (basket recovery / basket-stop / profit target)
      case DEAL_REASON_SL:       return "SL";
      case DEAL_REASON_TP:       return "TP";
      case DEAL_REASON_SO:       return "SO";       // margin stop-out
      default:                   return "OTHER";
   }
}
void OnTradeTransaction(const MqlTradeTransaction &trans, const MqlTradeRequest &req, const MqlTradeResult &res)
{
   if(StatsCollectionMode) return;
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD) return;
   ulong deal = trans.deal;
   if(!HistoryDealSelect(deal)) return;
   if(HistoryDealGetInteger(deal, DEAL_MAGIC) != MagicNumber) return;
   if(HistoryDealGetInteger(deal, DEAL_ENTRY) != DEAL_ENTRY_OUT) return;
   double profit = HistoryDealGetDouble(deal, DEAL_PROFIT)
                 + HistoryDealGetDouble(deal, DEAL_SWAP)
                 + HistoryDealGetDouble(deal, DEAL_COMMISSION);
   long dt = (HistoryDealGetInteger(deal, DEAL_TYPE) == DEAL_TYPE_BUY) ? 1 : 0; // closing deal type
   int fh = FileOpen("gridstat_trades_mt5.csv", FILE_READ|FILE_WRITE|FILE_CSV|FILE_COMMON|FILE_ANSI, ',');
   if(fh == INVALID_HANDLE) return;
   FileSeek(fh, 0, SEEK_END);
   FileWrite(fh,
      TimeToString((datetime)HistoryDealGetInteger(deal, DEAL_TIME), TIME_DATE|TIME_MINUTES),
      (dt==1 ? "close_buy" : "close_sell"),
      DoubleToString(HistoryDealGetDouble(deal, DEAL_VOLUME), 2),
      DoubleToString(HistoryDealGetDouble(deal, DEAL_PRICE), _Digits),
      DoubleToString(profit, 2),
      DealReasonStr(HistoryDealGetInteger(deal, DEAL_REASON)),
      HistoryDealGetString(deal, DEAL_COMMENT));
   FileClose(fh);
}

//+------------------------------------------------------------------+
double ReadBuf(int handle, int buf, int shift)
{
   double b[];
   if(CopyBuffer(handle, buf, shift, 1, b) <= 0) return(0);
   return(b[0]);
}

int BarHour(datetime t)
{
   MqlDateTime dt; TimeToStruct(t, dt); return(dt.hour);
}

//+------------------------------------------------------------------+
//| Goldminer signal (embedded, decoupled, instrumented)             |
//| Returns ORDER_TYPE_BUY / ORDER_TYPE_SELL / -1; sets bigMove, wpr  |
//+------------------------------------------------------------------+
double WprValue(int period, int shift)
{
   int hhs = iHighest(_Symbol, PERIOD_CURRENT, MODE_HIGH, period, shift);
   int lls = iLowest(_Symbol, PERIOD_CURRENT, MODE_LOW, period, shift);
   if(hhs < 0 || lls < 0) return(50);
   double hh = iHigh(_Symbol, PERIOD_CURRENT, hhs);
   double ll = iLow(_Symbol, PERIOD_CURRENT, lls);
   double cl = iClose(_Symbol, PERIOD_CURRENT, shift);
   double wpr = (hh - ll != 0) ? -100.0 * (hh - cl) / (hh - ll) : 0;
   return(100.0 - MathAbs(wpr));   // 0=oversold ... 100=overbought  (= 100-|WPR|)
}

// computes the adaptive value at bar j, sets bigMove + the period actually used for that bar
double GMValueAt(int j, bool &bigMove, int &periodUsed)
{
   double avgRange = 0;
   for(int k=j; k<=j+9; k++) avgRange += MathAbs(iHigh(_Symbol,PERIOD_CURRENT,k) - iLow(_Symbol,PERIOD_CURRENT,k));
   avgRange /= 10.0;
   bool gap=false, fast=false;
   for(int k=j; k<j+9 && !gap; k++)
   {
      double jump = (GM_GapMode==1) ? MathAbs(iClose(_Symbol,PERIOD_CURRENT,k) - iClose(_Symbol,PERIOD_CURRENT,k+1))
                                    : MathAbs(iOpen(_Symbol,PERIOD_CURRENT,k)  - iClose(_Symbol,PERIOD_CURRENT,k+1));
      if(jump >= GM_GapMult*avgRange) gap=true;
   }
   for(int k=j; k<j+6 && !fast; k++)
      if(MathAbs(iClose(_Symbol,PERIOD_CURRENT,k+3) - iClose(_Symbol,PERIOD_CURRENT,k)) >= GM_FastMult*avgRange) fast=true;
   int period = (GM_Period > 0) ? GM_Period : (grisk*2 + 3);
   if(gap)  period = 3;
   if(fast) period = 4;
   bigMove = (gap || fast);
   periodUsed = period;
   return(WprValue(period, j));
}

// signal at goldminershift; returns dir, sets bigMove + wpr + periodUsed + barsInBand (traverse length)
int GetGoldminerSignal(bool &bigMove, double &wpr, int &periodUsed, int &barsInBand)
{
   double upper = (GM_UpperBand > 0) ? GM_UpperBand : (grisk + 67);
   double lower = (GM_LowerBand > 0) ? GM_LowerBand : (33 - grisk);
   int LB = 40;                         // lookback for the band-cross scan
   double val[];
   ArrayResize(val, LB);
   bool bm0=false; int pu0=0;
   for(int k=0; k<LB; k++)
   {
      bool bm=false; int pu=0;
      val[k] = GMValueAt(goldminershift + k, bm, pu);
      if(k==0) { bm0 = bm; pu0 = pu; }
   }
   bigMove = bm0;
   wpr = val[0];
   periodUsed = pu0;
   barsInBand = 0;
   int dir = -1;
   int li = 1;
   if(val[0] > upper)
   {
      while(li<LB-1 && val[li]>=lower && val[li]<=upper) li++;
      if(val[li] < lower) dir = (int)ORDER_TYPE_BUY;     // surged oversold->overbought = BUY
   }
   else if(val[0] < lower)
   {
      while(li<LB-1 && val[li]>=lower && val[li]<=upper) li++;
      if(val[li] > upper) dir = (int)ORDER_TYPE_SELL;    // plunged overbought->oversold = SELL
   }
   barsInBand = li;   // bars from the opposite-extreme breakout to now = how long the swing took
   return(dir);
}

//+------------------------------------------------------------------+
bool IsDailyTrendBullish()
{
   return(ReadBuf(hMA_D1,0,0) > ReadBuf(hMA_D1,0,1));
}
double GetMAAngle()
{
   double m0 = ReadBuf(hMA,0,0), m1 = ReadBuf(hMA,0,5);
   double slope = (m0 - m1) / (5 * point);
   return(MathArctan(slope) * 180.0 / M_PI);
}
bool IsTrendStrong()
{
   double adx = ReadBuf(hADX,0,0);
   return(adx > ADX_Threshold && MathAbs(GetMAAngle()) > MA_Angle_Threshold);
}

// Ch.17 overextension regime: |close - D1EMA(DailyMA_Period)| / ATR(D1,60). High = price stretched
// far from the daily mean = the regime that breeds deep-DD/blow-up baskets on the metals (session 19o).
// Returns true when the current bar is overextended beyond OverextATRMult (trade-mode entry skip).
bool IsOverextended()
{
   if(!UseOverextensionFilter || OverextATRMult <= 0) return(false);
   double d1ma  = ReadBuf(hMA_D1,0,0);            // D1 EMA(DailyMA_Period)
   double atr60 = ReadBuf(hATR_D1_60,0,1);        // ATR(D1,60), last closed D1 bar
   if(atr60 <= 0) return(false);
   double dist = MathAbs(iClose(_Symbol,PERIOD_CURRENT,goldminershift) - d1ma) / atr60;
   return(dist >= OverextATRMult);
}

// dip-vs-continuation feature: directional price move over the last RunupBars before entry, in ATR units.
// + = price moved WITH the signal before entry (continuation); - = price moved against it (dip-buy / pop-sell).
double RunupBefore(int dir)
{
   double atr = ReadBuf(hATR_cur,0,1);
   if(atr <= 0) return(0);
   double now  = iClose(_Symbol, PERIOD_CURRENT, goldminershift);
   double then = iClose(_Symbol, PERIOD_CURRENT, goldminershift + RunupBars);
   double mv = now - then;
   if(dir == (int)ORDER_TYPE_SELL) mv = -mv;
   return(mv / atr);
}

string ClassifySetup(int dir)
{
   string d = (dir == ORDER_TYPE_BUY) ? "BUY" : "SELL";
   int hr = BarHour(TimeCurrent());
   string hrB = (hr<9) ? "HR_ASIA" : (hr<14) ? "HR_LDN" : (hr<18) ? "HR_OVL" : "HR_NY";
   double an = ReadBuf(hATR_cur,0,1), aa = ReadBuf(hATR_avg,0,1);
   string atrB;
   if(aa==0) atrB="ATR_NA";
   else if(an > aa*1.3) atrB="ATR_EXP";
   else if(an < aa*0.7) atrB="ATR_COMP";
   else atrB="ATR_NORM";
   return(d + "|" + hrB + "|" + atrB);
}

//+------------------------------------------------------------------+
void AddPendingSignal(string key, int dir, bool bigMove, double wpr,
                      double adx, double maAngle, double runup, int periodUsed, int barsInBand)
{
   if(pCount >= MAX_PENDING) return;
   double atrD1 = ReadBuf(hATR_D1,0,1);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double px = (dir == ORDER_TYPE_BUY) ? ask : bid;
   double um = (BarrierATRUpper > 0) ? BarrierATRUpper : BarrierATRMultiplier;  // target side
   double lm = (BarrierATRLower > 0) ? BarrierATRLower : BarrierATRMultiplier;  // stop side
   double bdU = atrD1 * um;
   double bdL = atrD1 * lm;
   pSetup[pCount]=key; pDir[pCount]=dir; pEntryTime[pCount]=TimeCurrent();
   pEntryPrice[pCount]=px; pUpperBarrier[pCount]=px+bdU; pLowerBarrier[pCount]=px-bdL;
   pTimeBarrier[pCount]=TimeCurrent() + TimeBarrierBars*PeriodSeconds(PERIOD_CURRENT);
   pAtrAtEntry[pCount]=atrD1; pPeakR[pCount]=0; pBigMove[pCount]=bigMove; pWpr[pCount]=wpr;
   pAdx[pCount]=adx; pMaAngle[pCount]=maAngle; pRunup[pCount]=runup; pPeriodUsed[pCount]=periodUsed;
   pBarsInBand[pCount]=barsInBand;
   pCount++;
}

void RemovePendingAt(int idx)
{
   for(int i=idx; i<pCount-1; i++)
   {
      pSetup[i]=pSetup[i+1]; pDir[i]=pDir[i+1]; pEntryTime[i]=pEntryTime[i+1];
      pEntryPrice[i]=pEntryPrice[i+1]; pUpperBarrier[i]=pUpperBarrier[i+1];
      pLowerBarrier[i]=pLowerBarrier[i+1]; pTimeBarrier[i]=pTimeBarrier[i+1];
      pAtrAtEntry[i]=pAtrAtEntry[i+1]; pPeakR[i]=pPeakR[i+1];
      pBigMove[i]=pBigMove[i+1]; pWpr[i]=pWpr[i+1];
      pAdx[i]=pAdx[i+1]; pMaAngle[i]=pMaAngle[i+1]; pRunup[i]=pRunup[i+1]; pPeriodUsed[i]=pPeriodUsed[i+1];
      pBarsInBand[i]=pBarsInBand[i+1];
   }
   pCount--;
}

void WriteOutcome(int idx, string hit, double r)
{
   g_shadowTotalR += r;
   if(MQLInfoInteger(MQL_OPTIMIZATION)) return;   // optimization: accumulate R only, no per-row CSV (avoids agent file contention)
   int fh = FileOpen(StatsCSVFile, FILE_READ|FILE_WRITE|FILE_CSV|FILE_COMMON|FILE_ANSI, ',');
   if(fh == INVALID_HANDLE) return;
   FileSeek(fh, 0, SEEK_END);
   FileWrite(fh,
      pSetup[idx],
      TimeToString(pEntryTime[idx], TIME_DATE|TIME_MINUTES),
      DoubleToString(pEntryPrice[idx], _Digits),
      (pDir[idx]==ORDER_TYPE_BUY) ? "BUY" : "SELL",
      DoubleToString(pUpperBarrier[idx], _Digits),
      DoubleToString(pLowerBarrier[idx], _Digits),
      TimeToString(pTimeBarrier[idx], TIME_DATE|TIME_MINUTES),
      DoubleToString(pAtrAtEntry[idx], _Digits),
      hit,
      DoubleToString(r, 3),
      TimeToString(TimeCurrent(), TIME_DATE|TIME_MINUTES),
      DoubleToString(pPeakR[idx], 3),
      (pBigMove[idx] ? "1" : "0"),
      DoubleToString(pWpr[idx], 1),
      DoubleToString(pAdx[idx], 1),
      DoubleToString(pMaAngle[idx], 1),
      DoubleToString(pRunup[idx], 3),
      IntegerToString(pPeriodUsed[idx]),
      IntegerToString(pBarsInBand[idx]));
   FileClose(fh);
}

void CheckPendingBarriers()
{
   double barHigh = iHigh(_Symbol, PERIOD_CURRENT, 0);
   double barLow  = iLow(_Symbol, PERIOD_CURRENT, 0);
   for(int i=pCount-1; i>=0; i--)
   {
      bool isBuy = (pDir[i]==ORDER_TYPE_BUY);
      // favDist = distance to the TARGET barrier; advDist = distance to the STOP barrier.
      // R is measured in units of advDist (the risk), so an asymmetric target pays favDist/advDist > 1R.
      double favDist = isBuy ? (pUpperBarrier[i]-pEntryPrice[i]) : (pEntryPrice[i]-pLowerBarrier[i]);
      double advDist = isBuy ? (pEntryPrice[i]-pLowerBarrier[i]) : (pUpperBarrier[i]-pEntryPrice[i]);
      if(favDist <= 0 || advDist <= 0) { RemovePendingAt(i); continue; }
      double favPeakR = (isBuy ? (barHigh-pEntryPrice[i]) : (pEntryPrice[i]-barLow)) / advDist;
      if(favPeakR > pPeakR[i]) pPeakR[i] = favPeakR;
      bool favHit = (isBuy ? (barHigh>=pUpperBarrier[i]) : (barLow<=pLowerBarrier[i]));
      bool advHit = (isBuy ? (barLow<=pLowerBarrier[i]) : (barHigh>=pUpperBarrier[i]));
      string outcome=""; double r=0;
      if(favHit)      { outcome = isBuy?"UPPER":"LOWER"; r =  favDist/advDist; }
      else if(advHit) { outcome = isBuy?"LOWER":"UPPER"; r = -1.0; }
      if(outcome=="" && TimeCurrent() >= pTimeBarrier[i])
      {
         outcome="TIME";
         double cur = isBuy ? SymbolInfoDouble(_Symbol,SYMBOL_BID) : SymbolInfoDouble(_Symbol,SYMBOL_ASK);
         r = (isBuy ? (cur-pEntryPrice[i]) : (pEntryPrice[i]-cur)) / advDist;
      }
      if(outcome != "") { WriteOutcome(i, outcome, r); RemovePendingAt(i); }
   }
}

//+------------------------------------------------------------------+
void OnTick()
{
   bool newBar = (iTime(_Symbol, PERIOD_CURRENT, 0) != lastBarTime);
   if(newBar) lastBarTime = iTime(_Symbol, PERIOD_CURRENT, 0);

   if(StatsCollectionMode) CheckPendingBarriers();
   else { ManageBreakEvenSL(); ManageGrid(); }
   if(!newBar) return;

   if(UseSessionFilter)
   {
      int hr = BarHour(TimeCurrent());
      if(!(hr >= SessionStartHour && hr < SessionEndHour)) return;
   }

   bool bigMove=false; double wpr=0; int periodUsed=0; int barsInBand=0;
   int dir = GetGoldminerSignal(bigMove, wpr, periodUsed, barsInBand);
   if(dir < 0) return;                       // no Goldminer signal -> nothing to log

   // ---- a Goldminer signal FIRED: evaluate every gate in the SAME order, capture WHY (for the log) ----
   double adx     = ReadBuf(hADX,0,0);
   double maAngle = (dir==ORDER_TYPE_BUY) ? GetMAAngle() : -GetMAAngle();  // + = MA slopes with the trade
   double runup   = RunupBefore(dir);
   bool   bull    = IsDailyTrendBullish();
   string key     = ClassifySetup(dir);
   string skip    = "";                       // "" = passes so far

   if(UseDailyTrendFilter && ((dir==ORDER_TYPE_BUY && !bull) || (dir==ORDER_TYPE_SELL && bull)))
      skip = "D1trend";
   else if(!IsTrendStrong())
      skip = "trendWeak(adx="+DoubleToString(adx,1)+",ang="+DoubleToString(MathAbs(maAngle),1)+")";

   double wr=0; int ns=0; bool known = LookupSetupStats(key, wr, ns);   // looked up for the log too

   if(StatsCollectionMode)
   {
      if(skip=="") AddPendingSignal(key, dir, bigMove, wpr, adx, maAngle, runup, periodUsed, barsInBand);
      LogSignal(dir, key, wpr, adx, maAngle, bull, wr, ns, (skip=="" ? "SHADOW_LOGGED" : "SHADOW_SKIP:"+skip));
      return;
   }

   // ===== STAGE 2: TRADE ENTRY (gates in the same order; behaviour unchanged, just records the reason) =====
   if(skip=="" && StatsFilterEnabled)
   {
      if(!known)                skip = "setupUnknown";
      else if(ns < MinSamples)  skip = "lowSamples(n="+IntegerToString(ns)+")";
      else if(wr < MinWinRate)  skip = "lowWinRate("+DoubleToString(wr,2)+"<"+DoubleToString(MinWinRate,2)+")";
   }
   if(skip=="" && IsOverextended()) skip = "overextended";
   double szMult = LookupSizing(key);                      // 1.0 if table off; 0 = negative/unknown setup
   if(skip=="" && UseSizingTable && szMult <= 0) skip = "sizingZero";
   int maxB = (MaxConcurrentBaskets < 1) ? 1 : MaxConcurrentBaskets;
   if(skip=="" && CountOpenBaskets() >= maxB) skip = "maxBaskets("+IntegerToString(maxB)+")";

   LogSignal(dir, key, wpr, adx, maAngle, bull, wr, ns, (skip=="" ? "TRADE" : "SKIP:"+skip));
   if(skip != "") return;                                  // any failed gate -> no trade (same as before)

   g_clusterSizeMult = (szMult > 0) ? szMult : 1.0;
   int newBid = (maxB > 1) ? NextBasketId() : -1;          // tag baskets only in multi mode (single mode untagged = original path)
   g_clusterSetup = key;
   double lot;
   if(UseRiskNormalizedLots) { lot = RiskNormalizedLot(0); if(lot < 0) return; }
   else                       { lot = CalculateLot(0); }
   lot = NormalizeDouble(lot * g_clusterSizeMult, 2);      // per-setup bet sizing (1.0 when table off)
   double minLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   if(lot < minLot) lot = minLot;
   OpenSimpleSLTP(dir, lot, key, newBid);
}

//+------------------------------------------------------------------+
//| STAGE 2 -- TRADE EXECUTION (port of MT4 GridStat GOLD build P)    |
//+------------------------------------------------------------------+
double Ask_()  { return SymbolInfoDouble(_Symbol, SYMBOL_ASK); }
double Bid_()  { return SymbolInfoDouble(_Symbol, SYMBOL_BID); }
double Bal_()  { return AccountInfoDouble(ACCOUNT_BALANCE); }
double DollarPerPricePerLot()
{
   double ts = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double tv = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   return (ts > 0) ? tv / ts : 0;
}

// win-rate gate: read StatsCSVFile (shadow DB), count r_multiple>0 for setupKey. Robust to column count.
bool LookupSetupStats(string setupKey, double &winRate, int &samples)
{
   int fh = FileOpen(StatsCSVFile, FILE_READ|FILE_CSV|FILE_COMMON|FILE_ANSI, ',');
   if(fh == INVALID_HANDLE) { winRate=0; samples=0; return false; }
   int ncol=0, rIdx=-1;
   while(!FileIsEnding(fh))                       // header row -> column count + r_multiple index
   {
      string c = FileReadString(fh);
      if(c == "r_multiple") rIdx = ncol;
      ncol++;
      if(FileIsLineEnding(fh)) break;
   }
   if(rIdx < 0 || ncol <= 0) { FileClose(fh); winRate=0; samples=0; return false; }
   int wins=0, total=0;
   while(!FileIsEnding(fh))
   {
      string key=""; double r=0; bool any=false;
      for(int c=0; c<ncol && !FileIsEnding(fh); c++)
      {
         string cell = FileReadString(fh); any=true;
         if(c==0)    key = cell;
         if(c==rIdx) r   = StringToDouble(cell);
      }
      if(!any) break;
      if(key == setupKey) { total++; if(r > 0) wins++; }
   }
   FileClose(fh);
   samples = total;
   if(total == 0) { winRate=0; return false; }
   winRate = (double)wins / (double)total;
   return true;
}

// per-setup size multiplier from SizingCSVFile (cols: setup_key,size_mult,...). 1.0 if table off.
// Returns 0 for negative-expectancy setups AND for unknown setups (=> caller skips the trade).
double LookupSizing(string setupKey)
{
   if(!UseSizingTable) return 1.0;
   int fh = FileOpen(SizingCSVFile, FILE_READ|FILE_CSV|FILE_COMMON|FILE_ANSI, ',');
   if(fh == INVALID_HANDLE) return 1.0;   // no table -> behave as flat (don't block trading)
   int ncol=0, mIdx=-1;
   while(!FileIsEnding(fh))
   {
      string c = FileReadString(fh);
      if(c == "size_mult") mIdx = ncol;
      ncol++;
      if(FileIsLineEnding(fh)) break;
   }
   if(mIdx < 0 || ncol <= 0) { FileClose(fh); return 1.0; }
   double mult = 0.0; bool found=false;
   while(!FileIsEnding(fh))
   {
      string key=""; double m=0; bool any=false;
      for(int c=0; c<ncol && !FileIsEnding(fh); c++)
      {
         string cell = FileReadString(fh); any=true;
         if(c==0)    key = cell;
         if(c==mIdx) m   = StringToDouble(cell);
      }
      if(!any) break;
      if(key == setupKey) { mult = m; found=true; break; }
   }
   FileClose(fh);
   if(!found) return 0.0;                 // unknown setup -> skip (table is the gate)
   if(mult > MaxSizeMult) mult = MaxSizeMult;
   return mult;
}

double LotScale()
{
   if(!UseCompounding || CompoundingBase <= 0) return 1.0;
   return MathMax(1.0, MathFloor(Bal_() / CompoundingBase));
}
double CalculateLot(int gridLevel)
{
   double base = LotSize * LotScale();
   int fib[] = {1,1,2,3,5,8,13,21};
   int idx = (gridLevel < 0) ? 0 : (gridLevel > 7 ? 7 : gridLevel);
   int mult = fib[idx];
   if(MaxFibMult > 0 && mult > MaxFibMult) mult = MaxFibMult;   // ladder cap (0 = original fib)
   return NormalizeDouble(base * mult, 2);
}
// 1R = RiskPctPerTrade% of balance (stop distance = lower-barrier ATR). -1 = volatility skip.
double RiskNormalizedLot(int gridLevel)
{
   double atrD1 = ReadBuf(hATR_D1,0,1);
   double lm = (BarrierATRLower > 0) ? BarrierATRLower : BarrierATRMultiplier;
   double stopDist = atrD1 * lm;
   double dppl = DollarPerPricePerLot();
   if(stopDist <= 0 || dppl <= 0) return CalculateLot(gridLevel);
   double minLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double riskPerMinLot = stopDist * dppl * minLot;
   if(riskPerMinLot > MaxRiskPctSkip/100.0 * Bal_()) return -1.0;
   double targetRisk = RiskPctPerTrade/100.0 * Bal_();
   double baseLot = targetRisk / (stopDist * dppl);
   int fib[] = {1,1,2,3,5,8,13,21};
   int idx = (gridLevel < 0) ? 0 : (gridLevel > 7 ? 7 : gridLevel);
   int multRN = fib[idx];
   if(MaxFibMult > 0 && multRN > MaxFibMult) multRN = MaxFibMult;   // ladder cap (0 = original fib)
   double lot = NormalizeDouble(baseLot * multRN, 2);
   double maxLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   if(lot < minLot) lot = minLot;
   if(maxLot > 0 && lot > maxLot) lot = maxLot;
   return lot;
}

// count my non-hedge market positions
int BasketLotCount()
{
   int c = 0;
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(tk==0 || !PositionSelectByTicket(tk)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      c++;
   }
   return c;
}

//--- Basket concurrency (only meaningful when MaxConcurrentBaskets>1) -----------
// Basket id is embedded in the comment as "_B<id>" (e.g. GridStat_B3_SLTP).
// When MaxConcurrentBaskets<=1 we write NO tag -> BasketIdOf == -1 for all my
// positions -> they form one untagged pool -> ManageOneBasket(-1) reproduces the
// original single-basket behaviour exactly (gold/silver byte-identical path).
string BasketTag(int bid) { return (bid >= 0) ? ("_B" + IntegerToString(bid)) : ""; }

int BasketIdOf(string cmt)
{
   int p = StringFind(cmt, "_B");
   if(p < 0) return -1;
   p += 2;
   int e = StringFind(cmt, "_", p);
   if(e < 0) e = StringLen(cmt);
   string num = StringSubstr(cmt, p, e - p);
   if(StringLen(num) == 0) return -1;
   return (int)StringToInteger(num);
}

// distinct open basket ids for my symbol+magic
int CollectBaskets(int &ids[])
{
   ArrayResize(ids, 0);
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(tk==0 || !PositionSelectByTicket(tk)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      int bid = BasketIdOf(PositionGetString(POSITION_COMMENT));
      bool found=false;
      for(int k=0;k<ArraySize(ids);k++) if(ids[k]==bid){ found=true; break; }
      if(!found){ int n=ArraySize(ids); ArrayResize(ids,n+1); ids[n]=bid; }
   }
   return ArraySize(ids);
}

int CountOpenBaskets() { int ids[]; return CollectBaskets(ids); }

int NextBasketId()
{
   int ids[]; CollectBaskets(ids);
   int mx=0; for(int k=0;k<ArraySize(ids);k++) if(ids[k]>mx) mx=ids[k];
   return mx + 1;
}

// total float across ALL my positions (portfolio-level, for the multi-basket floor)
double PortfolioFloat()
{
   double f=0;
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(tk==0 || !PositionSelectByTicket(tk)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      f += PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
   }
   return f;
}
void CloseEverything(string reason)
{
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(tk==0 || !PositionSelectByTicket(tk)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      trade.PositionClose(tk);
   }
}
// close only the positions belonging to one basket id
void CloseBasket(int targetBid, string reason)
{
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(tk==0 || !PositionSelectByTicket(tk)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(BasketIdOf(PositionGetString(POSITION_COMMENT)) != targetBid) continue;
      trade.PositionClose(tk);
   }
}

// open entry with SL/TP at the (possibly asymmetric) barrier distances
void OpenSimpleSLTP(int dir, double lot, string setupKey, int bid=-1)
{
   double atrD1 = ReadBuf(hATR_D1,0,1);
   double um = (BarrierATRUpper > 0) ? BarrierATRUpper : BarrierATRMultiplier;  // target side
   double lm = (BarrierATRLower > 0) ? BarrierATRLower : BarrierATRMultiplier;  // stop side
   double upDist = atrD1 * um, dnDist = atrD1 * lm;
   double price = (dir==ORDER_TYPE_BUY) ? Ask_() : Bid_();
   double sl, tp;
   if(dir==ORDER_TYPE_BUY) { sl = price - dnDist; tp = price + upDist; }
   else                    { sl = price + dnDist; tp = price - upDist; }
   if(!UseEntrySL) sl = 0;   // no per-entry hard stop -> grid recovery + basket floor handle downside
   string cmt = CommentText + BasketTag(bid) + "_SLTP";
   bool ok = (dir==ORDER_TYPE_BUY) ? trade.Buy(lot,_Symbol,price,sl,tp,cmt)
                                   : trade.Sell(lot,_Symbol,price,sl,tp,cmt);
   if(ok) g_clusterSetup = setupKey;
   else   Print("OpenSimpleSLTP failed err=", trade.ResultRetcode());
}

bool OpenGridLevel(int dir, double lot, int gridLvl, int bid=-1)
{
   double price = (dir==ORDER_TYPE_BUY) ? Ask_() : Bid_();
   string cmt = CommentText + BasketTag(bid) + "_L" + IntegerToString(gridLvl);
   bool ok = (dir==ORDER_TYPE_BUY) ? trade.Buy(lot,_Symbol,price,0,0,cmt)
                                   : trade.Sell(lot,_Symbol,price,0,0,cmt);
   return ok;
}
bool OpenHedge(int hedgeDir, double lot, int bid=-1)
{
   double price = (hedgeDir==ORDER_TYPE_BUY) ? Ask_() : Bid_();
   string cmt = CommentText + BasketTag(bid) + "_HEDGE";
   return (hedgeDir==ORDER_TYPE_BUY) ? trade.Buy(lot,_Symbol,price,0,0,cmt)
                                     : trade.Sell(lot,_Symbol,price,0,0,cmt);
}
void CloseAllBasket(string reason)
{
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(tk==0 || !PositionSelectByTicket(tk)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      trade.PositionClose(tk);
   }
}

double GetGridSpacingPoints()
{
   if(!UseATRSpacing) return MathMax(GridSpacingMinPoints, 50);
   double atrD1 = ReadBuf(hATR_D1,0,1);
   double pts = atrD1 / _Point * ATRSpacingMultiplier;
   if(pts < GridSpacingMinPoints) pts = GridSpacingMinPoints;
   if(pts > GridSpacingMaxPoints) pts = GridSpacingMaxPoints;
   return pts;
}

// OPT 3: was there a recent SL-hit close (loss, close near SL) within N hours?
bool HadRecentSL(int hours)
{
   datetime cutoff = TimeCurrent() - hours*3600;
   if(!HistorySelect(cutoff, TimeCurrent())) return false;
   for(int i=HistoryDealsTotal()-1; i>=0; i--)
   {
      ulong d = HistoryDealGetTicket(i);
      if(d==0) continue;
      if(HistoryDealGetInteger(d, DEAL_MAGIC) != MagicNumber) continue;
      if(HistoryDealGetString(d, DEAL_SYMBOL) != _Symbol) continue;
      if(HistoryDealGetInteger(d, DEAL_ENTRY) != DEAL_ENTRY_OUT) continue;
      if(HistoryDealGetDouble(d, DEAL_PROFIT) < 0) return true;
   }
   return false;
}

void ManageBreakEvenSL()
{
   if(!UseBreakEvenSL) return;
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(tk==0 || !PositionSelectByTicket(tk)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(StringFind(PositionGetString(POSITION_COMMENT), "_SLTP") < 0) continue;
      double op = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl = PositionGetDouble(POSITION_SL);
      double tp = PositionGetDouble(POSITION_TP);
      if(sl == 0) continue;
      long ptype = PositionGetInteger(POSITION_TYPE);
      double cur = (ptype==POSITION_TYPE_BUY) ? Bid_() : Ask_();
      double slDist = MathAbs(op - sl);
      if(slDist == 0) continue;
      double rNow = (ptype==POSITION_TYPE_BUY) ? (cur-op)/slDist : (op-cur)/slDist;
      if(rNow < BreakEvenTriggerR) continue;
      bool alreadyBE = (ptype==POSITION_TYPE_BUY) ? (sl>=op) : (sl<=op);
      if(alreadyBE) continue;
      trade.PositionModify(tk, op, tp);
   }
}

// Dispatcher: single pool (default = gold/silver path, UNCHANGED) or per-basket
// loop when MaxConcurrentBaskets>1 (lets new signals open their own basket so one
// stuck basket can't starve 200+ signals -- no time/hard stops involved).
void ManageGrid()
{
   int maxB = (MaxConcurrentBaskets < 1) ? 1 : MaxConcurrentBaskets;
   if(maxB <= 1) { ManageOneBasket(-1); return; }   // untagged single pool = original behaviour, byte-for-byte

   // portfolio-level catastrophe floor: cap TOTAL float across all baskets so concurrency
   // can't multiply tail risk. (single-basket case is already covered by the per-basket floor.)
   if(UseBasketStop && PortfolioFloat() <= -BasketMaxLossPct/100.0 * Bal_())
   { CloseEverything("PORTFOLIO STOP"); g_peakBasketFloat=0.0; return; }

   // ---- PORTFOLIO STAGED FLOOR: lighten the whole book BEFORE the portfolio floor fires.
   // Shares g_lastStageBar with the per-basket lever -> at most ONE staged cut of any kind
   // per bar; the realized loss + relief on the survivors self-hystereses the trigger.
   if(UseStagedFloorPortfolio && iTime(_Symbol, PERIOD_CURRENT, 0) != g_lastStageBar)
   {
      double bookF = PortfolioFloat();
      if(bookF <= -StagedFloorPortfolioPct/100.0 * Bal_())
      {
         int totalLegs=0; ulong worstTicket=0; double worstPnl=0;
         for(int wi=PositionsTotal()-1; wi>=0; wi--)
         {
            ulong wtk = PositionGetTicket(wi);
            if(wtk==0 || !PositionSelectByTicket(wtk)) continue;
            if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
            if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
            if(StringFind(PositionGetString(POSITION_COMMENT), "_HEDGE") >= 0) continue;
            totalLegs++;
            double wpnl = PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
            if(worstTicket==0 || wpnl < worstPnl) { worstTicket = wtk; worstPnl = wpnl; }
         }
         if(worstTicket > 0 && totalLegs >= 2)   // keep a book to lighten
         {
            if(trade.PositionClose(worstTicket))
               Print("PORTFOLIO STAGED FLOOR: closed worst leg #", worstTicket,
                     " pnl=", DoubleToString(worstPnl,2),
                     " (book float was ", DoubleToString(bookF,2), ")");
            else
               Print("PORTFOLIO STAGED FLOOR: close failed #", worstTicket, " err=", GetLastError());
            g_lastStageBar = iTime(_Symbol, PERIOD_CURRENT, 0);
            return;   // re-evaluate the lightened book next tick
         }
      }
   }

   int ids[]; int n = CollectBaskets(ids);
   for(int k=0; k<n; k++) ManageOneBasket(ids[k]);
}

// Manage ONE basket. targetBid = -1 means the untagged pool (the original single-basket
// path: the BasketIdOf filter is always true, so logic/decisions are identical to before).
void ManageOneBasket(int targetBid)
{
   int nLevels=0; double basketLots=0, basketSumPxLot=0, basketFloat=0;
   long initialDir=-1; double hedgeLots=0, hedgeFloat=0; bool hedgeOpen=false;
   datetime oldestOpen=0;
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(tk==0 || !PositionSelectByTicket(tk)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      string cmt = PositionGetString(POSITION_COMMENT);
      if(BasketIdOf(cmt) != targetBid) continue;          // basket filter (always true for untagged single pool)
      double lot = PositionGetDouble(POSITION_VOLUME);
      double op  = PositionGetDouble(POSITION_PRICE_OPEN);
      double pnl = PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
      datetime ot = (datetime)PositionGetInteger(POSITION_TIME);
      if(oldestOpen==0 || ot < oldestOpen) oldestOpen = ot;
      if(StringFind(cmt, "_HEDGE") >= 0) { hedgeOpen=true; hedgeLots+=lot; hedgeFloat+=pnl; }
      else { nLevels++; initialDir=PositionGetInteger(POSITION_TYPE); basketLots+=lot; basketSumPxLot+=op*lot; basketFloat+=pnl; }
   }
   if(nLevels==0) { g_peakBasketFloat=0.0; g_lockArmed=false; return; }
   double combinedFloat = basketFloat + hedgeFloat;

   double atrD1t = ReadBuf(hATR_D1,0,1);
   double lm = (BarrierATRLower > 0) ? BarrierATRLower : BarrierATRMultiplier;
   double oneR = atrD1t * lm * DollarPerPricePerLot() * (basketLots + hedgeLots);

   // catastrophic floor (per basket)
   if(UseBasketStop)
   {
      double maxLoss = -BasketMaxLossPct/100.0 * Bal_();
      if(combinedFloat <= maxLoss) { CloseBasket(targetBid, "BASKET STOP"); g_peakBasketFloat=0.0; return; }
   }
   // regime-aware exit: bail a LOSING basket when the D1 trend has flipped against it (caps the tail early -> lower equity DD)
   if(UseRegimeBasketExit && combinedFloat < 0 && initialDir >= 0)
   {
      bool d1bull = IsDailyTrendBullish();
      bool basketBuy = (initialDir == POSITION_TYPE_BUY);
      if((basketBuy && !d1bull) || (!basketBuy && d1bull))
      { CloseBasket(targetBid, "regime flip exit"); g_peakBasketFloat=0.0; return; }
   }
   // ---- STAGED FLOOR (user-designed live 2026-07-09; MT4 build T; PER BASKET here):
   // cut the single WORST leg of THIS basket when it floats <= -StagedFloorPct% of
   // balance, BEFORE the catastrophic floor -- lightens the basket (escape pulls
   // closer, floor pushes away, survival odds rise) for the price of one realized leg.
   // At most one cut per bar (global guard); the realized loss deepens neither float
   // nor trigger, so the mechanism self-hysteresis on the lightened basket.
   if(UseStagedFloor && nLevels >= 2 && iTime(_Symbol, PERIOD_CURRENT, 0) != g_lastStageBar &&
      combinedFloat <= -StagedFloorPct/100.0 * Bal_())
   {
      ulong worstTicket = 0; double worstPnl = 0;
      for(int wi=PositionsTotal()-1; wi>=0; wi--)
      {
         ulong wtk = PositionGetTicket(wi);
         if(wtk==0 || !PositionSelectByTicket(wtk)) continue;
         if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
         if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
         string wcmt = PositionGetString(POSITION_COMMENT);
         if(BasketIdOf(wcmt) != targetBid) continue;         // THIS basket only
         if(StringFind(wcmt, "_HEDGE") >= 0) continue;       // basket legs only
         double wpnl = PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
         if(worstTicket==0 || wpnl < worstPnl) { worstTicket = wtk; worstPnl = wpnl; }
      }
      if(worstTicket > 0)
      {
         if(trade.PositionClose(worstTicket))
            Print("STAGED FLOOR: closed worst leg #", worstTicket,
                  " pnl=", DoubleToString(worstPnl,2),
                  " (basket float was ", DoubleToString(combinedFloat,2),
                  " bid=", targetBid, ")");
         else
            Print("STAGED FLOOR: close failed #", worstTicket, " err=", GetLastError());
         g_lastStageBar = iTime(_Symbol, PERIOD_CURRENT, 0);
         return;   // re-evaluate the lightened basket next tick
      }
   }
   // profit exit
   if(UseLockTrailExit)
   {
      // RIDE-THE-TREND (user design): +ProfitTargetUSD is the TRIGGER to start riding, NOT the exit.
      // Once profit reaches the target, ARM: lock break-even (a triggered winner can't become a loss)
      // and let the trade RIDE the continuation; liquidate only when float retraces
      // LockTrailGivebackPct% from its running peak. So a small bounce at the target doesn't close it
      // (the choke in the prior version) — it rides moves like the chart's continuation down to 4114.
      // (g_peakBasketFloat / g_lockArmed are single globals -> reliable only at MaxConcurrentBaskets<=1.)
      // RIDE only TREND-ALIGNED baskets (continuation, like the chart's downtrend sell). BANK
      // counter-trend recoveries fast at the target — those are the bounce-that-fades baskets
      // that, when ridden, reverse and hit the -20% floor (the -$1,072/-$1,751 grid disasters).
      if(combinedFloat >= ProfitTargetUSD && !g_lockArmed)
      {
         bool d1bull   = IsDailyTrendBullish();
         bool basketBuy = (initialDir == POSITION_TYPE_BUY);
         bool aligned   = (basketBuy == d1bull);   // BUY&bull or SELL&bear = with the D1 trend
         if(aligned) g_lockArmed = true;           // trend-aligned -> ride the continuation
         else { CloseBasket(targetBid, "target (counter-trend bank)"); g_peakBasketFloat=0.0; return; } // bank +$
      }
      if(g_lockArmed)
      {
         if(combinedFloat > g_peakBasketFloat) g_peakBasketFloat = combinedFloat;
         double stop = g_peakBasketFloat * (1.0 - LockTrailGivebackPct/100.0);
         if(stop < 0) stop = 0;   // break-even floor: never give a triggered winner back into a loss
         if(combinedFloat <= stop) { CloseBasket(targetBid, "lock-trail exit"); g_peakBasketFloat=0.0; g_lockArmed=false; return; }
      }
   }
   else if(nLevels >= 2)
   {
      if(combinedFloat >= ProfitTargetUSD) { CloseBasket(targetBid, "grid recovery escape"); g_peakBasketFloat=0.0; return; }
   }
   else if(UseTrailingExit && oneR > 0)
   {
      if(combinedFloat > g_peakBasketFloat) g_peakBasketFloat = combinedFloat;
      if(g_peakBasketFloat >= TrailActivateR*oneR && combinedFloat <= g_peakBasketFloat - TrailDistanceR*oneR)
      { CloseBasket(targetBid, "trail exit"); g_peakBasketFloat=0.0; return; }
   }
   else
   {
      // single position: with an ASYMMETRIC upper barrier, let the wider TP run (skip the $ cap);
      // symmetric (BarrierATRUpper=0) keeps the $100 cap -> validated baseline unchanged.
      bool letRun = (BarrierATRUpper > 0);
      if(!letRun && combinedFloat >= ProfitTargetUSD) { CloseBasket(targetBid, "profit target"); return; }
   }
   if(oldestOpen > 0 && (TimeCurrent()-oldestOpen) > MaxDaysOpen*86400) { CloseBasket(targetBid, "max days"); return; }

   double basketAvg = (basketLots>0) ? basketSumPxLot/basketLots : 0;
   double currentPrice = (initialDir==POSITION_TYPE_BUY) ? Bid_() : Ask_();
   if(!hedgeOpen)
   {
      double beDistance = MathAbs(basketAvg - currentPrice) / point;
      if(UseHedge && beDistance >= HedgeBreakEvenPoints)
      {
         int hedgeSide = (initialDir==POSITION_TYPE_BUY) ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;
         double hedgeSize = NormalizeDouble(basketLots * HedgeRatio, 2);
         if(hedgeSize < 0.01) hedgeSize = 0.01;
         OpenHedge(hedgeSide, hedgeSize, targetBid);
         return;
      }
      if(nLevels < MaxGridLevels)
      {
         double spacing = GetGridSpacingPoints();
         double extremeEntry = basketAvg;
         for(int j=PositionsTotal()-1; j>=0; j--)
         {
            ulong tk2 = PositionGetTicket(j);
            if(tk2==0 || !PositionSelectByTicket(tk2)) continue;
            if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
            if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
            string cmt2 = PositionGetString(POSITION_COMMENT);
            if(BasketIdOf(cmt2) != targetBid) continue;
            if(StringFind(cmt2, "_HEDGE") >= 0) continue;
            double op2 = PositionGetDouble(POSITION_PRICE_OPEN);
            if(initialDir==POSITION_TYPE_BUY  && op2 < extremeEntry) extremeEntry = op2;
            if(initialDir==POSITION_TYPE_SELL && op2 > extremeEntry) extremeEntry = op2;
         }
         bool addNow = false;
         if(initialDir==POSITION_TYPE_BUY  && currentPrice <= extremeEntry - spacing*point) addNow=true;
         if(initialDir==POSITION_TYPE_SELL && currentPrice >= extremeEntry + spacing*point) addNow=true;
         if(addNow)
         {
            double currentTotalLots = basketLots + hedgeLots;
            double rawGridLot = UseRiskNormalizedLots ? RiskNormalizedLot(nLevels) : CalculateLot(nLevels);
            if(rawGridLot < 0) return;
            double newLot = NormalizeDouble(rawGridLot, 2);   // grid legs at base size (sizing applies to the initial entry only -> safe under concurrency)
            double minLotG = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
            if(newLot < minLotG) newLot = minLotG;
            if(currentTotalLots + newLot > MaxBasketLotsTotal) return;
            if(SkipGridAfterSL && HadRecentSL(SkipGridAfterSLHours)) return;
            int gdir = (initialDir==POSITION_TYPE_BUY) ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
            OpenGridLevel(gdir, newLot, nLevels+1, targetBid);
         }
      }
   }
}
//+------------------------------------------------------------------+
