//+------------------------------------------------------------------+
//|  Marius GridStat SCANNER v1.0  --  MULTI-ENGINE x SYMBOL x PARAM  |
//|  ONE chart / ONE run -> scans a symbol list across a PARAM sweep  |
//|  for ONE engine, exit-agnostic (horizon return + MFE + MAE / ATR).|
//|  ENGINES (TriggerMode):                                          |
//|    0 = Goldminer momentum (swing surge)     param = grisk        |
//|    1 = CUSUM-momentum (breakout, with drift) param = h x ATR     |
//|    2 = CUSUM-reversion (fade the breach)     param = h x ATR     |
//|    3 = mean-reversion (z-score/BB or RSI)    param = sigma / level|
//|  Set ParamList appropriate to the engine. Judge by MEAN & TOTAL  |
//|  horizon_r (cost-aware) + the gold control + inversion sanity.   |
//|  Shadow only; bar-driven (tick-mode-independent).                |
//+------------------------------------------------------------------+
#property copyright "Marius"
#property version   "1.30"

#define SCAN_BUILD "SCAN-2026-06-07-D"
#define MAXP 20000

input int    TriggerMode = 0;            // 0 Goldminer | 1 CUSUM-mom | 2 CUSUM-rev | 3 mean-reversion
//--- engine 3 sub-mode
input int    MR_Mode     = 0;            // 0 = z-score (=Bollinger) | 1 = RSI
input int    MR_Period   = 20;           // z-score MA/StdDev period, or RSI period
input bool   MR_RequireRanging = true;   // engines 2 & 3: only when ADX < ADX_Threshold

input string ScanSymbols = "GOLD,SILVER,EURUSD,GBPUSD,USDJPY,USDCHF,AUDUSD,USDCAD,NZDUSD,EURJPY,GBPJPY,EURGBP,EURCHF,AUDJPY,US500Cash,US100Cash,US30Cash,OILCash";
input ENUM_TIMEFRAMES SignalTF = PERIOD_M5;
input string OutCSV = "gridstat_scan.csv";

//--- PARAM sweep (engine-specific!): Goldminer="4,7,10,14,18,21"; CUSUM="1,2,3,4,5"; MR z="1.5,2,2.5,3" / RSI="20,25,30"
input string ParamList = "4,7,10,14,18,21";

//--- measurement window (exit-agnostic)
input double R_UnitATR   = 1.0;
input int    HorizonBars = 288;

//--- Goldminer constants (engine 0)
input double GM_GapMult   = 2.0;
input int    GM_GapMode   = 0;
input double GM_FastMult   = 4.6;
input int    goldminershift = 1;
input int    RunupBars    = 12;

//--- entry filters
input double MA_Angle_Threshold = 20.0;
input int    MA_Period          = 20;
input int    ADX_Period         = 14;
input double ADX_Threshold      = 25.0;
input bool   UseDailyTrendFilter = true;
input int    DailyMA_Period      = 50;
input bool   UseSessionFilter    = true;
input int    SessionStartHour    = 9;
input int    SessionEndHour      = 23;

//--- Globals
string   Sym[];   int NSym=0;
double   Params[]; int NP=0;
int      hMA[], hADX[], hMAd1[], hATRcur[], hATRavg[], hATRd1[], hMRma[], hMRsd[], hRSI[];
datetime symLast[];
double   symPoint[];
bool     symOK[];
double   cusPos[], cusNeg[];   // CUSUM state per (symbol,param): index s*NP+pi
string   ENG="MOM";

int      pSym[MAXP], pDir[MAXP], pPer[MAXP], pBib[MAXP];
double   pParam[MAXP];
string   pSetup[MAXP];
datetime pEntry[MAXP], pTime[MAXP];
double   pPx[MAXP], pRef[MAXP], pMFE[MAXP], pMAE[MAXP];
double   pWpr[MAXP], pAdx[MAXP], pAng[MAXP], pRun[MAXP];
int      pN=0;
double   g_total=0.0;

