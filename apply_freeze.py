#!/usr/bin/env python3
"""
Insert the CONDITIONAL FREEZE-vs-CUT mine-walk into the fib C SAFE MT4 EA.
All new code is gated behind UseConditionalFreeze (default false) so the base
config stays byte-identical to live. Edits the UTF-16 .mq4 via token splices.
"""
import io, sys

PATH = r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\98A82F92176B73A2100FCD1F8ABD7255\MQL4\Experts\Adapted\Marius Hedger M5 v1.0 fib C SAFE.mq4"

s = io.open(PATH, "r", encoding="utf-16").read()

if "UseConditionalFreeze" in s:
    print("ALREADY PATCHED -- aborting (no double-insert)."); sys.exit(1)

def insert_after_line(text, token, payload):
    """insert payload right after the newline that ends the line containing `token` (first occurrence)."""
    i = text.find(token)
    assert i != -1, f"ANCHOR NOT FOUND: {token!r}"
    nl = text.find("\n", i)
    assert nl != -1, f"no newline after {token!r}"
    return text[:nl+1] + payload + text[nl+1:]

def insert_before_line(text, token, payload):
    """insert payload at the start of the line containing `token` (first occurrence)."""
    i = text.find(token)
    assert i != -1, f"ANCHOR NOT FOUND: {token!r}"
    ls = text.rfind("\n", 0, i)
    assert ls != -1, f"no newline before {token!r}"
    return text[:ls+1] + payload + text[ls+1:]

def insert_before_token(text, token, payload):
    i = text.find(token)
    assert i != -1, f"ANCHOR NOT FOUND: {token!r}"
    return text[:i] + payload + text[i:]

def replace_first(text, old, new):
    i = text.find(old)
    assert i != -1, f"ANCHOR NOT FOUND: {old!r}"
    return text[:i] + new + text[i+len(old):]

# ---- 1. INPUTS (after the D1AlignedFloorMult input line) ----
inputs = (
"\n// --- CONDITIONAL FREEZE mine-walk (default OFF; base == live) ---\n"
"input bool   UseConditionalFreeze   = false;  // at floor trigger, FREEZE D1-ALIGNED baskets (full opposite hedge, loss capped) instead of cutting; still CUT counter-D1\n"
"input double FreezeReleaseGainPct    = 15.0;   // release the hedge once the ORIGINAL basket float recovers this % of balance above the freeze-trigger level (bounce reverted)\n"
"input double FreezeHardRuinPct       = 0.0;    // 0=off; last-resort hard cut if the frozen book ever floats below this % of balance\n"
)
s = insert_after_line(s, "D1AlignedFloorMult", inputs)

# ---- 2. GLOBALS (after dailyBullishInitialized decl) ----
globals_block = (
"bool   g_frozen          = false;\n"
"int    g_frozenDir       = -1;\n"
"double g_freezeTrigFloat = 0;\n"
"string FreezeTag         = \"FREEZE\";\n"
)
s = insert_after_line(s, "dailyBullishInitialized", globals_block)

