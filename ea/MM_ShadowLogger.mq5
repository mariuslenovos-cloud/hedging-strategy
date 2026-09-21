//+------------------------------------------------------------------+
//|                                          MM_ShadowLogger.mq5     |
//|                                                                  |
//|  FORWARD TEST RIG. PLACES NO ORDERS. EVER.                       |
//|                                                                  |
//|  Purpose: capture every signal the reverse-engineered Million    |
//|  Moves V5 logic produces, live, at the moment it fires, and      |
//|  score each one under SEVEN competing exit policies in parallel. |
//|                                                                  |
//|  This design exists to answer one question and nothing else:     |
//|                                                                  |
//|     Does the edge survive in ranging conditions, or does all of  |
//|     the profit sit in trending sessions?                         |
//|                                                                  |
//|  Every row carries the regime metrics computed AT SIGNAL TIME    |
//|  (efficiency ratio, ADX, volume state), never in hindsight, so   |
//|  the trend/range split cannot be fitted after the fact.          |
//|                                                                  |
//|  Output: MQL5/Files/mm_fires_<symbol>_<tf>.csv                   |
//+------------------------------------------------------------------+
#property copyright "Marius - forward test rig"
#property version   "1.00"
#property strict

//--- Build stamp. The forward test is only worth anything if the thing that
//--- is running is the thing on disk, so print a dated stamp on init and let
//--- framework_check reconcile running-vs-disk the same way it does for every
//--- other watched EA. A silently-dead logger reads exactly like a quiet
//--- market, which is how fib C lost a month.
#define EA_BUILD "MM-SHADOW-2026-09-21-M"

#include <MMEngine.mqh>
#include <Trade\Trade.mqh>

//--- exit policies scored simultaneously on every signal
#define MM_POL_COUNT 8
#define MM_POL_TP1      0   // vendor default, 0.5R
#define MM_POL_TP2      1   // 1.0R
#define MM_POL_TP3      2   // 1.5R
#define MM_POL_FIX2R    3   // flat 2.0R, no ladder
#define MM_POL_TRAIL    4   // hold until SuperTrend/cloud flips against
#define MM_POL_BE_TRAIL 5   // stop to BE at +1R, then cloud-flip trail
#define MM_POL_LADDER   7   // thirds at TP1/TP2/TP3 -- the vendor's OWN exit
#define MM_POL_SCALE    6   // half at TP1, remainder cloud-flip trailed

string MMPolicyName(const int p)
  {
   switch(p)
     {
      case MM_POL_TP1:      return "tp1_0.5R";
      case MM_POL_TP2:      return "tp2_1.0R";
      case MM_POL_TP3:      return "tp3_1.5R";
      case MM_POL_FIX2R:    return "fixed_2R";
      case MM_POL_TRAIL:    return "cloud_trail";
      case MM_POL_BE_TRAIL: return "be1R_then_trail";
      case MM_POL_SCALE:    return "half_tp1_trail";
     }
   return "?";
  }

//--- inputs -------------------------------------------------------
input group             "=== Signal engine ==="
input double            InpSensitivity     = 2.5;    // Sensitivity (ATR SuperTrend multiplier)
input int               InpAtrPeriod       = 10;     // ATR period
input ENUM_MM_TIER      InpMinTier         = MM_TIER_ALL; // Log signals from this tier upward

input group             "=== Cloud / stop model ==="
input int               InpCloudBasis      = 50;     // Gradient cloud basis EMA
input double            InpCloudOuterATR   = 3.5;    // Outer band = basis +/- k * ATR  (sets the stop)

input group             "=== Filters ==="
input int               InpEmaTrend        = 200;    // Trend EMA (Smart filter)
input int               InpMtfMinAgree     = 4;      // Smart+ : min timeframes agreeing
input int               InpVolLookback     = 50;     // Volume average lookback
input int               InpMinVolDots      = 1;      // Smart+ : min volume dots (0 = vendor "dash")

input group             "=== Regime capture ==="
input int               InpEffRatioBars    = 30;     // Efficiency ratio lookback
input int               InpAdxPeriod       = 14;     // ADX period

input group             "=== Test governance ==="
input int               InpMaxBarsInTrade  = 720;    // Force-close a virtual trade after N bars
input double            InpSpreadCostR     = 1.0;    // Charge this many spreads per round turn
input bool              InpChargeSpread    = true;   // Deduct spread cost from every R result
input group             "=== Stop construction ==="
//--- InpStopMode 0 reproduces the original cloud-band stop exactly, so the
//--- control instances are unchanged. Mode 1 is the form derived from the
//--- vendor's own published trades on 2026-09-08:
//---
//---     stop = entry -/+ 2.33 * ATR(M5, 14, WILDER)
//---
//--- k across four independent trades, two days, a 4x range of volatility:
//---     2.337  2.329  2.287  2.331   ->  cv 1.0%
//---
//--- The ATR definition is the whole story. TradingView's ta.atr() is RMA
//--- (Wilder) smoothed at a default period of 14, and he is on TradingView.
//--- MT5's iATR is a SIMPLE moving average of true range -- a different
//--- function. Fitting the same four trades against iATR(M5,10) scatters to
//--- cv 12.7%, no better than the cloud-band forms it replaced. So this does
//--- NOT call iATR: it computes Wilder's ATR directly.
input int               InpStopMode        = 0;    // 0=cloud band (original), 1=entry +/- k*ATR(TF)
input ENUM_TIMEFRAMES   InpStopAtrTF       = PERIOD_M5;  // TF for the stop ATR (mode 1)
input int               InpStopAtrPeriod   = 14;   // ATR period for the stop (mode 1)
input double            InpStopAtrMult     = 2.33; // k, fitted to the vendor's own trades

input group             "=== Live orders (demo visibility) ==="
//--- OFF by default. The shadow log is UNAFFECTED by this switch: every fire is
//--- still scored under all eight policies whether or not an order goes out, so
//--- turning this on cannot change the sample the gates are scored from.
//--- A real order can only follow ONE exit, so it follows the PRIMARY policy --
//--- the vendor ladder: a third out at TP1, a third at TP2, the rest at TP3,
//--- original stop throughout, no cloud-flip exit.
input bool              InpTrade           = false; // place REAL orders on this account
input double            InpLotsPerRung     = 0.01;  // lots per ladder rung (position = 3x this)
input int               InpMaxOpen         = 3;     // max concurrent POSITIONS (3 = one ladder)
input bool              InpReverseOnOpposite = true; // opposite signal closes the open ladder first
//--- build K (2026-09-15): the two levers that survived the 102-day walk-forward
//--- (mm_wfsweep / mm_seqlab2). Both default OFF = byte-identical behaviour.
input int               InpMinHoldMinutes  = 0;     // opposite signal inside this window neither reverses nor trades (0=off)
input ENUM_TIMEFRAMES   InpAlignEmaTF      = PERIOD_M5; // trend-alignment EMA timeframe
input int               InpAlignEmaPeriod  = 0;     // 0=off: new ladder only if entry is on the EMA side (BUY above / SELL below)
input int               InpTradeStartHour  = 0;     // build L: NEW ladders only from this server hour (inclusive)
input int               InpTradeEndHour    = 23;    // ... to this server hour (inclusive); start>end wraps midnight; 0/23 = all hours
input int               InpTradeSide       = 0;     // build M: REAL orders only for 0=both, 1=BUY fires, -1=SELL fires (shadow scores every fire regardless)
//--- A book holding BOTH sides is locked: the two legs cancel, so it can only
//--- be resolved by closing, never by waiting. Take it the moment it is green
//--- rather than letting one side decay into the other's stop. Reverse-on-
//--- opposite should stop a mixed book ever forming; this is the backstop for
//--- when it does anyway -- a failed close, the flag switched off, or a
//--- position opened by hand.
//--- BE AFTER TP1 (2026-09-11). Once the TP1 rung has banked, pull the stop on
//--- the rungs still open up to their own entry, so a ladder that has already
//--- paid cannot hand the rest back. Measured over 205 fires: on the vendor
//--- geometry it is worth only ~$26 and per-fire R does not move -- it buys hit
//--- rate (42.4->47.3%) by cutting the payoff ratio (1.31->1.09), which is the
//--- wrong direction for a book carried by payoff asymmetry. Its real value is
//--- as the PARTNER to wider rungs, where it is worth $60-97 and flips every
//--- wide geometry positive, because a further target leaves the remainder
//--- exposed for longer and this is the cap on that give-back.
//--- Default OFF; it earns its place on its own instance, not by assumption.
//--- RUNG GEOMETRY (2026-09-11). The vendor's 0.5/1.0/1.5R was never questioned
//--- and it is the worst-paying arrangement measured. Break-even for a target at
//--- X R is L/(L+X), and L -- the loss the book ACTUALLY takes -- is 0.48R, not
//--- 1.0, because reverse-on-opposite truncates losers. At that L every rung
//--- clears and THE MARGIN WIDENS WITH DISTANCE (0.5R 1.32x, 3.0R 1.65x), so the
//--- nearest rung is the worst-paying one and the engine takes a third off there.
//--- Measured as a DELTA vs the vendor geometry within each half of the sample,
//--- 1.0/1.5/2.0 paired with BE-after-TP1 is +$67 and +$73 -- positive in BOTH
//--- halves, the most balanced cell on the board. Defaults reproduce the vendor
//--- ladder exactly, so every existing instance is unchanged.
input double            InpRungR1          = 0.5;    // TP1 distance in R
input double            InpRungR2          = 1.0;    // TP2 distance in R
input double            InpRungR3          = 1.5;    // TP3 distance in R
input bool              UseBEAfterTP1      = false;  // after TP1 fills, stop to entry on the rest
input double            BEOffsetR          = 0.10;   // ... lifted this many R above entry
input bool              InpCloseMixedInProfit = true;  // close EVERYTHING when a mixed book is green
input double            InpMixedMinProfit  = 0.0;   // ... once combined P/L reaches this ($)
input long              InpMagic           = 0;     // 0 = derive from symbol+TF+tag

