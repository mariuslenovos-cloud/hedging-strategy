//+------------------------------------------------------------------+
//| Marius GridStat MT5 OIL SOLID -- keep-the-wins build (2026-07-29)
//| Base: OIL HEDGETEST. Changes vs OIL LOCKED: compounding cap 2,   
//| flat grid legs (MaxFibMult=1), CrashGuard v2 ON, same-dir taper ON,
//| FreezeHedge armed at -5% book. All new levers are tester inputs. 
//+------------------------------------------------------------------+
//+------------------------------------------------------------------+
//|  Marius GridStat MT5 v1.0 -- STAGE 1: SHADOW LOGGER               |
//|  Triple-barrier signal-edge measurement on MT5 (any instrument)   |
//|                                                                   |
//|  Port of the MT4 GridStat shadow engine, with the Goldminer       |
//|  signal EMBEDDED + IMPROVED:                                       |
//|   - DECOUPLED params: period / upper / lower / vol-multipliers     |
//|     are separate inputs (MT4 RISK locked them together)           |
//|   - INSTRUMENTED: logs big_move flag + wpr value per signal so we  |
//|     can test runner/dive hypotheses via feature-importance         |
//|                                                                   |
//|  Stage 1 = SHADOW ONLY (no trades). Use it to measure whether an  |
//|  instrument (oil, etc.) has edge BEFORE building trade execution. |
//|  Stage 2 (later) = CTrade grid/floor/risk-norm for proven symbols.|
//+------------------------------------------------------------------+
#property copyright "Marius"
#property version   "1.00"

#define EA_BUILD_VERSION "MT5-2026-07-29-OIL-SOLID1-KEEPWINS"
#define MAX_PENDING 5000

#include <Trade/Trade.mqh>
CTrade trade;   // Stage 2 execution

//--- Mode
const bool StatsCollectionMode = false;   // SHADOW: log signals + triple-barrier outcomes (Stage 1 is shadow-only)  // LOCKED (was input)
const string StatsCSVFile        = "gridstat_setups_oil_research.csv";  // per-symbol: e.g. gridstat_setups_oil.csv  // LOCKED (was input)

//--- Triple-barrier
const double BarrierATRMultiplier = 0.8;   // symmetric barrier ATR(D1) mult (used when the asym overrides below = 0)  // LOCKED (was input)
const double BarrierATRUpper      = 0;     // 0 = symmetric; else UPPER (target) barrier ATR mult -- set > lower to let winners run  // LOCKED (was input)
const double BarrierATRLower      = 0;     // 0 = symmetric; else LOWER (stop)  barrier ATR mult -- R is measured in units of this (the risk)  // LOCKED (was input)
const int TimeBarrierBars      = 288;   // time barrier (M5 bars; 288 = 24h)  // LOCKED (was input)

//--- Goldminer signal (DECOUPLED -- 0 = auto-derive from grisk like the MT4 original)
const int grisk        = 4;     // MT5-gold optimum (shadow-swept + trade-validated: +52% net vs 7 at same ~20% equity DD). legacy RISK knob; drives auto bands when overrides=0  // LOCKED (was input)
const int GM_Period    = 0;     // 0 = auto (grisk*2+3); else fixed WPR period  // LOCKED (was input)
const double GM_UpperBand = 0;     // 0 = auto (grisk+67); overbought threshold  // LOCKED (was input)
const double GM_LowerBand = 0;     // 0 = auto (33-grisk); oversold threshold  // LOCKED (was input)
const double GM_GapMult   = 2.0;   // gap detector: jump >= this * avgRange -> period 3  // LOCKED (was input)
const int GM_GapMode   = 0;     // 0 = original |Open-PrevClose| (MT4-equiv, ~dead on continuous CFDs); 1 = |Close-PrevClose| close-to-close jump (activates the runner detector on gold/oil)  // LOCKED (was input)
const double GM_FastMult  = 4.6;   // fast-move detector: |Close[i+3]-Close[i]| >= this * avgRange -> period 4  // LOCKED (was input)
const int goldminershift = 1;   // evaluate signal on this shift (1 = last closed bar)  // LOCKED (was input)
//--- SIGNAL-STRENGTH gate (2026-07-23 study): the WEAKEST Goldminer signals (barely past the band)
//    are the losers across gold/oil/silver buys (gold shallow buys 38%/-0.15R; silver monotonic 52->71%;
//    oil deep 64%/+0.15R vs shallow 52%/+0.02R). This gates a NEW-basket signal on its PENETRATION depth
//    past the band = direction-normalized strength (BUY: wpr-upper; SELL: lower-wpr). Rescue bypasses.
//    Default OFF (base unchanged). Validate every-tick per symbol; shadow win-rate != grid profit -> tester decides.
const bool UseSignalStrengthGate = false; // ON = skip signals with penetration < SignalStrengthMin  // LOCKED (was input)
const double SignalStrengthMin      = 0;    // min penetration past the band (wpr units); 0 = no cut  // LOCKED (was input)

//--- Feature-importance instrumentation (UNIVERSAL -- improves gold/silver selection too, not just oil)
//    Logs the features the coarse DIR|SESSION|ATR fingerprint throws away, so feature-importance
//    can find sharper, higher-P&L setup cuts per symbol (run on gold/silver/oil shadow alike).
const int RunupBars = 12;        // dip-vs-continuation: directional price move over last N bars before entry (/ATR)  // LOCKED (was input)

//--- Entry filters (so shadow measures only signals that WOULD be tradeable)
const double MA_Angle_Threshold = 20.0;  // LOCKED (was input)
const int MA_Period          = 20;  // LOCKED (was input)
const int ADX_Period         = 14;  // LOCKED (was input)
const double ADX_Threshold      = 25.0;  // LOCKED (was input)
const bool UseDailyTrendFilter = true;  // LOCKED (was input)
const int DailyMA_Period      = 50;  // LOCKED (was input)
//--- FASTER DOWNTREND GATE (2026-07-29): the slow EMA(50) trend filter LAGS a fast crash by ~3 days
//    (it stayed "bullish" as oil fell 113->82, so the grid kept BUYING into the downtrend = the floor hits).
//    This adds a faster gate: block a BUY when price is below a SHORT D1 EMA (and a SELL when above) ->
//    stops feeding a sustained downtrend days sooner = far fewer floor hits. Rescue bypasses. Default OFF.
const bool UseFastTrendGate   = false;  // LOCKED (was input)
const int FastTrendPeriod    = 15;      // D1 EMA period for the fast gate (shorter = catches a downtrend sooner)  // LOCKED (was input)
//--- CRASH GUARD (2026-07-29): the DIRECT "don't buy a falling knife" gate. Blocks a BUY when price is
//    CrashGuardPct% below its recent CrashGuardBars-day HIGH (and a SELL when the same % above the low).
//    Data-checked: this WOULD have blocked the 07-27 reopen buys (oil 84 vs a 10-day high of 93 = 10% down)
//    that the lagging MA filters let through, WITHOUT whipsawing on normal 3-5% uptrend pullbacks. Rescue bypasses. Default OFF.
input bool UseCrashGuard      = true;   // SOLID: ON -- v2 sticky state, data-checked vs the 07-27 reopen buys
input double CrashGuardPct      = 8.0;     // block BUYs when price is this% below the recent high (SELLs: above the low)
input int CrashGuardBars     = 10;      // D1 bars for the recent high/low window
//    v2 STATE-MACHINE (2026-07-29): the plain distance rule also blocked the RECOVERY buys (price still far
//    below the old high while basing/turning) = the -45% net cost. Fix: CRASH state is STICKY but exits on a
//    CONFIRMED TURN -- price breaks the last CrashGuardResumeBars days' high (first higher-high) -> resume
//    dip-buying immediately. "Don't buy while it's falling; buy again the moment it turns."
input int CrashGuardResumeBars = 3;     // exit CRASH state when price breaks this many days' high (0 = plain distance rule)
const bool UseSessionFilter    = true;  // LOCKED (was input)
const int SessionStartHour    = 9;  // LOCKED (was input)
const int SessionEndHour      = 23;  // LOCKED (was input)

