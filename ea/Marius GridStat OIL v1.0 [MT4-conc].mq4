//+------------------------------------------------------------------+
//|  Marius GridStat GOLD v1.0 -- BUILD 2026-06-05-P                 |
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

#define EA_BUILD_VERSION "2026-07-01-P-MT4CONC"
#define MAX_PENDING 5000

//--- Mode switches
input bool   StatsCollectionMode   = false;    // SHADOW mode: no trades, just barrier tracking. SET TO FALSE FOR TRADE MODE.
input bool   StatsFilterEnabled    = true;     // TRADE mode: filter by historical win rate. SET TO TRUE FOR TRADE MODE.
input double MinWinRate            = 0.55;     // Legacy win-rate gate (used only if UseSizingTable=false)
input int    MinSamples            = 10;
input string StatsCSVFile          = "gridstat_setups_oil_mt5.csv";

//--- Expected-R sizing table (AFML rigor: sizes bets, replaces win-rate gate)
input bool   UseSizingTable        = false;     // size by expected-R table; skip only negative-expectancy setups
input string SizingCSVFile         = "gridstat_sizing.csv";
input double MaxSizeMult           = 2.0;      // safety cap on per-setup size multiplier

//--- Triple-barrier parameters
input double BarrierATRMultiplier  = 0.8;     // upper/lower barriers at +/- ATR(D1) * this (tighter = more decisive outcomes)
input int    TimeBarrierBars       = 288;     // time barrier in M5 bars (288 = 24h)

//--- Trailing exit (SHADOW comparison logs it; live TRADE uses it when UseTrailingExit=true)
input bool   UseTrailingExit       = false;     // live: R-scaled trailing basket exit instead of fixed $ ProfitTargetUSD
input double TrailActivateR        = 1.0;      // activate trailing once favorable excursion reaches this R
input double TrailDistanceR        = 0.6;      // trail this many R behind the running peak (GOLD optimum; tune per symbol)

//--- Entry / signal
input int    MA_Period             = 20;
input double MA_Angle_Threshold    = 20.0;
input int    ADX_Period            = 14;
input double ADX_Threshold         = 25.0;
input int    grisk                 = 4;
input int    countbars             = 300;
input int    goldminershift        = 1;

//--- D1 trend filter
input bool   UseDailyTrendFilter   = true;
input int    DailyMA_Period        = 50;

//--- Session filter
input bool   UseSessionFilter      = true;
input int    SessionStartHour      = 9;
input int    SessionEndHour        = 23;

//--- Lot sizing (TRADE mode only)
input double LotSize               = 0.02;
input bool   UseCompounding        = true;
input double CompoundingBase       = 3000.0;

//--- Risk-normalized sizing (OFF by default -- gold keeps fixed LotSize; ON for volatile symbols like silver/oil)
input bool   UseRiskNormalizedLots = false;    // size each trade so 1R = RiskPctPerTrade% of balance (equalizes $ risk across symbols)
input double RiskPctPerTrade       = 3.0;      // target risk per trade as % of balance (gold-equivalent ~4%)
input double MaxRiskPctSkip        = 8.0;      // skip the trade if even min-lot 1R risk exceeds this % of balance (too volatile to size safely)

//--- Hedged grid (TRADE mode only)
input bool   UseATRSpacing         = true;
input double ATRSpacingMultiplier  = 0.5;
input int    GridSpacingMinPoints  = 300;
input int    GridSpacingMaxPoints  = 2000;
input int    MaxGridLevels         = 6;
input bool   UseHedge              = true;
input int    HedgeBreakEvenPoints  = 15000;
input double HedgeRatio            = 1.0;
input double ProfitTargetUSD       = 100.0;   // grid-recovery escape: bail basket at this small profit
input int    MaxDaysOpen           = 30;

//--- Basket catastrophic floor (account survival — the grid has no inherent stop)
input bool   UseBasketStop         = true;     // close the whole basket if loss exceeds BasketMaxLossPct of balance
input double BasketMaxLossPct      = 20.0;     // % of account balance — hard per-basket loss cap
input int    MaxConcurrentBaskets  = 1;        // [MT4-CONC] 1 = single basket (unchanged). >1 = N concurrent baskets, each grid-managed + a portfolio floor (oil/trenders need 3).
input bool   UseEntrySL            = true;     // [MT4-CONC] true = per-entry hard SL (unchanged). false = no per-entry stop, rely on the basket floor (oil pulls back -> SL-off lets the grid recover).