input string            InpRunTag          = "run1"; // Tag written to every row
input bool              InpVerbose         = true;   // Print each fire to the Experts log

//--- engine state -------------------------------------------------
CMMSuperTrend  g_st;
CMMDashboard   g_dash;
int            g_atr_handle  = INVALID_HANDLE;
int            g_ema_handle  = INVALID_HANDLE;
int            g_basis_handle= INVALID_HANDLE;
int            g_adx_handle  = INVALID_HANDLE;
datetime       g_last_bar    = 0;
string         g_file        = "";
int            g_stop_atr_handle = INVALID_HANDLE;

//--- live-order state. No per-bar management: each rung is a separate position
//--- carrying its own TP and the shared stop, so the broker resolves all of it.
CTrade         g_trade;
long           g_magic       = 0;
int            g_fire_seq    = 0;
double         g_point       = 0.0;

//--- one live virtual trade, scored across all policies -----------
struct MMVirtual
  {
   bool     active;
   int      id;
   int      dir;
   datetime open_time;
   int      bars_held;

   double   entry, sl, risk, tp1, tp2, tp3;
   double   mfe_r, mae_r;          // best / worst excursion in R

   bool     pol_open[MM_POL_COUNT];
   double   pol_r[MM_POL_COUNT];
   int      pol_bars[MM_POL_COUNT];
   string   pol_reason[MM_POL_COUNT];
   double   pol_stop[MM_POL_COUNT];  // per-policy working stop (BE moves this)
   double   pol_locked[MM_POL_COUNT];// realised R already banked (scale-out)
   double   pol_cost[MM_POL_COUNT];  // spread actually charged, in R
   double   pol_sp_exit[MM_POL_COUNT];// spread quoted when this policy closed
   int      pol_rungs[MM_POL_COUNT]; // ladder rungs already banked (0..3)

   // frozen context
   double   atr, ema200, ema_dist_atr, basis, adx, eff, vol_ratio, spread_pts;
   int      mtf_agree, mtf_checked, vol_dots, tier;
  };

MMVirtual g_trades[];
int       g_align_handle = INVALID_HANDLE;   // build K trend-alignment EMA

//+------------------------------------------------------------------+
int OnInit(void)
  {
   g_point = _Point;

   g_st.Reset(InpSensitivity);

   g_atr_handle   = iATR(_Symbol, _Period, InpAtrPeriod);
   g_ema_handle   = iMA(_Symbol, _Period, InpEmaTrend, 0, MODE_EMA, PRICE_CLOSE);
   g_basis_handle = iMA(_Symbol, _Period, InpCloudBasis, 0, MODE_EMA, PRICE_CLOSE);
   g_adx_handle   = iADX(_Symbol, _Period, InpAdxPeriod);

   if(g_atr_handle == INVALID_HANDLE || g_ema_handle == INVALID_HANDLE ||
      g_basis_handle == INVALID_HANDLE || g_adx_handle == INVALID_HANDLE)
     {
      Print("MM_ShadowLogger: indicator handle creation failed");
      return INIT_FAILED;
     }

   if(InpAlignEmaPeriod > 0)
     {
      g_align_handle = iMA(_Symbol, InpAlignEmaTF, InpAlignEmaPeriod, 0, MODE_EMA, PRICE_CLOSE);
      if(g_align_handle == INVALID_HANDLE)
        {
         Print("MM_ShadowLogger: alignment EMA handle creation failed");
         return INIT_FAILED;
        }
     }

   ENUM_TIMEFRAMES tfs[] = {PERIOD_M1, PERIOD_M5, PERIOD_M15,
                            PERIOD_M30, PERIOD_H1, PERIOD_D1};
   if(!g_dash.Init(_Symbol, InpEmaTrend, tfs))
      return INIT_FAILED;

   g_file = StringFormat("mm_fires_%s_%s_%s.csv", _Symbol,
                         EnumToString((ENUM_TIMEFRAMES)_Period), InpRunTag);
   if(!EnsureHeader())
      return INIT_FAILED;

   g_magic = InpMagic;
   if(g_magic == 0)
     {
      //--- distinct per symbol+TF+tag so two instances never share a magic
      string seed = _Symbol + IntegerToString((int)_Period) + InpRunTag;
      long acc = 0;
      for(int ci = 0; ci < StringLen(seed); ci++)
         acc = (acc * 31 + StringGetCharacter(seed, ci)) % 90000;
      g_magic = 900000 + acc;   // 900000+ is unused by every other EA here
     }
   g_trade.SetExpertMagicNumber(g_magic);
   g_trade.SetDeviationInPoints(20);
   g_trade.SetTypeFillingBySymbol(_Symbol);
   g_trade.LogLevel(LOG_LEVEL_ERRORS);

   ArrayResize(g_trades, 0);
   WarmUp();

   PrintFormat("MARIUS MM SHADOW LOGGER %s | %s %s | %s",
               EA_BUILD, _Symbol, EnumToString((ENUM_TIMEFRAMES)_Period),
               (InpTrade
                ? StringFormat("LIVE ORDERS ON magic=%d lots=%.2fx3 maxPos=%d %s",
                               g_magic, InpLotsPerRung, InpMaxOpen,
                               (InpReverseOnOpposite ? "reverse-on-opposite"
                                                     : "no-reverse"))
                : "NO ORDERS WILL BE PLACED"));
   PrintFormat("CONFIG | MM | stopMode=%d %s",
               InpStopMode,
               (InpStopMode == 1
                ? StringFormat("entry +/- %.2f*WilderATR(%s,%d)", InpStopAtrMult,
                               EnumToString(InpStopAtrTF), InpStopAtrPeriod)
                : "cloud band (original)"));
   PrintFormat("CONFIG | MM | sensitivity=%.2f atrPeriod=%d cloudBasis=%d "
               "cloudOuterATR=%.2f minTier=%d minVolDots=%d spread=%s tag=%s",
               InpSensitivity, InpAtrPeriod, InpCloudBasis, InpCloudOuterATR,
               InpMinTier, InpMinVolDots,
               (InpChargeSpread ? "charged" : "OFF"), InpRunTag);
   PrintFormat("CONFIG | MM | rungs=%.2f/%.2f/%.2fR beAfterTP1=%s offset=%.2fR tag=%s",
               InpRungR1, InpRungR2, InpRungR3,
               (UseBEAfterTP1 ? "ON" : "off"), BEOffsetR, InpRunTag);
   PrintFormat("CONFIG | MM | minHold=%dmin align=%s tag=%s",
               InpMinHoldMinutes,
               (InpAlignEmaPeriod > 0
                ? StringFormat("EMA%d(%s)", InpAlignEmaPeriod, EnumToString(InpAlignEmaTF))
                : "off"), InpRunTag);
   PrintFormat("CONFIG | MM | tradeWindow=%02d-%02d side=%s tag=%s",
               InpTradeStartHour, InpTradeEndHour,
               (InpTradeSide>0?"BUY":InpTradeSide<0?"SELL":"both"), InpRunTag);
   PrintFormat("CONFIG | MM | logging to Files/%s", g_file);
   LoadState();
   return INIT_SUCCEEDED;
  }