//=== STAGE 2 -- TRADE EXECUTION (only when StatsCollectionMode = false) ===
//--- Entry win-rate gate (mirrors locked GOLD: reads StatsCSVFile = the shadow DB)
const bool StatsFilterEnabled    = true;  // LOCKED (was input)
const double MinWinRate            = 0.55;  // LOCKED (was input)
const int MinSamples            = 12;  // LOCKED (was input)
//--- SIGNAL DIAGNOSTIC LOG (default OFF). Logs EVERY Goldminer fire + each gate's value/pass-fail +
//    the final TRADE/SKIP decision -> gridstat_signals_<symbol>.csv (Common\Files, per-symbol = no clobber).
//    Zero effect on trade behaviour; turn ON to see exactly why a signal was/wasn't taken (e.g. MT4 vs MT5 divergence).
input bool UseSignalLog          = false;
//--- Overextension regime filter (Ch.17 structural-break; session 19o). Skips entries when price is
//    stretched far from the D1 mean = the overextension regime that breeds deep-DD/blow-up baskets.
//    Python MAE study: gold corr(dist,MAE)=-0.61, silver -0.38 (both SEPARATE); oil -0.20 (NO separation
//    -> leave OFF for oil). DEFAULT OFF = locked configs byte-identical. Trade-mode only (shadow DB untouched).
//    Validate every-tick: does it lower equity DD without killing net? Per-symbol threshold (gold ~4.5, silver ~8).
const bool UseOverextensionFilter = false;  // LOCKED (was input)
const double OverextATRMult         = 4.5;   // skip if |close - D1EMA(DailyMA_Period)| / ATR(D1,60) >= this. 0 = off.  // LOCKED (was input)
//--- Per-setup bet-sizing (AFML): size ∝ edge. DEFAULT OFF = flat lots (unchanged). When ON, reads
//    SizingCSVFile (from gridstat_rigor.py): mult>0 sizes the bet (×base lot), mult==0 / unknown = SKIP.
//    Concentrates capital on high-edge setups (oil: 2× the star BUY|HR_OVL|EXP), zeros negatives.
const bool UseSizingTable        = true;  // LOCKED (was input)
const string SizingCSVFile         = "gridstat_sizing_oil_research.csv";  // LOCKED (was input)
const double MaxSizeMult           = 2.0;  // LOCKED (was input)
//--- Lot sizing
const double LotSize               = 0.02;  // LOCKED (was input)
const bool UseCompounding        = true;  // LOCKED (was input)
const double CompoundingBase       = 3000.0;  // LOCKED (was input)
//--- COMPOUNDING CAP (2026-07-14, S26): the fib C Session-20 lesson transplanted.
//    C1/C2 capital cells: uncapped compounding re-inflates risk faster than capital
//    protects ($5k start -> eqDD 36.9%, $10k -> every event at 3x lots, gross give-back
//    $8k of $13k). fib C's frontier: capping the COMPOUNDING multiplier (not recovery
//    levers) curbs the grown-account give-back -- MaxCompoundScale=3 dominated.
//    0 = uncapped (original behaviour, locked configs unchanged).
input int MaxCompoundScale      = 2;        // SOLID: capped (gold S26 fib C lesson) -- uncapped compounding re-inflates risk after growth = the give-back
//--- Grid-ladder shaping (Session 23, ported from MT4 build S): cap the fib multiplier of grid legs.
//    The fib ladder 1,1,2,3,5 is a martingale putting the BIGGEST lots at the WORST prices -- the deep
//    legs carried 40%+ of every observed floor loss (MT4 A/B: MaxFibMult=1 -> zero basket stops, net +86%,
//    PF 1.64->4.66, DD 21.6->11.7%). 0 = original fib (locked configs byte-identical); 1 = FLAT legs
//    (all = base lot; float at the adverse extreme shrinks ~60%; escapes need a slightly deeper retrace);
//    2 = capped ladder 1,1,2,2,2. Validate every-tick per symbol before re-locking.
input int MaxFibMult            = 1;  // SOLID: flat legs (MT4 A/B build S: zero basket stops, PF 4.66, DD halved)
const bool UseRiskNormalizedLots = true;   // OFF for gold; ON for volatile symbols (silver/oil)  // LOCKED (was input)
const double RiskPctPerTrade       = 2.5;  // LOCKED (was input)
const double MaxRiskPctSkip        = 8.0;  // LOCKED (was input)
//--- Hedged grid
const bool UseATRSpacing         = true;  // LOCKED (was input)
const double ATRSpacingMultiplier  = 0.5;  // LOCKED (was input)
const int GridSpacingMinPoints  = 300;  // LOCKED (was input)
const int GridSpacingMaxPoints  = 2000;  // LOCKED (was input)
const int MaxGridLevels         = 6;  // LOCKED (was input)
const int MaxConcurrentBaskets  = 3;    // 1 = one cluster at a time (gold/silver: UNCHANGED path). >1 = allow N independent baskets so a stuck basket can't starve 200+ signals (trending indices/oil). No time/hard stops.  // LOCKED (was input)
const bool UseHedge              = true;  // LOCKED (was input)
const int HedgeBreakEvenPoints  = 15000;  // LOCKED (was input)
const double HedgeRatio            = 1.0;  // LOCKED (was input)
const double ProfitTargetUSD       = 100.0;   // basket recovery escape + single-position $ cap  // LOCKED (was input)
const int MaxDaysOpen           = 30;  // LOCKED (was input)
//--- Single-position trailing exit (OFF for gold; only used when nLevels<2)
const bool UseTrailingExit       = false;  // LOCKED (was input)
const double TrailActivateR        = 1.0;  // LOCKED (was input)
const double TrailDistanceR        = 0.6;  // LOCKED (was input)
//--- Lock-and-trail exit (DEFAULT OFF = locked configs unchanged). When ON, a basket that
//    reaches ProfitTargetUSD does NOT close immediately: it LOCKS the target as a guaranteed
//    floor and TRAILS the excess (closes when float retraces LockTrailGiveback $ from peak,
//    but never banks below the locked target). Captures trend continuation past the fixed $
//    target (the chart problem) without the session-16 trailing failure modes (can't reverse
//    into a loss; pair with MaxConcurrentBaskets>1 so holding a runner doesn't starve entries).
const bool UseLockTrailExit      = false;  // LOCKED (was input)
const double LockTrailGivebackPct  = 15.0;   // % retrace from PEAK that liquidates (once +ProfitTargetUSD armed the ride); break-even is locked so a triggered winner can't become a loss  // LOCKED (was input)
//--- Per-entry hard SL toggle. true = SL at the lower barrier (gold-inherited triple-barrier, current).
//    false = NO per-entry stop; rely on grid recovery + the catastrophe basket floor (matches the
//    no-hard-stop hedging philosophy). On pullback-heavy BUY-tilted symbols (oil) the −1R entry stop
//    fires right before the grid would recover; removing it lets those losers recover. TEST per symbol.
const bool UseEntrySL            = false;  // LOCKED (was input)
//--- Basket catastrophic floor (the grid has no inherent stop)
const bool UseBasketStop         = true;  // LOCKED (was input)
const double BasketMaxLossPct      = 10.0;  // LOCKED (was input)
//--- STAGED FLOOR (Session 24; user-designed LIVE 2026-07-09, ported from MT4 build T):
//    when a basket floats <= -StagedFloorPct% of balance, close its single WORST leg --
//    lightens the basket (avg entry improves, escape pulls closer, floor pushes away)
//    for the price of one realized leg. Live episode: -$28 vs a near-certain -$388.
//    MT4 156-trade-panel sweep: plateau 12-14, RF 3.74 -> 4.99 at 12. Must be
//    < BasketMaxLossPct or the catastrophic floor fires first. Default OFF = base unchanged.
//    Threshold is PER-SYMBOL ([[exit-rules-per-symbol]]): gold 12; silver/oil need own sweeps.
const bool UseStagedFloor        = false;    // cut the worst leg early (default OFF)  // LOCKED (was input)
const double StagedFloorPct        = 8.0;     // ...at basket float <= -this% of balance  // LOCKED (was input)
//--- PORTFOLIO STAGED FLOOR (2026-07-12): the per-basket staged floor is provably INERT on
//    multi-basket streams whose pain is N shallow ONE-leg baskets drowning together (oil A/B:
//    byte-identical, zero fires -- every deep event was the PORTFOLIO floor, no basket near -8%).
//    This variant = the MT4 original's book-level semantics: TOTAL float <= -this% of balance ->
//    close the single WORST leg anywhere in the book. Multi-basket path only (conc=1 streams
//    use the per-basket lever -- identical there by construction). Default OFF.
const bool UseStagedFloorPortfolio = false;  // book-level staged cut (oil/silver, conc>1)  // LOCKED (was input)
const double StagedFloorPortfolioPct = 8.0;    // ...at TOTAL float <= -this% of balance (< BasketMaxLossPct)  // LOCKED (was input)
//--- SAME-DIRECTION BASKET GATE (2026-07-12, S21): oil's six ~-$1,0xx-1,4xx events are N
//    same-direction ONE-leg baskets drowning together (3x correlated exposure to one move),
//    and BOTH staged-floor variants failed there (per-basket inert; book-level cut realized
//    recoverable floats -> net -14%/DD +9pp). This lever refuses to COMPOUND a losing bet
//    instead of cutting one: block a NEW basket in direction D while the existing D-direction
//    legs float <= -SameDirGateLossPct% of balance. Gate-respecting (no forced realizations,
//    winners untouched, recovery adds inside existing baskets unaffected). Default OFF.
const bool UseSameDirBasketGate  = false;    // block new same-direction baskets while that side is deep  // LOCKED (was input)
const double SameDirGateLossPct    = 2.0;      // ...existing same-dir float <= -this% of balance blocks  // LOCKED (was input)
//--- SAME-DIRECTION SIZE TAPER (2026-07-12, S22): the GATE version above is RF-negative on
//    oil (PEP A/B @2%: blocked 22% of 89%-win flow to save 21% DD$ -> RF 3.23->2.98). Per
//    [[rigor-drives-sizing-not-gating]]: don't BLOCK the pile-in entry -- SHRINK it. A new
//    basket opening in direction D while D-side floats NEGATIVE opens at
//    SameDirTaperMult^(existing D-baskets) size: every winner still fires and pays; only the
//    correlated drown-together tail shrinks. Folds into g_clusterSizeMult -> applies to the
//    INITIAL entry only, same semantics as the sizing table (grid legs stay base size --
//    the observed oil tail anatomy is ONE-leg baskets, so the initial entry IS the exposure).
//    Default OFF.
input bool UseSameDirTaper       = true;     // SOLID: ON -- shrink the correlated pile-in (S22: RF-positive vs the gate)
input double SameDirTaperMult      = 0.5;      // lot mult per existing same-dir basket (0.5 -> 2nd=half, 3rd=quarter)
//--- ALLOW OPPOSITE WHEN DEEP (2026-07-12, S23; queued Session 24): the fib C recovery-hedge
//    anatomy, GridStat-shaped. Shadow-DB evidence on oil's six drowning events: Apr-May buy
//    drowns had ZERO sell signals passing (lagging D1-50 stayed bullish through the 115->69
//    collapse = fib C's trades-32/33 root cause); the Jun-09 event had 19 gate-passing SELLs
//    blocked ONLY by maxBaskets (slots full of drowning buys = the gold live evidence, a
//    58%-win sell skipped during the deep basket). This lever UNBLOCKS the natural hedge:
//    while the book floats <= -OppositeWhenDeepPct% of balance, a signal OPPOSITE the losing
//    side may open its basket even against the lagging D1 filter and gets ONE slot beyond
//    MaxConcurrentBaskets. Still requires Goldminer + ADX/angle + session + stats/sizing
//    gates (UNBLOCKS quality trades; never forces rejected ones -- the failed gold ride's
//    defect). The rescue basket is a normal basket: own +$ escape, own floor. Default OFF.
const bool AllowOppositeWhenDeep = true;    // unblock opposite-direction baskets while the book is deep  // LOCKED (was input)
const double OppositeWhenDeepPct   = 2.0;      // ...book float <= -this% of balance arms the unblock  // LOCKED (was input)
//    S24 completes fib C's EXIT choreography (S23 A/B: every drowning cluster shrank + DD$
//    -28%, but net -32% because the rescue basket was left to fend for itself -- it won
//    during the continuation then bled its gains back on the bounce while the losers
//    recovered = hedge-churn without fib C's book-level exit). While a rescue basket is
//    open: (a) the LOSING side stops grid-adding (stop feeding the loser), (b) the WHOLE
//    book (losers + rescue) closes together at +RescueBookTargetUSD (fib C's
//    RecoveryTargetUSD). 0 = disabled (S23 behaviour).
input double RescueBookTargetUSD   = 50.0;     // close the whole book at +this while rescued/frozen (0 = off)
//    S25 adds fib C's THIRD ingredient -- GROW the winning side. S24 A/B showed one rescue
//    basket (~1/3 of the losing exposure) cannot overtake 2-3 drowning baskets, so the book
//    never reaches the exit target before the floors fire. fib C rode EVERY winning-side
//    signal until the book recovered. RescueMaxBaskets grants up to N rescue slots beyond
//    MaxConcurrentBaskets while the book stays deep; each entry still needs its own
//    Goldminer signal + quality gates. 1 = S23/S24 behaviour.
const int RescueMaxBaskets      = 3;        // rescue slots beyond MaxConcurrentBaskets (fib C ramp: 2-3)  // LOCKED (was input)
//--- LOSS-GATED HEDGE (2026-07-28): the FIX for the signal-gated rescue that never fired in a downtrend.
//    RSQ2/AllowOppositeWhenDeep only opens the hedge when an OPPOSITE Goldminer signal fires -- in a
//    sustained downtrend that signal never comes (Goldminer fades dips = BUYs), so oil bled undefended
//    (0 rescues in 2 weeks live, incl. the -$403 weekend). This fires the SAME proven machinery
//    (book-exit at +RescueBookTargetUSD + stop-feeding the loser) on the DRAWDOWN LEVEL directly -- no
//    signal needed. Sized to OVERTAKE (ratio>1 -> net opposite) so a continued adverse move rides the
//    whole book to +target = "hedge into profit". Reversal-release = the tuning iteration (floor backstops v1).
input double RescueOnDrawdownPct   = 5.0;      // SOLID: book float <= -this% of balance arms the FREEZE (well before the 10% floor)
const double RescueHedgeRatio      = 1.5;      // hedge lots = losing-side lots x this (>1 = overtake -> ride into profit)  // LOCKED (was input)
//    BIGGER PROFITS (2026-07-28): instead of banking the whole book the instant it reaches
//    +RescueBookTargetUSD, TRAIL it -- ride a sustained down-move and bank near the bottom.
input double RescueBookTrailPct    = 0.0;      // >0: after +target, exit on this% giveback from the book's PEAK profit. 0 = fixed target
//--- FREEZE HEDGE (2026-07-29): the NON-directional hedge -- neutralize the drowning book 1:1 (NOT overtake,
//    so no bet on the trend continuing = no whipsaw crush), HOLD it frozen, and RELEASE the hedge only when
//    price bounces back off the adverse extreme, letting the recovering side run home. Default OFF.
input bool UseFreezeHedge        = true;     // SOLID: ON -- non-directional neutralize (oil DDs are REVERSIONS; ride/overtake both failed)
input double FreezeReleaseATR      = 1.5;      // release the hedge when price bounces this x ATR(D1) back from the adverse extreme
//--- equity-DD reducer (default OFF = locked config unchanged): close a LOSING basket when D1 trend flips AGAINST it
//    (the regime change that turns a recoverable dip into a one-way bleed) -> caps the tail before the -20% floor,
//    lowering intraday equity DD so the proven engine can be sized bigger. Validate every-tick vs the $7,908 baseline.
const bool UseRegimeBasketExit   = false;  // LOCKED (was input)
//--- Break-even SL + grid guards
const bool UseBreakEvenSL        = true;  // LOCKED (was input)
const double BreakEvenTriggerR     = 0.7;  // LOCKED (was input)
const double MaxBasketLotsTotal     = 0.30;  // LOCKED (was input)
const bool SkipGridAfterSL       = true;  // LOCKED (was input)
const int SkipGridAfterSLHours  = 4;  // LOCKED (was input)
//--- Misc
const string CommentText           = "GridSolid";  // distinct from the LOCKED oil EA
const int MagicSeed             = 0;       // 0 = auto-hash from symbol+period (matches MT4 scheme)  // LOCKED (was input)

