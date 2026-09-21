"""make_stgrid.py (2026-09-15) -- generate `Marius STGrid MT5 v1.0.mq5`: the GridStat
execution engine (grid recovery, $ harvest, entry SL, staged floor, pin+ride) fed by
the MM ShadowLogger's SuperTrend flip instead of Goldminer. A SEPARATE engine per
the user's instruction: derived from the S39 master by text transform, own build
stamp, own magic seed ("STGrid"), own signal/trade/shadow files. Defaults = the
live GOLD HPIN12 geometry + TriggerMode=1 (SuperTrend 4.0/20) + M5 EMA200 alignment,
no Goldminer-specific gates (ADX/angle thresholds 0, fingerprint gate OFF).
Everything stays an INPUT so the tester can sweep. Compiles on XM, DEMO, RUNNER."""
import io, os, sys, subprocess, datetime
import gridstat_make_cells as gm

SRC = os.path.join(gm.EA_DIR, "Marius GridStat MT5 v1.0.mq5")     # ea/ = the S39 master
NAME = "Marius STGrid MT5 v1.0"
BUILD = f"STGRID-{datetime.date.today():%Y-%m-%d}-C"
DEFAULTS = dict(gm.CELLS["GOLD HPIN12"],
    StatsFilterEnabled="false", UseSizingTable="false", UseSignalLog="false",
    StatsCSVFile='"stgrid_setups_gold.csv"',
    ADX_Threshold="0.0", MA_Angle_Threshold="0.0",        # Goldminer-era trend gate off (MM had none)
    UseDailyTrendFilter="false", UseSessionFilter="false",  # alignment EMA replaces both; sweepable
    # build C (2026-09-15): defaults = the runner winner (v4 cd360). The rescue/ride layer is OFF by
    # default here -- it is incompatible with this trigger's cadence (round 1: 31 pins, 0 book exits).
    RescueOnDrawdownPct="0.0", RescueTickArm="false", RescueImmediateLeg="false", RescueBookSingle="false",
    RescueSuspendsStaged="false", RescueLockDir="false", RescueRampByLegs="false")

ST_FUNCS = r'''//+------------------------------------------------------------------+
//| [STGRID] SuperTrend trigger -- faithful port of CMMSuperTrend      |
//+------------------------------------------------------------------+
void STFeed(double h, double l, double c, double atr, bool &flipped)
{
   flipped = false;
   if(atr <= 0.0) return;
   double hl2 = (h + l) * 0.5, bu = hl2 + ST_Sensitivity * atr, bl = hl2 - ST_Sensitivity * atr;
   if(!g_stSeeded)
   { g_stUpper = bu; g_stLower = bl; g_stDir = (c >= hl2) ? 1 : -1; g_stPrevClose = c; g_stSeeded = true; return; }
   double pu = g_stUpper, pl = g_stLower;
   g_stUpper = (bu < pu || g_stPrevClose > pu) ? bu : pu;
   g_stLower = (bl > pl || g_stPrevClose < pl) ? bl : pl;
   int prev = g_stDir;
   if(c > pu) g_stDir = 1; else if(c < pl) g_stDir = -1;
   if(prev != 0 && g_stDir != prev) flipped = true;
   g_stPrevClose = c;
}
void STWarmUp()   // seed the state from history so a fresh attach does not wait for a flip from cold
{
   if(TriggerMode != 1) return;
   int n = MathMin(600, Bars(_Symbol, PERIOD_CURRENT) - 2);
   for(int k = n; k >= 1; k--)
   {
      bool f; double a = ReadBuf(hST_ATR, 0, k);
      if(a <= 0) continue;
      STFeed(iHigh(_Symbol,PERIOD_CURRENT,k), iLow(_Symbol,PERIOD_CURRENT,k), iClose(_Symbol,PERIOD_CURRENT,k), a, f);
   }
   g_stBar = iTime(_Symbol, PERIOD_CURRENT, 1); g_stFlipped = false;
}
void STUpdateClosedBar()   // once per new bar, on the just-closed bar (shift 1), session-independent
{
   if(TriggerMode != 1) return;
   datetime tb = iTime(_Symbol, PERIOD_CURRENT, 1);
   if(tb == g_stBar) return;
   g_stBar = tb; g_stFlipped = false;
   double a = ReadBuf(hST_ATR, 0, 1);
   STFeed(iHigh(_Symbol,PERIOD_CURRENT,1), iLow(_Symbol,PERIOD_CURRENT,1), iClose(_Symbol,PERIOD_CURRENT,1), a, g_stFlipped);
}
int GetSuperTrendSignal()   // BUY/SELL on the flip bar (aligned if the gate is on), else -1
{
   if(!g_stFlipped || g_stDir == 0) return(-1);
   int dir = (g_stDir > 0) ? (int)ORDER_TYPE_BUY : (int)ORDER_TYPE_SELL;
   if(AlignEmaPeriod > 0)
   {
      double e = ReadBuf(hAlign, 0, 1), c = iClose(_Symbol, PERIOD_CURRENT, 1);
      if(e <= 0) return(-1);
      bool aligned = (dir == (int)ORDER_TYPE_BUY) ? (c > e) : (c < e);
      if(!aligned) return(-1);
   }
   return(dir);
}

bool IsDailyTrendBullish()
{'''

