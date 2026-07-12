//+------------------------------------------------------------------+
//| GENERATED FILE -- LOCKED GOLD config. Do NOT edit by hand.       
//| Regenerate after any master change:  python make_locked_eas.py    
//+------------------------------------------------------------------+
//+------------------------------------------------------------------+
//|  Marius GridStat GOLD v1.0 -- BUILD 2026-07-10-T                 |
//|  + RIDE TRIGGER SWEEP enablement: OnTester returns RECOVERY       |
//|    FACTOR (net/equityDD) in trade mode -> optimize on 'Custom'    |
//|    to map the ride's inverted-U (fib C Pass-A style; Session 22   |
//|    tested only -12%, fib C's winner lived at -3% + trail).        |
//|  + UseRecoveryTrail: fib C parity -- trail the recovered book     |
//|    from its post-target peak instead of flat-closing at +$30.     |
//|  + STAGED FLOOR (UseStagedFloor, user-designed LIVE 2026-07-09:   |
//|    resting SL on the worst leg turned a near-certain -$388 floor  |
//|    into a -$28 episode): cut the single WORST leg at -15% of      |
//|    balance -- lightens the basket, pulls the escape closer,       |
//|    pushes the floor away. Composable with the recovery ride.      |
//|  + MaxFibMult (0 by default = base unchanged): caps the Fibonacci  |
//|    multiplier of grid ADD legs. The fib ladder (1,1,2,3,5) is a    |
//|    martingale that puts the BIGGEST lots at the WORST prices --    |
//|    the 0.10 leg nearest the May-12 top carried 40% of the -$2,924  |
//|    floor loss. MaxFibMult=1 = FLAT adds (float at the extreme      |
//|    shrinks ~60%, all 6 observed floor events become survivable,    |
//|    escapes arrive 1-3 days later); =2 = capped ladder (1,1,2,2,2). |
//|    Same lever fib C got (gentler ladder, session 19r build C).     |
//|  + FLOOR-HEDGE v2 (UseFloorHedge, OFF by default = base unchanged):|
//|    at the -BasketMaxLossPct floor, HEDGE 1:1 by market order       |
//|    (freeze the loss) instead of realizing it; add overtake legs    |
//|    only on CONFIRMED continuation (new extremes beyond the freeze  |
//|    price) so a real breakout carries the book to the normal +$    |
//|    escape ("hedged to profit"); release the hedge when price comes |
//|    back through the freeze price (failed breakout -> grid resumes).|
//|    Fixes the Session-22 ride defects: fires AT the floor (grid     |
//|    keeps its full recovery domain), no Goldminer exhaustion        |
//|    entries, ruin backstop at FloorHedgeRuinPct.                    |
//|  + RECOVERY RIDE (UseRecoveryRide, OFF by default = base unchanged):|
//|    when a basket floats deep against a SUSTAINED trend, STOP adding|
//|    grid legs and RIDE the winning (trend) side on subsequent      |
//|    Goldminer signals (overriding session/D1/gate) until the whole |
//|    book climbs back to +RecoveryTargetUSD, then close all in      |
//|    profit. Fib C's mechanism; the basket floor stays the backstop.|
//|  + risk-normalized sizing (UseRiskNormalizedLots, OFF by default):|
//|    sizes 1R = RiskPctPerTrade% of balance + volatility skip, so    |
//|    silver/oil aren't over-risked vs gold. GOLD UNCHANGED (flag off)|
//|  + grisk optimization: OnTester returns total shadow R so the MT4 |
//|    optimizer (criterion=Custom, shadow mode) finds best grisk/symbol|
//|  + RISK FIX: basket catastrophic floor (UseBasketStop, % balance) |
//|    + trailing exit only for SINGLE positions; grid baskets use the |
//|    fast "+$ and out" recovery escape (build-M trailing starved it, |
//|    causing the Dec-29 grid cascade -> margin call). BE-SL tp guard |
//|  LIVE trailing exit (UseTrailingExit): R-scaled, activate 1R/give 0.6R |
//|  + SHADOW exit comparison: logs fixed-barrier R, trailing-exit R, |
//|    and MFE per signal (mfe_r/trail_hit/trail_r cols) so the exit  |
//|    rule can be measured & tuned PER SYMBOL before deploying        |
//|  + expected-R sizing table (gridstat_sizing.csv): sizes each      |
//|    entry by confidence, skips only negative-expectancy setups     |
//|  + live-close journal: logs every closed position to             |
//|    gridstat_live_<symbol>.csv for the Python learning loop       |
//|  BreakEvenTriggerR tuned 0.5 -> 0.7 + demo deployment ready      |
//|  Triple-barrier signal edge measurement + hedged grid trader     |
//|                                                                  |
//|  SHADOW MODE (StatsCollectionMode=true, no trades):              |
//|    Every signal -> log to pending list with upper/lower/time barriers
//|    Each tick -> check pending: which barrier hit first? log outcome
//|    Outcome columns: barrier_hit (UPPER/LOWER/TIME), R_multiple   |
//|                                                                  |
//|  TRADE MODE (StatsCollectionMode=false):                         |
//|    Lookup signal's setup in stats DB, only trade if win_rate >=  |
//|    MinWinRate AND samples >= MinSamples. Use hedged grid for exec|
//+------------------------------------------------------------------+
#property strict

#define EA_BUILD_VERSION "2026-07-12-T-GOLD-LOCKED"
#define MAX_PENDING 5000

//--- Mode switches
const bool StatsCollectionMode   = false;    // SHADOW mode: no trades, just barrier tracking. SET TO FALSE FOR TRADE MODE.  // LOCKED (was input)
const bool StatsFilterEnabled    = true;     // TRADE mode: filter by historical win rate. SET TO TRUE FOR TRADE MODE.  // LOCKED (was input)
const double MinWinRate            = 0.55;     // Legacy win-rate gate (used only if UseSizingTable=false)  // LOCKED (was input)
const int MinSamples            = 10;  // LOCKED (was input)
const string StatsCSVFile          = "gridstat_setups.csv";  // LOCKED (was input)

//--- Expected-R sizing table (AFML rigor: sizes bets, replaces win-rate gate)
const bool UseSizingTable        = false;     // size by expected-R table; skip only negative-expectancy setups  // LOCKED (was input)
const string SizingCSVFile         = "gridstat_sizing.csv";  // LOCKED (was input)
const double MaxSizeMult           = 2.0;      // safety cap on per-setup size multiplier  // LOCKED (was input)

//--- Triple-barrier parameters
const double BarrierATRMultiplier  = 0.8;     // upper/lower barriers at +/- ATR(D1) * this (tighter = more decisive outcomes)  // LOCKED (was input)
const int TimeBarrierBars       = 288;     // time barrier in M5 bars (288 = 24h)  // LOCKED (was input)

//--- Trailing exit (SHADOW comparison logs it; live TRADE uses it when UseTrailingExit=true)
const bool UseTrailingExit       = false;     // live: R-scaled trailing basket exit instead of fixed $ ProfitTargetUSD  // LOCKED (was input)
const double TrailActivateR        = 1.0;      // activate trailing once favorable excursion reaches this R  // LOCKED (was input)
const double TrailDistanceR        = 0.6;      // trail this many R behind the running peak (GOLD optimum; tune per symbol)  // LOCKED (was input)

//--- Entry / signal
const int MA_Period             = 20;  // LOCKED (was input)
const double MA_Angle_Threshold    = 20.0;  // LOCKED (was input)
const int ADX_Period            = 14;  // LOCKED (was input)
const double ADX_Threshold         = 25.0;  // LOCKED (was input)
const int grisk                 = 4;  // LOCKED (was input)
const int countbars             = 300;  // LOCKED (was input)
const int goldminershift        = 1;  // LOCKED (was input)

//--- D1 trend filter
const bool UseDailyTrendFilter   = true;  // LOCKED (was input)
const int DailyMA_Period        = 50;  // LOCKED (was input)

//--- Session filter
const bool UseSessionFilter      = true;  // LOCKED (was input)
const int SessionStartHour      = 9;  // LOCKED (was input)
const int SessionEndHour        = 23;  // LOCKED (was input)

//--- Lot sizing (TRADE mode only)
const double LotSize               = 0.02;  // LOCKED (was input)
const bool UseCompounding        = true;  // LOCKED (was input)
const double CompoundingBase       = 3000.0;  // LOCKED (was input)
//--- Grid-ladder shaping (Session 23): cap the fib multiplier of grid legs.
//    0 = original fib ladder 1,1,2,3,5,8 (martingale: biggest lots at the worst prices --
//    the deep legs carried 40%+ of every observed floor loss). 1 = FLAT legs (all = base lot:
//    float at the adverse extreme shrinks ~60%, every observed floor event becomes survivable;
//    escapes need a slightly deeper retrace = 1-3 days later). 2 = capped ladder 1,1,2,2,2.
const int MaxFibMult            = 0;  // LOCKED (was input)

//--- Risk-normalized sizing (OFF by default -- gold keeps fixed LotSize; ON for volatile symbols like silver/oil)
const bool UseRiskNormalizedLots = false;    // size each trade so 1R = RiskPctPerTrade% of balance (equalizes $ risk across symbols)  // LOCKED (was input)
const double RiskPctPerTrade       = 3.0;      // target risk per trade as % of balance (gold-equivalent ~4%)  // LOCKED (was input)
const double MaxRiskPctSkip        = 8.0;      // skip the trade if even min-lot 1R risk exceeds this % of balance (too volatile to size safely)  // LOCKED (was input)