//--- Globals
double   point;
datetime lastBarTime = 0;
int      hMA, hADX, hMA_D1, hMA_D1_fast, hATR_cur, hATR_avg, hATR_D1, hATR_D1_60;

// Pending signal tracking (triple-barrier)
string   pSetup[MAX_PENDING];
int      pDir[MAX_PENDING];
datetime pEntryTime[MAX_PENDING];
double   pEntryPrice[MAX_PENDING];
double   pUpperBarrier[MAX_PENDING];
double   pLowerBarrier[MAX_PENDING];
datetime pTimeBarrier[MAX_PENDING];
double   pAtrAtEntry[MAX_PENDING];
double   pPeakR[MAX_PENDING];
bool     pBigMove[MAX_PENDING];    // did Goldminer's big-move detector fire at entry?
double   pWpr[MAX_PENDING];        // the %R-derived value at entry (extremity)
double   pAdx[MAX_PENDING];        // ADX magnitude at entry (trend strength)
double   pMaAngle[MAX_PENDING];    // MA-angle steepness, directional (+ = MA sloping with the trade)
double   pRunup[MAX_PENDING];      // dip-vs-continuation: directional move into entry /ATR (+cont, -dip)
int      pPeriodUsed[MAX_PENDING]; // adaptive WPR period actually used (3/4 = accelerated, else base)
int      pBarsInBand[MAX_PENDING]; // how many bars the swing took (opposite-extreme breakout -> now)
int      pCount = 0;

double   g_shadowTotalR = 0.0;

// Stage 2 (trade) globals
long     MagicNumber = 0;
string   g_clusterSetup = "";
double   g_clusterSizeMult = 1.0;   // per-setup size multiplier for the active basket (sizing table)
double   g_peakBasketFloat = 0.0;
bool     g_lockArmed = false;   // lock-trail: basket has reached +ProfitTargetUSD and is now riding (Conc<=1 only)
datetime g_lastStageBar = 0;    // staged floor: at most one worst-leg cut per bar (across all baskets)
int      g_rescueDir = -1;      // AllowOppositeWhenDeep: direction of the open rescue basket(s), -1 = none
double   g_rescuePeak = 0.0;    // rescue trailing book-exit: peak book float while riding a rescue
double   g_freezeExtreme = 0.0; // freeze hedge: the adverse price extreme while frozen (release = bounce off it)
int      g_freezeDir = -1;      // freeze hedge: direction of the FROZEN (losing) side, -1 = not frozen
double   g_freezeAnchor = 0.0;  // freeze hedge anti-churn: after a release, re-freeze only at a NEW adverse extreme
bool     g_crashDown = false;   // crash-guard v2 state: sticky "falling knife" (blocks BUYs) until a confirmed turn up
bool     g_crashUp   = false;   // crash-guard v2 state: sticky "vertical spike" (blocks SELLs) until a confirmed turn down
double   g_crashDownAnchor = 0; // after a turn-exit: re-enter DOWN state only on a NEW breakdown below this (the basing low)
double   g_crashUpAnchor   = 0; // after a turn-exit: re-enter UP state only on a NEW breakout above this (the basing high)
                                // (research lever: not restart-safe; harden with a comment tag if promoted)

//+------------------------------------------------------------------+
int OnInit()
{

   // ---- LOCKED-EA GUARD (generated by make_locked_eas.py; do NOT edit this file by hand)
   if(_Symbol != "OILCash" && _Symbol != "SpotCrude")
   {
      Print("OIL SOLID EA attached to WRONG symbol: ", _Symbol, " (accepts: OILCash/SpotCrude). ABORTING.");
      return(INIT_FAILED);
   }
   Print("OIL SOLID EA -- keep-the-wins config; give-back levers exposed as tester inputs");
   point = (_Digits == 3 || _Digits == 5) ? _Point * 10 : _Point;
   hMA      = iMA(_Symbol, PERIOD_CURRENT, MA_Period, 0, MODE_EMA, PRICE_CLOSE);
   hADX     = iADX(_Symbol, PERIOD_CURRENT, ADX_Period);
   hMA_D1   = iMA(_Symbol, PERIOD_D1, DailyMA_Period, 0, MODE_EMA, PRICE_CLOSE);
   hMA_D1_fast = iMA(_Symbol, PERIOD_D1, FastTrendPeriod, 0, MODE_EMA, PRICE_CLOSE);
   hATR_cur = iATR(_Symbol, PERIOD_CURRENT, 20);
   hATR_avg = iATR(_Symbol, PERIOD_CURRENT, 100);
   hATR_D1  = iATR(_Symbol, PERIOD_D1, 14);
   hATR_D1_60 = iATR(_Symbol, PERIOD_D1, 60);   // overextension-filter normalizer (Python study used ATR(D1,60))
   if(hMA==INVALID_HANDLE || hADX==INVALID_HANDLE || hMA_D1==INVALID_HANDLE ||
      hATR_cur==INVALID_HANDLE || hATR_avg==INVALID_HANDLE || hATR_D1==INVALID_HANDLE || hATR_D1_60==INVALID_HANDLE)
   {
      Print("Handle creation failed"); return(INIT_FAILED);
   }
   Print("============================================================");
   Print("MARIUS GRIDSTAT MT5 ", EA_BUILD_VERSION, " | ", _Symbol,
         " | Mode: ", (StatsCollectionMode ? "SHADOW (no trades)" : "TRADE (not in Stage 1)"));
   Print("============================================================");
   if(StatsCollectionMode && !MQLInfoInteger(MQL_OPTIMIZATION))   // skip CSV during optimization (grisk sweep uses OnTester only)
   {
      int fh = FileOpen(StatsCSVFile, FILE_WRITE|FILE_CSV|FILE_COMMON|FILE_ANSI, ',');
      if(fh != INVALID_HANDLE)
      {
         FileWrite(fh, "setup_key","entry_time","entry_price","direction",
                   "upper_barrier","lower_barrier","time_barrier","atr_at_entry",
                   "barrier_hit","r_multiple","outcome_time","mfe_r","big_move","wpr",
                   "adx","ma_angle","runup","period_used","bars_in_band");
         FileClose(fh);
      }
   }
   if(!StatsCollectionMode)
   {
      MagicNumber = (MagicSeed != 0) ? MagicSeed : GenerateMagic("GridStatSolid", _Symbol, (int)Period());
      trade.SetExpertMagicNumber(MagicNumber);
      trade.SetDeviationInPoints(10);
      trade.SetTypeFillingBySymbol(_Symbol);
      Print("TRADE mode | Magic=", MagicNumber);
      Print("CONFIG | StatsFilterEnabled=", StatsFilterEnabled,
            " UseSizingTable=", UseSizingTable, " SizingCSVFile=", SizingCSVFile,
            " MaxConcurrentBaskets=", MaxConcurrentBaskets,
            " UseEntrySL=", UseEntrySL, " UseRiskNormalizedLots=", UseRiskNormalizedLots);
      Print("CONFIG | UseOverextensionFilter=", UseOverextensionFilter,
            " OverextATRMult=", DoubleToString(OverextATRMult,2));
      Print("CONFIG | MaxFibMult=", MaxFibMult, " (0=fib ladder, 1=flat legs, 2=capped)",
            " MaxCompoundScale=", MaxCompoundScale, " (0=uncapped)");
      Print("CONFIG | UseStagedFloor=", UseStagedFloor,
            " StagedFloorPct=", DoubleToString(StagedFloorPct,1),
            "% (worst-leg cut; floor=", DoubleToString(BasketMaxLossPct,1), "%)");
      Print("CONFIG | UseStagedFloorPortfolio=", UseStagedFloorPortfolio,
            " StagedFloorPortfolioPct=", DoubleToString(StagedFloorPortfolioPct,1),
            "% (book-level worst-leg cut, conc>1 only)");
      Print("CONFIG | UseSameDirBasketGate=", UseSameDirBasketGate,
            " SameDirGateLossPct=", DoubleToString(SameDirGateLossPct,1),
            "% (block new same-dir baskets while that side is deep)");
      Print("CONFIG | UseSameDirTaper=", UseSameDirTaper,
            " SameDirTaperMult=", DoubleToString(SameDirTaperMult,2),
            " (size-taper new same-dir baskets while that side is losing)");
      Print("CONFIG | AllowOppositeWhenDeep=", AllowOppositeWhenDeep,
            " OppositeWhenDeepPct=", DoubleToString(OppositeWhenDeepPct,1),
            "% RescueBookTargetUSD=", DoubleToString(RescueBookTargetUSD,0),
            " RescueMaxBaskets=", RescueMaxBaskets,
            " (unblock+GROW the natural hedge; while rescued: stop feeding loser + book exit at +target)");
      Print("CONFIG | RescueOnDrawdownPct=", DoubleToString(RescueOnDrawdownPct,1),
            "% RescueHedgeRatio=", DoubleToString(RescueHedgeRatio,2),
            " (LOSS-GATED hedge: fires the recovery hedge on the drawdown itself, no signal needed)");
      {
         int _szh = FileOpen(SizingCSVFile, FILE_READ|FILE_CSV|FILE_COMMON|FILE_ANSI, ',');
         Print("CONFIG | sizing file '", SizingCSVFile, "' open: ",
               (_szh!=INVALID_HANDLE ? "OK (found)" : "FAILED / NOT FOUND -> flat 1.0x"));
         if(_szh!=INVALID_HANDLE) FileClose(_szh);
      }
      int fh = FileOpen("gridstat_trades_mt5.csv", FILE_WRITE|FILE_CSV|FILE_COMMON|FILE_ANSI, ',');
      if(fh != INVALID_HANDLE)
      { FileWrite(fh,"time","type","volume","price","profit","reason","comment"); FileClose(fh); }
      // signal diagnostic log: per-symbol, created once (NOT truncated on reload -> accumulates)
      if(UseSignalLog && !FileIsExist(SigFile(), FILE_COMMON))
      {
         int sfh = FileOpen(SigFile(), FILE_WRITE|FILE_CSV|FILE_COMMON|FILE_ANSI, ',');
         if(sfh != INVALID_HANDLE)
         { FileWrite(sfh,"time","dir","setup_key","wpr","adx","ma_angle","d1_bull","winrate","n","decision"); FileClose(sfh); }
      }
      Print("CONFIG | UseSignalLog=", UseSignalLog, (UseSignalLog ? " -> "+SigFile() : ""));
   }
   return(INIT_SUCCEEDED);
}
string SigFile() { return "gridstat_signals_" + _Symbol + ".csv"; }
void LogSignal(int dir, string key, double wpr, double adx, double ang, bool bull, double wr, int ns, string decision)
{
   if(!UseSignalLog) return;
   int h = FileOpen(SigFile(), FILE_READ|FILE_WRITE|FILE_CSV|FILE_COMMON|FILE_ANSI, ',');
   if(h == INVALID_HANDLE) return;
   FileSeek(h, 0, SEEK_END);
   FileWrite(h, TimeToString(TimeCurrent(), TIME_DATE|TIME_MINUTES),
             (dir==ORDER_TYPE_BUY ? "BUY" : "SELL"), key,
             DoubleToString(wpr,1), DoubleToString(adx,1), DoubleToString(ang,1),
             (bull ? "1" : "0"), DoubleToString(wr,2), IntegerToString(ns), decision);
   FileClose(h);
}

int GenerateMagic(string eaName, string sym, int tf)
{
   int hash = 0;
   string s = eaName + sym + IntegerToString(tf);
   for(int i=0; i<StringLen(s); i++) hash += StringGetCharacter(s,i) * (i+1);
   return hash % 100000 + 50000;
}

double OnTester() { return(StatsCollectionMode ? g_shadowTotalR : 0); }