ST_INPUTS = '''input int    goldminershift = 1;
//--- [STGRID] trigger source: the MM ShadowLogger SuperTrend flip in place of Goldminer
input int             TriggerMode     = 1;         // 0 = Goldminer (GridStat original), 1 = SuperTrend flip (MM engine)
input double          ST_Sensitivity  = 2.5;       // SuperTrend ATR multiplier (2.5 = vendor = the grid's winner; 4.0 = s40 loses inside the grid)
input int             ST_AtrPeriod    = 10;        // SuperTrend ATR period on the chart TF, MT5 iATR (MM InpAtrPeriod)
input ENUM_TIMEFRAMES AlignEmaTF      = PERIOD_M5; // trend-alignment EMA timeframe
input int             AlignEmaPeriod  = 200;       // 0 = off: fire only if the bar closed on the EMA side (BUY above / SELL below)
input int             StagedCutCooldownMin = 360;  // [STGRID] no NEW basket for this many minutes after a staged-floor cut (0 = off); 4-8h plateau on the runner'''

ST_GLOBALS = '''int      hMA, hADX, hMA_D1, hMA_D1_fast, hATR_cur, hATR_avg, hATR_D1, hATR_D1_60;
//--- [STGRID] SuperTrend state (port of CMMSuperTrend::Update, MMEngine.mqh) + alignment EMA
int      hST_ATR = INVALID_HANDLE, hAlign = INVALID_HANDLE;
double   g_stUpper = 0, g_stLower = 0, g_stPrevClose = 0;
int      g_stDir = 0;            // +1 long / -1 short / 0 unseeded
bool     g_stSeeded = false, g_stFlipped = false;
datetime g_stBar = 0;
datetime g_lastStagedCut = 0;   // [STGRID] time of the last staged-floor cut'''

ST_INIT = '''   hATR_cur = iATR(_Symbol, PERIOD_CURRENT, 20);
   hST_ATR  = iATR(_Symbol, PERIOD_CURRENT, ST_AtrPeriod);                 // [STGRID]
   if(AlignEmaPeriod > 0) hAlign = iMA(_Symbol, AlignEmaTF, AlignEmaPeriod, 0, MODE_EMA, PRICE_CLOSE);
   if(hST_ATR == INVALID_HANDLE || (AlignEmaPeriod > 0 && hAlign == INVALID_HANDLE))
   { Print("STGRID: SuperTrend/alignment handle creation failed"); return(INIT_FAILED); }
   Print("CONFIG | STGRID | TriggerMode=", TriggerMode, " ST_Sensitivity=", DoubleToString(ST_Sensitivity,2),
         " ST_AtrPeriod=", ST_AtrPeriod, " align=", (AlignEmaPeriod>0 ? "EMA"+IntegerToString(AlignEmaPeriod)+"("+EnumToString(AlignEmaTF)+")" : "off"),
         " ADX_Threshold=", DoubleToString(ADX_Threshold,1), " MA_Angle_Threshold=", DoubleToString(MA_Angle_Threshold,1),
         " UseSessionFilter=", UseSessionFilter, " UseDailyTrendFilter=", UseDailyTrendFilter, " StatsFilterEnabled=", StatsFilterEnabled,
         " cutCooldown=", StagedCutCooldownMin, "min rescuePct=", DoubleToString(RescueOnDrawdownPct,1), " tickArm=", RescueTickArm, " stagedFloor=", UseStagedFloor, "/", DoubleToString(StagedFloorPct,1));
   STWarmUp();'''


