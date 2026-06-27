#!/usr/bin/env python3
"""
RECOVERY HEDGE (user's "hedge into profit") in the MT4 SAFE EA. Default OFF.
When the whole book floats <= -HedgeTriggerLoss, ARM: stop feeding the losing side,
and add the WINNING (hedge) side on every Goldminer signal -- OVERRIDING the D1 filter
(the thing that blocked the hedge and caused the landmines) -- growing it (Fibonacci)
until the combined book >= RecoveryTargetUSD, then close everything in profit.
The catastrophe floor remains the backstop if a violent reversal beats the recovery.
"""
import io, sys
PATH = r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\98A82F92176B73A2100FCD1F8ABD7255\MQL4\Experts\Adapted\Marius Hedger M5 v1.0 fib C SAFE.mq4"
s = io.open(PATH, "r", encoding="utf-16").read()
if "UseRecoveryHedge" in s:
    print("ALREADY PATCHED -- aborting."); sys.exit(1)

def rep(t, old, new):
    assert old in t, f"NOT FOUND: {old!r}"
    assert t.count(old)==1, f"AMBIGUOUS ({t.count(old)}x): {old!r}"
    return t.replace(old, new)
def after_line(t, token, payload):
    i=t.find(token); assert i!=-1, f"NOT FOUND {token!r}"; nl=t.find("\n", i); return t[:nl+1]+payload+t[nl+1:]
def before(t, token, payload):
    assert token in t, f"NOT FOUND {token!r}"; i=t.find(token); return t[:i]+payload+t[i:]

# 1. INPUTS (after FreezeWaitBars input line)
s = after_line(s, "FreezeWaitBars   = 2880;",
"\n// --- RECOVERY HEDGE: ride the trend with the winning side to recover a deep basket (default OFF) ---\n"
"input bool   UseRecoveryHedge   = false;  // book deep negative -> stop feeding the loser, add the WINNING side on every Goldminer signal (overriding D1) till profitable\n"
"input double HedgeTriggerLoss   = 300.0;  // book floating loss ($) that arms recovery ($250-350). Raise on bigger lots/accounts.\n"
"input double HedgeTriggerPctBal = 0.0;    // OR arm at this %% of balance (0 = use HedgeTriggerLoss $); scales with the account\n"
"input double RecoveryTargetUSD  = 30.0;   // close the WHOLE book once combined float >= this (banked in profit)\n")

# 2. GLOBALS (after the freeze start-time global)
s = after_line(s, "datetime g_freezeStartTime = 0;",
"bool g_recovering    = false;\nint  g_recoverWinDir = -1;\n")

# 3. NEW FUNCTION (before OnTick)
s = before(s, "void OnTick()",
"""//+----- RECOVERY HEDGE: ride the trend with the winning side to recover a deep basket (default OFF) -----+
void CheckRecoveryHedge() {
        if (!UseRecoveryHedge) return;
        double buyFloat=0, sellFloat=0; int openTotal=0;
        for (int i = OrdersTotal()-1; i >= 0; i--) {
                if (!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
                if (OrderMagicNumber() != MagicNumber) continue;
                if (OrderType()!=OP_BUY && OrderType()!=OP_SELL) continue;
                double pl = OrderProfit()+OrderSwap()+OrderCommission();
                if (OrderType()==OP_BUY) buyFloat += pl; else sellFloat += pl;
                openTotal++;
        }
        double bookFloat = buyFloat + sellFloat;
        if (g_recovering) {
                if (openTotal==0) { g_recovering=false; g_recoverWinDir=-1; return; }
                if (bookFloat >= RecoveryTargetUSD) {
                        Print("RECOVERY COMPLETE: book=+", DoubleToString(bookFloat,2), " -- closing all in profit");
                        CloseAllTrades(OP_BUY); CloseAllTrades(OP_SELL);
                        g_recovering=false; g_recoverWinDir=-1; peakBasketFloat=0;
                }
                return;
        }
        if (openTotal==0) return;
        double trigger = (HedgeTriggerPctBal>0) ? (HedgeTriggerPctBal/100.0)*AccountBalance() : HedgeTriggerLoss;
        if (bookFloat <= -trigger) {
                int deepLossDir = (buyFloat <= sellFloat) ? OP_BUY : OP_SELL;
                g_recoverWinDir = (deepLossDir==OP_BUY) ? OP_SELL : OP_BUY;
                g_recovering = true;
                Print("RECOVERY HEDGE ARMED: book=", DoubleToString(bookFloat,2),
                      " loser=", (deepLossDir==OP_BUY?"BUY":"SELL"),
                      " -> riding ", (g_recoverWinDir==OP_BUY?"BUY":"SELL"), " to recover");
        }
}

""")