// Diagnostic: log every closing deal with its close reason + net profit.
string DealReasonStr(long r)
{
   switch((int)r)
   {
      case DEAL_REASON_CLIENT:   return "CLIENT";
      case DEAL_REASON_EXPERT:   return "EXPERT";   // EA close (basket recovery / basket-stop / profit target)
      case DEAL_REASON_SL:       return "SL";
      case DEAL_REASON_TP:       return "TP";
      case DEAL_REASON_SO:       return "SO";       // margin stop-out
      default:                   return "OTHER";
   }
}
void OnTradeTransaction(const MqlTradeTransaction &trans, const MqlTradeRequest &req, const MqlTradeResult &res)
{
   if(StatsCollectionMode) return;
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD) return;
   ulong deal = trans.deal;
   if(!HistoryDealSelect(deal)) return;
   if(HistoryDealGetInteger(deal, DEAL_MAGIC) != MagicNumber) return;
   if(HistoryDealGetInteger(deal, DEAL_ENTRY) != DEAL_ENTRY_OUT) return;
   double profit = HistoryDealGetDouble(deal, DEAL_PROFIT)
                 + HistoryDealGetDouble(deal, DEAL_SWAP)
                 + HistoryDealGetDouble(deal, DEAL_COMMISSION);
   long dt = (HistoryDealGetInteger(deal, DEAL_TYPE) == DEAL_TYPE_BUY) ? 1 : 0; // closing deal type
   int fh = FileOpen("gridstat_trades_mt5.csv", FILE_READ|FILE_WRITE|FILE_CSV|FILE_COMMON|FILE_ANSI, ',');
   if(fh == INVALID_HANDLE) return;
   FileSeek(fh, 0, SEEK_END);
   FileWrite(fh,
      TimeToString((datetime)HistoryDealGetInteger(deal, DEAL_TIME), TIME_DATE|TIME_MINUTES),
      (dt==1 ? "close_buy" : "close_sell"),
      DoubleToString(HistoryDealGetDouble(deal, DEAL_VOLUME), 2),
      DoubleToString(HistoryDealGetDouble(deal, DEAL_PRICE), _Digits),
      DoubleToString(profit, 2),
      DealReasonStr(HistoryDealGetInteger(deal, DEAL_REASON)),
      HistoryDealGetString(deal, DEAL_COMMENT));
   FileClose(fh);
}

//+------------------------------------------------------------------+
double ReadBuf(int handle, int buf, int shift)
{
   double b[];
   if(CopyBuffer(handle, buf, shift, 1, b) <= 0) return(0);
   return(b[0]);
}

int BarHour(datetime t)
{
   MqlDateTime dt; TimeToStruct(t, dt); return(dt.hour);
}

//+------------------------------------------------------------------+
//| Goldminer signal (embedded, decoupled, instrumented)             |
//| Returns ORDER_TYPE_BUY / ORDER_TYPE_SELL / -1; sets bigMove, wpr  |
//+------------------------------------------------------------------+
double WprValue(int period, int shift)
{
   int hhs = iHighest(_Symbol, PERIOD_CURRENT, MODE_HIGH, period, shift);
   int lls = iLowest(_Symbol, PERIOD_CURRENT, MODE_LOW, period, shift);
   if(hhs < 0 || lls < 0) return(50);
   double hh = iHigh(_Symbol, PERIOD_CURRENT, hhs);
   double ll = iLow(_Symbol, PERIOD_CURRENT, lls);
   double cl = iClose(_Symbol, PERIOD_CURRENT, shift);
   double wpr = (hh - ll != 0) ? -100.0 * (hh - cl) / (hh - ll) : 0;
   return(100.0 - MathAbs(wpr));   // 0=oversold ... 100=overbought  (= 100-|WPR|)
}

// computes the adaptive value at bar j, sets bigMove + the period actually used for that bar
double GMValueAt(int j, bool &bigMove, int &periodUsed)
{
   double avgRange = 0;
   for(int k=j; k<=j+9; k++) avgRange += MathAbs(iHigh(_Symbol,PERIOD_CURRENT,k) - iLow(_Symbol,PERIOD_CURRENT,k));
   avgRange /= 10.0;
   bool gap=false, fast=false;
   for(int k=j; k<j+9 && !gap; k++)
   {
      double jump = (GM_GapMode==1) ? MathAbs(iClose(_Symbol,PERIOD_CURRENT,k) - iClose(_Symbol,PERIOD_CURRENT,k+1))
                                    : MathAbs(iOpen(_Symbol,PERIOD_CURRENT,k)  - iClose(_Symbol,PERIOD_CURRENT,k+1));
      if(jump >= GM_GapMult*avgRange) gap=true;
   }
   for(int k=j; k<j+6 && !fast; k++)
      if(MathAbs(iClose(_Symbol,PERIOD_CURRENT,k+3) - iClose(_Symbol,PERIOD_CURRENT,k)) >= GM_FastMult*avgRange) fast=true;
   int period = (GM_Period > 0) ? GM_Period : (grisk*2 + 3);
   if(gap)  period = 3;
   if(fast) period = 4;
   bigMove = (gap || fast);
   periodUsed = period;
   return(WprValue(period, j));
}

// signal at goldminershift; returns dir, sets bigMove + wpr + periodUsed + barsInBand (traverse length)
int GetGoldminerSignal(bool &bigMove, double &wpr, int &periodUsed, int &barsInBand)
{
   double upper = (GM_UpperBand > 0) ? GM_UpperBand : (grisk + 67);
   double lower = (GM_LowerBand > 0) ? GM_LowerBand : (33 - grisk);
   int LB = 40;                         // lookback for the band-cross scan
   double val[];
   ArrayResize(val, LB);
   bool bm0=false; int pu0=0;
   for(int k=0; k<LB; k++)
   {
      bool bm=false; int pu=0;
      val[k] = GMValueAt(goldminershift + k, bm, pu);
      if(k==0) { bm0 = bm; pu0 = pu; }
   }
   bigMove = bm0;
   wpr = val[0];
   periodUsed = pu0;
   barsInBand = 0;
   int dir = -1;
   int li = 1;
   if(val[0] > upper)
   {
      while(li<LB-1 && val[li]>=lower && val[li]<=upper) li++;
      if(val[li] < lower) dir = (int)ORDER_TYPE_BUY;     // surged oversold->overbought = BUY
   }
   else if(val[0] < lower)
   {
      while(li<LB-1 && val[li]>=lower && val[li]<=upper) li++;
      if(val[li] > upper) dir = (int)ORDER_TYPE_SELL;    // plunged overbought->oversold = SELL
   }
   barsInBand = li;   // bars from the opposite-extreme breakout to now = how long the swing took
   return(dir);
}

//+------------------------------------------------------------------+
bool IsDailyTrendBullish()
{
   return(ReadBuf(hMA_D1,0,0) > ReadBuf(hMA_D1,0,1));
}
double GetMAAngle()
{
   double m0 = ReadBuf(hMA,0,0), m1 = ReadBuf(hMA,0,5);
   double slope = (m0 - m1) / (5 * point);
   return(MathArctan(slope) * 180.0 / M_PI);
}
bool IsTrendStrong()
{
   double adx = ReadBuf(hADX,0,0);
   return(adx > ADX_Threshold && MathAbs(GetMAAngle()) > MA_Angle_Threshold);
}

// Ch.17 overextension regime: |close - D1EMA(DailyMA_Period)| / ATR(D1,60). High = price stretched
// far from the daily mean = the regime that breeds deep-DD/blow-up baskets on the metals (session 19o).
// Returns true when the current bar is overextended beyond OverextATRMult (trade-mode entry skip).
bool IsOverextended()
{
   if(!UseOverextensionFilter || OverextATRMult <= 0) return(false);
   double d1ma  = ReadBuf(hMA_D1,0,0);            // D1 EMA(DailyMA_Period)
   double atr60 = ReadBuf(hATR_D1_60,0,1);        // ATR(D1,60), last closed D1 bar
   if(atr60 <= 0) return(false);
   double dist = MathAbs(iClose(_Symbol,PERIOD_CURRENT,goldminershift) - d1ma) / atr60;
   return(dist >= OverextATRMult);
}

// dip-vs-continuation feature: directional price move over the last RunupBars before entry, in ATR units.
// + = price moved WITH the signal before entry (continuation); - = price moved against it (dip-buy / pop-sell).
double RunupBefore(int dir)
{
   double atr = ReadBuf(hATR_cur,0,1);
   if(atr <= 0) return(0);
   double now  = iClose(_Symbol, PERIOD_CURRENT, goldminershift);
   double then = iClose(_Symbol, PERIOD_CURRENT, goldminershift + RunupBars);
   double mv = now - then;
   if(dir == (int)ORDER_TYPE_SELL) mv = -mv;
   return(mv / atr);
}

string ClassifySetup(int dir)
{
   string d = (dir == ORDER_TYPE_BUY) ? "BUY" : "SELL";
   int hr = BarHour(TimeCurrent());
   string hrB = (hr<9) ? "HR_ASIA" : (hr<14) ? "HR_LDN" : (hr<18) ? "HR_OVL" : "HR_NY";
   double an = ReadBuf(hATR_cur,0,1), aa = ReadBuf(hATR_avg,0,1);
   string atrB;
   if(aa==0) atrB="ATR_NA";
   else if(an > aa*1.3) atrB="ATR_EXP";
   else if(an < aa*0.7) atrB="ATR_COMP";
   else atrB="ATR_NORM";
   return(d + "|" + hrB + "|" + atrB);
}

//+------------------------------------------------------------------+
void AddPendingSignal(string key, int dir, bool bigMove, double wpr,
                      double adx, double maAngle, double runup, int periodUsed, int barsInBand)
{
   if(pCount >= MAX_PENDING) return;
   double atrD1 = ReadBuf(hATR_D1,0,1);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double px = (dir == ORDER_TYPE_BUY) ? ask : bid;
   double um = (BarrierATRUpper > 0) ? BarrierATRUpper : BarrierATRMultiplier;  // target side
   double lm = (BarrierATRLower > 0) ? BarrierATRLower : BarrierATRMultiplier;  // stop side
   double bdU = atrD1 * um;
   double bdL = atrD1 * lm;
   pSetup[pCount]=key; pDir[pCount]=dir; pEntryTime[pCount]=TimeCurrent();
   pEntryPrice[pCount]=px; pUpperBarrier[pCount]=px+bdU; pLowerBarrier[pCount]=px-bdL;
   pTimeBarrier[pCount]=TimeCurrent() + TimeBarrierBars*PeriodSeconds(PERIOD_CURRENT);
   pAtrAtEntry[pCount]=atrD1; pPeakR[pCount]=0; pBigMove[pCount]=bigMove; pWpr[pCount]=wpr;
   pAdx[pCount]=adx; pMaAngle[pCount]=maAngle; pRunup[pCount]=runup; pPeriodUsed[pCount]=periodUsed;
   pBarsInBand[pCount]=barsInBand;
   pCount++;
}

void RemovePendingAt(int idx)
{
   for(int i=idx; i<pCount-1; i++)
   {
      pSetup[i]=pSetup[i+1]; pDir[i]=pDir[i+1]; pEntryTime[i]=pEntryTime[i+1];
      pEntryPrice[i]=pEntryPrice[i+1]; pUpperBarrier[i]=pUpperBarrier[i+1];
      pLowerBarrier[i]=pLowerBarrier[i+1]; pTimeBarrier[i]=pTimeBarrier[i+1];
      pAtrAtEntry[i]=pAtrAtEntry[i+1]; pPeakR[i]=pPeakR[i+1];
      pBigMove[i]=pBigMove[i+1]; pWpr[i]=pWpr[i+1];
      pAdx[i]=pAdx[i+1]; pMaAngle[i]=pMaAngle[i+1]; pRunup[i]=pRunup[i+1]; pPeriodUsed[i]=pPeriodUsed[i+1];
      pBarsInBand[i]=pBarsInBand[i+1];
   }
   pCount--;
}

void WriteOutcome(int idx, string hit, double r)
{
   g_shadowTotalR += r;
   if(MQLInfoInteger(MQL_OPTIMIZATION)) return;   // optimization: accumulate R only, no per-row CSV (avoids agent file contention)
   int fh = FileOpen(StatsCSVFile, FILE_READ|FILE_WRITE|FILE_CSV|FILE_COMMON|FILE_ANSI, ',');
   if(fh == INVALID_HANDLE) return;
   FileSeek(fh, 0, SEEK_END);
   FileWrite(fh,
      pSetup[idx],
      TimeToString(pEntryTime[idx], TIME_DATE|TIME_MINUTES),
      DoubleToString(pEntryPrice[idx], _Digits),
      (pDir[idx]==ORDER_TYPE_BUY) ? "BUY" : "SELL",
      DoubleToString(pUpperBarrier[idx], _Digits),
      DoubleToString(pLowerBarrier[idx], _Digits),
      TimeToString(pTimeBarrier[idx], TIME_DATE|TIME_MINUTES),
      DoubleToString(pAtrAtEntry[idx], _Digits),
      hit,
      DoubleToString(r, 3),
      TimeToString(TimeCurrent(), TIME_DATE|TIME_MINUTES),
      DoubleToString(pPeakR[idx], 3),
      (pBigMove[idx] ? "1" : "0"),
      DoubleToString(pWpr[idx], 1),
      DoubleToString(pAdx[idx], 1),
      DoubleToString(pMaAngle[idx], 1),
      DoubleToString(pRunup[idx], 3),
      IntegerToString(pPeriodUsed[idx]),
      IntegerToString(pBarsInBand[idx]));
   FileClose(fh);
}