def build(src):
    s = src
    out = []
    for ln in s.splitlines():
        m = gm.INPUT_RE.match(ln)
        if m and m.group(2) in DEFAULTS:
            typ, name, pad, default, tail = m.groups()
            ln = f"input {typ} {name}{pad}= {DEFAULTS[name]};{tail}  // STGRID default"
        out.append(ln)
    s = "\n".join(out)

    def rep(old, new, cnt=1):
        nonlocal s
        assert s.count(old) == cnt, (old[:70], s.count(old))
        s = s.replace(old, new)

    rep('#define EA_BUILD_VERSION "MT5-2026-09-06-S39-SIGLOG"', f'#define EA_BUILD_VERSION "{BUILD}"')
    rep('input int    goldminershift = 1;', ST_INPUTS)
    rep('int      hMA, hADX, hMA_D1, hMA_D1_fast, hATR_cur, hATR_avg, hATR_D1, hATR_D1_60;', ST_GLOBALS)
    rep('   hATR_cur = iATR(_Symbol, PERIOD_CURRENT, 20);', ST_INIT)
    rep('bool IsDailyTrendBullish()\n{', ST_FUNCS)
    rep('   if(newBar) lastBarTime = iTime(_Symbol, PERIOD_CURRENT, 0);\n',
        '   if(newBar) lastBarTime = iTime(_Symbol, PERIOD_CURRENT, 0);\n'
        '   if(newBar) STUpdateClosedBar();      // [STGRID] advance the trigger on every bar, before any gate\n')
    rep('   int dir = GetGoldminerSignal(bigMove, wpr, periodUsed, barsInBand);\n   if(dir < 0) return;',
        '   int dir = (TriggerMode == 1) ? GetSuperTrendSignal()\n'
        '                                : GetGoldminerSignal(bigMove, wpr, periodUsed, barsInBand);   // [STGRID]\n'
        '   if(dir < 0) return;')
    rep('         g_lastStageBar = iTime(_Symbol, PERIOD_CURRENT, 0);\n         return;   // re-evaluate the lightened basket next tick',
        '         g_lastStageBar = iTime(_Symbol, PERIOD_CURRENT, 0);\n         g_lastStagedCut = TimeCurrent();   // [STGRID]\n         return;   // re-evaluate the lightened basket next tick')
    rep('// no Goldminer signal -> nothing to log\n',
        '// no Goldminer signal -> nothing to log\n'
        '   if(TriggerMode == 1 && StagedCutCooldownMin > 0 && g_lastStagedCut > 0 &&\n'
        '      TimeCurrent() < g_lastStagedCut + (datetime)StagedCutCooldownMin * 60) return;   // [STGRID] post-cut cooldown on NEW baskets\n')
    rep('GenerateMagic("GridStat", _Symbol, (int)Period())', 'GenerateMagic("STGrid", _Symbol, (int)Period())')
    rep('return "gridstat_signals_" + _Symbol + ".csv";', 'return "stgrid_signals_" + _Symbol + ".csv";')
    rep('"gridstat_trades_mt5.csv"', '"stgrid_trades_mt5.csv"', cnt=2)
    rep('Print("MARIUS GRIDSTAT MT5 ", EA_BUILD_VERSION', 'Print("MARIUS STGRID MT5 ", EA_BUILD_VERSION')
    return ("//| Marius STGrid MT5 -- GridStat execution engine fed by the MM SuperTrend flip.   |\n"
            "//| GENERATED by make_stgrid.py from the S39 GridStat master; do not hand-edit.       |\n" + s + "\n")


