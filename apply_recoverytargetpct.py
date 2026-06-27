#!/usr/bin/env python3
"""
Part 1.2 -- SCALE the recovery target to the rescue size (default OFF).
A rescue that clawed back a -$577 basket aiming for the same +$40 as a -$80 one
is poor reward-for-risk. RecoveryTargetPct (>0) makes the effective target =
max(RecoveryTargetUSD, RecoveryTargetPct% of the DEEPEST loss the basket reached),
so the big rescues aim higher. Stacks with UseRecoveryTrail (the trail rides above
the scaled target). HONEST trade-off: a higher target takes longer to reach -> more
exposure -> a rescue can fail to complete on a fast reversal. The backtest decides.
"""
import io, sys
PATH = r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\98A82F92176B73A2100FCD1F8ABD7255\MQL4\Experts\Adapted\Marius Hedger M5 v1.0 fib C SAFE.mq4"
s = io.open(PATH, "r", encoding="utf-16").read()
if "RecoveryTargetPct" in s:
    print("ALREADY PATCHED -- aborting."); sys.exit(1)

def rep(t, old, new):
    assert old in t, f"NOT FOUND: {old!r}"
    assert t.count(old)==1, f"AMBIGUOUS ({t.count(old)}x): {old!r}"
    return t.replace(old, new)
def after_line(t, token, payload):
    i=t.find(token); assert i!=-1, f"NOT FOUND {token!r}"; nl=t.find("\n", i); return t[:nl+1]+payload+t[nl+1:]

# 1. INPUT
s = after_line(s, "RecoveryTrailGiveback =",
"input double RecoveryTargetPct  = 0.0;    // [Part1.2] 0=off; >0 scales the recovery target to this %% of the DEEPEST loss rescued (max w/ RecoveryTargetUSD)\n")

# 2. GLOBAL
s = after_line(s, "double g_recoverPeak  = 0;", "double g_recoverDeepest = 0;\n")

# 3. recovering-branch body -> use effTarget (scaled)
s = rep(s,
"""                if (UseRecoveryTrail) {
                        if (bookFloat >= RecoveryTargetUSD) {
                                if (!g_recoverArmed) g_recoverArmed = true;
                                if (bookFloat > g_recoverPeak) g_recoverPeak = bookFloat;
                        }
                        if (g_recoverArmed) {
                                double exitLvl = MathMax(RecoveryTargetUSD, g_recoverPeak - RecoveryTrailGiveback);
                                if (bookFloat <= exitLvl && bookFloat < g_recoverPeak) {
                                        Print("RECOVERY TRAIL exit: book=+", DoubleToString(bookFloat,2), " peak +", DoubleToString(g_recoverPeak,2), " -- closing all");
                                        CloseAllTrades(OP_BUY); CloseAllTrades(OP_SELL);
                                        g_recovering=false; g_recoverWinDir=-1; g_recoverArmed=false; g_recoverPeak=0; peakBasketFloat=0;
                                }
                        }
                        return;
                }
                if (bookFloat >= RecoveryTargetUSD) {
                        Print("RECOVERY COMPLETE: book=+", DoubleToString(bookFloat,2), " -- closing all in profit");
                        CloseAllTrades(OP_BUY); CloseAllTrades(OP_SELL);
                        g_recovering=false; g_recoverWinDir=-1; peakBasketFloat=0;
                }
                return;""",
"""                if (bookFloat < g_recoverDeepest) g_recoverDeepest = bookFloat;          // track deepest loss this rescue
                double effTarget = (RecoveryTargetPct>0) ? MathMax(RecoveryTargetUSD, (RecoveryTargetPct/100.0)*(-g_recoverDeepest)) : RecoveryTargetUSD;
                if (UseRecoveryTrail) {
                        if (bookFloat >= effTarget) {
                                if (!g_recoverArmed) g_recoverArmed = true;
                                if (bookFloat > g_recoverPeak) g_recoverPeak = bookFloat;
                        }
                        if (g_recoverArmed) {
                                double exitLvl = MathMax(effTarget, g_recoverPeak - RecoveryTrailGiveback);
                                if (bookFloat <= exitLvl && bookFloat < g_recoverPeak) {
                                        Print("RECOVERY TRAIL exit: book=+", DoubleToString(bookFloat,2), " peak +", DoubleToString(g_recoverPeak,2), " tgt ", DoubleToString(effTarget,0), " -- closing all");
                                        CloseAllTrades(OP_BUY); CloseAllTrades(OP_SELL);
                                        g_recovering=false; g_recoverWinDir=-1; g_recoverArmed=false; g_recoverPeak=0; g_recoverDeepest=0; peakBasketFloat=0;
                                }
                        }
                        return;
                }
                if (bookFloat >= effTarget) {
                        Print("RECOVERY COMPLETE: book=+", DoubleToString(bookFloat,2), " (tgt ", DoubleToString(effTarget,0), ") -- closing all in profit");
                        CloseAllTrades(OP_BUY); CloseAllTrades(OP_SELL);
                        g_recovering=false; g_recoverWinDir=-1; g_recoverDeepest=0; peakBasketFloat=0;
                }
                return;""")

# 4. reset deepest on arm
s = rep(s, "g_recovering = true; g_recoverArmed=false; g_recoverPeak=0;",
           "g_recovering = true; g_recoverArmed=false; g_recoverPeak=0; g_recoverDeepest=0;")

io.open(PATH, "w", encoding="utf-16").write(s)
print("RECOVERY TARGET-SCALING PATCH APPLIED OK.")
for t in ["RecoveryTargetPct","g_recoverDeepest","effTarget"]:
    print(f"  present: {t in s}   {t}")