void CheckPendingBarriers()
{
   double barHigh = iHigh(_Symbol, PERIOD_CURRENT, 0);
   double barLow  = iLow(_Symbol, PERIOD_CURRENT, 0);
   for(int i=pCount-1; i>=0; i--)
   {
      bool isBuy = (pDir[i]==ORDER_TYPE_BUY);
      // favDist = distance to the TARGET barrier; advDist = distance to the STOP barrier.
      // R is measured in units of advDist (the risk), so an asymmetric target pays favDist/advDist > 1R.
      double favDist = isBuy ? (pUpperBarrier[i]-pEntryPrice[i]) : (pEntryPrice[i]-pLowerBarrier[i]);
      double advDist = isBuy ? (pEntryPrice[i]-pLowerBarrier[i]) : (pUpperBarrier[i]-pEntryPrice[i]);
      if(favDist <= 0 || advDist <= 0) { RemovePendingAt(i); continue; }
      double favPeakR = (isBuy ? (barHigh-pEntryPrice[i]) : (pEntryPrice[i]-barLow)) / advDist;
      if(favPeakR > pPeakR[i]) pPeakR[i] = favPeakR;
      bool favHit = (isBuy ? (barHigh>=pUpperBarrier[i]) : (barLow<=pLowerBarrier[i]));
      bool advHit = (isBuy ? (barLow<=pLowerBarrier[i]) : (barHigh>=pUpperBarrier[i]));
      string outcome=""; double r=0;
      if(favHit)      { outcome = isBuy?"UPPER":"LOWER"; r =  favDist/advDist; }
      else if(advHit) { outcome = isBuy?"LOWER":"UPPER"; r = -1.0; }
      if(outcome=="" && TimeCurrent() >= pTimeBarrier[i])
      {
         outcome="TIME";
         double cur = isBuy ? SymbolInfoDouble(_Symbol,SYMBOL_BID) : SymbolInfoDouble(_Symbol,SYMBOL_ASK);
         r = (isBuy ? (cur-pEntryPrice[i]) : (pEntryPrice[i]-cur)) / advDist;
      }
      if(outcome != "") { WriteOutcome(i, outcome, r); RemovePendingAt(i); }
   }
}

//+------------------------------------------------------------------+
void OnTick()
{
   bool newBar = (iTime(_Symbol, PERIOD_CURRENT, 0) != lastBarTime);
   if(newBar) lastBarTime = iTime(_Symbol, PERIOD_CURRENT, 0);

   if(StatsCollectionMode) CheckPendingBarriers();
   else { ManageBreakEvenSL(); ManageGrid(); }
   if(!newBar) return;

   if(UseSessionFilter)
   {
      int hr = BarHour(TimeCurrent());
      if(!(hr >= SessionStartHour && hr < SessionEndHour)) return;
   }

   bool bigMove=false; double wpr=0; int periodUsed=0; int barsInBand=0;
   int dir = GetGoldminerSignal(bigMove, wpr, periodUsed, barsInBand);
   if(dir < 0) return;                       // no Goldminer signal -> nothing to log

   // ---- a Goldminer signal FIRED: evaluate every gate in the SAME order, capture WHY (for the log) ----
   double adx     = ReadBuf(hADX,0,0);
   double maAngle = (dir==ORDER_TYPE_BUY) ? GetMAAngle() : -GetMAAngle();  // + = MA slopes with the trade
   double runup   = RunupBefore(dir);
   bool   bull    = IsDailyTrendBullish();
   string key     = ClassifySetup(dir);
   string skip    = "";                       // "" = passes so far

   // rescue = the book is deep and THIS direction is not the losing side -> the natural
   // hedge the lagging D1 / full slots would otherwise refuse (fib C anatomy, S23)
   // RECOVERY HEDGE (fib C mechanism, user 2026-07-29): while the book is in DD, ride the NEW TREND
   // (= opposite the losing side) on EVERY Goldminer signal -- FORCE the trend direction and let the
   // hedge grow a leg per signal (capped by effMaxB below) until the book recovers to +target.
   bool rescue = false;
   if(UseFreezeHedge && g_freezeDir >= 0) return;   // FROZEN: no new entries on either side (freeze holds the book)
   bool bookDeep = (!UseFreezeHedge && RescueOnDrawdownPct > 0 && PortfolioFloat() <= -RescueOnDrawdownPct/100.0 * Bal_());
   if((g_rescueDir >= 0 || bookDeep) && PortfolioFloat() < RescueBookTargetUSD)
   {
      int loseDir  = (SameDirFloat(ORDER_TYPE_BUY) <= SameDirFloat(ORDER_TYPE_SELL)) ? (int)ORDER_TYPE_BUY : (int)ORDER_TYPE_SELL;
      int hedgeDir = (loseDir == (int)ORDER_TYPE_BUY) ? (int)ORDER_TYPE_SELL : (int)ORDER_TYPE_BUY;
      dir    = hedgeDir;      // ride the trend: force the winning (opposite-of-loser) side, override the signal's own dir
      rescue = true;
   }
   else if(AllowOppositeWhenDeep &&
      PortfolioFloat() <= -OppositeWhenDeepPct/100.0 * Bal_() &&
      SameDirFloat(dir) >= 0)
      rescue = true;

   if(!rescue && UseDailyTrendFilter && ((dir==ORDER_TYPE_BUY && !bull) || (dir==ORDER_TYPE_SELL && bull)))
      skip = "D1trend";
   else if(!rescue && !IsTrendStrong())
      skip = "trendWeak(adx="+DoubleToString(adx,1)+",ang="+DoubleToString(MathAbs(maAngle),1)+")";

   if(skip=="" && !rescue && UseFastTrendGate)     // FASTER downtrend gate: block a BUY below / SELL above the short D1 EMA
   {
      double fastMA = ReadBuf(hMA_D1_fast,0,0);
      double px     = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      if(fastMA > 0 && ((dir==ORDER_TYPE_BUY && px < fastMA) || (dir==ORDER_TYPE_SELL && px > fastMA)))
         skip = "fastTrend";
   }

   if(UseCrashGuard)         // CRASH GUARD v2: sticky crash state, exits on a CONFIRMED TURN (first higher-high)
   {
      double hh[], ll[], rh[], rl[];
      int rb = (CrashGuardResumeBars > 0) ? CrashGuardResumeBars : 1;
      if(CopyHigh(_Symbol, PERIOD_D1, 1, CrashGuardBars, hh)==CrashGuardBars &&
         CopyLow(_Symbol,  PERIOD_D1, 1, CrashGuardBars, ll)==CrashGuardBars &&
         CopyHigh(_Symbol, PERIOD_D1, 1, rb, rh)==rb &&
         CopyLow(_Symbol,  PERIOD_D1, 1, rb, rl)==rb)
      {
         double recHigh = hh[ArrayMaximum(hh)], recLow = ll[ArrayMinimum(ll)];
         double rsHigh  = rh[ArrayMaximum(rh)], rsLow  = rl[ArrayMinimum(rl)];
         double px2     = SymbolInfoDouble(_Symbol, SYMBOL_BID);
         // anchors reset once price is back inside the normal band (episode fully over)
         if(px2 >= recHigh*(1.0-CrashGuardPct/100.0)) g_crashDownAnchor = 0;
         if(px2 <= recLow *(1.0+CrashGuardPct/100.0)) g_crashUpAnchor   = 0;
         // ENTER crash state on the distance trigger (a real fall/spike, not a routine dip);
         // after a turn-exit, ONLY a NEW breakdown below the basing low re-enters (anti-churn anchor)
         if(!g_crashDown && px2 < recHigh*(1.0-CrashGuardPct/100.0) &&
            (g_crashDownAnchor==0 || px2 < g_crashDownAnchor))
            { g_crashDown=true; Print("CRASH-STATE DOWN entered (", DoubleToString(px2,2), " << ", DoubleToString(recHigh,2), "): BUYs off until a turn"); }
         if(!g_crashUp && px2 > recLow*(1.0+CrashGuardPct/100.0) &&
            (g_crashUpAnchor==0 || px2 > g_crashUpAnchor))
            { g_crashUp=true;   Print("CRASH-STATE UP entered (", DoubleToString(px2,2), " >> ", DoubleToString(recLow,2), "): SELLs off until a turn"); }
         // EXIT on a confirmed TURN: first break of the last ResumeBars days' extreme -> resume immediately
         if(CrashGuardResumeBars > 0)
         {
            if(g_crashDown && px2 > rsHigh) { g_crashDown=false; g_crashDownAnchor=rsLow; Print("CRASH-STATE DOWN exited: turn confirmed (", DoubleToString(px2,2), " > ", DoubleToString(rsHigh,2), ") -> BUYs resume; re-block only below ", DoubleToString(rsLow,2)); }
            if(g_crashUp   && px2 < rsLow)  { g_crashUp=false;   g_crashUpAnchor=rsHigh; Print("CRASH-STATE UP exited: turn confirmed -> SELLs resume"); }
         }
         else   // ResumeBars=0 -> v1 plain distance behaviour (state clears when distance normalizes)
         {
            if(g_crashDown && px2 >= recHigh*(1.0-CrashGuardPct/100.0)) g_crashDown=false;
            if(g_crashUp   && px2 <= recLow *(1.0+CrashGuardPct/100.0)) g_crashUp=false;
         }
         if(skip=="" && !rescue &&
            ((dir==ORDER_TYPE_BUY && g_crashDown) || (dir==ORDER_TYPE_SELL && g_crashUp)))
            skip = "crashState";
      }
   }

   double wr=0; int ns=0; bool known = LookupSetupStats(key, wr, ns);   // looked up for the log too

   if(StatsCollectionMode)
   {
      if(skip=="") AddPendingSignal(key, dir, bigMove, wpr, adx, maAngle, runup, periodUsed, barsInBand);
      LogSignal(dir, key, wpr, adx, maAngle, bull, wr, ns, (skip=="" ? "SHADOW_LOGGED" : "SHADOW_SKIP:"+skip));
      return;
   }

   // ===== STAGE 2: TRADE ENTRY (gates in the same order; behaviour unchanged, just records the reason) =====
   if(skip=="" && !rescue && StatsFilterEnabled)
   {
      if(!known)                skip = "setupUnknown";
      else if(ns < MinSamples)  skip = "lowSamples(n="+IntegerToString(ns)+")";
      else if(wr < MinWinRate)  skip = "lowWinRate("+DoubleToString(wr,2)+"<"+DoubleToString(MinWinRate,2)+")";
   }
   if(skip=="" && !rescue && UseSignalStrengthGate)        // cut the weak signals (barely past the band)
   {
      double gmUp = (GM_UpperBand > 0) ? GM_UpperBand : (grisk + 67);
      double gmLo = (GM_LowerBand > 0) ? GM_LowerBand : (33 - grisk);
      double pen  = (dir==ORDER_TYPE_BUY) ? (wpr - gmUp) : (gmLo - wpr);   // penetration past the band
      if(pen < SignalStrengthMin) skip = "weakSignal(pen="+DoubleToString(pen,1)+"<"+DoubleToString(SignalStrengthMin,1)+")";
   }
   if(skip=="" && !rescue && IsOverextended()) skip = "overextended";
   double szMult = LookupSizing(key);                      // 1.0 if table off; 0 = negative/unknown setup
   if(skip=="" && !rescue && UseSizingTable && szMult <= 0) skip = "sizingZero";  // hedge legs bypass (sells are zeroed)
   int maxB = (MaxConcurrentBaskets < 1) ? 1 : MaxConcurrentBaskets;
   int rescueSlots = (RescueMaxBaskets < 1) ? 1 : RescueMaxBaskets;
   int effMaxB = maxB + (rescue ? rescueSlots : 0);   // rescue earns up to N extra slots (fib C ramp)
   if(skip=="" && CountOpenBaskets() >= effMaxB) skip = "maxBaskets("+IntegerToString(effMaxB)+")";
   if(skip=="" && !rescue && UseSameDirBasketGate)
   {
      double sdF = SameDirFloat(dir);
      if(sdF <= -SameDirGateLossPct/100.0 * Bal_())
         skip = "sameDirDeep("+DoubleToString(sdF,0)+")";
   }

   LogSignal(dir, key, wpr, adx, maAngle, bull, wr, ns,
             (skip=="" ? (rescue ? "TRADE(rescue)" : "TRADE") : "SKIP:"+skip));
   if(skip != "") return;                                  // any failed gate -> no trade (same as before)
   if(rescue) Print("OPPOSITE-WHEN-DEEP: opening ", (dir==(int)ORDER_TYPE_BUY?"BUY":"SELL"),
                    " rescue basket (book float ", DoubleToString(PortfolioFloat(),2), ")");

   g_clusterSizeMult = (rescue || szMult <= 0) ? 1.0 : szMult;   // hedge legs open at base size (not table-sized)
   if(UseSameDirTaper)
   {
      int nSD = CountSameDirBaskets(dir);
      if(nSD > 0 && SameDirFloat(dir) < 0)
      {
         for(int q=0; q<nSD; q++) g_clusterSizeMult *= SameDirTaperMult;
         Print("SAMEDIR TAPER: new ", (dir==(int)ORDER_TYPE_BUY?"BUY":"SELL"),
               " basket sized x", DoubleToString(g_clusterSizeMult,2),
               " (", nSD, " same-dir basket(s) losing)");
      }
   }
   int newBid = (maxB > 1) ? NextBasketId() : -1;          // tag baskets only in multi mode (single mode untagged = original path)
   g_clusterSetup = key;
   double lot;
   if(UseRiskNormalizedLots) { lot = RiskNormalizedLot(0); if(lot < 0) return; }
   else                       { lot = CalculateLot(0); }
   lot = NormalizeDouble(lot * g_clusterSizeMult, 2);      // per-setup bet sizing (1.0 when table off)
   double minLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   if(lot < minLot) lot = minLot;
   OpenSimpleSLTP(dir, lot, key, newBid);
   if(rescue) { g_rescueDir = dir; g_rescuePeak = 0.0; }   // arm the book-level rescue choreography (S24)
}

