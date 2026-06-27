#!/usr/bin/env python3
"""
OPTION B -- FREEZE-AND-WAIT (no classifier) in the MT4 SAFE EA.
At the floor trigger: ALWAYS neutralize the book with a full opposite hedge
(loss capped, can't grow). Then let the market reveal itself:
  RELEASE -> if the basket claws back (origFloat >= trig + FreezeReleaseGainPct%), drop the hedge, basket rides/harvests.
  CUT     -> if it does NOT recover within FreezeWaitBars, cut the whole book at the (capped) loss.
Default OFF (UseFreezeWait=false) -> base byte-identical. Independent of the rejected
classifier (UseConditionalFreeze stays in code for reference).
"""
import io, sys
PATH = r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\98A82F92176B73A2100FCD1F8ABD7255\MQL4\Experts\Adapted\Marius Hedger M5 v1.0 fib C SAFE.mq4"
s = io.open(PATH, "r", encoding="utf-16").read()
if "UseFreezeWait" in s:
    print("ALREADY PATCHED -- aborting."); sys.exit(1)

def rep(text, old, new):
    assert old in text, f"ANCHOR NOT FOUND: {old!r}"
    assert text.count(old)==1, f"AMBIGUOUS ({text.count(old)}x): {old!r}"
    return text.replace(old, new)
def after_line(text, token, payload):
    i=text.find(token); assert i!=-1, f"NOT FOUND {token!r}"; nl=text.find("\n", i); return text[:nl+1]+payload+text[nl+1:]
def before(text, token, payload):
    assert token in text, f"NOT FOUND {token!r}"; i=text.find(token); return text[:i]+payload+text[i:]

# 1. INPUTS
s = after_line(s, "FreezeHardRuinPct",
"\n// --- OPTION B: FREEZE-AND-WAIT (no classifier; default OFF) ---\n"
"input bool   UseFreezeWait    = false;  // at floor trigger ALWAYS neutralize (full hedge, loss capped); release if it reverts, cut if not within the window\n"
"input int    FreezeWaitBars   = 2880;   // recovery window in M5 bars (~2 weeks) before a non-recovering frozen basket is cut at the capped loss\n")

# 2. GLOBAL
s = after_line(s, 'FreezeTag         = "FREEZE";', "datetime g_freezeStartTime = 0;\n")

# 3. OpenFreezeHedge: stamp the freeze start time
s = rep(s, "g_frozen = true; g_frozenDir = bookDir; g_freezeTrigFloat = trigFloat;",
           "g_frozen = true; g_frozenDir = bookDir; g_freezeTrigFloat = trigFloat; g_freezeStartTime = TimeCurrent();")

# 4. trigger condition: include FreezeWait
s = rep(s, "if (UseConditionalFreeze && !g_frozen && totalFloat <= maxLoss) {",
           "if ((UseFreezeWait || UseConditionalFreeze) && !g_frozen && totalFloat <= maxLoss) {")

# 5. freeze-or-cut decision: FreezeWait = always freeze; classifier = D1 alignment
s = rep(s,
"                        bool fd1  = IsDailyTrendBullish();\n"
"                        bool fal  = (fbDir==OP_BUY && fd1) || (fbDir==OP_SELL && !fd1);\n"
"                        if (fbDir != -1 && fal) { OpenFreezeHedge(fbDir, MathAbs(buyLots-sellLots), totalFloat); return; }\n",
"                        bool doFreeze;\n"
"                        if (UseFreezeWait) doFreeze = (fbDir != -1);\n"
"                        else { bool fd1=IsDailyTrendBullish(); doFreeze = (fbDir != -1) && ((fbDir==OP_BUY&&fd1)||(fbDir==OP_SELL&&!fd1)); }\n"
"                        if (doFreeze) { OpenFreezeHedge(fbDir, MathAbs(buyLots-sellLots), totalFloat); return; }\n")

# 6. CheckFreezeRelease: remove the early ABANDON block (cut decision moves below RELEASE)
s = rep(s,
"        // ABANDON: D1 flipped against the protected basket -> real regime change -> cut all\n"
"        bool d1Bull = IsDailyTrendBullish();\n"
"        bool stillAligned = (g_frozenDir==OP_BUY && d1Bull) || (g_frozenDir==OP_SELL && !d1Bull);\n"
"        if (!stillAligned) {\n"
'                Print("FREEZE ABANDON: D1 flipped against frozen ", (g_frozenDir==OP_BUY?"BUY":"SELL"),\n'
'                      " basket -- cutting whole book");\n'
"                CloseAllTrades(OP_BUY); CloseAllTrades(OP_SELL);\n"
"                g_frozen=false; g_frozenDir=-1; peakBasketFloat=0; return;\n"
"        }\n",
"        // (cut decision is below the RELEASE check -- mode-specific)\n")

# 7. insert the mode-specific CUT block right before the hard-ruin backstop (after RELEASE)
s = before(s, "        // optional hard-ruin backstop (should not fire while neutralized)\n",
"        // CUT decision (only after RELEASE failed) -- mode-specific:\n"
"        if (UseFreezeWait) {\n"
"                int barsFrozen = (g_freezeStartTime>0) ? iBarShift(NULL,0,g_freezeStartTime) : 0;\n"
"                if (barsFrozen >= FreezeWaitBars) {\n"
'                        Print("FREEZE-WAIT EXPIRED: no recovery in ", barsFrozen, " bars -- cutting at capped loss");\n'
"                        CloseAllTrades(OP_BUY); CloseAllTrades(OP_SELL);\n"
"                        g_frozen=false; g_frozenDir=-1; peakBasketFloat=0; return;\n"
"                }\n"
"        } else {\n"
"                bool d1Bull = IsDailyTrendBullish();\n"
"                bool stillAligned = (g_frozenDir==OP_BUY && d1Bull) || (g_frozenDir==OP_SELL && !d1Bull);\n"
"                if (!stillAligned) {\n"
'                        Print("FREEZE ABANDON: D1 flipped -- cutting whole book");\n'
"                        CloseAllTrades(OP_BUY); CloseAllTrades(OP_SELL);\n"
"                        g_frozen=false; g_frozenDir=-1; peakBasketFloat=0; return;\n"
"                }\n"
"        }\n")

# 8. config print
s = rep(s, '") frozen=", (g_frozen?"YES":"no")',
           '") FreezeWait(", (UseFreezeWait?"ON":"off"), ") frozen=", (g_frozen?"YES":"no")')

io.open(PATH, "w", encoding="utf-16").write(s)
print("FREEZE-AND-WAIT PATCH APPLIED OK.")
for t in ["UseFreezeWait","FreezeWaitBars","FREEZE-WAIT EXPIRED","if (UseFreezeWait) doFreeze","g_freezeStartTime = TimeCurrent()"]:
    print(f"  present: {t in s}   {t}")