//--- Hedged grid (TRADE mode only)
const bool UseATRSpacing         = true;  // LOCKED (was input)
const double ATRSpacingMultiplier  = 0.5;  // LOCKED (was input)
const int GridSpacingMinPoints  = 300;  // LOCKED (was input)
const int GridSpacingMaxPoints  = 2000;  // LOCKED (was input)
const int MaxGridLevels         = 6;  // LOCKED (was input)
const bool UseHedge              = true;  // LOCKED (was input)
const int HedgeBreakEvenPoints  = 15000;  // LOCKED (was input)
const double HedgeRatio            = 1.0;  // LOCKED (was input)
const double ProfitTargetUSD       = 100.0;   // grid-recovery escape: bail basket at this small profit  // LOCKED (was input)
const int MaxDaysOpen           = 30;  // LOCKED (was input)

//--- Basket catastrophic floor (account survival — the grid has no inherent stop)
const bool UseBasketStop         = true;     // close the whole basket if loss exceeds BasketMaxLossPct of balance  // LOCKED (was input)
const double BasketMaxLossPct      = 20.0;     // % of account balance — hard per-basket loss cap  // LOCKED (was input)

//--- Recovery ride (fib C mechanism, OFF by default = base config byte-identical):
//    when the basket floats deep against a SUSTAINED trend, STOP feeding the loser
//    and RIDE the winning (trend) side until the whole book recovers to +target,
//    then close all in profit. The basket floor (above) stays the V-reversal backstop.
const bool UseRecoveryRide       = false;    // enable the recovery-ride escape (Session-22 tested ONE trigger [-12%]; fib C's winner = -3% + trail -> SWEEP RecoveryTriggerPct on the RF OnTester before any verdict)  // LOCKED (was input)
const double RecoveryTriggerPct    = 12.0;     // arm when combined float <= -this% of balance (must be < BasketMaxLossPct; fib C locked = 3)  // LOCKED (was input)
const double RecoveryTargetUSD     = 30.0;     // close the whole book once combined float reaches +this  // LOCKED (was input)
const int MaxRideLegs           = 6;        // cap on winning-side legs opened during recovery  // LOCKED (was input)
const double MaxRideLotsTotal      = 0.60;     // cap on total winning-side lots during recovery  // LOCKED (was input)
const bool UseRecoveryTrail      = false;    // fib C parity (its LOCKED config trails): once book >= target, TRAIL from the peak instead of flat-closing  // LOCKED (was input)
const double RecoveryTrailGivebackPct = 15.0;  // close all when the book retraces this % from its post-target peak  // LOCKED (was input)

//--- STAGED FLOOR (user-designed LIVE 2026-07-09: a resting SL on the worst leg turned a
//    near-certain -$388 floor into a -$28 episode -- the leg-cut pulled the escape closer
//    [4104->4109, and gold only gave 4109] AND pushed the floor away [4139->4148]).
//    When the basket floats <= -StagedFloorPct% of balance, close the single WORST leg
//    (biggest $ loser), lightening the basket before the catastrophic floor.
//    Composable with UseRecoveryRide (cut the worst leg while riding the winner).
input bool UseStagedFloor        = false;    // cut the worst leg early (default OFF = base unchanged)
input double StagedFloorPct        = 12.0;     // ...at combined float <= -this% of balance (must be < BasketMaxLossPct)

//--- FLOOR-HEDGE v2 (Session 23; OFF by default = base config byte-identical).
//    The redesign of "hedge the loser to profit" that fixes the Session-22 ride's four defects:
//    (a) fires AT the -BasketMaxLossPct floor, REPLACING the loss realization -- the grid keeps its
//        full recovery domain up to the floor (the ride armed at -12% and disabled the working edge);
//    (b) the freeze is an immediate 1:1 MARKET hedge -- entries do NOT wait for Goldminer signals
//        (a surge-COMPLETION detector = worst possible continuation entry);
//    (c) OVERTAKE legs are added only on CONFIRMED continuation: each new adverse extreme
//        FH_ConfirmATR x ATR(D1) beyond the freeze price adds FH_OvertakeStep x basket lots
//        (capped at FH_OvertakeMaxRatio x basket lots) -> in a REAL breakout the winning side
//        exceeds the basket and the book climbs to the normal +ProfitTargetUSD escape
//        ("hedged to profit"); FH_OvertakeStep=0 = pure freeze mode for A/B isolation;
//    (d) RELEASE on confirmed reversal: price back through the freeze price by FH_ReleaseATR x ATR
//        in the basket's favor = the breakout failed -> close hedge legs only, the grid resumes its
//        own recovery to the +$ escape. FloorHedgeRuinPct = the absolute backstop (the floor's floor).
//    Do NOT enable together with UseRecoveryRide. Validate every-tick on a window that CONTAINS
//    the July-2026 live breakout floor-hit; judge per floor-hit event (rescue vs churn), not only net.
const bool UseFloorHedge         = false;    // at the floor: hedge/freeze instead of closing  // LOCKED (was input)
const double FloorHedgeRuinPct     = 30.0;     // absolute ruin backstop (% balance) while hedged  // LOCKED (was input)
const double FH_ConfirmATR         = 0.75;     // continuation step: new extreme this xATR(D1) beyond freeze price adds an overtake leg  // LOCKED (was input)
const double FH_OvertakeStep       = 0;      // overtake leg = this x basket lots per confirmed step (0 = pure freeze)  // LOCKED (was input)
const double FH_OvertakeMaxRatio   = 2.0;      // total opposite-side lots <= this x basket lots  // LOCKED (was input)
const double FH_ReleaseATR         = 0.5;      // release: price back through the freeze price by this xATR in the basket's favor  // LOCKED (was input)

//--- Optimizations (session 14)
const bool UseBreakEvenSL        = true;     // OPT 1: move SL to entry when +0.5R profit reached  // LOCKED (was input)
const double BreakEvenTriggerR     = 0.7;      // OPT 1: trigger at this R-multiple (0.7 = let winners breathe more)  // LOCKED (was input)
const double MaxBasketLotsTotal    = 0.30;     // OPT 2: hard cap on basket lots per direction  // LOCKED (was input)
const bool SkipGridAfterSL       = true;     // OPT 3: suppress grid expansion if recent SL hit  // LOCKED (was input)
const int SkipGridAfterSLHours  = 4;        // OPT 3: lookback hours  // LOCKED (was input)

//--- Magic
const string CommentText           = "GridStat";  // LOCKED (was input)

//--- Globals
int      MagicNumber = 0;
double   point;
datetime lastBarTime = 0;

// Pending signal tracking (triple-barrier)
string   pSetup[MAX_PENDING];
int      pDir[MAX_PENDING];
datetime pEntryTime[MAX_PENDING];
double   pEntryPrice[MAX_PENDING];
double   pUpperBarrier[MAX_PENDING];
double   pLowerBarrier[MAX_PENDING];
datetime pTimeBarrier[MAX_PENDING];
double   pAtrAtEntry[MAX_PENDING];
// Shadow exit-comparison state (per pending signal)
double   pPeakR[MAX_PENDING];      // max favorable excursion in R (MFE)
bool     pActivated[MAX_PENDING];  // trailing stop activated
double   pFixedR[MAX_PENDING];     // fixed-barrier outcome R (locked at first barrier touch)
string   pFixedHit[MAX_PENDING];   // fixed-barrier hit type (UPPER/LOWER/TIME)
bool     pFixedDone[MAX_PENDING];  // fixed outcome locked
int      pCount = 0;

// Live-close journal: track open tickets -> setup fingerprint so each close can
// be logged to a permanent live-only CSV (analytics layer reads this; backtests
// never write it, so it survives optimisation runs). See LogLiveClose section.
#define MAX_LIVE_TRACK 256
int      g_liveTickets[MAX_LIVE_TRACK];
string   g_liveSetup[MAX_LIVE_TRACK];
int      g_liveCount = 0;
string   g_clusterSetup = "";   // fingerprint of the current cluster's signal entry
double   g_clusterSizeMult = 1.0; // size multiplier of current cluster (sizing table)
double   g_peakBasketFloat = 0.0; // running peak of basket float $ (trailing exit)
double   g_shadowTotalR = 0.0;    // SHADOW: sum of fixed-barrier R (grisk optimization objective)
bool     g_recovering   = false;  // recovery-ride armed (UseRecoveryRide)
int      g_rideDir      = -1;     // winning side ridden during recovery (opposite the losing basket)
double   g_recoveryPeak = 0.0;    // post-target peak of the recovered book (UseRecoveryTrail)
datetime g_lastStageBar = 0;      // staged floor: at most one worst-leg cut per bar
double   g_fhLastAnchor = 0.0;    // floor-hedge re-arm hysteresis: last freeze price (0 = none)
int      g_fhLastDir    = -1;     // basket direction of the last freeze (re-freeze only at a NEW adverse extreme)

