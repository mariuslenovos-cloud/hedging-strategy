//+------------------------------------------------------------------+
//|  Marius GoldminerSingle  --  MT5 v0.1  (2026-08-19)               |
//|  The DEFINED-RISK SLEEVE: the exact GridStat Goldminer signal     |
//|  traded as ONE position with fixed R -- no grid, no adds, no      |
//|  hedge, no recovery. Validated on the shadow DB walk-forward:     |
//|  +16.8R raw, +24.3R with BE@0.5R/lock0.25R; rank3+ carried        |
//|  +13.8R; PM carried the session edge. This EA is that study,     |
//|  executable.                                                      |
//|                                                                   |
//|  SIGNAL (ported VERBATIM from GridStat GOLD LOCKED, grisk=4):     |
//|    adaptive-WPR band traverse (40-bar scan) + D1 EMA(50) trend    |
//|    + ADX(14)>25 & MA(20) angle>20 + overextension skip 4.5        |
//|  FILTERS (the two findings): entry hour >= 14; day-rank >= 2      |
//|  GATE: walk-forward per-setup stats built IN MEMORY from this     |
//|    EA's own observed signal outcomes (triple barrier, same as     |
//|    the shadow logger) -> no lookahead in the tester, and the      |
//|    tester replicates the +16.8R study by construction. Optional   |
//|    warm start from the production research CSV for live.          |
//|  TRADE: SL = 0.8 x ATR(D1) (this is 1R), TP = 0.8 x ATR(D1),      |
//|    BE+lock at +LockAtR/LockToR, time exit 24h. One position.      |
//|  EXPORT: goldminer_single_trades.csv (Common\Files) -- feed it    |
//|    straight to painwindow_check.py.                               |
//+------------------------------------------------------------------+
#property copyright "Marius"
#property version   "0.10"
#property strict
#include <Trade/Trade.mqh>
CTrade trade;

#define BUILD "GMSINGLE-MT5-2026-08-19-v0.1"

//=== signal (LOCKED values from GridStat GOLD -- do not tune these here) ===
const int    grisk            = 4;
const int    GM_Period        = 0;      // 0 = auto (grisk*2+3)
const double GM_UpperBand     = 0;      // 0 = auto (grisk+67)
const double GM_LowerBand     = 0;      // 0 = auto (33-grisk)
const double GM_GapMult       = 2.0;
const int    GM_GapMode       = 0;
const double GM_FastMult      = 4.6;
const int    goldminershift   = 1;
const int    MA_Period        = 20;
const int    ADX_Period       = 14;
const double ADX_Threshold    = 25.0;
const double MA_Angle_Threshold = 20.0;
const int    DailyMA_Period   = 50;
const double OverextATRMult   = 4.5;

//=== the sleeve's own knobs ===
input group "--- Entry filters (the two DB findings) ---"
input int    EntryStartHour   = 14;     // PM finding: AM (9-13) = -0.015R, PM = +0.17R. 9 = off
input int    EntryEndHour     = 23;
input int    MinDayRank       = 2;      // day-rank finding: rank1 +0.01R, rank2 +0.08R, rank3+ +0.22R. 1 = off
input group "--- Walk-forward stats gate ---"
input bool   UseStatsGate     = true;   // per-setup n>=MinSamples & wr>=MinWinRate, built in memory as signals resolve
input double MinWinRate       = 0.55;
input int    MinSamples       = 10;
input bool   WarmStartFromCSV = false;  // live: seed the in-memory stats from the production research CSV. Tester: leave FALSE (keeps it walk-forward)
input string WarmStartCSV     = "gridstat_setups_gold_research.csv";
input bool   UseDayRankInKey  = true;   // 4-dim keys (DIR|SESS|ATR|K) -- matches the S29 patch. false = 3-dim
input group "--- Trade shape (the validated study) ---"
input double BarrierATR       = 0.8;    // SL and TP distance = this x ATR(D1). SL distance == 1R
input double LockAtR          = 0.5;    // at +this R, move SL to +LockToR
input double LockToR          = 0.25;
input int    TimeExitHours    = 24;     // matches the study's time barrier
input group "--- Sizing / hygiene ---"
input double FixedLots        = 0.01;   // 0 = use RiskPct
input double RiskPct          = 1.0;    // used only if FixedLots = 0
input double MaxLots          = 0.10;
input int    MaxSpreadPoints  = 350;
input long   MagicNumber      = 260819;
input string CommentText      = "GMSingle";
input string TradeCSV         = "goldminer_single_trades.csv";  // Common\Files, painwindow_check.py-ready