//+------------------------------------------------------------------+
//| VIRTUAL-TRADE PERSISTENCE                                        |
//|                                                                  |
//| A recompile, a re-attach or a terminal restart runs OnDeinit and |
//| then OnInit with an empty g_trades[], so every virtual trade in  |
//| flight was silently dropped: 13 scores lost to re-attaches       |
//| between 09-08 and 09-11, plus whatever each restart costs. The   |
//| sample is the binding constraint on every open candidate (the    |
//| tier gate wants n>=50, the hold lever n>=200), which makes       |
//| losing scores the most expensive thing this logger does.         |
//|                                                                  |
//| SCOPE: measurement only. The order paths resolve live positions  |
//| from the broker by magic (OpenRealLadder, CloseMyPositions) and  |
//| never read g_trades[], so restoring this state cannot open,      |
//| close or mismanage a real trade. Deliberately kept that way.     |
//+------------------------------------------------------------------+
#define MM_STATE_MAGIC  "MM_STATE_V1"
#define MM_STATE_FIELDS 96
#define MM_STATE_MAXAGE (7 * 24 * 3600)

string StateFile(void)
  {
   return "mm_state_" + InpRunTag + ".csv";
  }

void SaveState(void)
  {
   int n = 0;
   for(int i = 0; i < ArraySize(g_trades); i++)
      if(g_trades[i].active)
         n++;

   if(n == 0)
     {
      if(FileIsExist(StateFile()))
         FileDelete(StateFile());
      return;
     }

   const int h = FileOpen(StateFile(), FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(h == INVALID_HANDLE)
     {
      PrintFormat("STATE[%s] cannot write %s (err %d) -- %d virtual trade(s) "
                  "will be lost", InpRunTag, StateFile(), GetLastError(), n);
      return;
     }

   FileWriteString(h, StringFormat("%s,%s,%s,%d,%d\r\n", MM_STATE_MAGIC,
                                   EA_BUILD, InpRunTag, (int)TimeCurrent(), n));

   for(int i = 0; i < ArraySize(g_trades); i++)
     {
      if(!g_trades[i].active)
         continue;

      string s = StringFormat("%d,%d,%d,%d,", g_trades[i].id, g_trades[i].dir,
                              (int)g_trades[i].open_time, g_trades[i].bars_held);
      s += DoubleToString(g_trades[i].entry, 8) + ",";
      s += DoubleToString(g_trades[i].sl, 8) + ",";
      s += DoubleToString(g_trades[i].risk, 8) + ",";
      s += DoubleToString(g_trades[i].tp1, 8) + ",";
      s += DoubleToString(g_trades[i].tp2, 8) + ",";
      s += DoubleToString(g_trades[i].tp3, 8) + ",";
      s += DoubleToString(g_trades[i].mfe_r, 8) + ",";
      s += DoubleToString(g_trades[i].mae_r, 8) + ",";
      s += DoubleToString(g_trades[i].atr, 8) + ",";
      s += DoubleToString(g_trades[i].ema200, 8) + ",";
      s += DoubleToString(g_trades[i].ema_dist_atr, 8) + ",";
      s += DoubleToString(g_trades[i].basis, 8) + ",";
      s += DoubleToString(g_trades[i].adx, 8) + ",";
      s += DoubleToString(g_trades[i].eff, 8) + ",";
      s += DoubleToString(g_trades[i].vol_ratio, 8) + ",";
      s += DoubleToString(g_trades[i].spread_pts, 8) + ",";
      s += StringFormat("%d,%d,%d,%d", g_trades[i].mtf_agree,
                        g_trades[i].mtf_checked, g_trades[i].vol_dots,
                        g_trades[i].tier);

      for(int p = 0; p < MM_POL_COUNT; p++)
        {
         string why = g_trades[i].pol_reason[p];
         StringReplace(why, ",", ";");          // never let a reason break the row
         s += StringFormat(",%d,", (g_trades[i].pol_open[p] ? 1 : 0));
         s += DoubleToString(g_trades[i].pol_r[p], 8) + ",";
         s += StringFormat("%d,%s,", g_trades[i].pol_bars[p], why);
         s += DoubleToString(g_trades[i].pol_stop[p], 8) + ",";
         s += DoubleToString(g_trades[i].pol_locked[p], 8) + ",";
         s += DoubleToString(g_trades[i].pol_cost[p], 8) + ",";
         s += DoubleToString(g_trades[i].pol_sp_exit[p], 8) + ",";
         s += StringFormat("%d", g_trades[i].pol_rungs[p]);
        }
      FileWriteString(h, s + "\r\n");
     }

   FileClose(h);
   PrintFormat("STATE[%s] saved %d in-flight virtual trade(s) -> %s",
               InpRunTag, n, StateFile());
  }

int LoadState(void)
  {
   if(!FileIsExist(StateFile()))
      return 0;

   const int h = FileOpen(StateFile(), FILE_READ | FILE_TXT | FILE_ANSI);
   if(h == INVALID_HANDLE)
     {
      PrintFormat("STATE[%s] cannot read %s (err %d)", InpRunTag, StateFile(),
                  GetLastError());
      return 0;
     }

   string head[];
   if(FileIsEnding(h) || StringSplit(FileReadString(h), ',', head) < 5
      || head[0] != MM_STATE_MAGIC || head[2] != InpRunTag)
     {
      FileClose(h);
      PrintFormat("STATE[%s] %s is not this instance's state -- ignored",
                  InpRunTag, StateFile());
      return 0;
     }

   const datetime saved = (datetime)StringToInteger(head[3]);
   if(TimeCurrent() - saved > MM_STATE_MAXAGE)
     {
      FileClose(h);
      FileDelete(StateFile());
      PrintFormat("STATE[%s] discarded: saved %s, older than %d days",
                  InpRunTag, TimeToString(saved), MM_STATE_MAXAGE / 86400);
      return 0;
     }

   int loaded = 0, bad = 0;
   while(!FileIsEnding(h))
     {
      const string line = FileReadString(h);
      if(StringLen(line) < 10)
         continue;
      string f[];
      if(StringSplit(line, ',', f) != MM_STATE_FIELDS)
        {
         bad++;
         continue;
        }

      MMVirtual v;
      v.active       = true;
      v.id           = (int)StringToInteger(f[0]);
      v.dir          = (int)StringToInteger(f[1]);
      v.open_time    = (datetime)StringToInteger(f[2]);
      v.bars_held    = (int)StringToInteger(f[3]);
      v.entry        = StringToDouble(f[4]);
      v.sl           = StringToDouble(f[5]);
      v.risk         = StringToDouble(f[6]);
      v.tp1          = StringToDouble(f[7]);
      v.tp2          = StringToDouble(f[8]);
      v.tp3          = StringToDouble(f[9]);
      v.mfe_r        = StringToDouble(f[10]);
      v.mae_r        = StringToDouble(f[11]);
      v.atr          = StringToDouble(f[12]);
      v.ema200       = StringToDouble(f[13]);
      v.ema_dist_atr = StringToDouble(f[14]);
      v.basis        = StringToDouble(f[15]);
      v.adx          = StringToDouble(f[16]);
      v.eff          = StringToDouble(f[17]);
      v.vol_ratio    = StringToDouble(f[18]);
      v.spread_pts   = StringToDouble(f[19]);
      v.mtf_agree    = (int)StringToInteger(f[20]);
      v.mtf_checked  = (int)StringToInteger(f[21]);
      v.vol_dots     = (int)StringToInteger(f[22]);
      v.tier         = (int)StringToInteger(f[23]);

      for(int p = 0; p < MM_POL_COUNT; p++)
        {
         const int b = 24 + p * 9;
         v.pol_open[p]    = (StringToInteger(f[b]) != 0);
         v.pol_r[p]       = StringToDouble(f[b + 1]);
         v.pol_bars[p]    = (int)StringToInteger(f[b + 2]);
         v.pol_reason[p]  = f[b + 3];
         v.pol_stop[p]    = StringToDouble(f[b + 4]);
         v.pol_locked[p]  = StringToDouble(f[b + 5]);
         v.pol_cost[p]    = StringToDouble(f[b + 6]);
         v.pol_sp_exit[p] = StringToDouble(f[b + 7]);
         v.pol_rungs[p]   = (int)StringToInteger(f[b + 8]);
        }

      if(v.risk <= 0.0 || v.entry <= 0.0)    // refuse nonsense rather than score it
        {
         bad++;
         continue;
        }

      const int n = ArraySize(g_trades);
      ArrayResize(g_trades, n + 1);
      g_trades[n] = v;
      loaded++;
      if(v.id > g_fire_seq)
         g_fire_seq = v.id;                  // never reuse a fire id
     }

   FileClose(h);
   FileDelete(StateFile());                  // consumed, so it can never replay
   PrintFormat("STATE[%s] restored %d in-flight virtual trade(s)%s (saved %s)",
               InpRunTag, loaded,
               (bad > 0 ? StringFormat(", %d row(s) REJECTED", bad) : ""),
               TimeToString(saved));
   return loaded;
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   SaveState();
   if(g_atr_handle   != INVALID_HANDLE) IndicatorRelease(g_atr_handle);
   if(g_ema_handle   != INVALID_HANDLE) IndicatorRelease(g_ema_handle);
   if(g_basis_handle != INVALID_HANDLE) IndicatorRelease(g_basis_handle);
   if(g_adx_handle   != INVALID_HANDLE) IndicatorRelease(g_adx_handle);
   g_dash.Release();
  }

//+------------------------------------------------------------------+
//| Seed the SuperTrend from history so the first live flip is real  |
//+------------------------------------------------------------------+
void WarmUp(void)
  {
   const int need = 500;
   const int bars = MathMin(need, Bars(_Symbol, _Period) - InpAtrPeriod - 2);
   if(bars <= 10)
      return;

   double atr[];
   ArraySetAsSeries(atr, true);
   if(CopyBuffer(g_atr_handle, 0, 0, bars + 2, atr) < bars)
      return;

   bool flipped;
   for(int i = bars; i >= 1; i--)
     {
      const double h = iHigh(_Symbol, _Period, i);
      const double l = iLow(_Symbol, _Period, i);
      const double c = iClose(_Symbol, _Period, i);
      if(h <= 0.0 || l <= 0.0 || c <= 0.0)
         continue;
      g_st.Update(h, l, c, atr[i], flipped);
     }
   g_last_bar = iTime(_Symbol, _Period, 0);
   PrintFormat("MM_ShadowLogger: warmed up over %d bars, direction=%d",
               bars, g_st.Direction());
  }

//+------------------------------------------------------------------+
bool EnsureHeader(void)
  {
   if(FileIsExist(g_file))
      return true;

   const int h = FileOpen(g_file, FILE_WRITE | FILE_CSV | FILE_ANSI, ',');
   if(h == INVALID_HANDLE)
     {
      PrintFormat("MM_ShadowLogger: cannot create %s (err %d)",
                  g_file, GetLastError());
      return false;
     }

   FileWrite(h,
             "run_tag", "fire_id", "symbol", "tf", "signal_time", "dir",
             "tier", "entry", "sl", "risk_price", "tp1", "tp2", "tp3",
             "atr", "ema200", "ema_dist_atr", "cloud_basis",
             "mtf_agree", "mtf_checked", "vol_dots", "vol_ratio",
             "adx", "eff_ratio", "spread_pts", "sensitivity",
             "close_time", "bars_held", "mfe_r", "mae_r",
             "r_tp1_0.5R",  "exit_tp1",
             "r_tp2_1.0R",  "exit_tp2",
             "r_tp3_1.5R",  "exit_tp3",
             "r_fixed_2R",  "exit_fixed_2R",
             "r_cloud_trail", "exit_cloud_trail",
             "r_be1R_trail",  "exit_be1R_trail",
             "r_half_tp1_trail", "exit_half_tp1_trail",
             "r_ladder", "exit_ladder",
             "spread_exit_max_pts",
             "c_tp1_0.5R", "c_tp2_1.0R", "c_tp3_1.5R", "c_fixed_2R",
             "c_cloud_trail", "c_be1R_trail", "c_half_tp1_trail", "c_ladder");
   FileClose(h);
   return true;
  }

//+------------------------------------------------------------------+
void OnTick(void)
  {
   //--- every tick, ahead of the new-bar gate: a locked book must be released
   //--- the moment it is green, and that window can close inside one bar
   if(InpTrade && InpCloseMixedInProfit)
      CheckMixedBookExit();

   if(InpTrade && UseBEAfterTP1)
      ProtectAfterTP1();

   const datetime t = iTime(_Symbol, _Period, 0);
   if(t == g_last_bar || t == 0)
      return;
   g_last_bar = t;

   //--- bar index 1 is the just-closed bar
   OnNewClosedBar();
  }

//+------------------------------------------------------------------+
void OnNewClosedBar(void)
  {
   double atr[1];
   if(CopyBuffer(g_atr_handle, 0, 1, 1, atr) != 1 || atr[0] <= 0.0)
      return;

   const double h = iHigh(_Symbol, _Period, 1);
   const double l = iLow(_Symbol, _Period, 1);
   const double c = iClose(_Symbol, _Period, 1);
   if(h <= 0.0 || l <= 0.0 || c <= 0.0)
      return;

   //--- 1. advance every open virtual trade over this bar FIRST,
   //---    using the SuperTrend direction as it stood BEFORE the flip.
   const int dir_before = g_st.Direction();
   UpdateVirtuals(h, l, c, dir_before);

   //--- 2. advance the signal engine
   bool flipped = false;
   const int dir_now = g_st.Update(h, l, c, atr[0], flipped);

   //--- 3. a flip closes trail-based policies on any opposing trade
   if(flipped)
      ApplyCloudFlip(dir_now);

   //--- 4. and may open a new fire
   if(flipped && dir_now != MM_DIR_NONE)
      TryFire(dir_now, c, atr[0]);
  }

//+------------------------------------------------------------------+
//| Build and record a signal                                        |
//+------------------------------------------------------------------+
void TryFire(const int dir, const double entry, const double atr)
  {
   double ema[1], basis[1], adx[1];
   if(CopyBuffer(g_ema_handle,   0, 1, 1, ema)   != 1) return;
   if(CopyBuffer(g_basis_handle, 0, 1, 1, basis) != 1) return;
   if(CopyBuffer(g_adx_handle,   0, 1, 1, adx)   != 1) adx[0] = 0.0;

   //--- tier classification
   int tier = MM_TIER_ALL;

   const bool smart_ok = (dir == MM_DIR_LONG)  ? (entry > ema[0])
                                               : (entry < ema[0]);
   int checked = 0;
   const int agree = g_dash.Agreement(dir, checked);

   double vol_ratio = 0.0;
   const int dots = MMVolumeDots(_Symbol, _Period, 1, InpVolLookback, vol_ratio);

   if(smart_ok)
     {
      tier = MM_TIER_SMART;
      if(agree >= InpMtfMinAgree && dots >= InpMinVolDots)
         tier = MM_TIER_SMARTP;
     }

   if(tier < InpMinTier)
      return;

   //--- stop
   double sl;
   if(InpStopMode == 1)
     {
      const double satr = WilderATR(InpStopAtrTF, InpStopAtrPeriod, 0);
      if(satr <= 0.0)
         return;
      sl = entry - dir * InpStopAtrMult * satr;
     }
   else
      sl = (dir == MM_DIR_LONG) ? basis[0] - InpCloudOuterATR * atr
                                : basis[0] + InpCloudOuterATR * atr;

   const double risk = MathAbs(entry - sl);
   if(risk <= 0.0 || risk < atr * 0.25)
      return;                          // degenerate geometry, skip

   MMVirtual v;
   ZeroMemory(v);
   v.active     = true;
   v.id         = ++g_fire_seq;
   v.dir        = dir;
   v.open_time  = iTime(_Symbol, _Period, 1);
   v.bars_held  = 0;
   v.entry      = entry;
   v.sl         = sl;
   v.risk       = risk;
   v.tp1        = entry + dir * InpRungR1 * risk;
   v.tp2        = entry + dir * InpRungR2 * risk;
   v.tp3        = entry + dir * InpRungR3 * risk;
   v.mfe_r      = 0.0;
   v.mae_r      = 0.0;

   v.atr          = atr;
   v.ema200       = ema[0];
   v.ema_dist_atr = (atr > 0.0) ? (entry - ema[0]) / atr : 0.0;
   v.basis        = basis[0];
   v.adx          = adx[0];
   v.eff          = MMEfficiencyRatio(_Symbol, _Period, 1, InpEffRatioBars);
   v.vol_ratio    = vol_ratio;
   v.vol_dots     = dots;
   v.mtf_agree    = agree;
   v.mtf_checked  = checked;
   v.tier         = tier;
   v.spread_pts   = (double)SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);

   for(int p = 0; p < MM_POL_COUNT; p++)
     {
      v.pol_open[p]   = true;
      v.pol_r[p]      = 0.0;
      v.pol_bars[p]   = 0;
      v.pol_reason[p] = "";
      v.pol_stop[p]   = sl;
      v.pol_locked[p] = 0.0;
      v.pol_cost[p]   = 0.0;
      v.pol_sp_exit[p]= 0.0;
      v.pol_rungs[p]  = 0;
     }

   const int n = ArraySize(g_trades);
   ArrayResize(g_trades, n + 1);
   g_trades[n] = v;

   //--- the shadow row above is already committed; the order below is a
   //--- side-effect and can fail without affecting the sample.
   if(InpTrade && (InpTradeSide == 0 || (InpTradeSide > 0) == (dir == MM_DIR_LONG)))
      OpenRealLadder(v);

   if(InpVerbose)
      PrintFormat("FIRE[%s] #%d %s tier=%d entry=%.2f sl=%.2f risk=%.2f "
                  "eff=%.2f adx=%.1f mtf=%d/%d vol=%d",
                  InpRunTag, v.id, (dir == MM_DIR_LONG ? "BUY" : "SELL"), tier,
                  entry, sl, risk, v.eff, v.adx, agree, checked, dots);
  }