//+------------------------------------------------------------------+
int OnInit()
{
   ushort sep=StringGetCharacter(",",0);
   NSym=StringSplit(ScanSymbols,sep,Sym);
   string ptmp[]; NP=StringSplit(ParamList,sep,ptmp);
   if(NSym<=0||NP<=0){ Print("Bad symbol/param list"); return(INIT_FAILED); }
   ArrayResize(Params,NP);
   for(int i=0;i<NP;i++){ StringTrimLeft(ptmp[i]); StringTrimRight(ptmp[i]); Params[i]=StringToDouble(ptmp[i]); }

   ArrayResize(hMA,NSym);ArrayResize(hADX,NSym);ArrayResize(hMAd1,NSym);ArrayResize(hATRcur,NSym);
   ArrayResize(hATRavg,NSym);ArrayResize(hATRd1,NSym);ArrayResize(hMRma,NSym);ArrayResize(hMRsd,NSym);ArrayResize(hRSI,NSym);
   ArrayResize(symLast,NSym);ArrayResize(symPoint,NSym);ArrayResize(symOK,NSym);
   ArrayResize(cusPos,NSym*NP);ArrayResize(cusNeg,NSym*NP);
   ArrayInitialize(cusPos,0);ArrayInitialize(cusNeg,0);

   int good=0;
   for(int s=0;s<NSym;s++)
   {
      StringTrimLeft(Sym[s]); StringTrimRight(Sym[s]);
      symOK[s]=false; symLast[s]=0;
      if(!SymbolSelect(Sym[s],true)){ Print("Symbol not found, skipping: ",Sym[s]); continue; }
      hMA[s]=iMA(Sym[s],SignalTF,MA_Period,0,MODE_EMA,PRICE_CLOSE);
      hADX[s]=iADX(Sym[s],SignalTF,ADX_Period);
      hMAd1[s]=iMA(Sym[s],PERIOD_D1,DailyMA_Period,0,MODE_EMA,PRICE_CLOSE);
      hATRcur[s]=iATR(Sym[s],SignalTF,20);
      hATRavg[s]=iATR(Sym[s],SignalTF,100);
      hATRd1[s]=iATR(Sym[s],PERIOD_D1,14);
      hMRma[s]=iMA(Sym[s],SignalTF,MR_Period,0,MODE_SMA,PRICE_CLOSE);
      hMRsd[s]=iStdDev(Sym[s],SignalTF,MR_Period,0,MODE_SMA,PRICE_CLOSE);
      hRSI[s]=iRSI(Sym[s],SignalTF,MR_Period,PRICE_CLOSE);
      if(hMA[s]==INVALID_HANDLE||hADX[s]==INVALID_HANDLE||hMAd1[s]==INVALID_HANDLE||hATRcur[s]==INVALID_HANDLE||
         hATRavg[s]==INVALID_HANDLE||hATRd1[s]==INVALID_HANDLE||hMRma[s]==INVALID_HANDLE||hMRsd[s]==INVALID_HANDLE||hRSI[s]==INVALID_HANDLE)
      { Print("Handle fail, skipping: ",Sym[s]); continue; }
      int dg=(int)SymbolInfoInteger(Sym[s],SYMBOL_DIGITS);
      double pt=SymbolInfoDouble(Sym[s],SYMBOL_POINT);
      symPoint[s]=(dg==3||dg==5)?pt*10:pt;
      symOK[s]=true; good++;
   }
   string en[]={"MOM","CUSUM-MOM","CUSUM-REV","MR"};
   ENG=en[(TriggerMode>=0&&TriggerMode<=3)?TriggerMode:0];
   if(TriggerMode==3) ENG=ENG+(MR_Mode==1?"-RSI":"-Z");
   Print("============================================================");
   Print("MARIUS GRIDSTAT SCANNER ",SCAN_BUILD," | ENGINE=",ENG," | symbols OK:",good,"/",NSym," | params:",ParamList);
   Print("============================================================");

   int fh=FileOpen(OutCSV,FILE_WRITE|FILE_CSV|FILE_COMMON|FILE_ANSI,',');
   if(fh!=INVALID_HANDLE)
   {
      FileWrite(fh,"symbol","engine","param","setup_key","entry_time","entry_price","direction",
                "atr_at_entry","horizon_r","mfe_r","mae_r","outcome_time",
                "wpr","adx","ma_angle","runup","period_used","bars_in_band");
      FileClose(fh);
   }
   return(INIT_SUCCEEDED);
}
double OnTester(){ return(g_total); }