//=== handles / state ===
int      hMA, hADX, hMA_D1, hATR_cur, hATR_D1, hATR_D1_60;
datetime g_lastBar = 0;
int      g_digits; double g_point;
// day-rank (same population rule as S29: gate-quality fires, i.e. all pre-stats gates passed)
int      g_dayRankDay = -1, g_dayRankCount = 0;
// open-trade state
double   g_entryPx = 0, g_riskDist = 0; bool g_locked = false; datetime g_openTime = 0;
string   g_openKey = "";
// in-memory walk-forward stats + pending signal tracker (the shadow logger, internalized)
#define MAX_KEYS 128
string   sKey[MAX_KEYS]; int sN[MAX_KEYS]; int sW[MAX_KEYS]; int sCount = 0;
#define MAX_PEND 64
string   pKey[MAX_PEND]; int pDir[MAX_PEND]; datetime pT[MAX_PEND];
double   pPx[MAX_PEND], pUp[MAX_PEND], pDn[MAX_PEND]; int pCount = 0;

//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(50);
   trade.SetTypeFillingBySymbol(_Symbol);
   g_point  = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   g_digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   hMA      = iMA(_Symbol, PERIOD_CURRENT, MA_Period, 0, MODE_EMA, PRICE_CLOSE);
   hADX     = iADX(_Symbol, PERIOD_CURRENT, ADX_Period);
   hMA_D1   = iMA(_Symbol, PERIOD_D1, DailyMA_Period, 0, MODE_EMA, PRICE_CLOSE);
   hATR_cur = iATR(_Symbol, PERIOD_CURRENT, 20);
   hATR_D1  = iATR(_Symbol, PERIOD_D1, 14);
   hATR_D1_60 = iATR(_Symbol, PERIOD_D1, 60);
   if(hMA==INVALID_HANDLE || hADX==INVALID_HANDLE || hMA_D1==INVALID_HANDLE ||
      hATR_cur==INVALID_HANDLE || hATR_D1==INVALID_HANDLE || hATR_D1_60==INVALID_HANDLE)
   { Print("handle failed"); return(INIT_FAILED); }
   if(WarmStartFromCSV) WarmStart();
   Print(BUILD, " | ", _Symbol, " ", EnumToString(Period()),
         " | PM>=", EntryStartHour, " rank>=", MinDayRank, " gate=", UseStatsGate,
         " (", MinWinRate, "/", MinSamples, ") warm=", WarmStartFromCSV,
         " | R=", BarrierATR, "xATR(D1) lock ", LockAtR, "->", LockToR);
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| ==== SIGNAL BLOCK: ported verbatim from GridStat GOLD LOCKED ====|
//+------------------------------------------------------------------+
double ReadBuf(int handle, int buf, int shift)
{
   double b[1];
   if(CopyBuffer(handle, buf, shift, 1, b) != 1) return(0);
   return(b[0]);
}
double WprValue(int period, int shift)
{
   int hhs = iHighest(_Symbol, PERIOD_CURRENT, MODE_HIGH, period, shift);
   int lls = iLowest(_Symbol, PERIOD_CURRENT, MODE_LOW, period, shift);
   if(hhs < 0 || lls < 0) return(50);
   double hh = iHigh(_Symbol, PERIOD_CURRENT, hhs);
   double ll = iLow(_Symbol, PERIOD_CURRENT, lls);
   double cl = iClose(_Symbol, PERIOD_CURRENT, shift);
   double wpr = (hh - ll != 0) ? -100.0 * (hh - cl) / (hh - ll) : 0;
   return(100.0 - MathAbs(wpr));
}
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
int GetGoldminerSignal(bool &bigMove, double &wpr, int &periodUsed, int &barsInBand)
{
   double upper = (GM_UpperBand > 0) ? GM_UpperBand : (grisk + 67);
   double lower = (GM_LowerBand > 0) ? GM_LowerBand : (33 - grisk);
   int LB = 40;
   double val[];
   ArrayResize(val, LB);
   bool bm0=false; int pu0=0;
   for(int k=0; k<LB; k++)
   {
      bool bm=false; int pu=0;
      val[k] = GMValueAt(goldminershift + k, bm, pu);
      if(k==0) { bm0 = bm; pu0 = pu; }
   }
   bigMove = bm0; wpr = val[0]; periodUsed = pu0; barsInBand = 0;
   int dir = -1; int li = 1;
   if(val[0] > upper)
   {
      while(li<LB-1 && val[li]>=lower && val[li]<=upper) li++;
      if(val[li] < lower) dir = (int)ORDER_TYPE_BUY;
   }
   else if(val[0] < lower)
   {
      while(li<LB-1 && val[li]>=lower && val[li]<=upper) li++;
      if(val[li] > upper) dir = (int)ORDER_TYPE_SELL;
   }
   barsInBand = li;
   return(dir);
}
bool IsDailyTrendBullish() { return(ReadBuf(hMA_D1,0,0) > ReadBuf(hMA_D1,0,1)); }
double GetMAAngle()
{
   double m0 = ReadBuf(hMA,0,0), m1 = ReadBuf(hMA,0,5);
   double atr = ReadBuf(hATR_cur,0,1);
   if(atr <= 0) return(0);
   return(MathArctan((m0-m1)/(5.0*atr*0.1))*180.0/M_PI);
}
bool IsOverextended()
{
   if(OverextATRMult <= 0) return(false);
   double d1ma  = ReadBuf(hMA_D1,0,0);
   double atr60 = ReadBuf(hATR_D1_60,0,1);
   if(atr60 <= 0) return(false);
   double dist = MathAbs(iClose(_Symbol,PERIOD_CURRENT,goldminershift) - d1ma) / atr60;
   return(dist >= OverextATRMult);
}
int BarHour(datetime t){ MqlDateTime s; TimeToStruct(t,s); return(s.hour); }
int BarDOY(datetime t){ MqlDateTime s; TimeToStruct(t,s); return(s.day_of_year); }
string ClassifySetup(int dir)
{
   string d = (dir == ORDER_TYPE_BUY) ? "BUY" : "SELL";
   int hr = BarHour(TimeCurrent());
   string hrB = (hr<9) ? "HR_ASIA" : (hr<14) ? "HR_LDN" : (hr<18) ? "HR_OVL" : "HR_NY";
   double an = ReadBuf(hATR_cur,0,1);
   double aa = ReadBuf(iATR(_Symbol,PERIOD_CURRENT,100),0,1);   // ATR(100) normalizer (as GridStat)
   string atrB;
   if(aa==0) atrB="ATR_NA";
   else if(an > aa*1.3) atrB="ATR_EXP";
   else if(an < aa*0.7) atrB="ATR_COMP";
   else atrB="ATR_NORM";
   string key = d + "|" + hrB + "|" + atrB;
   if(UseDayRankInKey)
   {
      int k = DayRankNow();
      key += "|" + (k<=1 ? "K1" : (k==2 ? "K2" : "K3+"));
   }
   return(key);
}