def compile_(mq5, metaed, portable=False):
    log = mq5[:-4] + "_compile.log"
    arglist = f"'/compile:\"{mq5}\"','/log:\"{log}\"'" + (",'/portable'" if portable else "")
    subprocess.run(["powershell.exe", "-NoProfile", "-Command",
                    f"Start-Process -FilePath '{metaed}' -ArgumentList {arglist} -Wait"], check=False)
    for enc in ("utf-16", "cp1252"):
        try:
            lines = [l for l in io.open(log, encoding=enc).read().splitlines() if "Result" in l]
            if lines:
                return lines[-1].strip()
        except Exception:
            pass
    return "?"


if __name__ == "__main__":
    src = io.open(SRC, encoding="utf-8", errors="replace").read()
    assert 'EA_BUILD_VERSION "MT5-2026-09-06-S39-SIGLOG"' in src, "ea/ master is not S39"
    code = build(src)
    targets = [
        (os.path.join(gm.EXPERTS, NAME + ".mq5"), gm.METAED, False),
        (r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\C54C4DDE98E7B1FB905AFE04A9333631\MQL5\Experts\%s.mq5" % NAME,
         r"C:\MT5 Pepperstone Instance 2\MetaEditor64.exe", False),
        (r"C:\MT5 Pepperstone Runner\MQL5\Experts\%s.mq5" % NAME, r"C:\MT5 Pepperstone Runner\MetaEditor64.exe", True),
    ]
    for path, me, port in targets:
        io.open(path, "w", encoding="utf-8").write(code)
        print(f"{path}\n   -> {compile_(path, me, port)}")
    io.open(os.path.join(gm.EA_DIR, NAME + ".mq5"), "w", encoding="utf-8").write(code)
    print("ea/ synced; build", BUILD)


# ---------------------------------------------------------------------------
# ZERO-INPUT CELLS (2026-09-15, user: "the inputs do not reset -- build the EA with the
# inputs embedded"). Every `input` becomes a `const` so the tester can cache nothing.
# ---------------------------------------------------------------------------
def lock(code, tag, overrides):
    out, seen = [], set()
    for ln in code.splitlines():
        m = gm.INPUT_RE.match(ln)
        if m:
            typ, name, pad, default, tail = m.groups()
            val = overrides.get(name, default.strip()); seen.add(name)
            ln = f"const {typ} {name}{pad}= {val};{tail}  // CELL-LOCKED"
        elif "#define EA_BUILD_VERSION" in ln:
            ln = f'#define EA_BUILD_VERSION "STGRID-CELL-{tag.replace(" ", "-")}-{datetime.date.today():%Y-%m-%d}"'
        out.append(ln)
    missing = set(overrides) - seen
    if missing: raise SystemExit(f"{tag}: unknown inputs {missing}")
    src = "\n".join(out)
    anchor = "int OnInit()\n{\n"
    assert anchor in src
    src = src.replace(anchor, anchor + f'\n   Print("STGRID TEST CELL {tag} -- zero-input; deltas: '
                      + ", ".join(f"{k}={v}" for k, v in overrides.items()) + '");\n', 1)
    return f"//| GENERATED ZERO-INPUT CELL {tag} -- regen via make_stgrid.py cells |\n" + src + "\n"

CELLS = {
    "STGrid CD360": {},                                  # = build C defaults = the runner winner
    "STGrid CD0":   {"StagedCutCooldownMin": "0"},       # control: same engine without the cooldown
}

def make_cells():
    src = io.open(SRC, encoding="utf-8", errors="replace").read()
    code = build(src)
    for tag, ov in CELLS.items():
        cell = lock(code, tag, ov)
        for path, me, port in [
            (os.path.join(gm.EXPERTS, tag + ".mq5"), gm.METAED, False),
            (r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\C54C4DDE98E7B1FB905AFE04A9333631\MQL5\Experts\%s.mq5" % tag,
             r"C:\MT5 Pepperstone Instance 2\MetaEditor64.exe", False),
            (r"C:\MT5 Pepperstone Runner\MQL5\Experts\%s.mq5" % tag, r"C:\MT5 Pepperstone Runner\MetaEditor64.exe", True)]:
            io.open(path, "w", encoding="utf-8").write(cell)
            print(f"{tag:<14} {os.path.dirname(path)[:40]:<40} -> {compile_(path, me, port)}")
        io.open(os.path.join(gm.EA_DIR, tag + ".mq5"), "w", encoding="utf-8").write(cell)

if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "cells":
    make_cells()
