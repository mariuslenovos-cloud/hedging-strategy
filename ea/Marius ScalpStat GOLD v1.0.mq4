//+------------------------------------------------------------------+
//|  Marius ScalpStat GOLD v1.0 -- BUILD 2026-06-02-C                |
//|  Configurable BarrierATR_TFMinutes (was D1 only). Defaults H1 for M1|
//|  Scalper version of GridStat with selectable signal source       |
//|  SignalSource:                                                   |
//|    "GOLDMINER" -- same Goldminer+ADX+MAangle (Level 1 tuning)    |
//|    "RSI"       -- RSI(14) extremes 30/70 reversal (Level 2)      |
//|    "BOTH"      -- trade ANY signal that fires (highest freq)     |
//|  Scalp defaults: ATR x0.3 barriers, 5h time, no grid, no hedge   |
//+------------------------------------------------------------------+
#property strict

#define EA_BUILD_VERSION "2026-06-02-C"
#define MAX_PENDING 10000

//--- Mode switches
input bool   StatsCollectionMode   = true;     // SHADOW mode first to collect scalp stats
input bool   StatsFilterEnabled    = false;    // Enable after stats DB populated
input double MinWinRate            = 0.55;
input int    MinSamples            = 20;       // higher for scalp due to more samples per bucket
input string StatsCSVFile          = "scalpstat_setups.csv";

//--- Signal source selector
input string SignalSource          = "BOTH";  // "GOLDMINER" | "RSI" | "BOTH"

//--- Triple-barrier parameters (scalp-tuned)
input double BarrierATRMultiplier  = 0.7;      // multiplier on ATR(BarrierATR_TFMinutes)
input int    BarrierATR_TFMinutes  = 60;       // ATR reference timeframe (60=H1 for M1 scalp; 1440=D1 for M5/M15 swing)
input int    TimeBarrierBars       = 60;       // 60 bars (60min on M1, 5h on M5)

//--- Entry / signal (Goldminer)
input int    MA_Period             = 20;
input double MA_Angle_Threshold    = 20.0;
input int    ADX_Period            = 14;
input double ADX_Threshold         = 25.0;
input int    grisk                 = 7;
input int    countbars             = 300;
input int    goldminershift        = 1;

//--- Entry / signal (RSI)
input int    RSI_Period            = 14;
input double RSI_OverboughtLevel   = 70.0;     // SELL when RSI >= this
input double RSI_OversoldLevel     = 30.0;     // BUY when RSI <= this

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

//--- Grid/hedge DISABLED for scalper (each trade stands alone)
input bool   UseATRSpacing         = true;
input double ATRSpacingMultiplier  = 0.5;
input int    GridSpacingMinPoints  = 300;
input int    GridSpacingMaxPoints  = 2000;
input int    MaxGridLevels         = 1;       // 1 = no grid expansion, single entry
input bool   UseHedge              = false;   // no hedge in scalper
input int    HedgeBreakEvenPoints  = 99999;
input double HedgeRatio            = 1.0;
input double ProfitTargetUSD       = 30.0;    // smaller scalp target
input int    MaxDaysOpen           = 2;       // scalp trades shouldn't sit long

//--- Optimizations (lighter for scalper)
input bool   UseBreakEvenSL        = false;   // scalp targets too tight to need BE
input double BreakEvenTriggerR     = 0.7;
input double MaxBasketLotsTotal    = 0.04;    // base lot only, no stacking
input bool   SkipGridAfterSL       = true;
input int    SkipGridAfterSLHours  = 4;

//--- Magic
input string CommentText           = "ScalpStat";

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
int      pCount = 0;

//+------------------------------------------------------------------+
int OnInit() {
    MagicNumber = GenerateMagic("ScalpStat", Symbol(), Period());
    point = (Digits == 3 || Digits == 5) ? Point * 10 : Point;
    Print("============================================================");
    Print("MARIUS SCALPSTAT GOLD ", EA_BUILD_VERSION, " | Magic=", MagicNumber, " | SignalSource=", SignalSource);
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
                          "atr_at_entry","barrier_hit","r_multiple","outcome_time");
            FileClose(fh);
        }
    }
    return INIT_SUCCEEDED;
}

int GenerateMagic(string eaName, string sym, int tf) {
    int hash = 0;
    string s = eaName + sym + IntegerToString(tf);
    for (int i = 0; i < StringLen(s); i++) hash += StringGetChar(s, i) * (i + 1);
    return hash % 100000 + 200000;  // offset 200000 to separate from GridStat range
}