//+------------------------------------------------------------------+
double RB(int handle,int buf,int shift){ double b[]; if(CopyBuffer(handle,buf,shift,1,b)<=0) return(0); return(b[0]); }
int BarHour(datetime t){ MqlDateTime dt; TimeToStruct(t,dt); return(dt.hour); }

double WprS(int s,int period,int shift)
{
   int hh=iHighest(Sym[s],SignalTF,MODE_HIGH,period,shift);
   int ll=iLowest(Sym[s],SignalTF,MODE_LOW,period,shift);
   if(hh<0||ll<0) return(50);
   double H=iHigh(Sym[s],SignalTF,hh),L=iLow(Sym[s],SignalTF,ll),C=iClose(Sym[s],SignalTF,shift);
   double w=(H-L!=0)?-100.0*(H-C)/(H-L):0;
   return(100.0-MathAbs(w));
}
double GMValS(int s,int j,int gr,bool &big,int &per)
{
   double avg=0;
   for(int k=j;k<=j+9;k++) avg+=MathAbs(iHigh(Sym[s],SignalTF,k)-iLow(Sym[s],SignalTF,k));
   avg/=10.0;
   bool gap=false,fast=false;
   for(int k=j;k<j+9 && !gap;k++)
   {
      double jump=(GM_GapMode==1)?MathAbs(iClose(Sym[s],SignalTF,k)-iClose(Sym[s],SignalTF,k+1))
                                 :MathAbs(iOpen(Sym[s],SignalTF,k)-iClose(Sym[s],SignalTF,k+1));
      if(jump>=GM_GapMult*avg) gap=true;
   }
   for(int k=j;k<j+6 && !fast;k++)
      if(MathAbs(iClose(Sym[s],SignalTF,k+3)-iClose(Sym[s],SignalTF,k))>=GM_FastMult*avg) fast=true;
   int period=gr*2+3;
   if(gap) period=3;
   if(fast) period=4;
   big=(gap||fast); per=period;
   return(WprS(s,period,j));
}
int GetSignalMOM(int s,int gr,bool &big,double &wpr,int &per,int &bib)
{
   double upper=gr+67, lower=33-gr;
   int LB=40; double val[]; ArrayResize(val,LB);
   bool b0=false; int p0=0;
   for(int k=0;k<LB;k++){ bool b=false; int p=0; val[k]=GMValS(s,goldminershift+k,gr,b,p); if(k==0){b0=b;p0=p;} }
   big=b0; wpr=val[0]; per=p0; bib=0;
   int dir=-1; int li=1;
   if(val[0]>upper){ while(li<LB-1 && val[li]>=lower && val[li]<=upper) li++; if(val[li]<lower) dir=(int)ORDER_TYPE_BUY; }
   else if(val[0]<lower){ while(li<LB-1 && val[li]>=lower && val[li]<=upper) li++; if(val[li]>upper) dir=(int)ORDER_TYPE_SELL; }
   bib=li; return(dir);
}
// CUSUM: accumulate last closed-bar return; breach when |cum| >= h (=param x ATR_cur). Resets the breached side.
// returns +1 up-breach, -1 down-breach, 0 none. Updates state at index si.
int CusumStep(int s,int si,double h)
{
   double rret=iClose(Sym[s],SignalTF,1)-iClose(Sym[s],SignalTF,2);
   cusPos[si]=MathMax(0.0, cusPos[si]+rret);
   cusNeg[si]=MathMin(0.0, cusNeg[si]+rret);
   if(cusPos[si]>=h){ cusPos[si]=0; return(1); }
   if(cusNeg[si]<=-h){ cusNeg[si]=0; return(-1); }
   return(0);
}
// mean-reversion: fresh cross into extreme. z-score (MR_Mode 0) param=sigma; RSI (MR_Mode 1) param=level.
int GetSignalMR(int s,double thr)
{
   if(MR_Mode==1)
   {
      double r0=RB(hRSI[s],0,1), r1=RB(hRSI[s],0,2);
      if(r0<thr && r1>=thr) return((int)ORDER_TYPE_BUY);
      if(r0>(100.0-thr) && r1<=(100.0-thr)) return((int)ORDER_TYPE_SELL);
      return(-1);
   }
   double sd1=RB(hMRsd[s],0,1), sd2=RB(hMRsd[s],0,2);
   if(sd1<=0||sd2<=0) return(-1);
   double z0=(iClose(Sym[s],SignalTF,1)-RB(hMRma[s],0,1))/sd1;
   double z1=(iClose(Sym[s],SignalTF,2)-RB(hMRma[s],0,2))/sd2;
   if(z0<-thr && z1>=-thr) return((int)ORDER_TYPE_BUY);
   if(z0> thr && z1<= thr) return((int)ORDER_TYPE_SELL);
   return(-1);
}
bool D1BullS(int s){ return(RB(hMAd1[s],0,0)>RB(hMAd1[s],0,1)); }
double AngleS(int s){ double m0=RB(hMA[s],0,0),m1=RB(hMA[s],0,5); double sl=(m0-m1)/(5*symPoint[s]); return(MathArctan(sl)*180.0/M_PI); }
double RunupS(int s,int dir){ double atr=RB(hATRcur[s],0,1); if(atr<=0) return(0); double now=iClose(Sym[s],SignalTF,goldminershift),then=iClose(Sym[s],SignalTF,goldminershift+RunupBars); double mv=now-then; if(dir==(int)ORDER_TYPE_SELL) mv=-mv; return(mv/atr); }
string ClassifyS(int s,int dir,datetime t)
{
   string d=(dir==ORDER_TYPE_BUY)?"BUY":"SELL";
   int hr=BarHour(t);
   string hrB=(hr<9)?"HR_ASIA":(hr<14)?"HR_LDN":(hr<18)?"HR_OVL":"HR_NY";
   double an=RB(hATRcur[s],0,1),aa=RB(hATRavg[s],0,1);
   string atrB; if(aa==0) atrB="ATR_NA"; else if(an>aa*1.3) atrB="ATR_EXP"; else if(an<aa*0.7) atrB="ATR_COMP"; else atrB="ATR_NORM";
   return(d+"|"+hrB+"|"+atrB);
}

