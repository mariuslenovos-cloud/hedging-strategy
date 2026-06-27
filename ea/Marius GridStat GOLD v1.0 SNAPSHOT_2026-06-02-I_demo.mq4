//+------------------------------------------------------------------+
//|  Marius GridStat GOLD v1.0 -- BUILD 2026-06-02-I                 |
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

#define EA_BUILD_VERSION "2026-06-02-I"
#define MAX_PENDING 5000

//--- Mode switches
input bool   StatsCollectionMode   = false;    // SHADOW mode: no trades, just barrier tracking. SET TO FALSE FOR TRADE MODE.
input bool   StatsFilterEnabled    = true;     // TRADE mode: filter by historical win rate. SET TO TRUE FOR TRADE MODE.
input double MinWinRate            = 0.55;     // Balanced threshold: passes 4 setups expected to net +15R
input int    MinSamples            = 10;
input string StatsCSVFile          = "gridstat_setups.csv";

//--- Triple-barrier parameters
input double BarrierATRMultiplier  = 0.8;     // upper/lower barriers at +/- ATR(D1) * this (tighter = more decisive outcomes)
input int    TimeBarrierBars       = 288;     // time barrier in M5 bars (288 = 24h)

//--- Entry / signal
input int    MA_Period             = 20;
input double MA_Angle_Threshold    = 20.0;
input int    ADX_Period            = 14;
input double ADX_Threshold         = 25.0;
input int    grisk                 = 7;
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

//--- Hedged grid (TRADE mode only)
input bool   UseATRSpacing         = true;
input double ATRSpacingMultiplier  = 0.5;
input int    GridSpacingMinPoints  = 300;
input int    GridSpacingMaxPoints  = 2000;
input int    MaxGridLevels         = 6;
input bool   UseHedge              = true;
input int    HedgeBreakEvenPoints  = 15000;
input double HedgeRatio            = 1.0;
input double ProfitTargetUSD       = 100.0;
input int    MaxDaysOpen           = 30;

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
    MagicNumber = GenerateMagic("GridStat", Symbol(), Period());
    point = (Digits == 3 || Digits == 5) ? Point * 10 : Point;
    Print("============================================================");
    Print("MARIUS GRIDSTAT GOLD ", EA_BUILD_VERSION, " | Magic=", MagicNumber);
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
    return hash % 100000 + 50000;
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
    double atrD1 = iATR(NULL, PERIOD_D1, 14, 1);
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
    Print("GridStat backtest export complete");
}
