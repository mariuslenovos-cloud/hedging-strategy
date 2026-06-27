#!/usr/bin/env python3
"""
Part 1.1 -- TRAIL THE RECOVERED WINNER (default OFF).
When the recovery hedge has dragged the book back to +RecoveryTargetUSD, instead
of flat-closing the whole book, TRAIL it: track the peak book float and close only
on a RecoveryTrailGiveback retrace from that peak (never giving back below the
target). The recovery is a CONFIRMED extended trend, so riding the winner here is
the one place it should pay -- unlike a fresh entry (mean-reversion).
"""
import io, sys
PATH = r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\98A82F92176B73A2100FCD1F8ABD7255\MQL4\Experts\Adapted\Marius Hedger M5 v1.0 fib C SAFE.mq4"
s = io.open(PATH, "r", encoding="utf-16").read()
if "UseRecoveryTrail" in s:
    print("ALREADY PATCHED -- aborting."); sys.exit(1)

def rep(t, old, new):
    assert old in t, f"NOT FOUND: {old!r}"
    assert t.count(old)==1, f"AMBIGUOUS ({t.count(old)}x): {old!r}"
    return t.replace(old, new)
def after_line(t, token, payload):
    i=t.find(token); assert i!=-1, f"NOT FOUND {token!r}"; nl=t.find("\n", i); return t[:nl+1]+payload+t[nl+1:]

# 1. INPUTS (after RecoveryTargetUSD)
s = after_line(s, "RecoveryTargetUSD  =",
"input bool   UseRecoveryTrail   = false;  // [Part1.1] once book recovers to +RecoveryTargetUSD, TRAIL the winning side (ride the trend) instead of flat-closing\n"
"input double RecoveryTrailGiveback = 20.0;// give-back ($) from the recovery peak that triggers the close (locks >= RecoveryTargetUSD)\n")

# 2. GLOBALS (after g_recoverWinDir)
s = after_line(s, "int  g_recoverWinDir = -1;",
"bool   g_recoverArmed = false;\ndouble g_recoverPeak  = 0;\n")

# 3. exit block: trail-or-flat
s = rep(s,
"""                if (bookFloat >= RecoveryTargetUSD) {
                        Print("RECOVERY COMPLETE: book=+", DoubleToString(bookFloat,2), " -- closing all in profit");
                        CloseAllTrades(OP_BUY); CloseAllTrades(OP_SELL);
                        g_recovering=false; g_recoverWinDir=-1; peakBasketFloat=0;
                }
                return;""",
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
                return;""")

# 4. reset trail state when recovery arms
s = rep(s, "g_recovering = true;", "g_recovering = true; g_recoverArmed=false; g_recoverPeak=0;")

io.open(PATH, "w", encoding="utf-16").write(s)
print("RECOVERY TRAIL PATCH APPLIED OK.")
for t in ["UseRecoveryTrail","RecoveryTrailGiveback","g_recoverPeak","RECOVERY TRAIL exit"]:
    print(f"  present: {t in s}   {t}")