//+------------------------------------------------------------------+
//| REAL orders. Everything below is optional and additive: none of it |
//| touches g_trades, the CSV, or the policy scoring.                  |
//+------------------------------------------------------------------+
//+------------------------------------------------------------------+
//| Wilder's ATR on any timeframe. MT5's iATR is an SMA of true range  |
//| and gives a materially different number, so it cannot be used for  |
//| a level fitted against a TradingView (RMA-smoothed) indicator.     |
//+------------------------------------------------------------------+
double WilderATR(const ENUM_TIMEFRAMES tf, const int period, const int shift)
  {
   const int need = period * 12 + shift + 2;   // long enough to converge
   MqlRates r[];
   ArraySetAsSeries(r, false);
   const int got = CopyRates(_Symbol, tf, 0, need, r);
   if(got < period + shift + 2)
      return 0.0;

   const int last = got - 1 - shift;           // shift 0 = the forming bar
   if(last < period)
      return 0.0;

   double atr = 0.0;
   for(int i = 1; i <= period; i++)            // seed: simple mean of the first TRs
     {
      const double tr = MathMax(r[i].high - r[i].low,
                        MathMax(MathAbs(r[i].high - r[i - 1].close),
                                MathAbs(r[i].low  - r[i - 1].close)));
      atr += tr;
     }
   atr /= period;
   for(int i = period + 1; i <= last; i++)     // then Wilder's recursive smoothing
     {
      const double tr = MathMax(r[i].high - r[i].low,
                        MathMax(MathAbs(r[i].high - r[i - 1].close),
                                MathAbs(r[i].low  - r[i - 1].close)));
      atr = (atr * (period - 1) + tr) / period;
     }
   return atr;
  }