//+------------------------------------------------------------------+
int OnInit() {

   // ---- LOCKED-EA GUARD (generated by make_locked_eas.py; do NOT edit this file by hand)
   if(_Symbol != "GOLD" && _Symbol != "XAUUSD")
   {
      Print("LOCKED GOLD EA attached to WRONG symbol: ", _Symbol, " (accepts: GOLD/XAUUSD). ABORTING.");
      return(INIT_FAILED);
   }
   Print("LOCKED GOLD EA -- all inputs hard-coded (generated 2026-07-12); only StagedFloor levers visible");
    MagicNumber = GenerateMagic("GridStat", Symbol(), Period());
    point = (Digits == 3 || Digits == 5) ? Point * 10 : Point;
    Print("============================================================");
    Print("MARIUS GRIDSTAT GOLD ", EA_BUILD_VERSION, " | Magic=", MagicNumber);
    Print("Mode: ", (StatsCollectionMode ? "SHADOW (no trades)" : "TRADING"),
          " | Filter: ", StatsFilterEnabled,
          " | BarrierATR x", BarrierATRMultiplier,
          " | TimeBarrier ", TimeBarrierBars, " bars");
    Print("CONFIG | MaxFibMult=", MaxFibMult, " (0=fib ladder, 1=flat legs, 2=capped)",
          " UseCompounding=", UseCompounding, " LotSize=", DoubleToString(LotSize,2));
    Print("CONFIG | UseRecoveryRide=", UseRecoveryRide,
          " UseFloorHedge=", UseFloorHedge,
          " Ruin=", DoubleToString(FloorHedgeRuinPct,1),
          "% ConfirmATR=", DoubleToString(FH_ConfirmATR,2),
          " OvertakeStep=", DoubleToString(FH_OvertakeStep,2),
          " MaxRatio=", DoubleToString(FH_OvertakeMaxRatio,2),
          " ReleaseATR=", DoubleToString(FH_ReleaseATR,2));
    Print("CONFIG | RecoveryTriggerPct=", DoubleToString(RecoveryTriggerPct,1),
          " RecoveryTargetUSD=", DoubleToString(RecoveryTargetUSD,0),
          " UseRecoveryTrail=", UseRecoveryTrail,
          " Giveback=", DoubleToString(RecoveryTrailGivebackPct,1),
          "% | UseStagedFloor=", UseStagedFloor,
          " StagedFloorPct=", DoubleToString(StagedFloorPct,1), "%");
    if (UseFloorHedge && UseRecoveryRide)
        Print("WARNING: UseFloorHedge and UseRecoveryRide are BOTH on -- they conflict; enable only one.");
    Print("============================================================");
    // Initialize fresh CSV in shadow mode
    if (StatsCollectionMode) {
        int fh = FileOpen(StatsCSVFile, FILE_WRITE|FILE_CSV|FILE_COMMON, ',');
        if (fh != INVALID_HANDLE) {
            FileWrite(fh, "setup_key","entry_time","entry_price","direction",
                          "upper_barrier","lower_barrier","time_barrier",
                          "atr_at_entry","barrier_hit","r_multiple","outcome_time",
                          "mfe_r","trail_hit","trail_r");
            FileClose(fh);
        }
    }
    // Adopt any positions already open at (re)start so their close still logs.
    if (!StatsCollectionMode) AdoptOpenTickets();
    return INIT_SUCCEEDED;
}

int GenerateMagic(string eaName, string sym, int tf) {
    int hash = 0;
    string s = eaName + sym + IntegerToString(tf);
    for (int i = 0; i < StringLen(s); i++) hash += StringGetChar(s, i) * (i + 1);
    return hash % 100000 + 50000;
}

// SHADOW mode: total signal R (grisk optimization). TRADE mode: RECOVERY FACTOR
// (net / equity DD) -- the fib C sweep metric; optimize with criterion = Custom
// to map the ride-trigger / staged-floor inverted-U.
double OnTester()
{
    ExportBacktestResults();
    if (StatsCollectionMode) return g_shadowTotalR;
    double dd  = TesterStatistics(STAT_EQUITY_DD);
    double net = TesterStatistics(STAT_PROFIT);
    return (dd > 0) ? net / dd : net;
}

//+------------------------------------------------------------------+
void OnTick() {
    RefreshRates();

    bool newBar = (Time[0] != lastBarTime);
    if (newBar) lastBarTime = Time[0];

    // SHADOW MODE: check pending signals against barriers
    if (StatsCollectionMode) CheckPendingBarriers();

    // TRADE MODE: manage hedged grid + break-even SL
    if (!StatsCollectionMode) {
        TrackLiveCloses();      // journal any positions closed since last tick
        ManageBreakEvenSL();
        ManageGrid();
    }

    // Only consider new signal entries on a NEW bar (Goldminer fires every tick)
    if (!newBar) return;

    // Goldminer signal (computed BEFORE the session/D1 gates so the recovery-ride
    // can override them; behaviour for normal entries is unchanged — Goldminer has
    // no side effects, and we still return at the same gates below when not recovering)
    double gred   = iCustom(NULL, 0, "goldminer1", grisk, countbars, 0, goldminershift);
    double ggreen = iCustom(NULL, 0, "goldminer1", grisk, countbars, 1, goldminershift);
    if (gred == EMPTY_VALUE || ggreen == EMPTY_VALUE) return;

    int signalDir = -1;
    if (ggreen > 0) signalDir = OP_BUY;
    if (gred   > 0) signalDir = OP_SELL;
    if (signalDir < 0) return;

    // RECOVERY RIDE: while armed, ride ONLY the winning (trend) side and OVERRIDE the
    // session/D1/win-rate gates. ManageGrid stops feeding the losing basket. This is
    // the whole point — the trend that's flooring the basket becomes the rescue.
    if (!StatsCollectionMode && g_recovering) {
        if (signalDir == g_rideDir) OpenRideLeg(signalDir);
        return;
    }

    // Session gate (normal entries only)
    if (UseSessionFilter) {
        int hr = TimeHour(TimeCurrent());
        if (!(hr >= SessionStartHour && hr < SessionEndHour)) return;
    }

    if (UseDailyTrendFilter) {
        bool d1Bull = IsDailyTrendBullish();
        if (signalDir == OP_BUY && !d1Bull) return;
        if (signalDir == OP_SELL && d1Bull) return;
    }
    if (!IsTrendStrong()) return;

    string setupKey = ClassifySetup(signalDir);

    // SHADOW MODE: add to pending barriers
    if (StatsCollectionMode) {
        AddPendingSignal(setupKey, signalDir);
        return;
    }

    // TRADE MODE: size by expected-R table (preferred) or legacy win-rate gate
    double sizeMult = 1.0;
    if (UseSizingTable) {
        if (!LookupSizing(setupKey, sizeMult)) {
            Print("Sizing: no table entry for ", setupKey, " - skip");
            return;
        }
        if (sizeMult <= 0.0) {
            Print("Sizing: ", setupKey, " negative-expectancy (mult=0) - skip");
            return;
        }
        if (sizeMult > MaxSizeMult) sizeMult = MaxSizeMult;
        Print("Sizing PASS: ", setupKey, " mult=", DoubleToString(sizeMult,2));
    }
    else if (StatsFilterEnabled) {
        double wr = 0; int samples = 0;
        if (!LookupSetupStats(setupKey, wr, samples)) {
            Print("Filter: no stats for ", setupKey, " - skip");
            return;
        }
        if (samples < MinSamples || wr < MinWinRate) {
            Print("Filter: ", setupKey, " wr=", DoubleToString(wr,3), " n=", samples, " - skip");
            return;
        }
        Print("Filter PASS: ", setupKey, " wr=", DoubleToString(wr,3), " n=", samples);
    }
    if (BasketLotCount() > 0) return;
    g_clusterSizeMult = sizeMult;                         // applied to grid legs too
    double lot;
    if (UseRiskNormalizedLots) {
        lot = RiskNormalizedLot(0);
        if (lot < 0) { Print("Vol skip: ", setupKey, " 1R risk > ", MaxRiskPctSkip, "% balance"); return; }
        lot = NormalizeDouble(lot * sizeMult, 2);
    } else {
        lot = NormalizeDouble(CalculateLot(0) * sizeMult, 2);
    }
    double minLot = MarketInfo(Symbol(), MODE_MINLOT);
    if (lot < minLot) lot = minLot;
    OpenSimpleSLTP(signalDir, lot, setupKey);
}

// Open with hard SL at -BarrierATR and TP at +BarrierATR (mirrors stats methodology)
void OpenSimpleSLTP(int dir, double lot, string setupKey) {
    double atrD1 = iATR(NULL, PERIOD_D1, 14, 1);
    double barrierDist = atrD1 * BarrierATRMultiplier;
    double price = (dir == OP_BUY) ? MarketInfo(Symbol(), MODE_ASK) : MarketInfo(Symbol(), MODE_BID);
    double sl, tp;
    if (dir == OP_BUY) { sl = price - barrierDist; tp = price + barrierDist; }
    else               { sl = price + barrierDist; tp = price - barrierDist; }
    if (UseTrailingExit) tp = 0;   // trailing basket exit manages the profit side (let winners run)
    int t = OrderSend(Symbol(), dir, lot, price, 3, sl, tp, CommentText + "_SLTP", MagicNumber, 0,
                     (dir == OP_BUY ? clrBlue : clrRed));
    if (t > 0) {
        g_clusterSetup = setupKey;          // remember for any grid legs/hedge in this cluster
        RegisterLiveTicket(t, setupKey);
        Print("Trade opened: ", (dir==OP_BUY?"BUY":"SELL"), " ", DoubleToString(lot,2),
              " @ ", price, " SL=", sl, " TP=", tp, " setup=", setupKey);
    }
    else       Print("OpenSimpleSLTP failed err=", GetLastError());
}