//+------------------------------------------------------------------+
//| STAGE 2 -- TRADE EXECUTION (port of MT4 GridStat GOLD build P)    |
//+------------------------------------------------------------------+
double Ask_()  { return SymbolInfoDouble(_Symbol, SYMBOL_ASK); }
double Bid_()  { return SymbolInfoDouble(_Symbol, SYMBOL_BID); }
double Bal_()  { return AccountInfoDouble(ACCOUNT_BALANCE); }

// number of DISTINCT baskets currently open in ONE direction (hedge legs excluded) --
// drives the same-direction size taper exponent.
int CountSameDirBaskets(int dir)
{
   int ids[50]; int n = 0;
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(tk==0 || !PositionSelectByTicket(tk)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      string cmt = PositionGetString(POSITION_COMMENT);
      if(StringFind(cmt, "_HEDGE") >= 0) continue;
      if((int)PositionGetInteger(POSITION_TYPE) != dir) continue;
      int b = BasketIdOf(cmt);
      bool seen = false;
      for(int k=0; k<n; k++) if(ids[k]==b) { seen=true; break; }
      if(!seen && n < 50) ids[n++] = b;
   }
   return n;
}

// combined float of this EA's basket legs in ONE direction (hedge legs excluded) --
// the same-direction basket gate's measure of "is this side already deep?"
double SameDirFloat(int dir)
{
   double f = 0;
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(tk==0 || !PositionSelectByTicket(tk)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(StringFind(PositionGetString(POSITION_COMMENT), "_HEDGE") >= 0) continue;
      if((int)PositionGetInteger(POSITION_TYPE) != dir) continue;
      f += PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
   }
   return f;
}
// total NON-HEDGE lots open in ONE direction -- sizes the loss-gated hedge to the losing exposure.
double SameDirLots(int dir)
{
   double v = 0;
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(tk==0 || !PositionSelectByTicket(tk)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(StringFind(PositionGetString(POSITION_COMMENT), "_HEDGE") >= 0) continue;
      if((int)PositionGetInteger(POSITION_TYPE) != dir) continue;
      v += PositionGetDouble(POSITION_VOLUME);
   }
   return v;
}
double DollarPerPricePerLot()
{
   double ts = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double tv = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   return (ts > 0) ? tv / ts : 0;
}

// win-rate gate: read StatsCSVFile (shadow DB), count r_multiple>0 for setupKey. Robust to column count.
bool LookupSetupStats(string setupKey, double &winRate, int &samples)
{
   int fh = FileOpen(StatsCSVFile, FILE_READ|FILE_CSV|FILE_COMMON|FILE_ANSI, ',');
   if(fh == INVALID_HANDLE) { winRate=0; samples=0; return false; }
   int ncol=0, rIdx=-1;
   while(!FileIsEnding(fh))                       // header row -> column count + r_multiple index
   {
      string c = FileReadString(fh);
      if(c == "r_multiple") rIdx = ncol;
      ncol++;
      if(FileIsLineEnding(fh)) break;
   }
   if(rIdx < 0 || ncol <= 0) { FileClose(fh); winRate=0; samples=0; return false; }
   int wins=0, total=0;
   while(!FileIsEnding(fh))
   {
      string key=""; double r=0; bool any=false;
      for(int c=0; c<ncol && !FileIsEnding(fh); c++)
      {
         string cell = FileReadString(fh); any=true;
         if(c==0)    key = cell;
         if(c==rIdx) r   = StringToDouble(cell);
      }
      if(!any) break;
      if(key == setupKey) { total++; if(r > 0) wins++; }
   }
   FileClose(fh);
   samples = total;
   if(total == 0) { winRate=0; return false; }
   winRate = (double)wins / (double)total;
   return true;
}

// per-setup size multiplier from SizingCSVFile (cols: setup_key,size_mult,...). 1.0 if table off.
// Returns 0 for negative-expectancy setups AND for unknown setups (=> caller skips the trade).
double LookupSizing(string setupKey)
{
   if(!UseSizingTable) return 1.0;
   int fh = FileOpen(SizingCSVFile, FILE_READ|FILE_CSV|FILE_COMMON|FILE_ANSI, ',');
   if(fh == INVALID_HANDLE) return 1.0;   // no table -> behave as flat (don't block trading)
   int ncol=0, mIdx=-1;
   while(!FileIsEnding(fh))
   {
      string c = FileReadString(fh);
      if(c == "size_mult") mIdx = ncol;
      ncol++;
      if(FileIsLineEnding(fh)) break;
   }
   if(mIdx < 0 || ncol <= 0) { FileClose(fh); return 1.0; }
   double mult = 0.0; bool found=false;
   while(!FileIsEnding(fh))
   {
      string key=""; double m=0; bool any=false;
      for(int c=0; c<ncol && !FileIsEnding(fh); c++)
      {
         string cell = FileReadString(fh); any=true;
         if(c==0)    key = cell;
         if(c==mIdx) m   = StringToDouble(cell);
      }
      if(!any) break;
      if(key == setupKey) { mult = m; found=true; break; }
   }
   FileClose(fh);
   if(!found) return 0.0;                 // unknown setup -> skip (table is the gate)
   if(mult > MaxSizeMult) mult = MaxSizeMult;
   return mult;
}

double LotScale()
{
   if(!UseCompounding || CompoundingBase <= 0) return 1.0;
   double sc = MathMax(1.0, MathFloor(Bal_() / CompoundingBase));
   if(MaxCompoundScale > 0 && sc > MaxCompoundScale) sc = MaxCompoundScale;   // fib C cap (S26)
   return sc;
}
double CalculateLot(int gridLevel)
{
   double base = LotSize * LotScale();
   int fib[] = {1,1,2,3,5,8,13,21};
   int idx = (gridLevel < 0) ? 0 : (gridLevel > 7 ? 7 : gridLevel);
   int mult = fib[idx];
   if(MaxFibMult > 0 && mult > MaxFibMult) mult = MaxFibMult;   // ladder cap (0 = original fib)
   return NormalizeDouble(base * mult, 2);
}
// 1R = RiskPctPerTrade% of balance (stop distance = lower-barrier ATR). -1 = volatility skip.
double RiskNormalizedLot(int gridLevel)
{
   double atrD1 = ReadBuf(hATR_D1,0,1);
   double lm = (BarrierATRLower > 0) ? BarrierATRLower : BarrierATRMultiplier;
   double stopDist = atrD1 * lm;
   double dppl = DollarPerPricePerLot();
   if(stopDist <= 0 || dppl <= 0) return CalculateLot(gridLevel);
   double minLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double riskPerMinLot = stopDist * dppl * minLot;
   if(riskPerMinLot > MaxRiskPctSkip/100.0 * Bal_()) return -1.0;
   double targetRisk = RiskPctPerTrade/100.0 * Bal_();
   double baseLot = targetRisk / (stopDist * dppl);
   int fib[] = {1,1,2,3,5,8,13,21};
   int idx = (gridLevel < 0) ? 0 : (gridLevel > 7 ? 7 : gridLevel);
   int multRN = fib[idx];
   if(MaxFibMult > 0 && multRN > MaxFibMult) multRN = MaxFibMult;   // ladder cap (0 = original fib)
   double lot = NormalizeDouble(baseLot * multRN, 2);
   double maxLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   if(lot < minLot) lot = minLot;
   if(maxLot > 0 && lot > maxLot) lot = maxLot;
   return lot;
}

// count my non-hedge market positions
int BasketLotCount()
{
   int c = 0;
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(tk==0 || !PositionSelectByTicket(tk)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      c++;
   }
   return c;
}

//--- Basket concurrency (only meaningful when MaxConcurrentBaskets>1) -----------
// Basket id is embedded in the comment as "_B<id>" (e.g. GridStat_B3_SLTP).
// When MaxConcurrentBaskets<=1 we write NO tag -> BasketIdOf == -1 for all my
// positions -> they form one untagged pool -> ManageOneBasket(-1) reproduces the
// original single-basket behaviour exactly (gold/silver byte-identical path).
string BasketTag(int bid) { return (bid >= 0) ? ("_B" + IntegerToString(bid)) : ""; }

int BasketIdOf(string cmt)
{
   int p = StringFind(cmt, "_B");
   if(p < 0) return -1;
   p += 2;
   int e = StringFind(cmt, "_", p);
   if(e < 0) e = StringLen(cmt);
   string num = StringSubstr(cmt, p, e - p);
   if(StringLen(num) == 0) return -1;
   return (int)StringToInteger(num);
}

// distinct open basket ids for my symbol+magic
int CollectBaskets(int &ids[])
{
   ArrayResize(ids, 0);
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(tk==0 || !PositionSelectByTicket(tk)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      int bid = BasketIdOf(PositionGetString(POSITION_COMMENT));
      bool found=false;
      for(int k=0;k<ArraySize(ids);k++) if(ids[k]==bid){ found=true; break; }
      if(!found){ int n=ArraySize(ids); ArrayResize(ids,n+1); ids[n]=bid; }
   }
   return ArraySize(ids);
}

int CountOpenBaskets() { int ids[]; return CollectBaskets(ids); }

int NextBasketId()
{
   int ids[]; CollectBaskets(ids);
   int mx=0; for(int k=0;k<ArraySize(ids);k++) if(ids[k]>mx) mx=ids[k];
   return mx + 1;
}

// total float across ALL my positions (portfolio-level, for the multi-basket floor)
double PortfolioFloat()
{
   double f=0;
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(tk==0 || !PositionSelectByTicket(tk)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      f += PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
   }
   return f;
}
void CloseEverything(string reason)
{
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(tk==0 || !PositionSelectByTicket(tk)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      trade.PositionClose(tk);
   }
}
// close only the positions belonging to one basket id
void CloseBasket(int targetBid, string reason)
{
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(tk==0 || !PositionSelectByTicket(tk)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(BasketIdOf(PositionGetString(POSITION_COMMENT)) != targetBid) continue;
      trade.PositionClose(tk);
   }
}