# ---- 3. NEW FUNCTIONS (before void OnTick) ----
funcs = r"""
//+----- Conditional FREEZE-vs-CUT mine-walk (default OFF) -----+
double NormalizeLots(double lots) {
        double step = MarketInfo(Symbol(), MODE_LOTSTEP);
        double minL = MarketInfo(Symbol(), MODE_MINLOT);
        double maxL = MarketInfo(Symbol(), MODE_MAXLOT);
        if (step <= 0) step = 0.01;
        lots = MathFloor(lots/step + 0.5) * step;
        if (lots < minL) lots = minL;
        if (lots > maxL) lots = maxL;
        return NormalizeDouble(lots, 2);
}
void CloseTicketByNum(int ticket) {
        if (!OrderSelect(ticket, SELECT_BY_TICKET)) return;
        double cp = (OrderType()==OP_BUY) ? MarketInfo(Symbol(),MODE_BID) : MarketInfo(Symbol(),MODE_ASK);
        if (!OrderClose(ticket, OrderLots(), cp, 5, clrAqua))
                Print("FREEZE hedge close failed. Error:", GetLastError());
}
void OpenFreezeHedge(int bookDir, double netLots, double trigFloat) {
        int hedgeType = (bookDir==OP_BUY) ? OP_SELL : OP_BUY;
        double lots = NormalizeLots(netLots);
        if (lots <= 0) return;
        double price = (hedgeType==OP_BUY) ? MarketInfo(Symbol(),MODE_ASK) : MarketInfo(Symbol(),MODE_BID);
        int ticket = OrderSend(Symbol(), hedgeType, lots, price, 5, 0, 0, FreezeTag, MagicNumber, 0, clrAqua);
        if (ticket > 0) {
                g_frozen = true; g_frozenDir = bookDir; g_freezeTrigFloat = trigFloat;
                Print("FREEZE: D1-aligned ", (bookDir==OP_BUY?"BUY":"SELL"),
                      " basket frozen with ", DoubleToString(lots,2), " ",
                      (hedgeType==OP_BUY?"BUY":"SELL"), " hedge @ ", DoubleToString(price,Digits),
                      " trigFloat=", DoubleToString(trigFloat,2));
        } else Print("FREEZE hedge FAILED. Error:", GetLastError());
}
void CheckFreezeRelease() {
        if (!g_frozen) return;
        double origFloat = 0, hedgeFloat = 0; int hedgeTicket = -1;
        for (int i = OrdersTotal()-1; i >= 0; i--) {
                if (!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
                if (OrderMagicNumber() != MagicNumber) continue;
                if (OrderType()!=OP_BUY && OrderType()!=OP_SELL) continue;
                double pl = OrderProfit()+OrderSwap()+OrderCommission();
                if (OrderComment()==FreezeTag) { hedgeFloat += pl; hedgeTicket = OrderTicket(); }
                else origFloat += pl;
        }
        double bal = AccountBalance();
        // ABANDON: D1 flipped against the protected basket -> real regime change -> cut all
        bool d1Bull = IsDailyTrendBullish();
        bool stillAligned = (g_frozenDir==OP_BUY && d1Bull) || (g_frozenDir==OP_SELL && !d1Bull);
        if (!stillAligned) {
                Print("FREEZE ABANDON: D1 flipped against frozen ", (g_frozenDir==OP_BUY?"BUY":"SELL"),
                      " basket -- cutting whole book");
                CloseAllTrades(OP_BUY); CloseAllTrades(OP_SELL);
                g_frozen=false; g_frozenDir=-1; peakBasketFloat=0; return;
        }
        // RELEASE: protected basket clawed back -> bounce reverted -> drop hedge, let it ride
        double releaseLevel = g_freezeTrigFloat + (FreezeReleaseGainPct/100.0)*bal;
        if (origFloat >= releaseLevel) {
                if (hedgeTicket > 0) CloseTicketByNum(hedgeTicket);
                Print("FREEZE RELEASE: basket recovered origFloat=", DoubleToString(origFloat,2),
                      " >= ", DoubleToString(releaseLevel,2), " -- hedge closed, basket rides");
                g_frozen=false; g_frozenDir=-1; peakBasketFloat=0; return;
        }
        // optional hard-ruin backstop (should not fire while neutralized)
        if (FreezeHardRuinPct > 0) {
                double both = origFloat + hedgeFloat;
                if (both <= -(FreezeHardRuinPct/100.0)*bal) {
                        Print("FREEZE HARD RUIN: combined=", DoubleToString(both,2), " -- cutting");
                        CloseAllTrades(OP_BUY); CloseAllTrades(OP_SELL);
                        g_frozen=false; g_frozenDir=-1; peakBasketFloat=0;
                }
        }
}
void AdoptFreeze() {
        g_frozen=false; g_frozenDir=-1;
        for (int i = OrdersTotal()-1; i >= 0; i--) {
                if (!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
                if (OrderMagicNumber() != MagicNumber) continue;
                if (OrderComment()==FreezeTag) {
                        g_frozen = true;
                        g_frozenDir = (OrderType()==OP_BUY) ? OP_SELL : OP_BUY;
                }
        }
        Print("BUILD 2026-06-24 ConditionalFreeze (", (UseConditionalFreeze?"ON":"off"),
              ") frozen=", (g_frozen?"YES":"no"));
}
"""
s = insert_before_token(s, "void OnTick()", funcs + "\n")

# ---- 4. OnTick hooks: freeze-release before floor; skip basket-trail while frozen ----
s = replace_first(s, "CheckCatastrophicFloor();",
                  "CheckFreezeRelease();\n                CheckCatastrophicFloor();")
s = replace_first(s, "CheckBasketTrail();",
                  "if(!g_frozen) CheckBasketTrail();")

# ---- 5. CheckCatastrophicFloor: skip while frozen + FREEZE-or-cut at trigger ----
# 5a: skip when frozen (right after the UseBasketStop guard)
s = insert_after_line(s, "!UseBasketStop", "                if (g_frozen) return;\n")
# 5b: freeze-or-cut block immediately before the cut-if
freeze_block = (
"                if (UseConditionalFreeze && !g_frozen && totalFloat <= maxLoss) {\n"
"                        int fbDir = (buyLots>sellLots) ? OP_BUY : ((sellLots>buyLots) ? OP_SELL : -1);\n"
"                        bool fd1  = IsDailyTrendBullish();\n"
"                        bool fal  = (fbDir==OP_BUY && fd1) || (fbDir==OP_SELL && !fd1);\n"
"                        if (fbDir != -1 && fal) { OpenFreezeHedge(fbDir, MathAbs(buyLots-sellLots), totalFloat); return; }\n"
"                }\n"
)
s = insert_before_line(s, "if (totalFloat <= maxLoss)", freeze_block)

# ---- 6. OpenTrade: block new entries while frozen ----
i = s.find("OpenTrade(int")
assert i != -1, "OpenTrade signature not found"
brace = s.find("{", i)
assert brace != -1
s = s[:brace+1] + "\n        if (g_frozen) return;" + s[brace+1:]

# ---- 7. OnInit: adopt an existing freeze on (re)start ----
s = replace_first(s, "return(INIT_SUCCEEDED);", "AdoptFreeze();\n        return(INIT_SUCCEEDED);")

io.open(PATH, "w", encoding="utf-16").write(s)
print("PATCH APPLIED OK.")
print("UseConditionalFreeze present:", "UseConditionalFreeze" in s)
print("CheckFreezeRelease present:", "CheckFreezeRelease()" in s)
print("OpenFreezeHedge present:", "OpenFreezeHedge(" in s)