//+------------------------------------------------------------------+
//| Triple-barrier shadow tracking                                    |
//+------------------------------------------------------------------+
void AddPendingSignal(string setupKey, int dir) {
    if (pCount >= MAX_PENDING) {
        Print("Pending signals buffer full, dropping oldest");
        RemovePendingAt(0);
    }
    double atrD1 = iATR(NULL, PERIOD_D1, 14, 1);
    double entryPx = (dir == OP_BUY) ? MarketInfo(Symbol(), MODE_ASK) : MarketInfo(Symbol(), MODE_BID);
    double barrierDist = atrD1 * BarrierATRMultiplier;

    pSetup[pCount]        = setupKey;
    pDir[pCount]          = dir;
    pEntryTime[pCount]    = TimeCurrent();
    pEntryPrice[pCount]   = entryPx;
    pUpperBarrier[pCount] = entryPx + barrierDist;
    pLowerBarrier[pCount] = entryPx - barrierDist;
    pTimeBarrier[pCount]  = TimeCurrent() + TimeBarrierBars * 60 * Period();
    pAtrAtEntry[pCount]   = atrD1;
    pPeakR[pCount]        = 0.0;
    pActivated[pCount]    = false;
    pFixedR[pCount]       = 0.0;
    pFixedHit[pCount]     = "";
    pFixedDone[pCount]    = false;
    pCount++;
}

void RemovePendingAt(int idx) {
    if (idx < 0 || idx >= pCount) return;
    for (int i = idx; i < pCount - 1; i++) {
        pSetup[i]        = pSetup[i+1];
        pDir[i]          = pDir[i+1];
        pEntryTime[i]    = pEntryTime[i+1];
        pEntryPrice[i]   = pEntryPrice[i+1];
        pUpperBarrier[i] = pUpperBarrier[i+1];
        pLowerBarrier[i] = pLowerBarrier[i+1];
        pTimeBarrier[i]  = pTimeBarrier[i+1];
        pAtrAtEntry[i]   = pAtrAtEntry[i+1];
        pPeakR[i]        = pPeakR[i+1];
        pActivated[i]    = pActivated[i+1];
        pFixedR[i]       = pFixedR[i+1];
        pFixedHit[i]     = pFixedHit[i+1];
        pFixedDone[i]    = pFixedDone[i+1];
    }
    pCount--;
}

// Tracks TWO exit strategies per signal in one pass:
//   FIXED   = original triple barrier (locked at first +/-1R touch)  -> barrier_hit, r_multiple
//   TRAIL   = let winners run: activate at TrailActivateR, trail TrailDistanceR
//             behind the peak; same -1R hard stop on the adverse side  -> trail_hit, trail_r
// Also logs MFE (pPeakR) so Python can model ANY trail distance offline, per symbol.
// All R-based, so distances auto-scale to each symbol's ATR (GOLD/SILVER/OIL).
void CheckPendingBarriers() {
    double barHigh = High[0];
    double barLow  = Low[0];

    for (int i = pCount - 1; i >= 0; i--) {
        double barrierDist = pUpperBarrier[i] - pEntryPrice[i];
        if (barrierDist <= 0) { RemovePendingAt(i); continue; }
        bool isBuy = (pDir[i] == OP_BUY);

        // favorable peak / adverse worst this bar, in R
        double favPeakR  = (isBuy ? (barHigh - pEntryPrice[i]) : (pEntryPrice[i] - barLow))  / barrierDist;
        double advWorstR = (isBuy ? (barLow  - pEntryPrice[i]) : (pEntryPrice[i] - barHigh)) / barrierDist;
        if (favPeakR > pPeakR[i]) pPeakR[i] = favPeakR;

        bool favHit = (isBuy ? (barHigh >= pUpperBarrier[i]) : (barLow  <= pLowerBarrier[i]));
        bool advHit = (isBuy ? (barLow  <= pLowerBarrier[i]) : (barHigh >= pUpperBarrier[i]));

        // ---- FIXED-barrier outcome: lock once, but do NOT terminate on the favorable side ----
        if (!pFixedDone[i]) {
            if (favHit)      { pFixedR[i] =  1.0; pFixedHit[i] = (isBuy ? "UPPER" : "LOWER"); pFixedDone[i] = true; }
            else if (advHit) { pFixedR[i] = -1.0; pFixedHit[i] = (isBuy ? "LOWER" : "UPPER"); pFixedDone[i] = true; }
        }

        // ---- activate trailing once peak reaches threshold ----
        if (!pActivated[i] && pPeakR[i] >= TrailActivateR) pActivated[i] = true;

        // ---- adverse hard stop (-1R) terminates both strategies if trailing never armed ----
        if (advHit && !pActivated[i]) {
            if (!pFixedDone[i]) { pFixedR[i] = -1.0; pFixedHit[i] = (isBuy ? "LOWER" : "UPPER"); pFixedDone[i] = true; }
            WriteOutcome(i, "STOP", -1.0);
            RemovePendingAt(i);
            continue;
        }

        // ---- trailing stop exit (after activation) ----
        if (pActivated[i]) {
            double trailStopR = pPeakR[i] - TrailDistanceR;
            if (advWorstR <= trailStopR) {
                if (!pFixedDone[i]) { pFixedR[i] = 1.0; pFixedHit[i] = (isBuy ? "UPPER" : "LOWER"); pFixedDone[i] = true; }
                WriteOutcome(i, "TRAIL", trailStopR);
                RemovePendingAt(i);
                continue;
            }
        }

        // ---- time barrier: both strategies close at current R ----
        if (TimeCurrent() >= pTimeBarrier[i]) {
            double curPx = isBuy ? MarketInfo(Symbol(), MODE_BID) : MarketInfo(Symbol(), MODE_ASK);
            double curR  = (isBuy ? (curPx - pEntryPrice[i]) : (pEntryPrice[i] - curPx)) / barrierDist;
            if (!pFixedDone[i]) { pFixedR[i] = curR; pFixedHit[i] = "TIME"; pFixedDone[i] = true; }
            WriteOutcome(i, "TIME", curR);
            RemovePendingAt(i);
            continue;
        }
    }
}

// barrier_hit / r_multiple columns carry the FIXED strategy (from pFixed* arrays);
// trailHit / trailR carry the TRAILING strategy; mfe_r is the max favorable excursion.
void WriteOutcome(int idx, string trailHit, double trailR) {
    g_shadowTotalR += pFixedR[idx];   // accumulate signal edge for grisk optimization
    int fh = FileOpen(StatsCSVFile, FILE_READ|FILE_WRITE|FILE_CSV|FILE_COMMON, ',');
    if (fh == INVALID_HANDLE) return;
    FileSeek(fh, 0, SEEK_END);
    FileWrite(fh,
        pSetup[idx],
        TimeToString(pEntryTime[idx], TIME_DATE|TIME_MINUTES),
        DoubleToString(pEntryPrice[idx], 2),
        (pDir[idx] == OP_BUY) ? "BUY" : "SELL",
        DoubleToString(pUpperBarrier[idx], 2),
        DoubleToString(pLowerBarrier[idx], 2),
        TimeToString(pTimeBarrier[idx], TIME_DATE|TIME_MINUTES),
        DoubleToString(pAtrAtEntry[idx], 2),
        pFixedHit[idx],
        DoubleToString(pFixedR[idx], 3),
        TimeToString(TimeCurrent(), TIME_DATE|TIME_MINUTES),
        DoubleToString(pPeakR[idx], 3),
        trailHit,
        DoubleToString(trailR, 3));
    FileClose(fh);
}

//+------------------------------------------------------------------+
//| Signal helpers                                                    |
//+------------------------------------------------------------------+
bool IsDailyTrendBullish() {
    double m0 = iMA(NULL, PERIOD_D1, DailyMA_Period, 0, MODE_EMA, PRICE_CLOSE, 0);
    double m1 = iMA(NULL, PERIOD_D1, DailyMA_Period, 0, MODE_EMA, PRICE_CLOSE, 1);
    return (m0 > m1);
}

bool IsTrendStrong() {
    double maAngle = GetMAAngle(MA_Period);
    double adx = iADX(Symbol(), PERIOD_CURRENT, ADX_Period, 0, MODE_MAIN, 0);
    return (adx > ADX_Threshold && MathAbs(maAngle) > MA_Angle_Threshold);
}

double GetMAAngle(int period) {
    double m0 = iMA(NULL, 0, period, 0, MODE_EMA, PRICE_CLOSE, 0);
    double m1 = iMA(NULL, 0, period, 0, MODE_EMA, PRICE_CLOSE, 5);
    double slope = (m0 - m1) / (5 * point);
    return MathArctan(slope) * 180.0 / M_PI;
}

double LotScale() {
    if (!UseCompounding || CompoundingBase <= 0) return 1.0;
    return MathMax(1.0, MathFloor(AccountBalance() / CompoundingBase));
}

double CalculateLot(int gridLevel) {
    double base = LotSize * LotScale();
    int fib[] = {1, 1, 2, 3, 5, 8, 13, 21};
    int idx = (gridLevel < 0) ? 0 : (gridLevel > 7 ? 7 : gridLevel);
    int mult = fib[idx];
    if (MaxFibMult > 0 && mult > MaxFibMult) mult = MaxFibMult;   // ladder cap (0 = original fib)
    return NormalizeDouble(base * mult, 2);
}