void AddPending(int s,double prm,string key,int dir,double wpr,double adx,double ang,double run,int per,int bib,datetime barTime)
{
   if(pN>=MAXP) return;
   double atrD1=RB(hATRd1[s],0,1);
   double ref=atrD1*R_UnitATR; if(ref<=0) return;
   double bid=SymbolInfoDouble(Sym[s],SYMBOL_BID),ask=SymbolInfoDouble(Sym[s],SYMBOL_ASK);
   double px=(dir==ORDER_TYPE_BUY)?ask:bid;
   pSym[pN]=s; pParam[pN]=prm; pSetup[pN]=key; pDir[pN]=dir; pEntry[pN]=barTime; pPx[pN]=px;
   pRef[pN]=ref; pTime[pN]=barTime+HorizonBars*PeriodSeconds(SignalTF);
   pMFE[pN]=0; pMAE[pN]=0; pWpr[pN]=wpr; pAdx[pN]=adx; pAng[pN]=ang; pRun[pN]=run; pPer[pN]=per; pBib[pN]=bib;
   pN++;
}
void RemoveAt(int idx)
{
   for(int i=idx;i<pN-1;i++)
   {
      pSym[i]=pSym[i+1]; pParam[i]=pParam[i+1]; pSetup[i]=pSetup[i+1]; pDir[i]=pDir[i+1]; pEntry[i]=pEntry[i+1];
      pPx[i]=pPx[i+1]; pRef[i]=pRef[i+1]; pTime[i]=pTime[i+1]; pMFE[i]=pMFE[i+1]; pMAE[i]=pMAE[i+1];
      pWpr[i]=pWpr[i+1]; pAdx[i]=pAdx[i+1]; pAng[i]=pAng[i+1]; pRun[i]=pRun[i+1]; pPer[i]=pPer[i+1]; pBib[i]=pBib[i+1];
   }
   pN--;
}
void WriteRow(int idx,double horizonR,datetime outTime)
{
   g_total+=horizonR;
   int s=pSym[idx]; int dg=(int)SymbolInfoInteger(Sym[s],SYMBOL_DIGITS);
   int fh=FileOpen(OutCSV,FILE_READ|FILE_WRITE|FILE_CSV|FILE_COMMON|FILE_ANSI,',');
   if(fh==INVALID_HANDLE) return;
   FileSeek(fh,0,SEEK_END);
   FileWrite(fh, Sym[s], ENG, DoubleToString(pParam[idx],2), pSetup[idx],
      TimeToString(pEntry[idx],TIME_DATE|TIME_MINUTES), DoubleToString(pPx[idx],dg),
      (pDir[idx]==ORDER_TYPE_BUY)?"BUY":"SELL", DoubleToString(pRef[idx],dg),
      DoubleToString(horizonR,3), DoubleToString(pMFE[idx],3), DoubleToString(pMAE[idx],3),
      TimeToString(outTime,TIME_DATE|TIME_MINUTES),
      DoubleToString(pWpr[idx],1), DoubleToString(pAdx[idx],1), DoubleToString(pAng[idx],1),
      DoubleToString(pRun[idx],3), IntegerToString(pPer[idx]), IntegerToString(pBib[idx]));
   FileClose(fh);
}
void UpdateForSymbol(int s,double barHigh,double barLow,datetime nowTime)
{
   for(int i=pN-1;i>=0;i--)
   {
      if(pSym[i]!=s) continue;
      bool isBuy=(pDir[i]==ORDER_TYPE_BUY);
      double fav=(isBuy?(barHigh-pPx[i]):(pPx[i]-barLow))/pRef[i];
      double adv=(isBuy?(pPx[i]-barLow):(barHigh-pPx[i]))/pRef[i];
      if(fav>pMFE[i]) pMFE[i]=fav;
      if(adv>pMAE[i]) pMAE[i]=adv;
      if(nowTime>=pTime[i])
      {
         double cur=iClose(Sym[s],SignalTF,1);
         double hr=(isBuy?(cur-pPx[i]):(pPx[i]-cur))/pRef[i];
         WriteRow(i,hr,nowTime); RemoveAt(i);
      }
   }
}

