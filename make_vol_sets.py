"""Generate fib C SAFE volatility-regime A/B .set presets (single fixed runs).
All non-vol params held at fib C SAFE defaults so the A/B isolates the vol filter.
Writes to the project dir AND the MT4 Presets folder."""
import os

PRESETS = r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\98A82F92176B73A2100FCD1F8ABD7255\MQL4\Presets"
PROJ = r"C:\Users\mariu\Downloads\hedging_strategy"

# fixed base (fib C SAFE defaults) — vol toggles overridden per-variant below
BASE = [
    ("LotSize", "0.02"), ("UseCompounding", "1"), ("CompoundingBase", "3000.0"),
    ("StopLoss", "0"), ("TakeProfit", "0"), ("LotMultiplier", "2"), ("UseFibonacci", "1"),
    ("ClosePreviousTrade", "1"), ("UseBuySellProfitThreshold", "1"), ("BuySellProfitThreshold", "50"),
    ("BuySellProfitThresholdInCurrency", "0"), ("UseBuyOneSellProfitThreshold", "0"),
    ("BuyOneSellProfitThreshold", "5"), ("CommentText", "MyEA"), ("UseSessionFilter", "1"),
    ("SessionStartHour", "9"), ("SessionEndHour", "23"), ("MaxSameTrades", "5"),
    ("UseCombinedClose", "0"), ("CombinedProfitThreshold", "50"), ("UseIndividualClose", "0"),
    ("UseBasketTrail", "1"), ("MinFloatToActivate", "80"), ("BasketTrailAmount", "15"),
    ("UseOrphanClose", "0"), ("OrphanMinBars", "200"), ("UseBasketStop", "1"),
    ("BasketMaxLossPct", "30.0"), ("UseMaxBasketLots", "0"), ("MaxBasketLotsTotal", "0.30"),
    ("UseDailyTrendFilter", "1"), ("DailyMA_Period", "50"), ("UseD1DirectionReset", "0"),
    ("UseImbalanceLock", "1"), ("ImbalanceThreshold", "2"),
    # vol-regime detector params (constant across the A/B)
    ("VolATRFastPeriod", "5"), ("VolATRSlowPeriod", "60"), ("VolRegimeMult", "3.0"),
    ("VolFloorMaxMult", "2.0"),
    ("ATRPeriod", "14"), ("ATRMultiplier", "2.0"), ("grisk", "7"), ("countbars", "200"),
    ("goldminershift", "1"), ("MA_Period", "20"), ("MA_Angle_Threshold", "20.0"),
    ("ADX_Period", "14"), ("ADX_Threshold", "25.0"), ("UseMaStop", "0"), ("MaStepTrail", "250"),
    ("UseAutoThreshold", "0"), ("AutoTrailDistance", "50"),
]

# variant -> (master, blockAll, blockStack, scaledFloor), description
VARIANTS = {
    "fibC_vol_0baseline": ((0, 1, 0, 0), "REFERENCE: vol filter OFF (= current behavior)"),
    "fibC_vol_a_blockall": ((1, 1, 0, 0), "(a) HOT -> block ALL new entries (sit out the storm)"),
    "fibC_vol_b_nostack":  ((1, 0, 1, 0), "(b) HOT -> block ADDS only (allow 1st entry/dir)"),
    "fibC_vol_c_floor":    ((1, 0, 0, 1), "(c) HOT -> widen floor 30%->60% (ride to recovery)"),
    "fibC_vol_bc_combo":   ((1, 0, 1, 1), "(b)+(c) no-stack + wide floor (best-of-both candidate)"),
}

HEADER = (";  fib C SAFE volatility-regime A/B -- SINGLE FIXED RUN (NOT optimization)\n"
          ";  GOLD M5 | Every tick | Dec2025-Jun2026 | compare Net/PF/maxDD%/Recovery\n"
          ";  Variant: {desc}\n"
          ";  Load via Tester -> Inputs -> Load. Leave Optimization UNTICKED.\n")

for name, ((m, a, b, c), desc) in VARIANTS.items():
    lines = [HEADER.format(desc=desc)]
    vol = [("UseVolRegimeFilter", str(m)), ("VolBlockAllEntries", str(a)),
           ("VolBlockStacking", str(b)), ("VolScaledFloor", str(c))]
    for k, v in BASE + vol:
        lines.append(f"{k}={v}")
    body = "\n".join(lines) + "\n"
    for d in (PROJ, PRESETS):
        with open(os.path.join(d, name + ".set"), "w", encoding="ascii") as f:
            f.write(body)
    print(f"wrote {name}.set  -- {desc}")

print("\nAll 5 presets written to project + MT4 Presets folder.")