//+------------------------------------------------------------------+
//| day-rank (S29 population rule: count gate-quality fires)         |
//+------------------------------------------------------------------+
int DayRankNow()
{
   int doy = BarDOY(TimeCurrent());
   if(doy != g_dayRankDay){ g_dayRankDay = doy; g_dayRankCount = 0; }
   return(g_dayRankCount+1);
}
void DayRankCount()
{
   int doy = BarDOY(TimeCurrent());
   if(doy != g_dayRankDay){ g_dayRankDay = doy; g_dayRankCount = 0; }
   g_dayRankCount++;
}

//+------------------------------------------------------------------+
//| in-memory walk-forward stats                                     |
//+------------------------------------------------------------------+
int KeyIdx(string k, bool createIfMissing)
{
   for(int i=0;i<sCount;i++) if(sKey[i]==k) return(i);
   if(!createIfMissing || sCount>=MAX_KEYS) return(-1);
   sKey[sCount]=k; sN[sCount]=0; sW[sCount]=0; sCount++;
   return(sCount-1);
}
bool GatePass(string k, double &wr, int &n)
{
   int i = KeyIdx(k,false);
   n = (i<0) ? 0 : sN[i];
   wr = (i<0 || sN[i]==0) ? 0 : (double)sW[i]/sN[i];
   if(!UseStatsGate) return(true);
   return(n >= MinSamples && wr >= MinWinRate);
}
void RecordOutcome(string k, bool win)
{
   int i = KeyIdx(k,true);
   if(i<0) return;
   sN[i]++; if(win) sW[i]++;
}
void WarmStart()   // seed stats from the production research CSV (setup_key col 0, r_multiple by header)
{
   int fh = FileOpen(WarmStartCSV, FILE_READ|FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_CSV|FILE_COMMON|FILE_ANSI, ',');
   if(fh == INVALID_HANDLE){ Print("warm start: cannot open ", WarmStartCSV); return; }
   int ncol=0, rIdx=-1;
   while(!FileIsEnding(fh))
   {
      string c = FileReadString(fh);
      if(c=="r_multiple") rIdx=ncol;
      ncol++;
      if(FileIsLineEnding(fh)) break;
   }
   if(rIdx<0){ FileClose(fh); Print("warm start: no r_multiple col"); return; }
   int rows=0;
   while(!FileIsEnding(fh))
   {
      string key=""; double r=0; bool any=false;
      for(int c=0; c<ncol && !FileIsEnding(fh); c++)
      {
         string cell = FileReadString(fh); any=true;
         if(c==0) key=cell;
         if(c==rIdx) r=StringToDouble(cell);
      }
      if(!any) break;
      RecordOutcome(key, r>0); rows++;
   }
   FileClose(fh);
   Print("warm start: ", rows, " rows -> ", sCount, " keys");
}