// open entry with SL/TP at the (possibly asymmetric) barrier distances
void OpenSimpleSLTP(int dir, double lot, string setupKey, int bid=-1)
{
   double atrD1 = ReadBuf(hATR_D1,0,1);
   double um = (BarrierATRUpper > 0) ? BarrierATRUpper : BarrierATRMultiplier;  // target side
   double lm = (BarrierATRLower > 0) ? BarrierATRLower : BarrierATRMultiplier;  // stop side
   double upDist = atrD1 * um, dnDist = atrD1 * lm;
   double price = (dir==ORDER_TYPE_BUY) ? Ask_() : Bid_();
   double sl, tp;
   if(dir==ORDER_TYPE_BUY) { sl = price - dnDist; tp = price + upDist; }
   else                    { sl = price + dnDist; tp = price - upDist; }
   if(!UseEntrySL) sl = 0;   // no per-entry hard stop -> grid recovery + basket floor handle downside
   string cmt = CommentText + BasketTag(bid) + "_SLTP";
   bool ok = (dir==ORDER_TYPE_BUY) ? trade.Buy(lot,_Symbol,price,sl,tp,cmt)
                                   : trade.Sell(lot,_Symbol,price,sl,tp,cmt);
   if(ok) g_clusterSetup = setupKey;
   else   Print("OpenSimpleSLTP failed err=", trade.ResultRetcode());
}

bool OpenGridLevel(int dir, double lot, int gridLvl, int bid=-1)
{
   double price = (dir==ORDER_TYPE_BUY) ? Ask_() : Bid_();
   string cmt = CommentText + BasketTag(bid) + "_L" + IntegerToString(gridLvl);
   bool ok = (dir==ORDER_TYPE_BUY) ? trade.Buy(lot,_Symbol,price,0,0,cmt)
                                   : trade.Sell(lot,_Symbol,price,0,0,cmt);
   return ok;
}
bool OpenHedge(int hedgeDir, double lot, int bid=-1)
{
   double price = (hedgeDir==ORDER_TYPE_BUY) ? Ask_() : Bid_();
   string cmt = CommentText + BasketTag(bid) + "_HEDGE";
   return (hedgeDir==ORDER_TYPE_BUY) ? trade.Buy(lot,_Symbol,price,0,0,cmt)
                                     : trade.Sell(lot,_Symbol,price,0,0,cmt);
}
void CloseAllBasket(string reason)
{
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(tk==0 || !PositionSelectByTicket(tk)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      trade.PositionClose(tk);
   }
}

double GetGridSpacingPoints()
{
   if(!UseATRSpacing) return MathMax(GridSpacingMinPoints, 50);
   double atrD1 = ReadBuf(hATR_D1,0,1);
   double pts = atrD1 / _Point * ATRSpacingMultiplier;
   if(pts < GridSpacingMinPoints) pts = GridSpacingMinPoints;
   if(pts > GridSpacingMaxPoints) pts = GridSpacingMaxPoints;
   return pts;
}

// OPT 3: was there a recent SL-hit close (loss, close near SL) within N hours?
bool HadRecentSL(int hours)
{
   datetime cutoff = TimeCurrent() - hours*3600;
   if(!HistorySelect(cutoff, TimeCurrent())) return false;
   for(int i=HistoryDealsTotal()-1; i>=0; i--)
   {
      ulong d = HistoryDealGetTicket(i);
      if(d==0) continue;
      if(HistoryDealGetInteger(d, DEAL_MAGIC) != MagicNumber) continue;
      if(HistoryDealGetString(d, DEAL_SYMBOL) != _Symbol) continue;
      if(HistoryDealGetInteger(d, DEAL_ENTRY) != DEAL_ENTRY_OUT) continue;
      if(HistoryDealGetDouble(d, DEAL_PROFIT) < 0) return true;
   }
   return false;
}

void ManageBreakEvenSL()
{
   if(!UseBreakEvenSL) return;
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(tk==0 || !PositionSelectByTicket(tk)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(StringFind(PositionGetString(POSITION_COMMENT), "_SLTP") < 0) continue;
      double op = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl = PositionGetDouble(POSITION_SL);
      double tp = PositionGetDouble(POSITION_TP);
      if(sl == 0) continue;
      long ptype = PositionGetInteger(POSITION_TYPE);
      double cur = (ptype==POSITION_TYPE_BUY) ? Bid_() : Ask_();
      double slDist = MathAbs(op - sl);
      if(slDist == 0) continue;
      double rNow = (ptype==POSITION_TYPE_BUY) ? (cur-op)/slDist : (op-cur)/slDist;
      if(rNow < BreakEvenTriggerR) continue;
      bool alreadyBE = (ptype==POSITION_TYPE_BUY) ? (sl>=op) : (sl<=op);
      if(alreadyBE) continue;
      trade.PositionModify(tk, op, tp);
   }
}

// Dispatcher: single pool (default = gold/silver path, UNCHANGED) or per-basket
// loop when MaxConcurrentBaskets>1 (lets new signals open their own basket so one
// stuck basket can't starve 200+ signals -- no time/hard stops involved).
void ManageGrid()
{
   int maxB = (MaxConcurrentBaskets < 1) ? 1 : MaxConcurrentBaskets;
   if(maxB <= 1) { ManageOneBasket(-1); return; }   // untagged single pool = original behaviour, byte-for-byte

   // portfolio-level catastrophe floor: cap TOTAL float across all baskets so concurrency
   // can't multiply tail risk. (single-basket case is already covered by the per-basket floor.)
   if(UseBasketStop && PortfolioFloat() <= -BasketMaxLossPct/100.0 * Bal_())
   { CloseEverything("PORTFOLIO STOP"); g_peakBasketFloat=0.0; return; }

   // ---- PORTFOLIO STAGED FLOOR: lighten the whole book BEFORE the portfolio floor fires.
   // Shares g_lastStageBar with the per-basket lever -> at most ONE staged cut of any kind
   // per bar; the realized loss + relief on the survivors self-hystereses the trigger.
   if(UseStagedFloorPortfolio && iTime(_Symbol, PERIOD_CURRENT, 0) != g_lastStageBar)
   {
      double bookF = PortfolioFloat();
      if(bookF <= -StagedFloorPortfolioPct/100.0 * Bal_())
      {
         int totalLegs=0; ulong worstTicket=0; double worstPnl=0;
         for(int wi=PositionsTotal()-1; wi>=0; wi--)
         {
            ulong wtk = PositionGetTicket(wi);
            if(wtk==0 || !PositionSelectByTicket(wtk)) continue;
            if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
            if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
            if(StringFind(PositionGetString(POSITION_COMMENT), "_HEDGE") >= 0) continue;
            totalLegs++;
            double wpnl = PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
            if(worstTicket==0 || wpnl < worstPnl) { worstTicket = wtk; worstPnl = wpnl; }
         }
         if(worstTicket > 0 && totalLegs >= 2)   // keep a book to lighten
         {
            if(trade.PositionClose(worstTicket))
               Print("PORTFOLIO STAGED FLOOR: closed worst leg #", worstTicket,
                     " pnl=", DoubleToString(worstPnl,2),
                     " (book float was ", DoubleToString(bookF,2), ")");
            else
               Print("PORTFOLIO STAGED FLOOR: close failed #", worstTicket, " err=", GetLastError());
            g_lastStageBar = iTime(_Symbol, PERIOD_CURRENT, 0);
            return;   // re-evaluate the lightened book next tick
         }
      }
   }

   // ---- RECOVERY HEDGE is now SIGNAL-DRIVEN (2026-07-29, user's fib-C mechanism): the ENTRY function
   //      rides the NEW TREND (opposite the losing side) on EVERY Goldminer signal while the book is in DD,
   //      growing the hedge progressively (a leg per signal, capped at RescueMaxBaskets) until it recovers
   //      to +RescueBookTargetUSD. The old ONE-SHOT mechanical overtake at the trigger was REMOVED -- a
   //      single static short can't hold a moving trend and whipsaws on every bounce (proven: floor-off
   //      run drew down 46% / -$2,442). RescueHedgeRatio now unused (kept as an input for back-compat).
   //      (Signal-ride itself then FAILED harder -- 65% DD -- oil's drawdowns are REVERSIONS, any net-
   //      directional hedge is crushed on the bounce -> the FREEZE below is the non-directional answer.)

   // ---- FREEZE HEDGE (2026-07-29): neutralize 1:1 (tag _FRZ), HOLD flat, RELEASE the hedge legs on a
   //      confirmed bounce (FreezeReleaseATR x ATR(D1) off the adverse extreme) so the recovering side
   //      runs home. Never net-directional -> nothing to crush. Book-exit at +target still applies while frozen.
   if(UseFreezeHedge && RescueOnDrawdownPct > 0)
   {
      double px = Bid_();
      if(PortfolioFloat() >= 0) g_freezeAnchor = 0.0;   // episode over (book healthy) -> reset the anti-churn anchor
      if(g_freezeDir < 0 && PortfolioFloat() <= -RescueOnDrawdownPct/100.0 * Bal_())
      {
         int loseDir  = (SameDirFloat(ORDER_TYPE_BUY) <= SameDirFloat(ORDER_TYPE_SELL)) ? (int)ORDER_TYPE_BUY : (int)ORDER_TYPE_SELL;
         int hedgeDir = (loseDir == (int)ORDER_TYPE_BUY) ? (int)ORDER_TYPE_SELL : (int)ORDER_TYPE_BUY;
         // anti-churn: after a release, only RE-freeze if price makes a NEW adverse extreme beyond the last episode's
         bool newExtreme = (g_freezeAnchor == 0.0) ||
                           (loseDir == (int)ORDER_TYPE_BUY ? px < g_freezeAnchor : px > g_freezeAnchor);
         double need  = SameDirLots(loseDir) - SameDirLots(hedgeDir);   // 1:1 neutralize the net exposure
         if(need > 0 && newExtreme)
         {
            double minLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
            double hlot = NormalizeDouble(need, 2); if(hlot < minLot) hlot = minLot;
            string cmt = CommentText + "_FRZ";
            bool ok = (hedgeDir==ORDER_TYPE_BUY) ? trade.Buy(hlot,_Symbol,Ask_(),0,0,cmt)
                                                 : trade.Sell(hlot,_Symbol,px,0,0,cmt);
            if(ok)
            {
               g_freezeDir = loseDir; g_freezeExtreme = px;
               Print("FREEZE HEDGE: ", (hedgeDir==ORDER_TYPE_BUY?"BUY":"SELL"), " ", DoubleToString(hlot,2),
                     " lots 1:1 (book ", DoubleToString(PortfolioFloat(),2), " frozen; release on ",
                     DoubleToString(FreezeReleaseATR,1), "xATR bounce)");
            }
         }
      }
      else if(g_freezeDir >= 0)
      {
         double atrD1f = ReadBuf(hATR_D1,0,1);
         bool bounce = false;
         if(g_freezeDir == (int)ORDER_TYPE_BUY)        // frozen LONGS: extreme = the low; release on a bounce UP
         { if(px < g_freezeExtreme) g_freezeExtreme = px; bounce = (px >= g_freezeExtreme + FreezeReleaseATR*atrD1f); }
         else                                          // frozen SHORTS: extreme = the high; release on a fall back
         { if(px > g_freezeExtreme) g_freezeExtreme = px; bounce = (px <= g_freezeExtreme - FreezeReleaseATR*atrD1f); }

         if(PortfolioFloat() >= RescueBookTargetUSD)   // whole book green while frozen -> bank it all
         {
            CloseEverything("FREEZE BOOK EXIT +" + DoubleToString(PortfolioFloat(),2));
            g_freezeDir = -1; g_freezeAnchor = 0.0; g_peakBasketFloat = 0.0;
            return;
         }
         if(bounce)                                     // confirmed reversal -> release the hedge, let the book recover
         {
            for(int i=PositionsTotal()-1; i>=0; i--)
            {
               ulong tk = PositionGetTicket(i);
               if(tk==0 || !PositionSelectByTicket(tk)) continue;
               if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
               if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
               if(StringFind(PositionGetString(POSITION_COMMENT), "_FRZ") < 0) continue;
               trade.PositionClose(tk);
            }
            Print("FREEZE RELEASED on bounce (extreme ", DoubleToString(g_freezeExtreme,2),
                  " -> ", DoubleToString(px,2), "); book recovers unhedged");
            g_freezeAnchor = g_freezeExtreme;   // anti-churn: re-freeze only beyond this
            g_freezeDir = -1;
         }
         if(g_freezeDir >= 0) return;                   // frozen: no other book management this tick
      }
   }

   // ---- RESCUE BOOK EXIT (S24, fib C's RecoveryTargetUSD): while a rescue basket is open,
   // close the WHOLE book (losers + rescue) together once combined float reaches the target.
   // (guard is g_rescueDir>=0 alone -- it's armed only by a rescue path, signal-gated OR loss-gated)
   if(g_rescueDir >= 0)
   {
      if(CountSameDirBaskets(g_rescueDir) == 0)
         { g_rescueDir = -1; g_rescuePeak = 0.0; }             // rescue basket(s) gone -> disarm
      else if(RescueBookTargetUSD > 0 && PortfolioFloat() >= RescueBookTargetUSD)
      {
         double pf = PortfolioFloat();
         if(RescueBookTrailPct > 0)                            // TRAIL: ride the move, bank near the bottom
         {
            if(pf > g_rescuePeak) g_rescuePeak = pf;           // track the book's peak profit
            if(pf <= g_rescuePeak * (1.0 - RescueBookTrailPct/100.0))
            {
               CloseEverything("RESCUE TRAIL EXIT +" + DoubleToString(pf,2) + " (peak +" + DoubleToString(g_rescuePeak,2) + ")");
               g_rescueDir = -1; g_rescuePeak = 0.0; g_peakBasketFloat = 0.0;
               return;
            }
         }
         else                                                 // fixed target (original behaviour)
         {
            CloseEverything("RESCUE BOOK EXIT +" + DoubleToString(pf,2));
            g_rescueDir = -1; g_rescuePeak = 0.0; g_peakBasketFloat = 0.0;
            return;
         }
      }
   }

   int ids[]; int n = CollectBaskets(ids);
   for(int k=0; k<n; k++) ManageOneBasket(ids[k]);
}