int CountMyPositions(void)
  {
   int n = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      const ulong tk = PositionGetTicket(i);
      if(tk == 0 || !PositionSelectByTicket(tk))
         continue;
      if(PositionGetInteger(POSITION_MAGIC) == g_magic
         && PositionGetString(POSITION_SYMBOL) == _Symbol)
         n++;
     }
   return n;
  }

//--- direction of this instance's open book: +1 long, -1 short, 0 flat.
//--- Returns 0 for a mixed book too, which can only exist as a leftover from
//--- the pre-2026-09-08-F guard bug; the caller flattens it either way.
int MyPositionDir(void)
  {
   int longs = 0, shorts = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      const ulong tk = PositionGetTicket(i);
      if(tk == 0 || !PositionSelectByTicket(tk))
         continue;
      if(PositionGetInteger(POSITION_MAGIC) != g_magic
         || PositionGetString(POSITION_SYMBOL) != _Symbol)
         continue;
      if(PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY)
         longs++;
      else
         shorts++;
     }
   if(longs > 0 && shorts > 0)
      return 0;
   return (longs > 0) ? MM_DIR_LONG : (shorts > 0 ? MM_DIR_SHORT : 0);
  }

//+------------------------------------------------------------------+
//| A long and a short open together is a locked book: the legs offset,|
//| so time cannot improve it -- only a close can. Run this every TICK,|
//| not per bar, because the window where both sides are green can be  |
//| shorter than a minute.                                             |
//+------------------------------------------------------------------+
void CheckMixedBookExit(void)
  {
   int longs = 0, shorts = 0;
   double pl = 0.0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      const ulong tk = PositionGetTicket(i);
      if(tk == 0 || !PositionSelectByTicket(tk))
         continue;
      if(PositionGetInteger(POSITION_MAGIC) != g_magic
         || PositionGetString(POSITION_SYMBOL) != _Symbol)
         continue;
      if(PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY)
         longs++;
      else
         shorts++;
      //--- swap counted, commission is not: it sits on the deals, not the
      //--- position, so this reads a shade optimistic on a 0.01-lot book
      pl += PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
     }
   if(longs == 0 || shorts == 0)
      return;                                   // not a mixed book
   if(pl < InpMixedMinProfit)
      return;                                   // green, but not yet enough

   PrintFormat("REAL[%s] MIXED BOOK GREEN: %d long / %d short, combined %.2f "
               ">= %.2f -> closing all", InpRunTag, longs, shorts, pl,
               InpMixedMinProfit);
   CloseMyPositions("mixed book taken in profit");
  }

