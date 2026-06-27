#!/usr/bin/env python3
"""
Port the FIRST-ENTRY PROBABILITY GATE from the MT5 fib C into the MT4 SAFE EA.
Default OFF (UseFirstEntryGate=false) -> base config byte-identical to live.
Reads the SAME GridStat shadow DB (gridstat_setups_gold.csv) from the shared
Common\\Files (read-only). Gates ONLY the first leg of a basket; recovery legs bypass.
"""
import io, sys

PATH = r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\98A82F92176B73A2100FCD1F8ABD7255\MQL4\Experts\Adapted\Marius Hedger M5 v1.0 fib C SAFE.mq4"
s = io.open(PATH, "r", encoding="utf-16").read()

if "UseFirstEntryGate" in s:
    print("ALREADY PATCHED -- aborting."); sys.exit(1)

def insert_after_line(text, token, payload):
    i = text.find(token); assert i != -1, f"ANCHOR NOT FOUND: {token!r}"
    nl = text.find("\n", i); assert nl != -1
    return text[:nl+1] + payload + text[nl+1:]

def insert_before_line(text, token, payload):
    i = text.find(token); assert i != -1, f"ANCHOR NOT FOUND: {token!r}"
    ls = text.rfind("\n", 0, i); assert ls != -1
    return text[:ls+1] + payload + text[ls+1:]

def insert_before_token(text, token, payload):
    i = text.find(token); assert i != -1, f"ANCHOR NOT FOUND: {token!r}"
    return text[:i] + payload + text[i:]

# ---- 1. INPUTS (after the freeze inputs block) ----
inputs = (
"\n// --- FIRST-ENTRY PROBABILITY GATE (default OFF; base == live) ---\n"
"input bool   UseFirstEntryGate       = false;  // gate the FIRST leg of a basket on its fingerprint win-rate (recovery legs bypass)\n"
"input string FirstGateStatsCSV       = \"gridstat_setups_gold.csv\";  // GridStat shadow DB in Common\\Files (read-only)\n"
"input double FirstGateMinWinRate     = 0.55;   // BUY-start win-rate threshold\n"
"input double FirstGateSellMinWinRate = 0.65;   // SELL-start threshold (0 = use FirstGateMinWinRate); gold longs >> shorts\n"
"input int    FirstGateMinSamples     = 10;     // min samples for a fingerprint to be tradeable\n"
)
s = insert_after_line(s, "FreezeHardRuinPct", inputs)

# ---- 2. FUNCTIONS (before void OnTick) ----
funcs = r"""
//+----- FIRST-ENTRY PROBABILITY GATE (ported from GridStat/MT5 fib C; default OFF) -----+
// Gate ONLY the first leg of a basket on the historical win-rate of its fingerprint
// (DIR|HR_session|ATR_regime), read from the GridStat shadow DB. Recovery legs bypass.
string ClassifySetup(int dir) {
        string d   = (dir==OP_BUY) ? "BUY" : "SELL";
        int    hr  = TimeHour(TimeCurrent());
        string hrB = (hr<9) ? "HR_ASIA" : (hr<14) ? "HR_LDN" : (hr<18) ? "HR_OVL" : "HR_NY";
        double an  = iATR(NULL, 0, 20, 1);
        double aa  = iATR(NULL, 0, 100, 1);
        string atrB= (aa==0) ? "ATR_NA" : (an>aa*1.3) ? "ATR_EXP" : (an<aa*0.7) ? "ATR_COMP" : "ATR_NORM";
        return(d + "|" + hrB + "|" + atrB);
}
bool LookupFirstGateStats(string setupKey, double &winRate, int &samples) {
        int fh = FileOpen(FirstGateStatsCSV, FILE_READ|FILE_CSV|FILE_COMMON, ',');
        if (fh==INVALID_HANDLE) { winRate=0; samples=0; return(false); }
        int ncol=0, rIdx=-1;
        while (!FileIsEnding(fh)) {
                string c = FileReadString(fh);
                if (c=="r_multiple") rIdx=ncol;
                ncol++;
                if (FileIsLineEnding(fh)) break;
        }
        if (rIdx<0 || ncol<=0) { FileClose(fh); winRate=0; samples=0; return(false); }
        int wins=0, total=0;
        while (!FileIsEnding(fh)) {
                string key=""; double r=0; bool any=false;
                for (int c=0; c<ncol && !FileIsEnding(fh); c++) {
                        string cell = FileReadString(fh); any=true;
                        if (c==0) key=cell;
                        if (c==rIdx) r=StringToDouble(cell);
                }
                if (!any) break;
                if (key==setupKey) { total++; if (r>0) wins++; }
        }
        FileClose(fh);
        samples=total; winRate=(total>0) ? (double)wins/total : 0.0;
        return(total>0);
}
"""
s = insert_before_token(s, "void OnTick()", funcs + "\n")

# ---- 3. GATE in OpenTrade (before the MaxSameTrades cap; first leg only) ----
gate = (
"                if (UseFirstEntryGate && CountOpenTrades(orderType) == 0) {\n"
"                        double fgWr=0; int fgN=0; string fgKey=ClassifySetup(orderType);\n"
"                        if (!LookupFirstGateStats(fgKey, fgWr, fgN)) return;       // unknown fingerprint -> don't start\n"
"                        double fgThr = FirstGateMinWinRate;\n"
"                        if (orderType==OP_SELL && FirstGateSellMinWinRate>0) fgThr = FirstGateSellMinWinRate;\n"
"                        if (fgN < FirstGateMinSamples || fgWr < fgThr) return;     // low-probability -> don't start\n"
"                }\n"
)
s = insert_before_line(s, "if (CountOpenTrades(orderType) >= MaxSameTrades)", gate)

# ---- 4. OnInit: print the gate config ----
cfg = (
"        Print(\"CONFIG | FirstEntryGate=\", (UseFirstEntryGate?\"ON\":\"off\"),\n"
"              (UseFirstEntryGate ? \" (BUY>=\"+DoubleToString(FirstGateMinWinRate,2)+\" SELL>=\"+DoubleToString(FirstGateSellMinWinRate>0?FirstGateSellMinWinRate:FirstGateMinWinRate,2)+\" n>=\"+IntegerToString(FirstGateMinSamples)+\" DB=\"+FirstGateStatsCSV+\")\" : \"\"));\n"
)
s = insert_before_token(s, "AdoptFreeze();", cfg)

io.open(PATH, "w", encoding="utf-16").write(s)
print("GATE PATCH APPLIED OK.")
for t in ["UseFirstEntryGate","ClassifySetup(","LookupFirstGateStats(","FirstGateSellMinWinRate>0) fgThr"]:
    print(f"  {t:32} present:", t in s)