//+------------------------------------------------------------------+
//| pending-signal tracker (triple barrier, feeds the gate)          |
//+------------------------------------------------------------------+
void AddPending(string key, int dir)
{
   if(pCount >= MAX_PEND) return;
   double atrD1 = ReadBuf(hATR_D1,0,1);
   if(atrD1 <= 0) return;
   double px = (dir==ORDER_TYPE_BUY) ? SymbolInfoDouble(_Symbol,SYMBOL_ASK) : SymbolInfoDouble(_Symbol,SYMBOL_BID);
   pKey[pCount]=key; pDir[pCount]=dir; pT[pCount]=TimeCurrent(); pPx[pCount]=px;
   pUp[pCount]=px + BarrierATR*atrD1; pDn[pCount]=px - BarrierATR*atrD1;
   pCount++;
}
void CheckPending()
{
   double bid = SymbolInfoDouble(_Symbol,SYMBOL_BID);
   for(int i=pCount-1; i>=0; i--)
   {
      int res = 0;   // 0 pending, +1 win, -1 loss
      if(pDir[i]==ORDER_TYPE_BUY)
      {
         if(bid >= pUp[i]) res=1; else if(bid <= pDn[i]) res=-1;
      }
      else
      {
         if(bid <= pDn[i]) res=1; else if(bid >= pUp[i]) res=-1;
      }
      if(res==0 && TimeCurrent()-pT[i] >= TimeExitHours*3600)
      {
         double mv = (pDir[i]==ORDER_TYPE_BUY) ? (bid-pPx[i]) : (pPx[i]-bid);
         res = (mv > 0) ? 1 : -1;
      }
      if(res != 0)
      {
         RecordOutcome(pKey[i], res==1);
         for(int j=i; j<pCount-1; j++)
         { pKey[j]=pKey[j+1]; pDir[j]=pDir[j+1]; pT[j]=pT[j+1]; pPx[j]=pPx[j+1]; pUp[j]=pUp[j+1]; pDn[j]=pDn[j+1]; }
         pCount--;
      }
   }
}