// Size so 1R (the SL distance = barrierDist) costs RiskPctPerTrade% of balance,
// equalizing $ risk across instruments regardless of their ATR. Returns -1 to
// signal a volatility skip (even min lot risks more than MaxRiskPctSkip%).
// Only called when UseRiskNormalizedLots=true; gold (flag off) never reaches here.
double RiskNormalizedLot(int gridLevel) {
    double atrD1 = iATR(NULL, PERIOD_D1, 14, 1);
    double barrierDist = atrD1 * BarrierATRMultiplier;
    double tickSize = MarketInfo(Symbol(), MODE_TICKSIZE);
    double dollarPerPricePerLot = (tickSize > 0) ? MarketInfo(Symbol(), MODE_TICKVALUE) / tickSize : 0;
    if (barrierDist <= 0 || dollarPerPricePerLot <= 0)
        return CalculateLot(gridLevel);   // safe fallback if market info unavailable

    double minLot = MarketInfo(Symbol(), MODE_MINLOT);
    double riskPerMinLot = barrierDist * dollarPerPricePerLot * minLot;
    if (riskPerMinLot > MaxRiskPctSkip / 100.0 * AccountBalance())
        return -1.0;                      // too volatile to size safely -> caller skips

    double targetRisk = RiskPctPerTrade / 100.0 * AccountBalance();
    double baseLot = targetRisk / (barrierDist * dollarPerPricePerLot);
    int fib[] = {1, 1, 2, 3, 5, 8, 13, 21};
    int idx = (gridLevel < 0) ? 0 : (gridLevel > 7 ? 7 : gridLevel);
    int multRN = fib[idx];
    if (MaxFibMult > 0 && multRN > MaxFibMult) multRN = MaxFibMult;   // ladder cap (0 = original fib)
    double lot = NormalizeDouble(baseLot * multRN, 2);
    double maxLot = MarketInfo(Symbol(), MODE_MAXLOT);
    if (lot < minLot) lot = minLot;
    if (maxLot > 0 && lot > maxLot) lot = maxLot;
    return lot;
}

// COARSE fingerprint: DIRECTION | SESSION | ATR_REGIME
// ~12 buckets total, gives ~15-20 samples each over 6 months
string ClassifySetup(int dir) {
    string dirStr = (dir == OP_BUY) ? "BUY" : "SELL";
    int hr = TimeHour(TimeCurrent());
    string hrB = (hr < 9) ? "HR_ASIA" : (hr < 14) ? "HR_LDN" : (hr < 18) ? "HR_OVL" : "HR_NY";
    double atrNow = iATR(NULL, 0, 20, 1);
    double atrAvg = iATR(NULL, 0, 100, 1);
    string atrB;
    if (atrAvg == 0) atrB = "ATR_NA";
    else if (atrNow > atrAvg * 1.3) atrB = "ATR_EXP";
    else if (atrNow < atrAvg * 0.7) atrB = "ATR_COMP";
    else                            atrB = "ATR_NORM";
    return dirStr + "|" + hrB + "|" + atrB;
}

bool LookupSetupStats(string setupKey, double &winRate, int &samples) {
    int fh = FileOpen(StatsCSVFile, FILE_READ|FILE_CSV|FILE_COMMON, ',');
    if (fh == INVALID_HANDLE) return false;
    int wins = 0, total = 0;
    // skip header (14 cells)
    for (int i = 0; i < 14; i++) FileReadString(fh);
    while (!FileIsEnding(fh)) {
        string key = FileReadString(fh);
        if (key == "") break;
        for (int j = 0; j < 7; j++) FileReadString(fh);  // skip middle
        string barrierHit = FileReadString(fh);
        string rStr = FileReadString(fh);
        string outTime = FileReadString(fh);
        for (int z = 0; z < 3; z++) FileReadString(fh);  // skip mfe_r, trail_hit, trail_r
        if (key == setupKey) {
            total++;
            double r = StrToDouble(rStr);
            if (r > 0) wins++;
        }
    }
    FileClose(fh);
    samples = total;
    if (total == 0) { winRate = 0; return false; }
    winRate = (double)wins / (double)total;
    return true;
}

// Look up the expected-R size multiplier for a setup from gridstat_sizing.csv.
// Columns: setup_key, size_mult, eff_n, avg_r, t_stat, tier (6 cells/row).
// Returns false if the setup is absent (unknown edge -> caller skips).
bool LookupSizing(string setupKey, double &mult) {
    int fh = FileOpen(SizingCSVFile, FILE_READ|FILE_CSV|FILE_COMMON, ',');
    if (fh == INVALID_HANDLE) return false;
    for (int i = 0; i < 6; i++) FileReadString(fh);   // skip header
    bool found = false;
    while (!FileIsEnding(fh)) {
        string key = FileReadString(fh);
        if (key == "") break;
        string mStr = FileReadString(fh);
        for (int j = 0; j < 4; j++) FileReadString(fh);  // eff_n,avg_r,t_stat,tier
        if (key == setupKey) { mult = StrToDouble(mStr); found = true; break; }
    }
    FileClose(fh);
    return found;
}

//+------------------------------------------------------------------+
//| Live-close journal (analytics layer feed)                        |
//| Writes one row per closed position to a PERMANENT live-only CSV  |
//| (gridstat_live_<symbol>.csv). Backtests never write this file,   |
//| so live results survive optimisation runs. Pure logging - never  |
//| touches execution.                                                |
//+------------------------------------------------------------------+
string LiveFileName() {
    string sym = Symbol();
    StringToLower(sym);   // MQL4: modifies in place, returns bool
    return "gridstat_live_" + sym + ".csv";
}

void RegisterLiveTicket(int ticket, string setupKey) {
    if (g_liveCount >= MAX_LIVE_TRACK) return;
    for (int i = 0; i < g_liveCount; i++)
        if (g_liveTickets[i] == ticket) return;   // already tracked
    g_liveTickets[g_liveCount] = ticket;
    g_liveSetup[g_liveCount]   = (setupKey == "") ? "UNKNOWN" : setupKey;
    g_liveCount++;
}

// Reconstruct DIRECTION|SESSION|? from an order's open time (regime unknown at
// restart - the analytics layer resolves it from the approved-setup table).
string ReconstructSetup(int dir, datetime openTime) {
    string dirStr = (dir == OP_BUY) ? "BUY" : "SELL";
    int hr = TimeHour(openTime);
    string hrB = (hr < 9) ? "HR_ASIA" : (hr < 14) ? "HR_LDN" : (hr < 18) ? "HR_OVL" : "HR_NY";
    return dirStr + "|" + hrB + "|?";
}