//+------------------------------------------------------------------+
//| BE AFTER TP1 -- once the TP1 rung is gone, protect the remainder. |
//|                                                                   |
//| State-free by construction: the ladder is identified by the rung   |
//| tags this EA writes (MM_<tag>_TP1/2/3) and "entry" is each         |
//| position's OWN open price, so a restart or a re-attach cannot lose |
//| track of it and nothing has to be persisted. Only ever TIGHTENS a  |
//| stop -- it can reduce exposure, never add it.                      |
//+------------------------------------------------------------------+
void ProtectAfterTP1(void)
  {
   const string tag1 = StringFormat("MM_%s_TP1", InpRunTag);
   bool tp1_open = false;
   int  rest = 0;

   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      const ulong tk = PositionGetTicket(i);
      if(tk == 0 || !PositionSelectByTicket(tk))
         continue;
      if(PositionGetInteger(POSITION_MAGIC) != g_magic
         || PositionGetString(POSITION_SYMBOL) != _Symbol)
         continue;
      if(PositionGetString(POSITION_COMMENT) == tag1)
         tp1_open = true;
      else
         rest++;
     }

   //--- nothing banked yet, or nothing left to protect
   if(tp1_open || rest == 0)
      return;

   const long stops = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   const double need = stops * g_point;

   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      const ulong tk = PositionGetTicket(i);
      if(tk == 0 || !PositionSelectByTicket(tk))
         continue;
      if(PositionGetInteger(POSITION_MAGIC) != g_magic
         || PositionGetString(POSITION_SYMBOL) != _Symbol)
         continue;

      const bool   is_long = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY);
      const double open    = PositionGetDouble(POSITION_PRICE_OPEN);
      const double cur_sl  = PositionGetDouble(POSITION_SL);
      const double tp      = PositionGetDouble(POSITION_TP);
      //--- the ladder's own risk: TP1 sits at 0.5R, so R = |open - sl_original|.
      //--- Use the live stop distance while it is still the original one; once
      //--- moved, there is nothing left to do for this position anyway.
      const double risk = MathAbs(open - cur_sl);
      if(risk <= 0.0)
         continue;

      double be = is_long ? open + BEOffsetR * risk : open - BEOffsetR * risk;
      be = NormalizeDouble(be, (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS));

      //--- tighten only
      const bool improves = is_long ? (be > cur_sl) : (be < cur_sl);
      if(!improves)
         continue;

      //--- refuse rather than have the broker silently move it
      const double px = is_long ? SymbolInfoDouble(_Symbol, SYMBOL_BID)
                                : SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      if(stops > 0 && MathAbs(px - be) < need)
         continue;
      if(is_long ? (be >= px) : (be <= px))      // already through it: leave the exit alone
         continue;

      if(g_trade.PositionModify(tk, be, tp))
         PrintFormat("REAL[%s] BE after TP1: ticket %I64u stop %.2f -> %.2f",
                     InpRunTag, tk, cur_sl, be);
      else
         PrintFormat("REAL[%s] BE after TP1 FAILED ticket %I64u: %d %s", InpRunTag,
                     tk, g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription());
     }
  }

//+------------------------------------------------------------------+
//--- build K: age of the open ladder, read from the BROKER (restart-safe)
datetime MyOldestOpenTime(void)
  {
   datetime oldest = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      const ulong tk = PositionGetTicket(i);
      if(tk == 0 || !PositionSelectByTicket(tk))
         continue;
      if(PositionGetInteger(POSITION_MAGIC) != g_magic
         || PositionGetString(POSITION_SYMBOL) != _Symbol)
         continue;
      const datetime ot = (datetime)PositionGetInteger(POSITION_TIME);
      if(oldest == 0 || ot < oldest)
         oldest = ot;
     }
   return oldest;
  }

//--- build K: is this fire on the trend side of the alignment EMA?
//--- build L: server-hour window for OPENING a ladder. Closing/reversing is never gated.
bool InTradeWindow(void)
  {
   if(InpTradeStartHour == 0 && InpTradeEndHour == 23)
      return true;
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   if(InpTradeStartHour <= InpTradeEndHour)
      return (dt.hour >= InpTradeStartHour && dt.hour <= InpTradeEndHour);
   return (dt.hour >= InpTradeStartHour || dt.hour <= InpTradeEndHour);
  }

bool AlignedWithTrend(const int dir, const double entry)
  {
   if(InpAlignEmaPeriod <= 0 || g_align_handle == INVALID_HANDLE)
      return true;
   double e[1];
   if(CopyBuffer(g_align_handle, 0, 1, 1, e) != 1)   // last CLOSED bar on the EMA TF
      return false;
   return (dir == MM_DIR_LONG) ? (entry > e[0]) : (entry < e[0]);
  }

int CloseMyPositions(const string why)
  {
   int closed = 0;
   for(int pass = 0; pass < 3; pass++)          // retry: tickets shift as they close
     {
      bool any = false;
      for(int i = PositionsTotal() - 1; i >= 0; i--)
        {
         const ulong tk = PositionGetTicket(i);
         if(tk == 0 || !PositionSelectByTicket(tk))
            continue;
         if(PositionGetInteger(POSITION_MAGIC) != g_magic
            || PositionGetString(POSITION_SYMBOL) != _Symbol)
            continue;
         any = true;
         if(g_trade.PositionClose(tk))
            closed++;
         else
            PrintFormat("REAL[%s] close FAILED ticket %I64u: %d", InpRunTag, tk,
                        g_trade.ResultRetcode());
        }
      if(!any)
         break;
     }
   if(closed > 0)
      PrintFormat("REAL[%s] closed %d position(s): %s", InpRunTag, closed, why);
   return closed;
  }

void OpenRealLadder(const MMVirtual &v)
  {
   //--- What he does, established 2026-09-08: a new arrow can print while the
   //--- previous trade is still partly open (his 05:02 sell had banked TP1 and
   //--- TP2, its stop untouched, when the 06:03 buy printed). So "wait until
   //--- flat" is ruled out by his own behaviour -- it is what made us skip the
   //--- 12:40 signal our engine had matched to 3 cents. An opposite signal
   //--- therefore CLOSES the book and takes the new side; a same-side signal is
   //--- ignored, since nothing observed suggests he pyramids.
   const int have = MyPositionDir();
   if(have != 0 && have == v.dir)
      return;                                   // already on this side
   //--- build K: minimum hold. An opposite signal inside the window is ignored
   //--- entirely -- it neither cuts the open ladder nor opens its own.
   if(have != 0 && InpMinHoldMinutes > 0)
     {
      const datetime t0 = MyOldestOpenTime();
      if(t0 > 0 && (TimeCurrent() - t0) < (long)InpMinHoldMinutes * 60)
        {
         PrintFormat("REAL[%s] #%d ignored: opposite signal %d s into a %d-min hold",
                     InpRunTag, v.id, (int)(TimeCurrent() - t0), InpMinHoldMinutes);
         return;
        }
     }
   if(have != 0 || CountMyPositions() > 0)
     {
      if(!InpReverseOnOpposite)
         return;
      CloseMyPositions(have == 0 ? "mixed book cleared"
                                 : "reversed by opposite signal");
     }

   //--- cap AFTER any reversal, counting positions rather than ladders: a
   //--- partially-filled ladder used to slip past a ladder-count check and let
   //--- a long and a short run side by side.
   if(CountMyPositions() + 3 > InpMaxOpen)
      return;

   //--- build K: alignment gate AFTER the reversal -- a counter-trend signal
   //--- still cuts the old ladder (the trigger flipped), it just does not
   //--- open its own.
   if(!AlignedWithTrend(v.dir, v.entry))
     {
      PrintFormat("REAL[%s] #%d skipped: %s not aligned with EMA%d(%s)",
                  InpRunTag, v.id, (v.dir == MM_DIR_LONG ? "BUY" : "SELL"),
                  InpAlignEmaPeriod, EnumToString(InpAlignEmaTF));
      return;
     }

   //--- build L: trading window AFTER the reversal and the alignment gate -- an
   //--- out-of-window opposite signal still cuts the old ladder, it just does not
   //--- open its own (15-month replay: 22:00-08:59 server keeps the ladder positive
   //--- in both halves, every other hour bucket loses in both).
   if(!InTradeWindow())
     {
      MqlDateTime dtw;
      TimeToStruct(TimeCurrent(), dtw);
      PrintFormat("REAL[%s] #%d skipped: hour %02d outside trade window %02d-%02d",
                  InpRunTag, v.id, dtw.hour, InpTradeStartHour, InpTradeEndHour);
      return;
     }

   const double minlot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   const double step   = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double rung = MathMax(InpLotsPerRung, minlot);
   if(step > 0.0)
      rung = MathRound(rung / step) * step;
   rung = NormalizeDouble(rung, 2);

   //--- refuse rather than distort: a stop or target inside the broker's
   //--- minimum distance would be silently moved and the R-multiple would lie
   const long stops = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   const double need = stops * g_point;
   if(stops > 0 && (MathAbs(v.entry - v.sl) < need
                    || MathAbs(v.entry - v.tp1) < need))
     {
      PrintFormat("REAL[%s] skipped #%d: stop/TP1 inside stops-level %d pts",
                  InpRunTag, v.id, (int)stops);
      return;
     }

   //--- one position per published rung, each carrying its own target and the
   //--- shared stop. This IS his ladder, and the broker fills each rung at its
   //--- level instead of at whatever price the next bar opens at.
   const double tps[3] = {v.tp1, v.tp2, v.tp3};
   int placed = 0;
   for(int r = 0; r < 3; r++)
     {
      const string tag = StringFormat("MM_%s_TP%d", InpRunTag, r + 1);
      const bool ok = (v.dir == MM_DIR_LONG)
                      ? g_trade.Buy(rung, _Symbol, 0.0, v.sl, tps[r], tag)
                      : g_trade.Sell(rung, _Symbol, 0.0, v.sl, tps[r], tag);
      if(ok)
         placed++;
      else
         PrintFormat("REAL[%s] rung %d FAILED on #%d: %d %s", InpRunTag, r + 1,
                     v.id, g_trade.ResultRetcode(),
                     g_trade.ResultRetcodeDescription());
     }

   if(placed > 0)
      PrintFormat("REAL[%s] OPEN #%d %s %d rungs x %.2f @%.2f  sl %.2f  "
                  "tp %.2f / %.2f / %.2f", InpRunTag, v.id,
                  (v.dir == MM_DIR_LONG ? "BUY" : "SELL"), placed, rung,
                  v.entry, v.sl, v.tp1, v.tp2, v.tp3);
  }