//+------------------------------------------------------------------+
//| trade management + CSV export                                    |
//+------------------------------------------------------------------+
ulong OurPosition(int &type)
{
   type = -1;
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(tk==0) continue;
      if(PositionGetString(POSITION_SYMBOL)!=_Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC)!=MagicNumber) continue;
      type = (int)PositionGetInteger(POSITION_TYPE);
      return(tk);
   }
   return(0);
}
void ManageOpen()
{
   int type; ulong tk = OurPosition(type);
   if(tk==0){ g_entryPx=0; g_locked=false; return; }
   if(!PositionSelectByTicket(tk)) return;
   bool isBuy = (type==POSITION_TYPE_BUY);
   double bid=SymbolInfoDouble(_Symbol,SYMBOL_BID), ask=SymbolInfoDouble(_Symbol,SYMBOL_ASK);
   double px = isBuy ? bid : ask;
   double prog = (isBuy ? (px-g_entryPx) : (g_entryPx-px)) / g_riskDist;   // in R
   // time exit
   if(TimeExitHours>0 && TimeCurrent()-g_openTime >= TimeExitHours*3600)
   { trade.PositionClose(tk); Print("GMS: time exit at ", DoubleToString(prog,2), "R"); return; }
   // lock
   if(!g_locked && prog >= LockAtR)
   {
      double newSL = isBuy ? (g_entryPx + LockToR*g_riskDist) : (g_entryPx - LockToR*g_riskDist);
      newSL = NormalizeDouble(newSL, g_digits);
      long stopsLvl = SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL);
      bool legal = isBuy ? (bid-newSL >= stopsLvl*g_point) : (newSL-ask >= stopsLvl*g_point);
      if(legal && trade.PositionModify(tk, newSL, PositionGetDouble(POSITION_TP)))
      { g_locked = true; Print("GMS: locked +", DoubleToString(LockToR,2), "R at +", DoubleToString(prog,2), "R"); }
   }
}
void ExportDeal(ulong dealTicket)
{
   if(!HistoryDealSelect(dealTicket)) return;
   if(HistoryDealGetInteger(dealTicket, DEAL_MAGIC) != MagicNumber) return;
   if(HistoryDealGetInteger(dealTicket, DEAL_ENTRY) != DEAL_ENTRY_OUT) return;
   double pnl = HistoryDealGetDouble(dealTicket, DEAL_PROFIT)
              + HistoryDealGetDouble(dealTicket, DEAL_SWAP)
              + HistoryDealGetDouble(dealTicket, DEAL_COMMISSION);
   int fh = FileOpen(TradeCSV, FILE_READ|FILE_WRITE|FILE_CSV|FILE_COMMON|FILE_ANSI, ',');
   if(fh==INVALID_HANDLE) return;
   if(FileSize(fh)==0) FileWrite(fh,"close_time","setup_key","dir","entry_price","close_price","r_multiple","pnl_usd");
   FileSeek(fh,0,SEEK_END);
   double cpx = HistoryDealGetDouble(dealTicket, DEAL_PRICE);
   long   dt  = HistoryDealGetInteger(dealTicket, DEAL_TYPE);   // closing deal type: SELL closes BUY
   int dir    = (dt==DEAL_TYPE_SELL) ? (int)ORDER_TYPE_BUY : (int)ORDER_TYPE_SELL;
   double r   = (g_riskDist>0) ? ((dir==ORDER_TYPE_BUY) ? (cpx-g_entryPx) : (g_entryPx-cpx))/g_riskDist : 0;
   FileWrite(fh, TimeToString(TimeCurrent(),TIME_DATE|TIME_MINUTES), g_openKey,
             (dir==ORDER_TYPE_BUY?"BUY":"SELL"), DoubleToString(g_entryPx,g_digits),
             DoubleToString(cpx,g_digits), DoubleToString(r,3), DoubleToString(pnl,2));
   FileClose(fh);
}
void OnTradeTransaction(const MqlTradeTransaction &trans, const MqlTradeRequest &req, const MqlTradeResult &res)
{
   if(trans.type == TRADE_TRANSACTION_DEAL_ADD) ExportDeal(trans.deal);
}
double LotsNow(double stopDist)
{
   if(FixedLots > 0) return(MathMin(FixedLots, MaxLots));
   double riskUSD = AccountInfoDouble(ACCOUNT_BALANCE) * RiskPct / 100.0;
   double tickVal = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSz  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tickVal<=0 || tickSz<=0 || stopDist<=0) return(0);
   double lots = riskUSD / ((stopDist/tickSz)*tickVal);
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   lots = MathFloor(lots/step)*step;
   double minL = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   if(lots < minL) return(0);
   return(NormalizeDouble(MathMin(lots, MaxLots),2));
}