//+------------------------------------------------------------------+
void OnTick()
{
   for(int s=0;s<NSym;s++)
   {
      if(!symOK[s]) continue;
      datetime t0=iTime(Sym[s],SignalTF,0);
      if(t0==0 || t0==symLast[s]) continue;
      symLast[s]=t0;

      double bh=iHigh(Sym[s],SignalTF,1), bl=iLow(Sym[s],SignalTF,1);
      UpdateForSymbol(s,bh,bl,t0);

      bool inSession = (!UseSessionFilter) || (BarHour(t0)>=SessionStartHour && BarHour(t0)<SessionEndHour);

      bool bull=D1BullS(s);
      double adx=RB(hADX[s],0,0);
      double ang0=AngleS(s);
      bool strong=(adx>ADX_Threshold && MathAbs(ang0)>MA_Angle_Threshold);
      double atrcur=RB(hATRcur[s],0,1);

      for(int pi=0; pi<NP; pi++)
      {
         double prm=Params[pi];
         int si=s*NP+pi;
         int dir=-1; bool big=false; double wpr=0; int per=0,bib=0;

         if(TriggerMode==1 || TriggerMode==2)
         {
            int br=CusumStep(s,si, prm*atrcur);   // ALWAYS step CUSUM (accumulation) before session gate
            if(!inSession || br==0) continue;
            dir = (TriggerMode==1) ? (br>0?(int)ORDER_TYPE_BUY:(int)ORDER_TYPE_SELL)
                                   : (br>0?(int)ORDER_TYPE_SELL:(int)ORDER_TYPE_BUY);
            if(TriggerMode==2 && MR_RequireRanging && adx>=ADX_Threshold) continue;
         }
         else
         {
            if(!inSession) continue;
            if(TriggerMode==3)
            {
               dir=GetSignalMR(s,prm);
               if(dir<0) continue;
               if(MR_RequireRanging && adx>=ADX_Threshold) continue;
            }
            else
            {
               dir=GetSignalMOM(s,(int)prm,big,wpr,per,bib);
               if(dir<0) continue;
               if(!strong) continue;
               if(UseDailyTrendFilter){ if(dir==ORDER_TYPE_BUY && !bull) continue; if(dir==ORDER_TYPE_SELL && bull) continue; }
            }
         }
         double ang=(dir==ORDER_TYPE_BUY)?ang0:-ang0;
         double run=RunupS(s,dir);
         string key=ClassifyS(s,dir,t0);
         AddPending(s,prm,key,dir,wpr,adx,ang,run,per,bib,t0);
      }
   }
}
//+------------------------------------------------------------------+