double OnTester() { ExportBacktestResults(); return 0; }

//+------------------------------------------------------------------+
void OnTick() {
    RefreshRates();

    bool newBar = (Time[0] != lastBarTime);
    if (newBar) lastBarTime = Time[0];

    // SHADOW MODE: check pending signals against barriers
    if (StatsCollectionMode) CheckPendingBarriers();

    // TRADE MODE: manage hedged grid + break-even SL
    if (!StatsCollectionMode) {
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

    // Signal source dispatch
    int signalDir = -1;
    string signalTag = "";

    if (SignalSource == "GOLDMINER" || SignalSource == "BOTH") {
        double gred   = iCustom(NULL, 0, "goldminer1", grisk, countbars, 0, goldminershift);
        double ggreen = iCustom(NULL, 0, "goldminer1", grisk, countbars, 1, goldminershift);
        if (gred != EMPTY_VALUE && ggreen != EMPTY_VALUE) {
            if (ggreen > 0) { signalDir = OP_BUY;  signalTag = "GM"; }
            if (gred   > 0) { signalDir = OP_SELL; signalTag = "GM"; }
        }
    }

    if (signalDir < 0 && (SignalSource == "RSI" || SignalSource == "BOTH")) {
        double rsi = iRSI(NULL, 0, RSI_Period, PRICE_CLOSE, 0);
        double rsiPrev = iRSI(NULL, 0, RSI_Period, PRICE_CLOSE, 1);
        // Zone-entry trigger: fire ONCE when RSI crosses INTO extreme zone (more signals than cross-back)
        // Dedup: must have been outside the zone on previous bar
        if (rsiPrev > RSI_OversoldLevel && rsi <= RSI_OversoldLevel) {
            signalDir = OP_BUY;  signalTag = "RSI";  // entering oversold = buy
        } else if (rsiPrev < RSI_OverboughtLevel && rsi >= RSI_OverboughtLevel) {
            signalDir = OP_SELL; signalTag = "RSI";  // entering overbought = sell
        }
    }

    if (signalDir < 0) return;

    if (UseDailyTrendFilter) {
        bool d1Bull = IsDailyTrendBullish();
        if (signalDir == OP_BUY && !d1Bull) return;
        if (signalDir == OP_SELL && d1Bull) return;
    }
    // Goldminer needs strong trend; RSI reversal does NOT (it works against weak trends)
    if (signalTag == "GM" && !IsTrendStrong()) return;

    string setupKey = signalTag + "|" + ClassifySetup(signalDir);

    // SHADOW MODE: add to pending barriers
    if (StatsCollectionMode) {
        AddPendingSignal(setupKey, signalDir);
        return;
    }

    // TRADE MODE: filter + open simple SL/TP position (no grid, no hedge)
    if (StatsFilterEnabled) {
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
    double lot = CalculateLot(0);
    OpenSimpleSLTP(signalDir, lot);
}

// Open with hard SL at -BarrierATR and TP at +BarrierATR (mirrors stats methodology)
void OpenSimpleSLTP(int dir, double lot) {
    double atrD1 = iATR(NULL, BarrierATR_TFMinutes, 14, 1);
    double barrierDist = atrD1 * BarrierATRMultiplier;
    double price = (dir == OP_BUY) ? MarketInfo(Symbol(), MODE_ASK) : MarketInfo(Symbol(), MODE_BID);
    double sl, tp;
    if (dir == OP_BUY) { sl = price - barrierDist; tp = price + barrierDist; }
    else               { sl = price + barrierDist; tp = price - barrierDist; }
    int t = OrderSend(Symbol(), dir, lot, price, 3, sl, tp, CommentText + "_SLTP", MagicNumber, 0,
                     (dir == OP_BUY ? clrBlue : clrRed));
    if (t > 0) Print("Trade opened: ", (dir==OP_BUY?"BUY":"SELL"), " ", DoubleToString(lot,2),
                     " @ ", price, " SL=", sl, " TP=", tp);
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
    double atrD1 = iATR(NULL, BarrierATR_TFMinutes, 14, 1);
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
    }
    pCount--;
}

void CheckPendingBarriers() {
    double high = MarketInfo(Symbol(), MODE_ASK);
    double low  = MarketInfo(Symbol(), MODE_BID);
    // Use M5 bar high/low for more accurate barrier hits (bid/ask only show current tick)
    double barHigh = High[0];
    double barLow  = Low[0];

    for (int i = pCount - 1; i >= 0; i--) {
        string outcome = "";
        double rMultiple = 0;
        double barrierDist = pUpperBarrier[i] - pEntryPrice[i];  // = entryPx - lower = positive

        // For BUY: upper = favorable, lower = unfavorable
        // For SELL: lower = favorable, upper = unfavorable
        if (pDir[i] == OP_BUY) {
            if (barHigh >= pUpperBarrier[i]) {
                outcome = "UPPER";
                rMultiple = 1.0;  // hit favorable barrier first = +1R
            } else if (barLow <= pLowerBarrier[i]) {
                outcome = "LOWER";
                rMultiple = -1.0;
            }
        } else {  // SELL
            if (barLow <= pLowerBarrier[i]) {
                outcome = "LOWER";
                rMultiple = 1.0;
            } else if (barHigh >= pUpperBarrier[i]) {
                outcome = "UPPER";
                rMultiple = -1.0;
            }
        }

        // Time barrier
        if (outcome == "" && TimeCurrent() >= pTimeBarrier[i]) {
            outcome = "TIME";
            double curPx = (pDir[i] == OP_BUY) ? MarketInfo(Symbol(), MODE_BID) : MarketInfo(Symbol(), MODE_ASK);
            double moveDirection = (pDir[i] == OP_BUY) ? (curPx - pEntryPrice[i]) : (pEntryPrice[i] - curPx);
            rMultiple = moveDirection / barrierDist;  // partial R (positive = favorable)
        }

        if (outcome != "") {
            WriteOutcome(i, outcome, rMultiple);
            RemovePendingAt(i);
        }
    }
}

void WriteOutcome(int idx, string barrierHit, double rMultiple) {
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
        barrierHit,
        DoubleToString(rMultiple, 3),
        TimeToString(TimeCurrent(), TIME_DATE|TIME_MINUTES));
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
    // skip header (11 cells)
    for (int i = 0; i < 11; i++) FileReadString(fh);
    while (!FileIsEnding(fh)) {
        string key = FileReadString(fh);
        if (key == "") break;
        for (int j = 0; j < 7; j++) FileReadString(fh);  // skip middle
        string barrierHit = FileReadString(fh);
        string rStr = FileReadString(fh);
        string outTime = FileReadString(fh);
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

void ManageGrid() {
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
    if (nLevels == 0) return;
    double combinedFloat = basketFloat + hedgeFloat;
    if (combinedFloat >= ProfitTargetUSD) { CloseAllBasket("profit target " + DoubleToString(combinedFloat,2)); return; }
    if (oldestOpen > 0 && (TimeCurrent() - oldestOpen) > MaxDaysOpen * 86400) { CloseAllBasket("max days"); return; }
    double basketAvg = (basketLots > 0) ? basketSumPxLot / basketLots : 0;
    double currentPrice = (initialDir == OP_BUY) ? MarketInfo(Symbol(), MODE_BID) : MarketInfo(Symbol(), MODE_ASK);
    if (!hedgeOpen) {
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
                double newLot = CalculateLot(nLevels);
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
    double atrD1 = iATR(NULL, BarrierATR_TFMinutes, 14, 1);
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
        if (sl == 0 || tp == 0) continue;
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
    int fh = FileOpen("scalpstat_summary.csv", FILE_WRITE|FILE_CSV|FILE_COMMON, ',');
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
    // Flush any remaining pending signals as TIME_END outcomes
    if (StatsCollectionMode) {
        for (int i = pCount - 1; i >= 0; i--) {
            double curPx = (pDir[i] == OP_BUY) ? MarketInfo(Symbol(), MODE_BID) : MarketInfo(Symbol(), MODE_ASK);
            double barrierDist = pUpperBarrier[i] - pEntryPrice[i];
            double moveDir = (pDir[i] == OP_BUY) ? (curPx - pEntryPrice[i]) : (pEntryPrice[i] - curPx);
            double r = (barrierDist > 0) ? moveDir / barrierDist : 0;
            WriteOutcome(i, "TEST_END", r);
        }
        pCount = 0;
    }
    Print("ScalpStat backtest export complete");
}