//--- Optimizations (session 14)
input bool   UseBreakEvenSL        = true;     // OPT 1: move SL to entry when +0.5R profit reached
input double BreakEvenTriggerR     = 0.7;      // OPT 1: trigger at this R-multiple (0.7 = let winners breathe more)
input double MaxBasketLotsTotal    = 0.30;     // OPT 2: hard cap on basket lots per direction
input bool   SkipGridAfterSL       = true;     // OPT 3: suppress grid expansion if recent SL hit
input int    SkipGridAfterSLHours  = 4;        // OPT 3: lookback hours

//--- Magic
input string CommentText           = "GridStat";

//--- Globals
int      MagicNumber = 0;
int      g_curBasketId = -1;   // [MT4-CONC]
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

//+------------------------------------------------------------------+
int OnInit() {
    MagicNumber = GenerateMagic("GridStat", Symbol(), Period());
    point = (Digits == 3 || Digits == 5) ? Point * 10 : Point;
    Print("============================================================");
    Print("MARIUS GRIDSTAT OIL ", EA_BUILD_VERSION, " | Magic=", MagicNumber, " | maxBaskets=", MaxConcurrentBaskets, " UseEntrySL=", UseEntrySL);
    Print("Mode: ", (StatsCollectionMode ? "SHADOW (no trades)" : "TRADING"),
          " | Filter: ", StatsFilterEnabled,
          " | BarrierATR x", BarrierATRMultiplier,
          " | TimeBarrier ", TimeBarrierBars, " bars");
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

// In SHADOW mode, return total signal R so the MT4 optimizer (criterion=Custom)
// can find the grisk that maximizes a symbol's triple-barrier edge. 0 otherwise.
double OnTester() { ExportBacktestResults(); return (StatsCollectionMode ? g_shadowTotalR : 0); }

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

    // Session gate (entries only)
    if (UseSessionFilter) {
        int hr = TimeHour(TimeCurrent());
        if (!(hr >= SessionStartHour && hr < SessionEndHour)) return;
    }

    // Goldminer signal
    double gred   = iCustom(NULL, 0, "goldminer1", grisk, countbars, 0, goldminershift);
    double ggreen = iCustom(NULL, 0, "goldminer1", grisk, countbars, 1, goldminershift);
    if (gred == EMPTY_VALUE || ggreen == EMPTY_VALUE) return;

    int signalDir = -1;
    if (ggreen > 0) signalDir = OP_BUY;
    if (gred   > 0) signalDir = OP_SELL;
    if (signalDir < 0) return;

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
    if (CountOpenBaskets() >= MaxConcurrentBaskets) return;   // [MT4-CONC] basket-concurrency cap
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
    if (!UseEntrySL) sl = 0;                                   // [MT4-CONC] no per-entry stop
    int bid = NextBasketId();                                  // [MT4-CONC] fresh basket id (-1 in single mode)
    int t = OrderSend(Symbol(), dir, lot, price, 3, sl, tp, CommentText + "_SLTP" + BTag(bid), MagicNumber, 0,
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
    return NormalizeDouble(base * fib[idx], 2);
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
    double lot = NormalizeDouble(baseLot * fib[idx], 2);
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
        string key = ReconstructSetup(OrderType(), OrderOpenTime());
        if (g_clusterSetup == "") g_clusterSetup = key;
        RegisterLiveTicket(OrderTicket(), key);
    }
    if (g_liveCount > 0) Print("Adopted ", g_liveCount, " open ticket(s) for live journal");
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
//+------------------------------------------------------------------+
//| [MT4-CONC] multi-basket helpers (default maxBaskets<=1 => no-op)   |
//+------------------------------------------------------------------+
string BTag(int id) { return (MaxConcurrentBaskets > 1) ? (".B" + IntegerToString(id)) : ""; }
int BIdOf(string cmt) {
    int p = StringFind(cmt, ".B");
    if (p < 0) return -1;
    return (int)StringToInteger(StringSubstr(cmt, p + 2));
}
int CollectBaskets(int &ids[]) {
    ArrayResize(ids, 0);
    for (int i = OrdersTotal()-1; i >= 0; i--) {
        if (!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
        if (OrderMagicNumber() != MagicNumber) continue;
        if (OrderType() != OP_BUY && OrderType() != OP_SELL) continue;
        int bid = BIdOf(OrderComment()); bool have = false;
        for (int k = 0; k < ArraySize(ids); k++) if (ids[k] == bid) { have = true; break; }
        if (!have) { int n = ArraySize(ids); ArrayResize(ids, n+1); ids[n] = bid; }
    }
    return ArraySize(ids);
}
int CountOpenBaskets() { int ids[]; return CollectBaskets(ids); }
int NextBasketId() {
    if (MaxConcurrentBaskets <= 1) return -1;
    int maxId = -1;
    for (int i = OrdersTotal()-1; i >= 0; i--) {
        if (!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
        if (OrderMagicNumber() != MagicNumber) continue;
        int bid = BIdOf(OrderComment()); if (bid > maxId) maxId = bid;
    }
    return maxId + 1;
}
double PortfolioFloat() {
    double f = 0;
    for (int i = OrdersTotal()-1; i >= 0; i--) {
        if (!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
        if (OrderMagicNumber() != MagicNumber) continue;
        if (OrderType() != OP_BUY && OrderType() != OP_SELL) continue;
        f += OrderProfit() + OrderSwap() + OrderCommission();
    }
    return f;
}
void CloseBasket(int bid, string reason) {
    if (bid == -1) { CloseAllBasket(reason); return; }   // single-pool: close everything
    Print("CloseBasket ", bid, ": ", reason);
    for (int i = OrdersTotal()-1; i >= 0; i--) {
        if (!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
        if (OrderMagicNumber() != MagicNumber) continue;
        if (OrderType() != OP_BUY && OrderType() != OP_SELL) continue;
        if (BIdOf(OrderComment()) != bid) continue;
        double cp = (OrderType() == OP_BUY) ? MarketInfo(Symbol(), MODE_BID) : MarketInfo(Symbol(), MODE_ASK);
        OrderClose(OrderTicket(), OrderLots(), cp, 3, clrYellow);
    }
}

int BasketLotCount() {
    int c = 0;
    for (int i = OrdersTotal()-1; i >= 0; i--) {
        if (!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
        if (OrderMagicNumber() != MagicNumber) continue;
        if (OrderType() == OP_BUY || OrderType() == OP_SELL) c++;
    }
    return c;
}

bool OpenGridLevel(int dir, double lot, int gridLvl, int bid) {
    double price = (dir == OP_BUY) ? MarketInfo(Symbol(), MODE_ASK) : MarketInfo(Symbol(), MODE_BID);
    string cmt = CommentText + "_L" + IntegerToString(gridLvl) + BTag(bid);
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

bool OpenHedge(int hedgeDir, double lot, int bid) {
    double price = (hedgeDir == OP_BUY) ? MarketInfo(Symbol(), MODE_ASK) : MarketInfo(Symbol(), MODE_BID);
    int t = OrderSend(Symbol(), hedgeDir, lot, price, 3, 0, 0, CommentText + "_HEDGE" + BTag(bid), MagicNumber, 0, clrMagenta);
    if (t > 0) RegisterLiveTicket(t, g_clusterSetup);
    return (t > 0);
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

void ManageOneBasket(int bid) {
    int nLevels = 0;
    double basketLots = 0, basketSumPxLot = 0, basketFloat = 0;
    int    initialDir = -1;
    double hedgeLots = 0, hedgeFloat = 0;
    bool   hedgeOpen = false;
    datetime oldestOpen = 0;

    for (int i = OrdersTotal()-1; i >= 0; i--) {
        if (!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
        if (OrderMagicNumber() != MagicNumber) continue;
        if (OrderType() != OP_BUY && OrderType() != OP_SELL) continue;
        if (bid != -1 && BIdOf(OrderComment()) != bid) continue;   // [MT4-CONC] this basket only
        string cmt = OrderComment();
        double lot = OrderLots();
        double op  = OrderOpenPrice();
        double pnl = OrderProfit() + OrderSwap() + OrderCommission();
        if (oldestOpen == 0 || OrderOpenTime() < oldestOpen) oldestOpen = OrderOpenTime();

        if (StringFind(cmt, "_HEDGE") >= 0) {
            hedgeOpen = true;
            hedgeLots += lot;
            hedgeFloat += pnl;
        } else {
            nLevels++;
            initialDir = OrderType();
            basketLots += lot;
            basketSumPxLot += op * lot;
            basketFloat += pnl;
        }
    }
    if (nLevels == 0) { g_peakBasketFloat = 0.0; return; }
    double combinedFloat = basketFloat + hedgeFloat;

    // 1R in $ for the current basket (barrier price distance x $/price/lot x open lots)
    double atrD1t   = iATR(NULL, PERIOD_D1, 14, 1);
    double barDistT = atrD1t * BarrierATRMultiplier;
    double tickSizeT = MarketInfo(Symbol(), MODE_TICKSIZE);
    double dollarPerPricePerLot = (tickSizeT > 0) ? MarketInfo(Symbol(), MODE_TICKVALUE) / tickSizeT : 0;
    double oneR = barDistT * dollarPerPricePerLot * (basketLots + hedgeLots);

    // ---- CATASTROPHIC FLOOR (account survival): cap basket loss at % of balance.
    // The grid is a martingale with no inherent floor; this bounds the tail in a
    // one-way move where the recovery escape never triggers (Dec 29 blow-up fix).
    if (UseBasketStop) {
        double maxLoss = -BasketMaxLossPct / 100.0 * AccountBalance();
        if (combinedFloat <= maxLoss) {
            CloseBasket(bid, "BASKET STOP " + DoubleToString(combinedFloat,2) + " <= " + DoubleToString(maxLoss,2));
            g_peakBasketFloat = 0.0;
            return;
        }
    }

    // ---- PROFIT EXIT ----
    if (nLevels >= 2) {
        // Grid is in recovery: bail the WHOLE basket at the first small profit to
        // de-risk fast (build-I "+$ and out" escape). Trailing is wrong here -- it
        // needs +1R of the grown basket (~9x), leaving the martingale exposed.
        if (combinedFloat >= ProfitTargetUSD) {
            CloseBasket(bid, "grid recovery escape +" + DoubleToString(combinedFloat,2));
            g_peakBasketFloat = 0.0;
            return;
        }
    } else if (UseTrailingExit && oneR > 0) {
        // Single clean position: let the winner run with the R-scaled trail.
        if (combinedFloat > g_peakBasketFloat) g_peakBasketFloat = combinedFloat;
        if (g_peakBasketFloat >= TrailActivateR * oneR &&
            combinedFloat <= g_peakBasketFloat - TrailDistanceR * oneR) {
            CloseBasket(bid, "trail exit @R=" + DoubleToString(combinedFloat / oneR, 2));
            g_peakBasketFloat = 0.0;
            return;
        }
    } else {
        if (combinedFloat >= ProfitTargetUSD) { CloseBasket(bid, "profit target " + DoubleToString(combinedFloat,2)); return; }
    }
    if (oldestOpen > 0 && (TimeCurrent() - oldestOpen) > MaxDaysOpen * 86400) { CloseBasket(bid, "max days"); return; }
    double basketAvg = (basketLots > 0) ? basketSumPxLot / basketLots : 0;
    double currentPrice = (initialDir == OP_BUY) ? MarketInfo(Symbol(), MODE_BID) : MarketInfo(Symbol(), MODE_ASK);
    if (!hedgeOpen) {
        double beDistance = MathAbs(basketAvg - currentPrice) / point;
        if (UseHedge && beDistance >= HedgeBreakEvenPoints) {
            int hedgeSide = (initialDir == OP_BUY) ? OP_SELL : OP_BUY;
            double hedgeSize = NormalizeDouble(basketLots * HedgeRatio, 2);
            if (hedgeSize < 0.01) hedgeSize = 0.01;
            OpenHedge(hedgeSide, hedgeSize, bid);
            return;
        }
        if (nLevels < MaxGridLevels) {
            double spacing = GetGridSpacingPoints();
            double extremeEntry = basketAvg;
            for (int j = OrdersTotal()-1; j >= 0; j--) {
                if (!OrderSelect(j, SELECT_BY_POS, MODE_TRADES)) continue;
                if (OrderMagicNumber() != MagicNumber) continue;
                if (StringFind(OrderComment(), "_HEDGE") >= 0) continue;
                if (bid != -1 && BIdOf(OrderComment()) != bid) continue;   // [MT4-CONC]
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
                OpenGridLevel(initialDir, newLot, nLevels + 1, bid);
            }
        }
    }
}

void ManageGrid() {
    if (MaxConcurrentBaskets <= 1) { ManageOneBasket(-1); return; }   // single-pool = unchanged
    // [MT4-CONC] portfolio catastrophe floor: cap TOTAL float across all concurrent baskets
    if (UseBasketStop) {
        double pf = PortfolioFloat();
        if (pf <= -BasketMaxLossPct / 100.0 * AccountBalance()) { CloseAllBasket("PORTFOLIO STOP " + DoubleToString(pf,2)); return; }
    }
    int ids[]; int nb = CollectBaskets(ids);
    for (int k = 0; k < nb; k++) ManageOneBasket(ids[k]);
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
