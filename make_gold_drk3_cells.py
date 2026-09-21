#!/usr/bin/env python3
"""
make_gold_drk3_cells.py -- K3 x CALM-ATR cells from the deployed GOLD DAYRANK source (2026-08-29).

ML program item (1) found ONE interaction that survived the within-cell + halves control:
   day_rank >= 3 AND ATR(D1)/price <= ~2.5%  ->  +0.37R (n104, 73% win)
   day_rank >= 3 AND ATR(D1)/price  > ~2.5%  ->  +0.03R
i.e. the K3 upsize earns in CALM regimes and collapses on high-vol days (the melt-up class).
Hypothesis to kill-test in TRADE mode: gate DayRankSizeMultK3 on ATR% -- mult=1.5 when calm,
1.0 (no upsize) when ATR(D1)/price exceeds the threshold.

Cells (zero-input, injected into `ea/GOLD DAYRANK.mq5` = GOLD LOCKED + the S29 patch):
   GOLD DR15    K3 x1.5, no ATR gate           = CONTROL (the 08-17 up15 champion, re-run on today's tick basis)
   GOLD DR15A25 K3 x1.5, suppressed above 2.5%  = the ML-proposed refinement
   GOLD DR15A30 K3 x1.5, suppressed above 3.0%  = sensitivity (is 2.5 a cliff or a plateau?)
   GOLD DR15A20 K3 x1.5, suppressed above 2.0%  = sensitivity (tighter)
Judge vs control on RF + eqDD + the Aug melt-up/whipsaw episodes; net secondary (sizing-not-gating).
"""
import io, os, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "ea", "GOLD DAYRANK.mq5")
TARGETS = [
    (r"C:\MT5 Pepperstone Runner\MQL5\Experts",
     r"C:\MT5 Pepperstone Runner\MetaEditor64.exe", ["/portable"]),
    (r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\C54C4DDE98E7B1FB905AFE04A9333631\MQL5\Experts",
     r"C:\Program Files\Pepperstone MetaTrader 5\MetaEditor64.exe", []),
]
CELLS = {"GOLD DR15": 0.0, "GOLD DR15A25": 2.5, "GOLD DR15A30": 3.0, "GOLD DR15A20": 2.0}

def build(tag, thr, src):
    out = src.replace('#define EA_BUILD_VERSION "GS-CELL-GOLD-DAYRANK-2026-08-17"',
                      f'#define EA_BUILD_VERSION "GS-CELL-{tag.replace(" ", "-")}-2026-08-29"')
    # bake the K3 multiplier + the new threshold const
    o = "input double DayRankSizeMultK3    = 1.0;"
    assert out.count(o) == 1, "K3 input anchor"
    out = out.replace(o, "const double DayRankSizeMultK3    = 1.5;   // CELL-LOCKED\n"
                         f"const double DayRankK3MaxATRPct   = {thr};   // [ML-1 INJECT] suppress the K3 upsize when ATR(D1)/price*100 > this (0 = off)")
    # research cell must not pollute the shared signal CSV
    for o2 in ("input bool UseSignalLog          = true;", "input bool   UseSignalLog          = true;"):
        if o2 in out:
            out = out.replace(o2, "const bool   UseSignalLog          = false;  // CELL")
    # the gate on the K3 multiply
    o3 = "   if(!rescue && !crashSell && dayRank >= 3 && DayRankSizeMultK3 != 1.0) g_clusterSizeMult *= DayRankSizeMultK3;"
    assert out.count(o3) == 1, "K3 multiply anchor"
    out = out.replace(o3,
        "   {\n"
        "      double k3AtrPct = (DayRankK3MaxATRPct > 0 && Bid_() > 0) ? 100.0 * ReadBuf(hATR_D1,0,1) / Bid_() : 0.0;\n"
        "      bool   k3Calm   = (DayRankK3MaxATRPct <= 0) || (k3AtrPct <= DayRankK3MaxATRPct);\n"
        "      if(!rescue && !crashSell && dayRank >= 3 && DayRankSizeMultK3 != 1.0)\n"
        "      {\n"
        "         if(k3Calm) g_clusterSizeMult *= DayRankSizeMultK3;\n"
        "         else Print(\"K3 UPSIZE SUPPRESSED: ATR% \", DoubleToString(k3AtrPct,2), \" > \", DoubleToString(DayRankK3MaxATRPct,2));\n"
        "      }\n"
        "   }")
    oninit = "int OnInit()\n{\n"
    assert oninit in out
    out = out.replace(oninit, oninit +
                      f'   Print("GOLD DAYRANK K3xATR CELL {tag} -- K3=1.5, K3MaxATRPct={thr}");\n', 1)
    return f"//| GENERATED CELL {tag} from GOLD DAYRANK -- regen via make_gold_drk3_cells.py |\n" + out

def main():
    import sys
    only = set(sys.argv[1:])
    src = io.open(SRC, encoding="utf-8", errors="replace").read()
    for tag, thr in CELLS.items():
        if only and tag not in only: continue
        code = build(tag, thr, src)
        for expdir, metaed, extra in TARGETS:
            path = os.path.join(expdir, f"{tag}.mq5")
            io.open(path, "w", encoding="utf-8").write(code)
            log = path[:-4] + ".clog"
            subprocess.run(f'"{metaed}" {" ".join(extra)} /compile:"{path}" /log:"{log}"', check=False)
            res = "?"
            for enc in ("utf-16", "cp1252"):
                try:
                    L = [l for l in io.open(log, encoding=enc).read().splitlines() if "Result" in l]
                    if L: res = L[-1].strip(); break
                except Exception: continue
            print(f"{tag:14s} {res}")
        io.open(os.path.join(HERE, "ea", f"{tag}.mq5"), "w", encoding="utf-8").write(code)

if __name__ == "__main__":
    main()