# 4. ManageGoldminerLogic: ride only the winning side while recovering, overriding D1
s = before(s, "    // Buy Signal\n",
"""    // RECOVERY HEDGE: ride ONLY the winning side, overriding D1, till the book recovers
    if (g_recovering) {
        if (g_recoverWinDir==OP_BUY  && ggreen > 0) OpenTrade(OP_BUY);
        if (g_recoverWinDir==OP_SELL && gred   > 0) OpenTrade(OP_SELL);
        return;
    }
""")

# 5. OpenTrade: recovery branch (bypass all gates for the winning side; block the loser)
s = rep(s,
"void OpenTrade(int orderType) {\n        if (g_frozen) return;\n",
"""void OpenTrade(int orderType) {
        if (g_frozen) return;
        if (g_recovering) {
                if (orderType != g_recoverWinDir) return;                 // never feed the loser
                double rlots = CalculateLotSize(orderType);               // grow the winning side
                double rprice = (orderType==OP_BUY) ? MarketInfo(Symbol(),MODE_ASK) : MarketInfo(Symbol(),MODE_BID);
                int rt = OrderSend(Symbol(), orderType, rlots, rprice, 3, 0, 0, "FIB C RCV", MagicNumber, 0, clrMagenta);
                if (rt>0) { tradesThisBar++; Print("RECOVERY add ", (orderType==OP_BUY?"BUY":"SELL"), " ", DoubleToString(rlots,2), " @ ", DoubleToString(rprice,Digits)); }
                else Print("RECOVERY add FAILED. Error:", GetLastError());
                return;
        }
""")

# 6. OnTick hooks
s = rep(s, "CheckFreezeRelease();\n                CheckCatastrophicFloor();",
           "CheckFreezeRelease();\n                CheckRecoveryHedge();\n                CheckCatastrophicFloor();")
s = rep(s, "if (!inSession) return;", "if (!inSession && !g_recovering) return;")
s = rep(s, "if(!g_frozen) CheckBasketTrail();", "if(!g_frozen && !g_recovering) CheckBasketTrail();")

# 7. CheckCatastrophicFloor: don't freeze while recovering; reset recovery on floor cut
s = rep(s, "if ((UseFreezeWait || UseConditionalFreeze) && !g_frozen && totalFloat <= maxLoss) {",
           "if ((UseFreezeWait || UseConditionalFreeze) && !g_recovering && !g_frozen && totalFloat <= maxLoss) {")
s = rep(s,
'                      " (floorPct=", DoubleToString(floorPct,1), ") -- closing entire book");\n'
"                CloseAllTrades(OP_BUY);\n"
"                CloseAllTrades(OP_SELL);\n"
"                peakBasketFloat = 0;\n",
'                      " (floorPct=", DoubleToString(floorPct,1), ") -- closing entire book");\n'
"                CloseAllTrades(OP_BUY);\n"
"                CloseAllTrades(OP_SELL);\n"
"                peakBasketFloat = 0;\n"
"                g_recovering=false; g_recoverWinDir=-1;\n")

# 8. config print
s = rep(s, '") FreezeWait("', '") Recovery(", (UseRecoveryHedge?"ON":"off"), ") FreezeWait("')

io.open(PATH, "w", encoding="utf-16").write(s)
print("RECOVERY HEDGE PATCH APPLIED OK.")
for t in ["UseRecoveryHedge","CheckRecoveryHedge()","g_recoverWinDir","RECOVERY add ","if (g_recovering) {"]:
    print(f"  present: {t in s}   {t}")