//+------------------------------------------------------------------+
//| Advance every open virtual trade over one closed bar             |
//|                                                                  |
//| Intrabar ordering is unknowable from bar data, so when a bar     |
//| touches both the stop and the target the STOP is assumed first.  |
//| That biases every result pessimistically, which is the correct   |
//| direction to be wrong in when deciding whether to risk money.    |
//+------------------------------------------------------------------+
void UpdateVirtuals(const double bar_h, const double bar_l,
                    const double bar_c, const int cur_dir)
  {
   for(int i = 0; i < ArraySize(g_trades); i++)
     {
      if(!g_trades[i].active)
         continue;

      g_trades[i].bars_held++;

      const int    dir   = g_trades[i].dir;
      const double entry = g_trades[i].entry;
      const double risk  = g_trades[i].risk;

      //--- excursions in R
      const double fav = (dir == MM_DIR_LONG) ? (bar_h - entry) : (entry - bar_l);
      const double adv = (dir == MM_DIR_LONG) ? (bar_l - entry) : (entry - bar_h);
      const double fav_r = fav / risk;
      const double adv_r = adv / risk;
      if(fav_r > g_trades[i].mfe_r) g_trades[i].mfe_r = fav_r;
      if(adv_r < g_trades[i].mae_r) g_trades[i].mae_r = adv_r;

      for(int p = 0; p < MM_POL_COUNT; p++)
        {
         if(!g_trades[i].pol_open[p])
            continue;

         g_trades[i].pol_bars[p]++;

         const double stop = g_trades[i].pol_stop[p];
         const bool stop_hit = (dir == MM_DIR_LONG) ? (bar_l <= stop)
                                                    : (bar_h >= stop);

         //--- pessimistic: stop resolves before any target on the same bar
         if(stop_hit)
           {
            const double raw = dir * (stop - entry) / risk;
            //--- a scale-out that already banked half only has half left running
            double r = raw;
            if(p == MM_POL_SCALE && g_trades[i].pol_locked[p] > 0.0)
               r = g_trades[i].pol_locked[p] + 0.5 * raw;
            else if(p == MM_POL_LADDER && g_trades[i].pol_rungs[p] > 0)
              {
               const double left = 1.0 - g_trades[i].pol_rungs[p] / 3.0;
               r = g_trades[i].pol_locked[p] + left * raw;
              }
            ClosePolicy(i, p, r, (MathAbs(raw) < 0.0001 ? "be_stop" : "stop"));
            continue;
           }

         //--- fixed-target policies
         double target = 0.0;
         switch(p)
           {
            case MM_POL_TP1:   target = g_trades[i].tp1;                 break;
            case MM_POL_TP2:   target = g_trades[i].tp2;                 break;
            case MM_POL_TP3:   target = g_trades[i].tp3;                 break;
            case MM_POL_FIX2R: target = entry + dir * 2.0 * risk;        break;
            default:           target = 0.0;                             break;
           }

         if(target != 0.0)
           {
            const bool tp_hit = (dir == MM_DIR_LONG) ? (bar_h >= target)
                                                     : (bar_l <= target);
            if(tp_hit)
              {
               ClosePolicy(i, p, dir * (target - entry) / risk, "target");
               continue;
              }
           }

         //--- BE management at +1R
         if(p == MM_POL_BE_TRAIL && fav_r >= 1.0)
           {
            const double be = entry;
            const bool improved = (dir == MM_DIR_LONG) ? (be > g_trades[i].pol_stop[p])
                                                       : (be < g_trades[i].pol_stop[p]);
            if(improved)
               g_trades[i].pol_stop[p] = be;
           }

         //--- THE VENDOR'S OWN EXIT: a third banked at each published rung.
         //--- No cloud-flip exit and no stop move -- he publishes TP1/TP2/TP3 and
         //--- a fixed stop, and nothing observed says he does anything else.
         if(p == MM_POL_LADDER)
           {
            for(int rung = g_trades[i].pol_rungs[p]; rung < 3; rung++)
              {
               const double tgt = (rung == 0) ? g_trades[i].tp1
                                  : (rung == 1) ? g_trades[i].tp2 : g_trades[i].tp3;
               const bool hit = (dir == MM_DIR_LONG) ? (bar_h >= tgt) : (bar_l <= tgt);
               if(!hit)
                  break;
               g_trades[i].pol_locked[p] += (1.0 / 3.0) * (0.5 * (rung + 1));
               g_trades[i].pol_rungs[p]   = rung + 1;
              }
            if(g_trades[i].pol_rungs[p] >= 3)
              {
               ClosePolicy(i, p, g_trades[i].pol_locked[p], "ladder_full");
               continue;
              }
           }

         //--- scale-out: bank half at TP1, leave the rest trailing
         if(p == MM_POL_SCALE && g_trades[i].pol_locked[p] == 0.0)
           {
            const double t1 = g_trades[i].tp1;
            const bool hit = (dir == MM_DIR_LONG) ? (bar_h >= t1) : (bar_l <= t1);
            if(hit)
              {
               g_trades[i].pol_locked[p] = 0.5 * 0.5;   // half position at 0.5R
               const double be = entry;
               const bool improved = (dir == MM_DIR_LONG)
                                     ? (be > g_trades[i].pol_stop[p])
                                     : (be < g_trades[i].pol_stop[p]);
               if(improved)
                  g_trades[i].pol_stop[p] = be;
              }
           }

         //--- timeout
         if(g_trades[i].pol_bars[p] >= InpMaxBarsInTrade)
           {
            const double raw_to = dir * (bar_c - entry) / risk;
            double r_to = raw_to;
            if(p == MM_POL_SCALE && g_trades[i].pol_locked[p] > 0.0)
               r_to = g_trades[i].pol_locked[p] + 0.5 * raw_to;
            else if(p == MM_POL_LADDER && g_trades[i].pol_rungs[p] > 0)
              {
               const double left = 1.0 - g_trades[i].pol_rungs[p] / 3.0;
               r_to = g_trades[i].pol_locked[p] + left * raw_to;
              }
            ClosePolicy(i, p, r_to, "timeout");
           }
        }

      RetireIfDone(i);
     }
   Compact();
  }