//+------------------------------------------------------------------+
void OnTick()
{
   CheckPending();
   ManageOpen();

   bool newBar = (iTime(_Symbol,PERIOD_CURRENT,0) != g_lastBar);
   if(!newBar) return;
   g_lastBar = iTime(_Symbol,PERIOD_CURRENT,0);

   // ---- signal & gates: SAME ORDER as GridStat, then the two sleeve filters ----
   bool bigMove=false; double wpr=0; int periodUsed=0, barsInBand=0;
   int dir = GetGoldminerSignal(bigMove, wpr, periodUsed, barsInBand);
   if(dir < 0) return;

   double adx     = ReadBuf(hADX,0,0);
   double maAngle = (dir==ORDER_TYPE_BUY) ? GetMAAngle() : -GetMAAngle();
   bool   bull    = IsDailyTrendBullish();
   string skip    = "";
   if((dir==ORDER_TYPE_BUY && !bull) || (dir==ORDER_TYPE_SELL && bull)) skip="D1trend";
   if(skip=="" && !(adx > ADX_Threshold && MathAbs(maAngle) > MA_Angle_Threshold)) skip="trendWeak";
   if(skip=="" && IsOverextended()) skip="overextended";

   string key = ClassifySetup(dir);    // includes day-rank bucket if UseDayRankInKey
   int rank = DayRankNow();
   if(skip=="")
   {
      DayRankCount();                  // gate-quality fire: count it (S29 population)
      AddPending(key, dir);            // feed the walk-forward stats regardless of whether we trade it
   }
   if(skip != "") return;

   // ---- sleeve filters ----
   int hr = BarHour(TimeCurrent());
   if(!(hr >= EntryStartHour && hr < EntryEndHour)) return;         // PM finding
   if(rank < MinDayRank) return;                                    // day-rank finding
   double wr=0; int n=0;
   if(!GatePass(key, wr, n)) return;                                // walk-forward stats gate
   int type; if(OurPosition(type)!=0) return;                       // one position
   if(SymbolInfoInteger(_Symbol,SYMBOL_SPREAD) > MaxSpreadPoints) return;

   // ---- trade ----
   double atrD1 = ReadBuf(hATR_D1,0,1);
   if(atrD1 <= 0) return;
   double stopDist = BarrierATR*atrD1;
   double lots = LotsNow(stopDist);
   if(lots <= 0){ Print("GMS: skip, sizing zero"); return; }
   double ask=SymbolInfoDouble(_Symbol,SYMBOL_ASK), bid=SymbolInfoDouble(_Symbol,SYMBOL_BID);
   double px = (dir==ORDER_TYPE_BUY) ? ask : bid;
   double sl = (dir==ORDER_TYPE_BUY) ? px-stopDist : px+stopDist;
   double tp = (dir==ORDER_TYPE_BUY) ? px+stopDist : px-stopDist;
   sl=NormalizeDouble(sl,g_digits); tp=NormalizeDouble(tp,g_digits);
   bool ok = (dir==ORDER_TYPE_BUY) ? trade.Buy(lots,_Symbol,px,sl,tp,CommentText)
                                   : trade.Sell(lots,_Symbol,px,sl,tp,CommentText);
   if(ok)
   {
      g_entryPx=px; g_riskDist=stopDist; g_locked=false; g_openTime=TimeCurrent(); g_openKey=key;
      Print("GMS: ", (dir==ORDER_TYPE_BUY?"BUY":"SELL"), " ", lots, " @", px,
            " key=", key, " rank=", rank, " wr=", DoubleToString(wr,2), " n=", n,
            " R=$", DoubleToString(stopDist,1));
   }
   else Print("GMS: order failed err=", GetLastError(), " ret=", trade.ResultRetcode());
}
//+------------------------------------------------------------------+