// On (re)start, adopt positions already open for this magic so their eventual
// close still gets journalled (in-memory tracking was lost on recompile).
void AdoptOpenTickets() {
    g_liveCount = 0;
    for (int i = OrdersTotal()-1; i >= 0; i--) {
        if (!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
        if (OrderMagicNumber() != MagicNumber) continue;
        if (OrderType() != OP_BUY && OrderType() != OP_SELL) continue;
        // restart safety: if a recovery ride was in progress, re-arm from its legs
        if (StringFind(OrderComment(), "_RCV") >= 0) { g_recovering = true; g_rideDir = OrderType(); }
        string key = ReconstructSetup(OrderType(), OrderOpenTime());
        if (g_clusterSetup == "") g_clusterSetup = key;
        RegisterLiveTicket(OrderTicket(), key);
    }
    if (g_liveCount > 0) Print("Adopted ", g_liveCount, " open ticket(s) for live journal");
    if (g_recovering) Print("Recovery ride RE-ARMED on restart: ride=", (g_rideDir==OP_BUY?"BUY":"SELL"));
}

// Append the currently-selected (closed) order to the live CSV.
void WriteLiveClose(string setupKey) {
    double op = OrderOpenPrice();
    double cl = OrderClosePrice();
    double tp = OrderTakeProfit();
    int    dir = OrderType();
    double pnl = OrderProfit() + OrderSwap() + OrderCommission();
    // realized R relative to the barrier distance baked into TP at entry
    string rStr = "";
    double barrier = MathAbs(tp - op);
    if (barrier > 0) {
        double move = (dir == OP_BUY) ? (cl - op) : (op - cl);
        rStr = DoubleToString(move / barrier, 3);
    }
    int fh = FileOpen(LiveFileName(), FILE_READ|FILE_WRITE|FILE_CSV|FILE_COMMON, ',');
    if (fh == INVALID_HANDLE) { Print("WriteLiveClose: open failed ", GetLastError()); return; }
    bool isNew = (FileSize(fh) == 0);
    FileSeek(fh, 0, SEEK_END);
    if (isNew)
        FileWrite(fh, "open_time","close_time","type","lots","open_price",
                      "close_price","profit","comment","setup_key","realized_r");
    FileWrite(fh,
        TimeToString(OrderOpenTime(),  TIME_DATE|TIME_MINUTES),
        TimeToString(OrderCloseTime(), TIME_DATE|TIME_MINUTES),
        (dir == OP_BUY) ? "BUY" : "SELL",
        DoubleToString(OrderLots(), 2),
        DoubleToString(op, 2),
        DoubleToString(cl, 2),
        DoubleToString(pnl, 2),
        OrderComment(),
        setupKey,
        rStr);
    FileClose(fh);
    Print("LiveClose logged: ", (dir==OP_BUY?"BUY":"SELL"), " ", setupKey,
          " profit=", DoubleToString(pnl,2), " R=", rStr);
}

// Each tick: any tracked ticket no longer open -> log it and stop tracking.
void TrackLiveCloses() {
    for (int i = g_liveCount - 1; i >= 0; i--) {
        int ticket = g_liveTickets[i];
        if (!OrderSelect(ticket, SELECT_BY_TICKET)) continue;  // can't read yet, retry next tick
        if (OrderCloseTime() == 0) continue;                   // still open
        WriteLiveClose(g_liveSetup[i]);
        g_liveTickets[i] = g_liveTickets[g_liveCount-1];       // compact array
        g_liveSetup[i]   = g_liveSetup[g_liveCount-1];
        g_liveCount--;
    }
}

//+------------------------------------------------------------------+
//| Trade execution (TRADE mode only)                                |
//+------------------------------------------------------------------+
int BasketLotCount() {
    int c = 0;
    for (int i = OrdersTotal()-1; i >= 0; i--) {
        if (!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
        if (OrderMagicNumber() != MagicNumber) continue;
        if (OrderType() == OP_BUY || OrderType() == OP_SELL) c++;
    }
    return c;
}

bool OpenGridLevel(int dir, double lot, int gridLvl) {
    double price = (dir == OP_BUY) ? MarketInfo(Symbol(), MODE_ASK) : MarketInfo(Symbol(), MODE_BID);
    string cmt = CommentText + "_L" + IntegerToString(gridLvl);
    int t = OrderSend(Symbol(), dir, lot, price, 3, 0, 0, cmt, MagicNumber, 0,
                     (dir == OP_BUY ? clrBlue : clrRed));
    if (t > 0) {
        RegisterLiveTicket(t, g_clusterSetup);
        Print("GridLevel ", gridLvl, " opened: ", (dir==OP_BUY?"BUY":"SELL"),
              " ", DoubleToString(lot,2), " @ ", price);
        return true;
    }
    Print("GridLevel open failed err=", GetLastError());
    return false;
}

bool OpenHedge(int hedgeDir, double lot) {
    double price = (hedgeDir == OP_BUY) ? MarketInfo(Symbol(), MODE_ASK) : MarketInfo(Symbol(), MODE_BID);
    int t = OrderSend(Symbol(), hedgeDir, lot, price, 3, 0, 0, CommentText + "_HEDGE", MagicNumber, 0, clrMagenta);
    if (t > 0) RegisterLiveTicket(t, g_clusterSetup);
    return (t > 0);
}

// Recovery-ride leg: opened during recovery on a winning-side Goldminer signal.
// Sizes with the same Fibonacci ladder as the grid (indexed by ride count) so the
// winning side ramps up to EXCEED the losing basket -> continued trend nets the book
// positive. Bounded by MaxRideLegs (count) and MaxRideLotsTotal (lots). Tagged _RCV.
void OpenRideLeg(int dir) {
    int rideCount = 0; double rideLots = 0;
    for (int i = OrdersTotal()-1; i >= 0; i--) {
        if (!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
        if (OrderMagicNumber() != MagicNumber) continue;
        if (StringFind(OrderComment(), "_RCV") < 0) continue;
        rideCount++; rideLots += OrderLots();
    }
    if (rideCount >= MaxRideLegs) return;
    double lot = UseRiskNormalizedLots ? RiskNormalizedLot(rideCount) : CalculateLot(rideCount);
    if (lot < 0) return;                                 // volatility skip
    double minLot = MarketInfo(Symbol(), MODE_MINLOT);
    if (lot < minLot) lot = minLot;
    if (rideLots + lot > MaxRideLotsTotal) {
        lot = NormalizeDouble(MaxRideLotsTotal - rideLots, 2);
        if (lot < minLot) return;                        // total-lots cap reached
    }
    double price = (dir == OP_BUY) ? MarketInfo(Symbol(), MODE_ASK) : MarketInfo(Symbol(), MODE_BID);
    int t = OrderSend(Symbol(), dir, lot, price, 3, 0, 0, CommentText + "_RCV", MagicNumber, 0, clrLime);
    if (t > 0) {
        RegisterLiveTicket(t, g_clusterSetup);
        Print("RECOVERY RIDE leg ", rideCount+1, ": ", (dir==OP_BUY?"BUY":"SELL"),
              " ", DoubleToString(lot,2), " @ ", price, " (rideLots now ", DoubleToString(rideLots+lot,2), ")");
    } else Print("OpenRideLeg failed err=", GetLastError());
}

// Floor-hedge leg: an OPPOSITE-direction market order that freezes (1:1) or overtakes the
// losing basket at/beyond the floor. Tagged _FHDG so ManageGrid can track/release it.
bool OpenFloorHedgeLeg(int dir, double lot) {
    double price = (dir == OP_BUY) ? MarketInfo(Symbol(), MODE_ASK) : MarketInfo(Symbol(), MODE_BID);
    int t = OrderSend(Symbol(), dir, lot, price, 3, 0, 0, CommentText + "_FHDG", MagicNumber, 0, clrOrange);
    if (t > 0) RegisterLiveTicket(t, g_clusterSetup);
    else Print("OpenFloorHedgeLeg failed err=", GetLastError());
    return (t > 0);
}

// Close only the floor-hedge legs (release: the flooring move failed; the grid resumes recovery).
void CloseFloorHedgeLegs() {
    for (int i = OrdersTotal()-1; i >= 0; i--) {
        if (!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
        if (OrderMagicNumber() != MagicNumber) continue;
        if (OrderType() != OP_BUY && OrderType() != OP_SELL) continue;
        if (StringFind(OrderComment(), "_FHDG") < 0) continue;
        double cp = (OrderType() == OP_BUY) ? MarketInfo(Symbol(), MODE_BID) : MarketInfo(Symbol(), MODE_ASK);
        if (!OrderClose(OrderTicket(), OrderLots(), cp, 3, clrYellow))
            Print("CloseFloorHedgeLegs: close failed ticket=", OrderTicket(), " err=", GetLastError());
    }
}

void CloseAllBasket(string reason) {
    Print("CloseAllBasket: ", reason);
    for (int i = OrdersTotal()-1; i >= 0; i--) {
        if (!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
        if (OrderMagicNumber() != MagicNumber) continue;
        if (OrderType() != OP_BUY && OrderType() != OP_SELL) continue;
        double cp = (OrderType() == OP_BUY) ? MarketInfo(Symbol(), MODE_BID) : MarketInfo(Symbol(), MODE_ASK);
        OrderClose(OrderTicket(), OrderLots(), cp, 3, clrYellow);
    }
}

void ManageGrid() {
    int nLevels = 0;
    double basketLots = 0, basketSumPxLot = 0, basketFloat = 0;
    int    initialDir = -1;
    double hedgeLots = 0, hedgeFloat = 0;
    bool   hedgeOpen = false;
    double rideLots = 0, rideFloat = 0;
    int    rideCount = 0;
    bool   rideOpen = false;
    double fhdgLots = 0, fhdgFloat = 0, fhdgAnchor = 0;
    int    fhdgCount = 0;
    datetime fhdgAnchorTime = 0;
    datetime oldestOpen = 0;

    for (int i = OrdersTotal()-1; i >= 0; i--) {
        if (!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
        if (OrderMagicNumber() != MagicNumber) continue;
        if (OrderType() != OP_BUY && OrderType() != OP_SELL) continue;
        string cmt = OrderComment();
        double lot = OrderLots();
        double op  = OrderOpenPrice();
        double pnl = OrderProfit() + OrderSwap() + OrderCommission();
        if (oldestOpen == 0 || OrderOpenTime() < oldestOpen) oldestOpen = OrderOpenTime();

        if (StringFind(cmt, "_FHDG") >= 0) {
            // floor-hedge legs: the anchor = open price of the FIRST (oldest) leg = the freeze price.
            // State is fully position-derived -> restart-safe without globals.
            fhdgCount++;
            fhdgLots += lot;
            fhdgFloat += pnl;
            if (fhdgAnchorTime == 0 || OrderOpenTime() < fhdgAnchorTime) { fhdgAnchorTime = OrderOpenTime(); fhdgAnchor = op; }
        } else if (StringFind(cmt, "_HEDGE") >= 0) {
            hedgeOpen = true;
            hedgeLots += lot;
            hedgeFloat += pnl;
        } else if (StringFind(cmt, "_RCV") >= 0) {
            rideOpen = true;
            rideLots += lot;
            rideFloat += pnl;
            rideCount++;
        } else {
            nLevels++;
            initialDir = OrderType();
            basketLots += lot;
            basketSumPxLot += op * lot;
            basketFloat += pnl;
        }
    }
    if (nLevels == 0) {
        if (rideOpen) CloseAllBasket("recovery ride: basket gone, close orphan ride");  // safety
        if (fhdgCount > 0) CloseFloorHedgeLegs();  // safety: never leave an orphan floor-hedge
        g_peakBasketFloat = 0.0; g_recovering = false; g_rideDir = -1; g_recoveryPeak = 0.0;
        g_fhLastAnchor = 0.0; g_fhLastDir = -1;
        return;
    }
    double combinedFloat = basketFloat + hedgeFloat + rideFloat + fhdgFloat;

    // 1R in $ for the current basket (barrier price distance x $/price/lot x open lots)
    double atrD1t   = iATR(NULL, PERIOD_D1, 14, 1);
    double barDistT = atrD1t * BarrierATRMultiplier;
    double tickSizeT = MarketInfo(Symbol(), MODE_TICKSIZE);
    double dollarPerPricePerLot = (tickSizeT > 0) ? MarketInfo(Symbol(), MODE_TICKVALUE) / tickSizeT : 0;
    double oneR = barDistT * dollarPerPricePerLot * (basketLots + hedgeLots + rideLots + fhdgLots);

    // ---- CATASTROPHIC FLOOR (account survival): cap basket loss at % of balance.
    // The grid is a martingale with no inherent floor; this bounds the tail in a
    // one-way move where the recovery escape never triggers (Dec 29 blow-up fix).
    // FLOOR-HEDGE v2: when UseFloorHedge=true the floor does NOT realize the loss --
    // it FREEZES it with a 1:1 opposite market hedge (the loss can't grow), keeping the
    // option on the basket; FloorHedgeRuinPct stays the absolute close-everything backstop.
    if (UseBasketStop) {
        double maxLoss = -BasketMaxLossPct / 100.0 * AccountBalance();
        if (UseFloorHedge) {
            // the floor's floor: bounds overtake whipsaw + any hysteresis-hold bleed
            if (combinedFloat <= -FloorHedgeRuinPct / 100.0 * AccountBalance()) {
                CloseAllBasket("FLOOR-HEDGE RUIN " + DoubleToString(combinedFloat,2));
                g_peakBasketFloat = 0.0; g_recovering = false; g_rideDir = -1; g_recoveryPeak = 0.0;
                g_fhLastAnchor = 0.0; g_fhLastDir = -1;
                return;
            }
            if (combinedFloat <= maxLoss && fhdgCount == 0) {
                double pxF = (initialDir == OP_BUY) ? MarketInfo(Symbol(), MODE_BID) : MarketInfo(Symbol(), MODE_ASK);
                // re-arm hysteresis: after a release, only re-freeze at a NEW adverse extreme
                // beyond the previous freeze price (otherwise release->bounce->re-freeze churns)
                bool newExtreme = true;
                if (g_fhLastDir == initialDir && g_fhLastAnchor > 0)
                    newExtreme = (initialDir == OP_BUY) ? (pxF < g_fhLastAnchor) : (pxF > g_fhLastAnchor);
                double netExp = NormalizeDouble(basketLots - hedgeLots - rideLots, 2);
                double minLotF = MarketInfo(Symbol(), MODE_MINLOT);
                if (newExtreme && netExp >= minLotF) {
                    int hdirF = (initialDir == OP_BUY) ? OP_SELL : OP_BUY;
                    if (OpenFloorHedgeLeg(hdirF, netExp)) {
                        g_fhLastAnchor = pxF; g_fhLastDir = initialDir;
                        Print("FLOOR-HEDGE FROZEN: float=", DoubleToString(combinedFloat,2),
                              " lots=", DoubleToString(netExp,2), " @ ", DoubleToString(pxF, Digits),
                              " (was BASKET STOP -> loss frozen, not realized)");
                    }
                }
                return;   // in the floor zone: frozen, or holding for a new extreme -- no adds/exits below
            }
        }
        else if (combinedFloat <= maxLoss) {
            CloseAllBasket("BASKET STOP " + DoubleToString(combinedFloat,2) + " <= " + DoubleToString(maxLoss,2));
            g_peakBasketFloat = 0.0; g_recovering = false; g_rideDir = -1; g_recoveryPeak = 0.0;
            return;
        }
    }

    // ---- STAGED FLOOR (user-designed live 2026-07-09): cut the single WORST leg when the
    // basket is deep, BEFORE the catastrophic floor -- lightens the basket (escape pulls
    // closer, floor pushes away, survival odds rise) for the price of one realized leg.
    // Once per bar; the realized loss lowers balance/float so the trigger self-hysteresis.
    if (UseStagedFloor && nLevels >= 2 && Time[0] != g_lastStageBar &&
        combinedFloat <= -StagedFloorPct / 100.0 * AccountBalance()) {
        int    worstTicket = -1;
        double worstPnl    = 0;
        for (int wi = OrdersTotal()-1; wi >= 0; wi--) {
            if (!OrderSelect(wi, SELECT_BY_POS, MODE_TRADES)) continue;
            if (OrderMagicNumber() != MagicNumber) continue;
            if (OrderType() != OP_BUY && OrderType() != OP_SELL) continue;
            string wcmt = OrderComment();
            if (StringFind(wcmt, "_FHDG") >= 0 || StringFind(wcmt, "_RCV") >= 0 ||
                StringFind(wcmt, "_HEDGE") >= 0) continue;               // basket legs only
            double wpnl = OrderProfit() + OrderSwap() + OrderCommission();
            if (worstTicket < 0 || wpnl < worstPnl) { worstTicket = OrderTicket(); worstPnl = wpnl; }
        }
        if (worstTicket > 0 && OrderSelect(worstTicket, SELECT_BY_TICKET)) {
            double wcp = (OrderType() == OP_BUY) ? MarketInfo(Symbol(), MODE_BID)
                                                 : MarketInfo(Symbol(), MODE_ASK);
            if (OrderClose(worstTicket, OrderLots(), wcp, 3, clrOrange))
                Print("STAGED FLOOR: closed worst leg #", worstTicket,
                      " pnl=", DoubleToString(worstPnl,2),
                      " (book was ", DoubleToString(combinedFloat,2), ")");
            else
                Print("STAGED FLOOR: close failed #", worstTicket, " err=", GetLastError());
            g_lastStageBar = Time[0];
            return;   // re-evaluate the lightened basket next tick
        }
    }

    // ---- RECOVERY RIDE: arm when the basket floats deep against a sustained trend.
    // Once armed, OnTick opens winning-side (trend) legs and ManageGrid stops adding
    // to the losing basket (the !g_recovering guard on grid expansion below). Close
    // the WHOLE book at +RecoveryTargetUSD. The floor above (now incl. the ride) is
    // the V-reversal backstop. Arm level must be < BasketMaxLossPct or it never fires.
    if (UseRecoveryRide) {
        if (!g_recovering && nLevels >= 2 && !rideOpen &&
            combinedFloat <= -RecoveryTriggerPct / 100.0 * AccountBalance()) {
            g_recovering = true;
            g_rideDir = (initialDir == OP_BUY) ? OP_SELL : OP_BUY;   // opposite the losing basket = the trend
            Print("RECOVERY RIDE ARMED: float=", DoubleToString(combinedFloat,2),
                  " basket=", (initialDir==OP_BUY?"BUY":"SELL"),
                  " ride=", (g_rideDir==OP_BUY?"BUY":"SELL"));
        }
        if (g_recovering && combinedFloat >= RecoveryTargetUSD) {
            if (!UseRecoveryTrail) {
                CloseAllBasket("RECOVERY RIDE complete +" + DoubleToString(combinedFloat,2));
                g_recovering = false; g_rideDir = -1; g_peakBasketFloat = 0.0; g_recoveryPeak = 0.0;
                return;
            }
            if (combinedFloat > g_recoveryPeak) g_recoveryPeak = combinedFloat;   // trail: ride the recovered book
        }
        if (g_recovering && UseRecoveryTrail && g_recoveryPeak >= RecoveryTargetUSD) {
            double rStop = g_recoveryPeak * (1.0 - RecoveryTrailGivebackPct / 100.0);
            if (rStop < 0) rStop = 0;
            if (combinedFloat <= rStop) {
                CloseAllBasket("RECOVERY TRAIL exit +" + DoubleToString(combinedFloat,2) +
                               " (peak " + DoubleToString(g_recoveryPeak,2) + ")");
                g_recovering = false; g_rideDir = -1; g_peakBasketFloat = 0.0; g_recoveryPeak = 0.0;
                return;
            }
        }
    }

    // ---- PROFIT EXIT ----
    if (nLevels >= 2) {
        // Grid is in recovery: bail the WHOLE basket at the first small profit to
        // de-risk fast (build-I "+$ and out" escape). Trailing is wrong here -- it
        // needs +1R of the grown basket (~9x), leaving the martingale exposed.
        // (While the recovery TRAIL manages a ridden book, defer to it -- fib C parity.)
        if (combinedFloat >= ProfitTargetUSD && !(g_recovering && UseRecoveryTrail)) {
            CloseAllBasket("grid recovery escape +" + DoubleToString(combinedFloat,2));
            g_peakBasketFloat = 0.0;
            return;
        }
    } else if (UseTrailingExit && oneR > 0) {
        // Single clean position: let the winner run with the R-scaled trail.
        if (combinedFloat > g_peakBasketFloat) g_peakBasketFloat = combinedFloat;
        if (g_peakBasketFloat >= TrailActivateR * oneR &&
            combinedFloat <= g_peakBasketFloat - TrailDistanceR * oneR) {
            CloseAllBasket("trail exit @R=" + DoubleToString(combinedFloat / oneR, 2));
            g_peakBasketFloat = 0.0;
            return;
        }
    } else {
        if (combinedFloat >= ProfitTargetUSD) { CloseAllBasket("profit target " + DoubleToString(combinedFloat,2)); return; }
    }
    if (oldestOpen > 0 && (TimeCurrent() - oldestOpen) > MaxDaysOpen * 86400) { CloseAllBasket("max days"); return; }

    // ---- FLOOR-HEDGE management: release on confirmed reversal, overtake on confirmed continuation.
    // While hedged the book is frozen (or net-with-trend after overtakes); the normal profit exits
    // above close EVERYTHING at +ProfitTargetUSD = the "hedged to profit" completion.
    if (UseFloorHedge && fhdgCount > 0) {
        double atrFH = iATR(NULL, PERIOD_D1, 14, 1);
        bool basketBuy = (initialDir == OP_BUY);
        double pxFH = basketBuy ? MarketInfo(Symbol(), MODE_BID) : MarketInfo(Symbol(), MODE_ASK);
        if (atrFH > 0 && fhdgAnchor > 0) {
            // REVERSAL: price back through the freeze price by FH_ReleaseATR in the basket's favor
            // = the flooring move failed -> release the hedge; the grid resumes its own recovery.
            double relLvl = basketBuy ? (fhdgAnchor + FH_ReleaseATR * atrFH)
                                      : (fhdgAnchor - FH_ReleaseATR * atrFH);
            if ((basketBuy && pxFH >= relLvl) || (!basketBuy && pxFH <= relLvl)) {
                CloseFloorHedgeLegs();
                Print("FLOOR-HEDGE RELEASED: anchor=", DoubleToString(fhdgAnchor, Digits),
                      " px=", DoubleToString(pxFH, Digits),
                      " float=", DoubleToString(combinedFloat,2), " -> grid resumes recovery");
                return;
            }
            // CONTINUATION: each new adverse extreme FH_ConfirmATR x ATR beyond the freeze price
            // = confirmed breakout -> add an overtake leg so the winning side EXCEEDS the basket
            // and the whole book climbs to the +ProfitTargetUSD escape ("hedged to profit").
            if (FH_OvertakeStep > 0) {
                int over = fhdgCount - 1;   // legs beyond the 1:1 freeze
                double nextLvl = basketBuy ? (fhdgAnchor - (over + 1) * FH_ConfirmATR * atrFH)
                                           : (fhdgAnchor + (over + 1) * FH_ConfirmATR * atrFH);
                bool confirmed = basketBuy ? (pxFH <= nextLvl) : (pxFH >= nextLvl);
                double maxOpp = FH_OvertakeMaxRatio * basketLots;
                double addLot = NormalizeDouble(MathMin(FH_OvertakeStep * basketLots,
                                                        maxOpp - (hedgeLots + fhdgLots)), 2);
                double minLotO = MarketInfo(Symbol(), MODE_MINLOT);
                if (confirmed && addLot >= minLotO) {
                    int hdirO = basketBuy ? OP_SELL : OP_BUY;
                    if (OpenFloorHedgeLeg(hdirO, addLot))
                        Print("FLOOR-HEDGE OVERTAKE +", DoubleToString(addLot,2),
                              " @ ", DoubleToString(pxFH, Digits),
                              " (opposite lots now ", DoubleToString(hedgeLots + fhdgLots + addLot,2), ")");
                }
            }
        }
        return;   // while hedged: no grid adds (don't feed the loser), no old-style hedge
    }

    double basketAvg = (basketLots > 0) ? basketSumPxLot / basketLots : 0;
    double currentPrice = (initialDir == OP_BUY) ? MarketInfo(Symbol(), MODE_BID) : MarketInfo(Symbol(), MODE_ASK);
    // !g_recovering: while riding, STOP feeding the losing basket (no more grid legs)
    // fhdgCount==0: belt-and-braces (unreachable while hedged via the return above, but also
    // guards a toggled-off restart with _FHDG legs still open)
    if (!hedgeOpen && !g_recovering && fhdgCount == 0) {
        double beDistance = MathAbs(basketAvg - currentPrice) / point;
        if (UseHedge && beDistance >= HedgeBreakEvenPoints) {
            int hedgeSide = (initialDir == OP_BUY) ? OP_SELL : OP_BUY;
            double hedgeSize = NormalizeDouble(basketLots * HedgeRatio, 2);
            if (hedgeSize < 0.01) hedgeSize = 0.01;
            OpenHedge(hedgeSide, hedgeSize);
            return;
        }
        if (nLevels < MaxGridLevels) {
            double spacing = GetGridSpacingPoints();
            double extremeEntry = basketAvg;
            for (int j = OrdersTotal()-1; j >= 0; j--) {
                if (!OrderSelect(j, SELECT_BY_POS, MODE_TRADES)) continue;
                if (OrderMagicNumber() != MagicNumber) continue;
                if (StringFind(OrderComment(), "_HEDGE") >= 0) continue;
                if (initialDir == OP_BUY  && OrderOpenPrice() < extremeEntry) extremeEntry = OrderOpenPrice();
                if (initialDir == OP_SELL && OrderOpenPrice() > extremeEntry) extremeEntry = OrderOpenPrice();
            }
            bool addNow = false;
            if (initialDir == OP_BUY  && currentPrice <= extremeEntry - spacing * point) addNow = true;
            if (initialDir == OP_SELL && currentPrice >= extremeEntry + spacing * point) addNow = true;
            if (addNow) {
                // OPT 2: max basket lots cap
                double currentTotalLots = basketLots + hedgeLots;
                double rawGridLot = UseRiskNormalizedLots ? RiskNormalizedLot(nLevels) : CalculateLot(nLevels);
                if (rawGridLot < 0) return;   // volatility skip: don't deepen the grid when too volatile
                double newLot = NormalizeDouble(rawGridLot * g_clusterSizeMult, 2);
                double minLotG = MarketInfo(Symbol(), MODE_MINLOT);
                if (newLot < minLotG) newLot = minLotG;
                if (currentTotalLots + newLot > MaxBasketLotsTotal) {
                    Print("Grid expansion BLOCKED: would exceed MaxBasketLotsTotal (", currentTotalLots, " + ", newLot, " > ", MaxBasketLotsTotal, ")");
                    return;
                }
                // OPT 3: skip grid expansion if recent SL hit
                if (SkipGridAfterSL && HadRecentSL(SkipGridAfterSLHours)) {
                    Print("Grid expansion BLOCKED: recent SL hit within ", SkipGridAfterSLHours, "h");
                    return;
                }
                OpenGridLevel(initialDir, newLot, nLevels + 1);
            }
        }
    }
}

double GetGridSpacingPoints() {
    if (!UseATRSpacing) return MathMax(GridSpacingMinPoints, 50);
    double atrD1 = iATR(NULL, PERIOD_D1, 14, 1);
    double pts = atrD1 / Point * ATRSpacingMultiplier;
    if (pts < GridSpacingMinPoints) pts = GridSpacingMinPoints;
    if (pts > GridSpacingMaxPoints) pts = GridSpacingMaxPoints;
    return pts;
}

//+------------------------------------------------------------------+
//| OPT 3: detect recent SL closure                                  |
//+------------------------------------------------------------------+
bool HadRecentSL(int hours) {
    datetime cutoff = TimeCurrent() - hours * 3600;
    for (int i = OrdersHistoryTotal() - 1; i >= 0; i--) {
        if (!OrderSelect(i, SELECT_BY_POS, MODE_HISTORY)) continue;
        if (OrderMagicNumber() != MagicNumber) continue;
        if (OrderType() != OP_BUY && OrderType() != OP_SELL) continue;
        if (OrderCloseTime() < cutoff) break;  // history sorted, can stop
        // SL hit: closePrice == StopLoss (approx) AND profit negative
        if (OrderStopLoss() > 0 && OrderProfit() < 0) {
            double slDist = MathAbs(OrderClosePrice() - OrderStopLoss());
            if (slDist < 5 * Point) return true;  // close enough = SL fired
        }
    }
    return false;
}

//+------------------------------------------------------------------+
//| OPT 1: move SL to entry once profit reaches +BreakEvenTriggerR   |
//+------------------------------------------------------------------+
void ManageBreakEvenSL() {
    if (!UseBreakEvenSL) return;
    for (int i = OrdersTotal() - 1; i >= 0; i--) {
        if (!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
        if (OrderMagicNumber() != MagicNumber) continue;
        if (StringFind(OrderComment(), "_SLTP") < 0) continue;  // only SLTP-tagged trades
        double op = OrderOpenPrice();
        double sl = OrderStopLoss();
        double tp = OrderTakeProfit();
        if (sl == 0) continue;   // R is measured from SL distance; tp=0 is valid under trailing
        double cur = (OrderType() == OP_BUY) ? MarketInfo(Symbol(), MODE_BID) : MarketInfo(Symbol(), MODE_ASK);
        double slDist = MathAbs(op - sl);
        if (slDist == 0) continue;

        double rNow = (OrderType() == OP_BUY) ? (cur - op) / slDist : (op - cur) / slDist;
        if (rNow < BreakEvenTriggerR) continue;

        // Already at or beyond break-even?
        bool alreadyBE = (OrderType() == OP_BUY) ? (sl >= op) : (sl <= op);
        if (alreadyBE) continue;

        if (!OrderModify(OrderTicket(), op, op, tp, 0, clrGreen))
            Print("BreakEvenSL modify failed ticket=", OrderTicket(), " err=", GetLastError());
        else
            Print("BreakEvenSL: ticket ", OrderTicket(), " SL moved to entry @ ", op, " (R=", DoubleToString(rNow,2), ")");
    }
}

void ExportBacktestResults() {
    int fh = FileOpen("gridstat_summary.csv", FILE_WRITE|FILE_CSV|FILE_COMMON, ',');
    if (fh != INVALID_HANDLE) {
        FileWrite(fh, "build","mode","pending_remaining","net","gross_profit","gross_loss","trades","pf","max_dd");
        FileWrite(fh, EA_BUILD_VERSION,
            (StatsCollectionMode ? "SHADOW" : "TRADE"),
            IntegerToString(pCount),
            DoubleToString(TesterStatistics(STAT_PROFIT),2),
            DoubleToString(TesterStatistics(STAT_GROSS_PROFIT),2),
            DoubleToString(TesterStatistics(STAT_GROSS_LOSS),2),
            IntegerToString((int)TesterStatistics(STAT_TRADES)),
            DoubleToString(TesterStatistics(STAT_PROFIT_FACTOR),4),
            DoubleToString(TesterStatistics(STAT_BALANCE_DD),2));
        FileClose(fh);
    }
    // Flush any remaining pending signals as TEST_END outcomes (both strategies)
    if (StatsCollectionMode) {
        for (int i = pCount - 1; i >= 0; i--) {
            double curPx = (pDir[i] == OP_BUY) ? MarketInfo(Symbol(), MODE_BID) : MarketInfo(Symbol(), MODE_ASK);
            double barrierDist = pUpperBarrier[i] - pEntryPrice[i];
            double r = (barrierDist > 0)
                ? ((pDir[i] == OP_BUY) ? (curPx - pEntryPrice[i]) : (pEntryPrice[i] - curPx)) / barrierDist
                : 0;
            if (!pFixedDone[i]) { pFixedR[i] = r; pFixedHit[i] = "TEST_END"; pFixedDone[i] = true; }
            WriteOutcome(i, "TEST_END", r);
        }
        pCount = 0;
    }
    Print("GridStat backtest export complete");
}