//+------------------------------------------------------------------+
//| SuperTrend flipped: close every trail-based policy still open    |
//+------------------------------------------------------------------+
void ApplyCloudFlip(const int new_dir)
  {
   const double px = iClose(_Symbol, _Period, 1);

   for(int i = 0; i < ArraySize(g_trades); i++)
     {
      if(!g_trades[i].active)
         continue;
      if(g_trades[i].dir == new_dir)
         continue;                    // flip agrees with us, nothing to do

      const int dir = g_trades[i].dir;
      const double r = dir * (px - g_trades[i].entry) / g_trades[i].risk;

      int trail_pols[3] = {MM_POL_TRAIL, MM_POL_BE_TRAIL, MM_POL_SCALE};
      for(int k = 0; k < 3; k++)
        {
         const int p = trail_pols[k];
         if(!g_trades[i].pol_open[p])
            continue;

         double realised = r;
         if(p == MM_POL_SCALE && g_trades[i].pol_locked[p] > 0.0)
            realised = g_trades[i].pol_locked[p] + 0.5 * r;   // half already banked

         ClosePolicy(i, p, realised, "cloud_flip");
        }
      RetireIfDone(i);
     }
   Compact();
  }

//+------------------------------------------------------------------+
void ClosePolicy(const int idx, const int p, const double r_raw,
                 const string reason)
  {
   double r = r_raw;
   double cost_r = 0.0;
   const double sp_exit = (double)SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);

   //--- Charge the spread against every result, in R terms.
   //--- The spread that matters is NOT only the one quoted when the signal
   //--- fired: M1 gold widens precisely when a stop is being taken out, so a
   //--- signal-time-only charge understates the cost of losers and leaves the
   //--- cost of winners about right. Charge the mean of entry and exit spread,
   //--- and record what was charged so the analyzer can stress it.
   if(InpChargeSpread && g_trades[idx].risk > 0.0)
     {
      const double sp_avg     = 0.5 * (g_trades[idx].spread_pts + sp_exit);
      const double cost_price = sp_avg * g_point * InpSpreadCostR;
      cost_r = cost_price / g_trades[idx].risk;
      r -= cost_r;
     }

   g_trades[idx].pol_open[p]    = false;
   g_trades[idx].pol_r[p]       = r;
   g_trades[idx].pol_reason[p]  = reason;
   g_trades[idx].pol_cost[p]    = cost_r;
   g_trades[idx].pol_sp_exit[p] = sp_exit;
  }

//+------------------------------------------------------------------+
void RetireIfDone(const int idx)
  {
   for(int p = 0; p < MM_POL_COUNT; p++)
      if(g_trades[idx].pol_open[p])
         return;

   WriteRow(idx);
   g_trades[idx].active = false;
  }

//+------------------------------------------------------------------+
void Compact(void)
  {
   int w = 0;
   const int n = ArraySize(g_trades);
   for(int i = 0; i < n; i++)
      if(g_trades[i].active)
        {
         if(w != i)
            g_trades[w] = g_trades[i];
         w++;
        }
   if(w != n)
      ArrayResize(g_trades, w);
  }

//+------------------------------------------------------------------+
void WriteRow(const int i)
  {
   const int h = FileOpen(g_file, FILE_READ | FILE_WRITE | FILE_CSV | FILE_ANSI, ',');
   if(h == INVALID_HANDLE)
     {
      PrintFormat("MM_ShadowLogger: cannot append to %s (err %d)",
                  g_file, GetLastError());
      return;
     }
   FileSeek(h, 0, SEEK_END);

   //--- widest spread seen at any of this fire's seven exits: the diagnostic
   //--- for "does the spread blow out exactly when we are being stopped?"
   double sp_exit_max = 0.0;
   for(int p = 0; p < MM_POL_COUNT; p++)
      if(g_trades[i].pol_sp_exit[p] > sp_exit_max)
         sp_exit_max = g_trades[i].pol_sp_exit[p];

   FileWrite(h,
             InpRunTag,
             IntegerToString(g_trades[i].id),
             _Symbol,
             EnumToString((ENUM_TIMEFRAMES)_Period),
             TimeToString(g_trades[i].open_time, TIME_DATE | TIME_SECONDS),
             (g_trades[i].dir == MM_DIR_LONG ? "BUY" : "SELL"),
             IntegerToString(g_trades[i].tier),
             DoubleToString(g_trades[i].entry, _Digits),
             DoubleToString(g_trades[i].sl, _Digits),
             DoubleToString(g_trades[i].risk, _Digits),
             DoubleToString(g_trades[i].tp1, _Digits),
             DoubleToString(g_trades[i].tp2, _Digits),
             DoubleToString(g_trades[i].tp3, _Digits),
             DoubleToString(g_trades[i].atr, _Digits),
             DoubleToString(g_trades[i].ema200, _Digits),
             DoubleToString(g_trades[i].ema_dist_atr, 3),
             DoubleToString(g_trades[i].basis, _Digits),
             IntegerToString(g_trades[i].mtf_agree),
             IntegerToString(g_trades[i].mtf_checked),
             IntegerToString(g_trades[i].vol_dots),
             DoubleToString(g_trades[i].vol_ratio, 3),
             DoubleToString(g_trades[i].adx, 2),
             DoubleToString(g_trades[i].eff, 4),
             DoubleToString(g_trades[i].spread_pts, 1),
             DoubleToString(InpSensitivity, 2),
             TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS),
             IntegerToString(g_trades[i].bars_held),
             DoubleToString(g_trades[i].mfe_r, 4),
             DoubleToString(g_trades[i].mae_r, 4),
             DoubleToString(g_trades[i].pol_r[MM_POL_TP1], 4),
             g_trades[i].pol_reason[MM_POL_TP1],
             DoubleToString(g_trades[i].pol_r[MM_POL_TP2], 4),
             g_trades[i].pol_reason[MM_POL_TP2],
             DoubleToString(g_trades[i].pol_r[MM_POL_TP3], 4),
             g_trades[i].pol_reason[MM_POL_TP3],
             DoubleToString(g_trades[i].pol_r[MM_POL_FIX2R], 4),
             g_trades[i].pol_reason[MM_POL_FIX2R],
             DoubleToString(g_trades[i].pol_r[MM_POL_TRAIL], 4),
             g_trades[i].pol_reason[MM_POL_TRAIL],
             DoubleToString(g_trades[i].pol_r[MM_POL_BE_TRAIL], 4),
             g_trades[i].pol_reason[MM_POL_BE_TRAIL],
             DoubleToString(g_trades[i].pol_r[MM_POL_SCALE], 4),
             g_trades[i].pol_reason[MM_POL_SCALE],
             DoubleToString(g_trades[i].pol_r[MM_POL_LADDER], 4),
             g_trades[i].pol_reason[MM_POL_LADDER],
             DoubleToString(sp_exit_max, 1),
             DoubleToString(g_trades[i].pol_cost[MM_POL_TP1], 5),
             DoubleToString(g_trades[i].pol_cost[MM_POL_TP2], 5),
             DoubleToString(g_trades[i].pol_cost[MM_POL_TP3], 5),
             DoubleToString(g_trades[i].pol_cost[MM_POL_FIX2R], 5),
             DoubleToString(g_trades[i].pol_cost[MM_POL_TRAIL], 5),
             DoubleToString(g_trades[i].pol_cost[MM_POL_BE_TRAIL], 5),
             DoubleToString(g_trades[i].pol_cost[MM_POL_SCALE], 5),
             DoubleToString(g_trades[i].pol_cost[MM_POL_LADDER], 5));

   FileClose(h);

   if(InpVerbose)
      PrintFormat("CLOSED[%s] #%d  ladder=%.2fR  tp3=%.2fR  trail=%.2fR  "
                  "be+trail=%.2fR  mfe=%.2fR mae=%.2fR",
                  InpRunTag, g_trades[i].id,
                  g_trades[i].pol_r[MM_POL_LADDER],
                  g_trades[i].pol_r[MM_POL_TP3],
                  g_trades[i].pol_r[MM_POL_TRAIL],
                  g_trades[i].pol_r[MM_POL_BE_TRAIL],
                  g_trades[i].mfe_r, g_trades[i].mae_r);
  }
//+------------------------------------------------------------------+