// Manage ONE basket. targetBid = -1 means the untagged pool (the original single-basket
// path: the BasketIdOf filter is always true, so logic/decisions are identical to before).
void ManageOneBasket(int targetBid)
{
   int nLevels=0; double basketLots=0, basketSumPxLot=0, basketFloat=0;
   long initialDir=-1; double hedgeLots=0, hedgeFloat=0; bool hedgeOpen=false;
   datetime oldestOpen=0;
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(tk==0 || !PositionSelectByTicket(tk)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      string cmt = PositionGetString(POSITION_COMMENT);
      if(BasketIdOf(cmt) != targetBid) continue;          // basket filter (always true for untagged single pool)
      double lot = PositionGetDouble(POSITION_VOLUME);
      double op  = PositionGetDouble(POSITION_PRICE_OPEN);
      double pnl = PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
      datetime ot = (datetime)PositionGetInteger(POSITION_TIME);
      if(oldestOpen==0 || ot < oldestOpen) oldestOpen = ot;
      if(StringFind(cmt, "_HEDGE") >= 0) { hedgeOpen=true; hedgeLots+=lot; hedgeFloat+=pnl; }
      else { nLevels++; initialDir=PositionGetInteger(POSITION_TYPE); basketLots+=lot; basketSumPxLot+=op*lot; basketFloat+=pnl; }
   }
   if(nLevels==0) { g_peakBasketFloat=0.0; g_lockArmed=false; return; }
   double combinedFloat = basketFloat + hedgeFloat;

   double atrD1t = ReadBuf(hATR_D1,0,1);
   double lm = (BarrierATRLower > 0) ? BarrierATRLower : BarrierATRMultiplier;
   double oneR = atrD1t * lm * DollarPerPricePerLot() * (basketLots + hedgeLots);

   // catastrophic floor (per basket)
   if(UseBasketStop)
   {
      double maxLoss = -BasketMaxLossPct/100.0 * Bal_();
      if(combinedFloat <= maxLoss) { CloseBasket(targetBid, "BASKET STOP"); g_peakBasketFloat=0.0; return; }
   }
   // regime-aware exit: bail a LOSING basket when the D1 trend has flipped against it (caps the tail early -> lower equity DD)
   if(UseRegimeBasketExit && combinedFloat < 0 && initialDir >= 0)
   {
      bool d1bull = IsDailyTrendBullish();
      bool basketBuy = (initialDir == POSITION_TYPE_BUY);
      if((basketBuy && !d1bull) || (!basketBuy && d1bull))
      { CloseBasket(targetBid, "regime flip exit"); g_peakBasketFloat=0.0; return; }
   }
   // ---- STAGED FLOOR (user-designed live 2026-07-09; MT4 build T; PER BASKET here):
   // cut the single WORST leg of THIS basket when it floats <= -StagedFloorPct% of
   // balance, BEFORE the catastrophic floor -- lightens the basket (escape pulls
   // closer, floor pushes away, survival odds rise) for the price of one realized leg.
   // At most one cut per bar (global guard); the realized loss deepens neither float
   // nor trigger, so the mechanism self-hysteresis on the lightened basket.
   if(UseStagedFloor && nLevels >= 2 && iTime(_Symbol, PERIOD_CURRENT, 0) != g_lastStageBar &&
      combinedFloat <= -StagedFloorPct/100.0 * Bal_())
   {
      ulong worstTicket = 0; double worstPnl = 0;
      for(int wi=PositionsTotal()-1; wi>=0; wi--)
      {
         ulong wtk = PositionGetTicket(wi);
         if(wtk==0 || !PositionSelectByTicket(wtk)) continue;
         if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
         if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
         string wcmt = PositionGetString(POSITION_COMMENT);
         if(BasketIdOf(wcmt) != targetBid) continue;         // THIS basket only
         if(StringFind(wcmt, "_HEDGE") >= 0) continue;       // basket legs only
         double wpnl = PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
         if(worstTicket==0 || wpnl < worstPnl) { worstTicket = wtk; worstPnl = wpnl; }
      }
      if(worstTicket > 0)
      {
         if(trade.PositionClose(worstTicket))
            Print("STAGED FLOOR: closed worst leg #", worstTicket,
                  " pnl=", DoubleToString(worstPnl,2),
                  " (basket float was ", DoubleToString(combinedFloat,2),
                  " bid=", targetBid, ")");
         else
            Print("STAGED FLOOR: close failed #", worstTicket, " err=", GetLastError());
         g_lastStageBar = iTime(_Symbol, PERIOD_CURRENT, 0);
         return;   // re-evaluate the lightened basket next tick
      }
   }
   // profit exit
   if(UseLockTrailExit)
   {
      // RIDE-THE-TREND (user design): +ProfitTargetUSD is the TRIGGER to start riding, NOT the exit.
      // Once profit reaches the target, ARM: lock break-even (a triggered winner can't become a loss)
      // and let the trade RIDE the continuation; liquidate only when float retraces
      // LockTrailGivebackPct% from its running peak. So a small bounce at the target doesn't close it
      // (the choke in the prior version) — it rides moves like the chart's continuation down to 4114.
      // (g_peakBasketFloat / g_lockArmed are single globals -> reliable only at MaxConcurrentBaskets<=1.)
      // RIDE only TREND-ALIGNED baskets (continuation, like the chart's downtrend sell). BANK
      // counter-trend recoveries fast at the target — those are the bounce-that-fades baskets
      // that, when ridden, reverse and hit the -20% floor (the -$1,072/-$1,751 grid disasters).
      if(combinedFloat >= ProfitTargetUSD && !g_lockArmed)
      {
         bool d1bull   = IsDailyTrendBullish();
         bool basketBuy = (initialDir == POSITION_TYPE_BUY);
         bool aligned   = (basketBuy == d1bull);   // BUY&bull or SELL&bear = with the D1 trend
         if(aligned) g_lockArmed = true;           // trend-aligned -> ride the continuation
         else { CloseBasket(targetBid, "target (counter-trend bank)"); g_peakBasketFloat=0.0; return; } // bank +$
      }
      if(g_lockArmed)
      {
         if(combinedFloat > g_peakBasketFloat) g_peakBasketFloat = combinedFloat;
         double stop = g_peakBasketFloat * (1.0 - LockTrailGivebackPct/100.0);
         if(stop < 0) stop = 0;   // break-even floor: never give a triggered winner back into a loss
         if(combinedFloat <= stop) { CloseBasket(targetBid, "lock-trail exit"); g_peakBasketFloat=0.0; g_lockArmed=false; return; }
      }
   }
   else if(nLevels >= 2)
   {
      if(combinedFloat >= ProfitTargetUSD) { CloseBasket(targetBid, "grid recovery escape"); g_peakBasketFloat=0.0; return; }
   }
   else if(UseTrailingExit && oneR > 0)
   {
      if(combinedFloat > g_peakBasketFloat) g_peakBasketFloat = combinedFloat;
      if(g_peakBasketFloat >= TrailActivateR*oneR && combinedFloat <= g_peakBasketFloat - TrailDistanceR*oneR)
      { CloseBasket(targetBid, "trail exit"); g_peakBasketFloat=0.0; return; }
   }
   else
   {
      // single position: with an ASYMMETRIC upper barrier, let the wider TP run (skip the $ cap);
      // symmetric (BarrierATRUpper=0) keeps the $100 cap -> validated baseline unchanged.
      bool letRun = (BarrierATRUpper > 0);
      if(!letRun && combinedFloat >= ProfitTargetUSD) { CloseBasket(targetBid, "profit target"); return; }
   }
   if(oldestOpen > 0 && (TimeCurrent()-oldestOpen) > MaxDaysOpen*86400) { CloseBasket(targetBid, "max days"); return; }

   double basketAvg = (basketLots>0) ? basketSumPxLot/basketLots : 0;
   double currentPrice = (initialDir==POSITION_TYPE_BUY) ? Bid_() : Ask_();
   if(!hedgeOpen)
   {
      double beDistance = MathAbs(basketAvg - currentPrice) / point;
      if(UseHedge && beDistance >= HedgeBreakEvenPoints)
      {
         int hedgeSide = (initialDir==POSITION_TYPE_BUY) ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;
         double hedgeSize = NormalizeDouble(basketLots * HedgeRatio, 2);
         if(hedgeSize < 0.01) hedgeSize = 0.01;
         OpenHedge(hedgeSide, hedgeSize, targetBid);
         return;
      }
      if(nLevels < MaxGridLevels)
      {
         double spacing = GetGridSpacingPoints();
         double extremeEntry = basketAvg;
         for(int j=PositionsTotal()-1; j>=0; j--)
         {
            ulong tk2 = PositionGetTicket(j);
            if(tk2==0 || !PositionSelectByTicket(tk2)) continue;
            if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
            if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
            string cmt2 = PositionGetString(POSITION_COMMENT);
            if(BasketIdOf(cmt2) != targetBid) continue;
            if(StringFind(cmt2, "_HEDGE") >= 0) continue;
            double op2 = PositionGetDouble(POSITION_PRICE_OPEN);
            if(initialDir==POSITION_TYPE_BUY  && op2 < extremeEntry) extremeEntry = op2;
            if(initialDir==POSITION_TYPE_SELL && op2 > extremeEntry) extremeEntry = op2;
         }
         bool addNow = false;
         if(initialDir==POSITION_TYPE_BUY  && currentPrice <= extremeEntry - spacing*point) addNow=true;
         if(initialDir==POSITION_TYPE_SELL && currentPrice >= extremeEntry + spacing*point) addNow=true;
         if(addNow)
         {
            // rescue choreography (S24): stop FEEDING the losing side while a rescue basket rides
            if(g_rescueDir >= 0 && (int)initialDir != g_rescueDir) return;  // stop feeding the loser (signal- OR loss-gated rescue)
            double currentTotalLots = basketLots + hedgeLots;
            double rawGridLot = UseRiskNormalizedLots ? RiskNormalizedLot(nLevels) : CalculateLot(nLevels);
            if(rawGridLot < 0) return;
            double newLot = NormalizeDouble(rawGridLot, 2);   // grid legs at base size (sizing applies to the initial entry only -> safe under concurrency)
            double minLotG = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
            if(newLot < minLotG) newLot = minLotG;
            if(currentTotalLots + newLot > MaxBasketLotsTotal) return;
            if(SkipGridAfterSL && HadRecentSL(SkipGridAfterSLHours)) return;
            int gdir = (initialDir==POSITION_TYPE_BUY) ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
            OpenGridLevel(gdir, newLot, nLevels+1, targetBid);
         }
      }
   }
}
//+------------------------------------------------------------------+
