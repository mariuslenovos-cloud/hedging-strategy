//| GENERATED TEST CELL GOLD HPIN -- regen via gridstat_make_cells.py |
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

#define EA_BUILD_VERSION "GS-CELL-GOLD-HPIN-S39-2026-09-06"
#define MAX_PENDING 5000

#include <Trade/Trade.mqh>
CTrade trade;   // Stage 2 execution

//--- Mode
const bool StatsCollectionMode = false;   // SHADOW: log signals + triple-barrier outcomes (Stage 1 is shadow-only)  // CELL-LOCKED
const string StatsCSVFile        = "gridstat_setups_gold.csv";  // per-symbol: e.g. gridstat_setups_oil.csv  // CELL-LOCKED

//--- Triple-barrier
const double BarrierATRMultiplier = 0.8;   // symmetric barrier ATR(D1) mult (used when the asym overrides below = 0)  // CELL-LOCKED
const double BarrierATRUpper      = 0;     // 0 = symmetric; else UPPER (target) barrier ATR mult -- set > lower to let winners run  // CELL-LOCKED
const double BarrierATRLower      = 0;     // 0 = symmetric; else LOWER (stop)  barrier ATR mult -- R is measured in units of this (the risk)  // CELL-LOCKED
const int TimeBarrierBars      = 288;   // time barrier (M5 bars; 288 = 24h)  // CELL-LOCKED

//--- Goldminer signal (DECOUPLED -- 0 = auto-derive from grisk like the MT4 original)
const int grisk        = 4;     // MT5-gold optimum (shadow-swept + trade-validated: +52% net vs 7 at same ~20% equity DD). legacy RISK knob; drives auto bands when overrides=0  // CELL-LOCKED
const int GM_Period    = 0;     // 0 = auto (grisk*2+3); else fixed WPR period  // CELL-LOCKED
const double GM_UpperBand = 0;     // 0 = auto (grisk+67); overbought threshold  // CELL-LOCKED
const double GM_LowerBand = 0;     // 0 = auto (33-grisk); oversold threshold  // CELL-LOCKED
const double GM_GapMult   = 2.0;   // gap detector: jump >= this * avgRange -> period 3  // CELL-LOCKED
const int GM_GapMode   = 0;     // 0 = original |Open-PrevClose| (MT4-equiv, ~dead on continuous CFDs); 1 = |Close-PrevClose| close-to-close jump (activates the runner detector on gold/oil)  // CELL-LOCKED
const double GM_FastMult  = 4.6;   // fast-move detector: |Close[i+3]-Close[i]| >= this * avgRange -> period 4  // CELL-LOCKED
const int goldminershift = 1;   // evaluate signal on this shift (1 = last closed bar)  // CELL-LOCKED
//--- SIGNAL-STRENGTH gate (2026-07-23 study): the WEAKEST Goldminer signals (barely past the band)
//    are the losers across gold/oil/silver buys (gold shallow buys 38%/-0.15R; silver monotonic 52->71%;
//    oil deep 64%/+0.15R vs shallow 52%/+0.02R). This gates a NEW-basket signal on its PENETRATION depth
//    past the band = direction-normalized strength (BUY: wpr-upper; SELL: lower-wpr). Rescue bypasses.
//    Default OFF (base unchanged). Validate every-tick per symbol; shadow win-rate != grid profit -> tester decides.
const bool UseSignalStrengthGate = false; // ON = skip signals with penetration < SignalStrengthMin  // CELL-LOCKED
const double SignalStrengthMin      = 0;    // min penetration past the band (wpr units); 0 = no cut  // CELL-LOCKED

//--- Feature-importance instrumentation (UNIVERSAL -- improves gold/silver selection too, not just oil)
//    Logs the features the coarse DIR|SESSION|ATR fingerprint throws away, so feature-importance
//    can find sharper, higher-P&L setup cuts per symbol (run on gold/silver/oil shadow alike).
const int RunupBars = 12;        // dip-vs-continuation: directional price move over last N bars before entry (/ATR)  // CELL-LOCKED

//--- Entry filters (so shadow measures only signals that WOULD be tradeable)
const double MA_Angle_Threshold = 20.0;  // CELL-LOCKED
const int MA_Period          = 20;  // CELL-LOCKED
const int ADX_Period         = 14;  // CELL-LOCKED
const double ADX_Threshold      = 25.0;  // CELL-LOCKED
const bool UseDailyTrendFilter = true;  // CELL-LOCKED
const int DailyMA_Period      = 50;  // CELL-LOCKED
//--- FASTER DOWNTREND GATE (2026-07-29): the slow EMA(50) trend filter LAGS a fast crash by ~3 days
//    (it stayed "bullish" as oil fell 113->82, so the grid kept BUYING into the downtrend = the floor hits).
//    This adds a faster gate: block a BUY when price is below a SHORT D1 EMA (and a SELL when above) ->
//    stops feeding a sustained downtrend days sooner = far fewer floor hits. Rescue bypasses. Default OFF.
const bool UseFastTrendGate   = false;  // CELL-LOCKED
const int FastTrendPeriod    = 15;      // D1 EMA period for the fast gate (shorter = catches a downtrend sooner)  // CELL-LOCKED
//--- CRASH GUARD (2026-07-29): the DIRECT "don't buy a falling knife" gate. Blocks a BUY when price is
//    CrashGuardPct% below its recent CrashGuardBars-day HIGH (and a SELL when the same % above the low).
//    Data-checked: this WOULD have blocked the 07-27 reopen buys (oil 84 vs a 10-day high of 93 = 10% down)
//    that the lagging MA filters let through, WITHOUT whipsawing on normal 3-5% uptrend pullbacks. Rescue bypasses. Default OFF.
const bool UseCrashGuard      = false;  // CELL-LOCKED
const double CrashGuardPct      = 8.0;     // block BUYs when price is this% below the recent high (SELLs: above the low)  // CELL-LOCKED
const int CrashGuardBars     = 10;      // D1 bars for the recent high/low window  // CELL-LOCKED
//--- [S37 2026-09-04] RANGE-POSITION GUARD (user: "the engines are not intelligent enough — selling on an
//    uptrend, buying oil on a downtrend"). Both live specimens were the SAME error with the sign flipped:
//    gold 09-02 SOLD within 1-2%% of its 10-day LOW after a 3-day slide (7%% below the 10d high) and got the
//    bounce; oil 09-03 BOUGHT 0.7%% below its 10-day HIGH after a 2-day +6%% run and got the dip. The D1
//    filter was right by its rule both times; the engine simply has no idea where price sits in its own
//    recent range. This gate blocks NEW basket STARTS only: no BUY within RangeGuardPct%% of the N-day high,
//    no SELL within RangeGuardPct%% of the N-day low. Grid legs and rescue legs untouched. Default OFF.
const bool UseRangeGuard      = false;   // block fades AT the range edge (new basket starts only)  // CELL-LOCKED
const double RangeGuardPct      = 2.0;     // within this %% of the N-day high (BUY) / low (SELL) = blocked  // CELL-LOCKED
const int RangeGuardDays     = 10;      // D1 lookback for the range  // CELL-LOCKED
//--- [S38 2026-09-04] VELOCITY GUARD (08-11 improvement #1, finally built). The range guard (S37) failed because
//    Goldminer fires AT range extremes by design; what the three live disasters share is SPEED, not position:
//    gold 09-02 -7.5%%/3d into the sells, Aug-4/5 +4.7%%/2.5d into the sells, oil 09-03 +6%%/2d into the buy.
//    No NEW basket starts while |current price / D1 close N days ago - 1| exceeds VelocityGuardPct -- rare by
//    construction (a p95 threshold blocks ~5%% of days), symmetric (sit out the storm both ways = the fib C
//    vol-regime lesson), and it leaves the ordinary range-edge harvests alone. Grid/rescue legs untouched.
const bool UseVelocityGuard   = false;   // block new basket starts during a fast multi-day move  // CELL-LOCKED
const double VelocityGuardPct   = 4.0;     // |N-day move| above this %% = blocked  // CELL-LOCKED
const int VelocityGuardDays  = 3;       // D1 bars back for the reference close  // CELL-LOCKED
//    v2 STATE-MACHINE (2026-07-29): the plain distance rule also blocked the RECOVERY buys (price still far
//    below the old high while basing/turning) = the -45% net cost. Fix: CRASH state is STICKY but exits on a
//    CONFIRMED TURN -- price breaks the last CrashGuardResumeBars days' high (first higher-high) -> resume
//    dip-buying immediately. "Don't buy while it's falling; buy again the moment it turns."
const int CrashGuardResumeBars = 3;     // exit CRASH state when price breaks this many days' high (0 = plain distance rule)  // CELL-LOCKED
//--- CRASH-STATE SELLS (2026-07-30): in crash-state, SELL signals trade the bounces = the regime's winning
//    side; bypasses the lagging D1 filter + stats gate + sell-zeroed sizing. Base size, own escape/floor. Default OFF.
const bool UseCrashStateSells = false;  // ON = in crash-state, sell the bounces (spike-state: buy the dips)  // CELL-LOCKED
const bool UseSessionFilter    = true;  // CELL-LOCKED
const int SessionStartHour    = 9;  // CELL-LOCKED
const int SessionEndHour      = 23;  // CELL-LOCKED

//=== STAGE 2 -- TRADE EXECUTION (only when StatsCollectionMode = false) ===
//--- Entry win-rate gate (mirrors locked GOLD: reads StatsCSVFile = the shadow DB)
const bool StatsFilterEnabled    = true;  // CELL-LOCKED
const double MinWinRate            = 0.55;  // CELL-LOCKED
const int MinSamples            = 10;  // CELL-LOCKED
// [S30] MKT-STATE regime gate (the 08-09 spec): judge a fingerprint on its win rate IN THE CURRENT
// REGIME (D1 5-day momentum UP/DOWN) when the gate DB carries mkt_state and the cell is thick enough;
// thin cell -> all-regime fallback (= today's behaviour). DEFAULT OFF; also inert until a state-bearing
// DB is PROMOTED (the NDB rule: a fresh table must WIN an A/B first).
const bool UseRegimeGate         = false;  // CELL-LOCKED
const int RegimeGateMinN        = 8;  // CELL-LOCKED
//--- SIGNAL DIAGNOSTIC LOG (default OFF). Logs EVERY Goldminer fire + each gate's value/pass-fail +
//    the final TRADE/SKIP decision -> gridstat_signals_<symbol>.csv (Common\Files, per-symbol = no clobber).
//    Zero effect on trade behaviour; turn ON to see exactly why a signal was/wasn't taken (e.g. MT4 vs MT5 divergence).
const bool UseSignalLog          = false;  // CELL-LOCKED
//--- Overextension regime filter (Ch.17 structural-break; session 19o). Skips entries when price is
//    stretched far from the D1 mean = the overextension regime that breeds deep-DD/blow-up baskets.
//    Python MAE study: gold corr(dist,MAE)=-0.61, silver -0.38 (both SEPARATE); oil -0.20 (NO separation
//    -> leave OFF for oil). DEFAULT OFF = locked configs byte-identical. Trade-mode only (shadow DB untouched).
//    Validate every-tick: does it lower equity DD without killing net? Per-symbol threshold (gold ~4.5, silver ~8).
const bool UseOverextensionFilter = false;  // CELL-LOCKED
const double OverextATRMult         = 4.5;   // skip if |close - D1EMA(DailyMA_Period)| / ATR(D1,60) >= this. 0 = off.  // CELL-LOCKED
//--- Per-setup bet-sizing (AFML): size ∝ edge. DEFAULT OFF = flat lots (unchanged). When ON, reads
//    SizingCSVFile (from gridstat_rigor.py): mult>0 sizes the bet (×base lot), mult==0 / unknown = SKIP.
//    Concentrates capital on high-edge setups (oil: 2× the star BUY|HR_OVL|EXP), zeros negatives.
const bool UseSizingTable        = false;  // CELL-LOCKED
const string SizingCSVFile         = "gridstat_sizing_oil.csv";  // CELL-LOCKED
const double MaxSizeMult           = 2.0;  // CELL-LOCKED
//--- Lot sizing
const double LotSize               = 0.01;  // CELL-LOCKED
const bool UseCompounding        = true;  // CELL-LOCKED
const double CompoundingBase       = 3000.0;  // CELL-LOCKED
//--- COMPOUNDING CAP (2026-07-14, S26): the fib C Session-20 lesson transplanted.
//    C1/C2 capital cells: uncapped compounding re-inflates risk faster than capital
//    protects ($5k start -> eqDD 36.9%, $10k -> every event at 3x lots, gross give-back
//    $8k of $13k). fib C's frontier: capping the COMPOUNDING multiplier (not recovery
//    levers) curbs the grown-account give-back -- MaxCompoundScale=3 dominated.
//    0 = uncapped (original behaviour, locked configs unchanged).
const int MaxCompoundScale      = 2;        // cap floor(balance/CompoundingBase); 0 = uncapped  // CELL-LOCKED
//--- Grid-ladder shaping (Session 23, ported from MT4 build S): cap the fib multiplier of grid legs.
//    The fib ladder 1,1,2,3,5 is a martingale putting the BIGGEST lots at the WORST prices -- the deep
//    legs carried 40%+ of every observed floor loss (MT4 A/B: MaxFibMult=1 -> zero basket stops, net +86%,
//    PF 1.64->4.66, DD 21.6->11.7%). 0 = original fib (locked configs byte-identical); 1 = FLAT legs
//    (all = base lot; float at the adverse extreme shrinks ~60%; escapes need a slightly deeper retrace);
//    2 = capped ladder 1,1,2,2,2. Validate every-tick per symbol before re-locking.
const int MaxFibMult            = 0;  // CELL-LOCKED
const bool UseRiskNormalizedLots = false;   // OFF for gold; ON for volatile symbols (silver/oil)  // CELL-LOCKED
const double RiskPctPerTrade       = 3.0;  // CELL-LOCKED
const double MaxRiskPctSkip        = 8.0;  // CELL-LOCKED
//--- Hedged grid
const bool UseATRSpacing         = true;  // CELL-LOCKED
const double ATRSpacingMultiplier  = 0.5;  // CELL-LOCKED
const int GridSpacingMinPoints  = 300;  // CELL-LOCKED
const int GridSpacingMaxPoints  = 2000;  // CELL-LOCKED
const int MaxGridLevels         = 6;  // CELL-LOCKED
const int MaxConcurrentBaskets  = 1;    // 1 = one cluster at a time (gold/silver: UNCHANGED path). >1 = allow N independent baskets so a stuck basket can't starve 200+ signals (trending indices/oil). No time/hard stops.  // CELL-LOCKED
const bool UseHedge              = true;  // CELL-LOCKED
const int HedgeBreakEvenPoints  = 15000;  // CELL-LOCKED
const double HedgeRatio            = 1.0;  // CELL-LOCKED
const double ProfitTargetUSD       = 50.0;   // basket recovery escape + single-position $ cap  // CELL-LOCKED
const int MaxDaysOpen           = 30;  // CELL-LOCKED
//--- Single-position trailing exit (OFF for gold; only used when nLevels<2)
const bool UseTrailingExit       = false;  // CELL-LOCKED
const double TrailActivateR        = 1.0;  // CELL-LOCKED
const double TrailDistanceR        = 0.6;  // CELL-LOCKED
//--- Lock-and-trail exit (DEFAULT OFF = locked configs unchanged). When ON, a basket that
//    reaches ProfitTargetUSD does NOT close immediately: it LOCKS the target as a guaranteed
//    floor and TRAILS the excess (closes when float retraces LockTrailGiveback $ from peak,
//    but never banks below the locked target). Captures trend continuation past the fixed $
//    target (the chart problem) without the session-16 trailing failure modes (can't reverse
//    into a loss; pair with MaxConcurrentBaskets>1 so holding a runner doesn't starve entries).
const bool UseLockTrailExit      = false;  // CELL-LOCKED
const double LockTrailGivebackPct  = 15.0;   // % retrace from PEAK that liquidates (once +ProfitTargetUSD armed the ride); break-even is locked so a triggered winner can't become a loss  // CELL-LOCKED
//--- Per-entry hard SL toggle. true = SL at the lower barrier (gold-inherited triple-barrier, current).
//    false = NO per-entry stop; rely on grid recovery + the catastrophe basket floor (matches the
//    no-hard-stop hedging philosophy). On pullback-heavy BUY-tilted symbols (oil) the −1R entry stop
//    fires right before the grid would recover; removing it lets those losers recover. TEST per symbol.
const bool UseEntrySL            = true;  // CELL-LOCKED
//--- Basket catastrophic floor (the grid has no inherent stop)
const bool UseBasketStop         = true;  // CELL-LOCKED
const double BasketMaxLossPct      = 20.0;  // CELL-LOCKED
//--- STAGED FLOOR (Session 24; user-designed LIVE 2026-07-09, ported from MT4 build T):
//    when a basket floats <= -StagedFloorPct% of balance, close its single WORST leg --
//    lightens the basket (avg entry improves, escape pulls closer, floor pushes away)
//    for the price of one realized leg. Live episode: -$28 vs a near-certain -$388.
//    MT4 156-trade-panel sweep: plateau 12-14, RF 3.74 -> 4.99 at 12. Must be
//    < BasketMaxLossPct or the catastrophic floor fires first. Default OFF = base unchanged.
//    Threshold is PER-SYMBOL ([[exit-rules-per-symbol]]): gold 12; silver/oil need own sweeps.
const bool UseStagedFloor        = true;    // cut the worst leg early (default OFF)  // CELL-LOCKED
const double StagedFloorPct        = 12.0;     // ...at basket float <= -this% of balance  // CELL-LOCKED
//--- PORTFOLIO STAGED FLOOR (2026-07-12): the per-basket staged floor is provably INERT on
//    multi-basket streams whose pain is N shallow ONE-leg baskets drowning together (oil A/B:
//    byte-identical, zero fires -- every deep event was the PORTFOLIO floor, no basket near -8%).
//    This variant = the MT4 original's book-level semantics: TOTAL float <= -this% of balance ->
//    close the single WORST leg anywhere in the book. Multi-basket path only (conc=1 streams
//    use the per-basket lever -- identical there by construction). Default OFF.
const bool UseStagedFloorPortfolio = false;  // book-level staged cut (oil/silver, conc>1)  // CELL-LOCKED
const double StagedFloorPortfolioPct = 8.0;    // ...at TOTAL float <= -this% of balance (< BasketMaxLossPct)  // CELL-LOCKED
//--- SAME-DIRECTION BASKET GATE (2026-07-12, S21): oil's six ~-$1,0xx-1,4xx events are N
//    same-direction ONE-leg baskets drowning together (3x correlated exposure to one move),
//    and BOTH staged-floor variants failed there (per-basket inert; book-level cut realized
//    recoverable floats -> net -14%/DD +9pp). This lever refuses to COMPOUND a losing bet
//    instead of cutting one: block a NEW basket in direction D while the existing D-direction
//    legs float <= -SameDirGateLossPct% of balance. Gate-respecting (no forced realizations,
//    winners untouched, recovery adds inside existing baskets unaffected). Default OFF.
const bool UseSameDirBasketGate  = false;    // block new same-direction baskets while that side is deep  // CELL-LOCKED
const double SameDirGateLossPct    = 2.0;      // ...existing same-dir float <= -this% of balance blocks  // CELL-LOCKED
//--- SAME-DIRECTION SIZE TAPER (2026-07-12, S22): the GATE version above is RF-negative on
//    oil (PEP A/B @2%: blocked 22% of 89%-win flow to save 21% DD$ -> RF 3.23->2.98). Per
//    [[rigor-drives-sizing-not-gating]]: don't BLOCK the pile-in entry -- SHRINK it. A new
//    basket opening in direction D while D-side floats NEGATIVE opens at
//    SameDirTaperMult^(existing D-baskets) size: every winner still fires and pays; only the
//    correlated drown-together tail shrinks. Folds into g_clusterSizeMult -> applies to the
//    INITIAL entry only, same semantics as the sizing table (grid legs stay base size --
//    the observed oil tail anatomy is ONE-leg baskets, so the initial entry IS the exposure).
//    Default OFF.
const bool UseSameDirTaper       = false;    // taper new same-direction basket SIZE while that side is losing  // CELL-LOCKED
const double SameDirTaperMult      = 0.5;      // lot mult per existing same-dir basket (0.5 -> 2nd=half, 3rd=quarter)  // CELL-LOCKED
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
const bool AllowOppositeWhenDeep = false;    // unblock opposite-direction baskets while the book is deep  // CELL-LOCKED
const double OppositeWhenDeepPct   = 5.0;      // ...book float <= -this% of balance arms the unblock  // CELL-LOCKED
//    S24 completes fib C's EXIT choreography (S23 A/B: every drowning cluster shrank + DD$
//    -28%, but net -32% because the rescue basket was left to fend for itself -- it won
//    during the continuation then bled its gains back on the bounce while the losers
//    recovered = hedge-churn without fib C's book-level exit). While a rescue basket is
//    open: (a) the LOSING side stops grid-adding (stop feeding the loser), (b) the WHOLE
//    book (losers + rescue) closes together at +RescueBookTargetUSD (fib C's
//    RecoveryTargetUSD). 0 = disabled (S23 behaviour).
const double RescueBookTargetUSD   = 20.0;     // close the whole book at +this while rescued (0 = off)  // CELL-LOCKED
//    S25 adds fib C's THIRD ingredient -- GROW the winning side. S24 A/B showed one rescue
//    basket (~1/3 of the losing exposure) cannot overtake 2-3 drowning baskets, so the book
//    never reaches the exit target before the floors fire. fib C rode EVERY winning-side
//    signal until the book recovered. RescueMaxBaskets grants up to N rescue slots beyond
//    MaxConcurrentBaskets while the book stays deep; each entry still needs its own
//    Goldminer signal + quality gates. 1 = S23/S24 behaviour.
const int RescueMaxBaskets      = 5;        // rescue slots beyond MaxConcurrentBaskets (fib C ramp: 2-3)  // CELL-LOCKED
//--- LOSS-GATED HEDGE (2026-07-28): the FIX for the signal-gated rescue that never fired in a downtrend.
//    RSQ2/AllowOppositeWhenDeep only opens the hedge when an OPPOSITE Goldminer signal fires -- in a
//    sustained downtrend that signal never comes (Goldminer fades dips = BUYs), so oil bled undefended
//    (0 rescues in 2 weeks live, incl. the -$403 weekend). This fires the SAME proven machinery
//    (book-exit at +RescueBookTargetUSD + stop-feeding the loser) on the DRAWDOWN LEVEL directly -- no
//    signal needed. Sized to OVERTAKE (ratio>1 -> net opposite) so a continued adverse move rides the
//    whole book to +target = "hedge into profit". Reversal-release = the tuning iteration (floor backstops v1).
const double RescueOnDrawdownPct   = 5.0;      // book float <= -this% of balance FIRES the hedge (no signal). 0 = OFF  // CELL-LOCKED
const double RescueHedgeRatio      = 1.5;      // hedge lots = losing-side lots x this (>1 = overtake -> ride into profit)  // CELL-LOCKED
//    BIGGER PROFITS (2026-07-28): instead of banking the whole book the instant it reaches
//    +RescueBookTargetUSD, TRAIL it -- ride a sustained down-move and bank near the bottom.
const double RescueBookTrailPct    = 20.0;      // >0: after +target, exit on this% giveback from the book's PEAK profit. 0 = fixed target  // CELL-LOCKED
//--- REGIME-GATED RESCUE (2026-08-05, the fib-C-hedge-on-GridStat build the live 08-04/05 gold breakout
//    justified: fib C's hedge rode it +$277 while GridStat's stops paid -$300 fading it. The UNCONDITIONAL
//    ride failed (rode dip-bounces); this gates the loss-gated ride to CONFIRMED breakout states only:
//    a drowning SELL book rides BUYs only while g_crashUp (spike confirmed); drowning BUYs only in g_crashDown.
const bool RescueOnlyInCrashState = false;   // ON = the drawdown-fired ride requires the matching crash/spike state  // CELL-LOCKED
//--- CROSS-MARKET RISK FLAG (2026-08-05): oil<->gold hourly corr -0.204 = same-hour risk-off comove (no lead-lag;
//    event study: entries off oil's cross do NOT survive). USE = risk, not entries: when the named symbol's
//    crash-DOWN state is active (published via terminal globals), THIS symbol's spike-UP detection gets 2x more
//    sensitive (threshold halved). Live-only (tester runs one symbol -> flag inert in backtests).
const string CrossCrashSymbol       = "";      // e.g. gold sets "SpotCrude": oil crashing -> gold spike-risk elevated  // CELL-LOCKED
//    GATE-ONLY mode (2026-08-05, the gold finding: gold's breakouts ~= its noise amplitude -> distance
//    blocking kills half the profitable fade flow, B run $9,226->$4,833). ON = compute + publish the states
//    and use them for the REGIME-GATED RESCUE + cross flag, but do NOT block entries.
const bool CrashGuardGateOnly     = false;  // CELL-LOCKED
//--- SUB-8%% TRIGGER RE-ENGINEERING (2026-08-07, the C1 sweep cliff autopsy: 3/6/7%% = IDENTICAL death
//    spiral because (a) the trigger was SAMPLED only at signal times — gold blows through the 3-7%% band
//    between signals so all sub-8 configs armed at the SAME signal; (b) the flat +$40 book exit is crumbs
//    for an 8-11-leg armed book -> churn -> shrinking balance -> %%-trigger arms on pennies -> death.
//    All default-OFF -> locked behaviour byte-identical. These are the enablers for a usable 5-7%% trigger.
const bool RescueTickArm          = true;   // evaluate the loss-trigger EVERY TICK (persistent arm state) instead of only at signal times — fib C parity (fib C arms on-tick); gives sub-8 triggers real resolution  // CELL-LOCKED
const double RescueTargetPctDeepest = 10.0;     // >0: book exit target = max(RescueBookTargetUSD, this%% of the DEEPEST book loss this rescue) — scales the exit to the book it is rescuing  // CELL-LOCKED
const int RescueRearmCooldownBars = 288;      // >0: after a rescue ends (exit OR disarm), no re-arm for this many bars — kills the arm->exit->re-arm churn  // CELL-LOCKED
//--- [S36 2026-09-03] PIN-THEN-RIDE -- the 09-02/03 double guard-trip autopsy. The FIBC8 ride never ran:
//    it arms at the SAME -8%% as the Book Guard but is signal-sampled (guard is tick-evaluated) and every
//    ride leg needs a Goldminer signal -- there were NONE for 15h overnight. First-order sim on the real
//    bars (live HALF book, 4 sells 0.07): tick-arm alone = guard trip -$223 (no signal, nothing to ride);
//    immediate 1.5x overtake = guard trip on the first pullback (the 07-29 oil finding again);
//    immediate 1:1 PIN + fib-ramped rides = BOOK EXIT +$160 at 13:00. So: neutralize NOW at the arm
//    (no signal, any hour), then let the signal-driven overtake grow on top. All default-OFF.
const bool RescueImmediateLeg     = true;   // on TICK-ARM open a naked hedge leg at market immediately (no signal) = the PIN  // CELL-LOCKED
const double RescueImmediateRatio   = 1.0;     // pin lots = losing-side lots x this (1.0 = neutral; >1 = immediate overtake, tested-rejected)  // CELL-LOCKED
const bool RescueRampByLegs       = true;   // ride ladder steps per ride LEG (single-basket engines: CountSameDirBaskets is always 1 -> the fib ramp never stepped; demo 09-03: ten 0.02 legs)  // CELL-LOCKED
const bool RescueSuspendsStaged   = true;   // no STAGED FLOOR cuts while the rescue is armed/riding (treatment before amputation)  // CELL-LOCKED
const bool RescueBookSingle       = true;   // [S36b] run the rescue book manager (tick-arm/pin/book-exit/state-release) on SINGLE-basket engines too -- it was unreachable there (same gate S33 found for the freeze)  // CELL-LOCKED
const bool RescueLockDir          = true;   // [S36c] an armed ride keeps its direction (never re-derived from floats -> no pullback flip after a pin)  // CELL-LOCKED
//--- STATE-RELEASE OVERLAY (S31, 2026-08-24 -- fib C build P port, validated on fib C's full-tick
//    bench: PF 1.47->2.00, RF 1.83->2.96, worst episode -810->-169 at -5.7%% net; plateau-checked
//    (MinMark -200/-300 identical, cliff at -400). While a RESCUE ride is live and the book has not
//    reached its exit, track the ride's post-arm extreme vs ATR(D1,14); at the first bad state --
//    (pull>=SR_PullATR AND stale>=SR_StaleHours) OR (pos<=0 AND pull>=SR_PullATR) -- close the WHOLE
//    book at market, but ONLY while the loss is still small (>= StateReleaseMinMark). Deep books are
//    never state-released (they mostly recover); the floor stays the backstop. DEFAULT OFF.
const bool UseStateRelease       = false;  // CELL-LOCKED
const double SR_PullATR            = 0.30;    // pullback off the post-arm extreme, x ATR(D1,14)  // CELL-LOCKED
const double SR_StaleHours         = 7.0;     // hours without a new post-arm extreme  // CELL-LOCKED
const double StateReleaseMinMark   = -200.0;  // release only while book float >= this $ (0 = always)  // CELL-LOCKED
const bool SR_UsePosLeg          = true;    // include the (pos<=0 & pull) leg of the trigger  // CELL-LOCKED
//--- EPISODE TIME-CAP (S32, 2026-08-24 -- the 08-20 TIMECAP-N build, priced utility: cap-10d
//    ~ -$201/8.5mo at $3k oil scale, no new tail (floor binds first), eliminates multi-week sits.
//    Episode age = oldest open position's age (position-derived -> restart-safe). DEFAULT OFF.
const double MaxEpisodeDays        = 0.0;     // >0: close ALL positions once the oldest is this many days old  // CELL-LOCKED
//--- FREEZE HEDGE (2026-07-29): the NON-directional hedge -- neutralize the drowning book 1:1 (NOT overtake,
//    so no bet on the trend continuing = no whipsaw crush), HOLD it frozen, and RELEASE the hedge only when
//    price bounces back off the adverse extreme, letting the recovering side run home. Default OFF.
const bool UseFreezeHedge        = false;    // ON = freeze/neutralize + release-on-bounce (overrides the signal-driven ride)  // CELL-LOCKED
const double FreezeReleaseATR      = 1.5;      // release the hedge when price bounces this x ATR(D1) back from the adverse extreme  // CELL-LOCKED
//--- [S34 2026-08-27] GOLD-NATIVE FREEZE: the 07-29 freeze carried two OIL design choices verbatim, and both
//    are why it failed on gold (08-26: net -90%, eqDD 13->44%): (1) it BLOCKS ENTRIES while frozen -> gold's
//    turnover edge starves; (2) it RELEASES ON A 1.5xATR BOUNCE -> gold's adverse moves SUSTAIN, so release ->
//    re-drown -> deeper re-freeze. Two default-OFF dials:
const bool FreezeAllowEntries    = false;    // keep trading NEW baskets while a basket is frozen (needs MaxConcurrentBaskets>1 so the frozen basket keeps its own tag/exit)  // CELL-LOCKED
const int FreezeReleaseMode     = 0;        // 0 = bounce FreezeReleaseATR x ATR (oil); 1 = EXHAUSTION: release only once the adverse move is DEAD (pulled back >= SR_PullATR x ATR off its extreme AND no new extreme for >= SR_StaleHours) -- the S31 gauges as the release trigger  // CELL-LOCKED
//--- equity-DD reducer (default OFF = locked config unchanged): close a LOSING basket when D1 trend flips AGAINST it
//    (the regime change that turns a recoverable dip into a one-way bleed) -> caps the tail before the -20% floor,
//    lowering intraday equity DD so the proven engine can be sized bigger. Validate every-tick vs the $7,908 baseline.
const bool UseRegimeBasketExit   = false;  // CELL-LOCKED
//--- [S35 2026-08-28] FRIDAY GREEN-STOP -- the operator's Friday-risk regime, automated.
//    On Friday from FridayGuardHour (server), place a break-even-PLUS stop under any leg that is
//    ALREADY IN PROFIT, so a wild Friday session or a reversal into the close cannot turn a green
//    leg red. THE SAFETY RULES ARE THE POINT:
//      * GREEN LEGS ONLY -- it never touches a red position. Realizing a recoverable oil float is
//        the documented cut-class disease (6 kills: delev / melt / age-cap / state-release /
//        time-cap / rescue-cap). This lever can only protect profit, never realize a loss.
//      * SKIPPED while a RESCUE or FREEZE is armed -- those manage the WHOLE book, and stopping one
//        leg strips the structure (the fib C naked-ride-leg lesson: an individual exit on a hedged
//        book leaves the losers naked).
//      * Never loosens an existing stop; respects the broker stops level (skips if too close).
//    Offset is ATR-SCALED so it transfers across symbols per [[exit-rules-per-symbol]]:
//    0.01 x ATR(D1) is ~0.028 on oil (= the 0.029 the operator set by hand on 2026-08-28) and
//    ~0.94 on gold. FridayStopLockPct > 0 additionally locks that fraction of the leg's open profit.
//    WARNING (the operator's own 07-27 finding): a stop is NOT weekend-gap protection -- the order
//    executes on the Monday reopen at the GAP price, not at the level. It caps a live Friday session.
const bool UseFridayGreenStop    = false;   // default OFF -> every locked config byte-identical  // CELL-LOCKED
const int FridayGuardHour       = 16;      // server hour from which the guard acts on Fridays  // CELL-LOCKED
const double FridayStopOffsetATR   = 0.01;    // break-even-plus offset as a fraction of ATR(D1)  // CELL-LOCKED
const double FridayStopLockPct     = 0.0;     // >0 = also lock this fraction of the leg's open profit  // CELL-LOCKED
//--- [S35b 2026-08-28] FRIDAY BANK (the BOOK-level version -- built after the per-leg stop tested
//    NEGATIVE: BE-stopping individual green legs DISMANTLES a hedged book. 2026-01-09 specimen: five
//    green rescue BUYs stopped at BE in six minutes, leaving the red side naked -> gross profit -45%
//    and the largest single loss GREW. The green legs are LOAD-BEARING.)
//    This version acts on the WHOLE BOOK and only when the whole book is green: at the Friday cutoff,
//    if total float >= FridayBankMinUSD, close everything and bank it. Structurally it can never
//    realize a red book and can never leave a naked leg -- it is the 08-10 weekend spec's state (1)
//    ("book green/~flat -> FLATTEN & BANK, free + zero gap risk"), which is the branch the operator
//    executes by hand.
const bool UseFridayBank         = false;   // default OFF  // CELL-LOCKED
const int FridayBankHour        = 20;      // server hour on Friday to bank a green book  // CELL-LOCKED
const double FridayBankMinUSD      = 0.0;     // only bank when total book float >= this  // CELL-LOCKED
//--- Break-even SL + grid guards
const bool UseBreakEvenSL        = true;  // CELL-LOCKED
const double BreakEvenTriggerR     = 0.7;  // CELL-LOCKED
const double MaxBasketLotsTotal     = 0.30;  // CELL-LOCKED
const bool SkipGridAfterSL       = true;  // CELL-LOCKED
const int SkipGridAfterSLHours  = 4;  // CELL-LOCKED
//--- Misc
const string CommentText           = "GridStat";  // CELL-LOCKED
const int MagicSeed             = 0;       // 0 = auto-hash from symbol+period (matches MT4 scheme)  // CELL-LOCKED

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
string   pSkip[MAX_PENDING];       // [S28] gate-skip reason ("" = passed) -- ALL fires get barrier outcomes now
string   pState[MAX_PENDING];      // [S30] MKT-STATE (UP/DOWN) at signal time -> mkt_state column
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
bool     g_outOfSession = false; // fib C overlay: out-of-session processing exists ONLY for the rescue
double   g_freezeExtreme = 0.0; // freeze hedge: the adverse price extreme while frozen (release = bounce off it)
datetime g_freezeExtremeTime = 0; // [S34] when the adverse extreme was last set (exhaustion release = stale off it)
int      g_freezeDir = -1;      // freeze hedge: direction of the FROZEN (losing) side, -1 = not frozen
double   g_freezeAnchor = 0.0;  // freeze hedge anti-churn: after a release, re-freeze only at a NEW adverse extreme
bool     g_crashDown = false;   // crash-guard v2 state: sticky "falling knife" (blocks BUYs) until a confirmed turn up
bool     g_crashUp   = false;   // crash-guard v2 state: sticky "vertical spike" (blocks SELLs) until a confirmed turn down
double   g_crashDownAnchor = 0; // after a turn-exit: re-enter DOWN state only on a NEW breakdown below this (the basing low)
double   g_crashUpAnchor   = 0; // after a turn-exit: re-enter UP state only on a NEW breakout above this (the basing high)
                                // (research lever: not restart-safe; harden with a comment tag if promoted)
bool     g_rideArm = false;         // [sub-8] tick-armed rescue state: trigger crossed at SOME tick; next signal rides
double   g_rescueDeepest = 0.0;     // [sub-8] deepest book float this rescue (for RescueTargetPctDeepest)
datetime g_rescueCooldownUntil = 0; // [sub-8] no re-arm before this time (RescueRearmCooldownBars)
double   g_srArmPrice = 0, g_srExt = 0;  // [S31] state-release: post-arm extreme tracking
datetime g_srExtTime = 0;

//+------------------------------------------------------------------+
int OnInit()
{

   Print("GRIDSTAT TEST CELL GOLD HPIN -- zero-input; deltas vs SF12 lock: LotSize=0.01, ProfitTargetUSD=50.0, MaxCompoundScale=2, RescueBookTargetUSD=20.0, RescueMaxBaskets=5, RescueOnDrawdownPct=5.0, RescueTickArm=true, RescueTargetPctDeepest=10.0, RescueBookSingle=true, RescueLockDir=true, RescueRearmCooldownBars=288, RescueImmediateLeg=true, RescueImmediateRatio=1.0, RescueRampByLegs=true, RescueSuspendsStaged=true");
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
                   "adx","ma_angle","runup","period_used","bars_in_band","mkt_state");
         FileClose(fh);
      }
      // [S28] ALL-FIRES research file: every in-session Goldminer fire incl. gate-SKIPPED ones,
      // with the skip reason as a trailing column. The production research CSV above stays
      // byte-identical (gate-passers only) -- consumers/promote path untouched.
      int fh2 = FileOpen(AllFiresFile(), FILE_WRITE|FILE_CSV|FILE_COMMON|FILE_ANSI, ',');
      if(fh2 != INVALID_HANDLE)
      {
         FileWrite(fh2, "setup_key","entry_time","entry_price","direction",
                   "upper_barrier","lower_barrier","time_barrier","atr_at_entry",
                   "barrier_hit","r_multiple","outcome_time","mfe_r","big_move","wpr",
                   "adx","ma_angle","runup","period_used","bars_in_band","skip_reason","mkt_state");
         FileClose(fh2);
      }
      Print("CONFIG | [S28] all-fires shadow log -> ", AllFiresFile());
   }
   if(!StatsCollectionMode)
   {
      MagicNumber = (MagicSeed != 0) ? MagicSeed : GenerateMagic("GridStat", _Symbol, (int)Period());
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
      Print("CONFIG | S38-VELOCITYGUARD | UseVelocityGuard=", UseVelocityGuard, " pct=", DoubleToString(VelocityGuardPct,1), " days=", VelocityGuardDays);
      Print("CONFIG | S37-RANGEGUARD | UseRangeGuard=", UseRangeGuard, " pct=", DoubleToString(RangeGuardPct,1), " days=", RangeGuardDays);
      Print("CONFIG | S36-PINRIDE | RescueBookSingle=", RescueBookSingle, " RescueLockDir=", RescueLockDir, " RescueImmediateLeg=", RescueImmediateLeg, " ratio=", DoubleToString(RescueImmediateRatio,2),
            " RescueRampByLegs=", RescueRampByLegs, " RescueSuspendsStaged=", RescueSuspendsStaged);
      Print("CONFIG | SUB8-RECAL | RescueTickArm=", RescueTickArm,
            " RescueTargetPctDeepest=", DoubleToString(RescueTargetPctDeepest,0),
            "% RescueRearmCooldownBars=", RescueRearmCooldownBars);
      Print("CONFIG | S31 STATE-RELEASE | UseStateRelease=", UseStateRelease,
            " pull>=", DoubleToString(SR_PullATR,2), "xATR14 stale>=", DoubleToString(SR_StaleHours,1),
            "h minMark=", DoubleToString(StateReleaseMinMark,0), " posLeg=", SR_UsePosLeg);
      Print("CONFIG | S32 TIMECAP | MaxEpisodeDays=", DoubleToString(MaxEpisodeDays,1), (MaxEpisodeDays>0?" (episode force-close)":" (off)"));
      Print("CONFIG | S34 GOLD-FREEZE | FreezeAllowEntries=", FreezeAllowEntries, " FreezeReleaseMode=", FreezeReleaseMode, (FreezeReleaseMode==1?" (EXHAUSTION: pull>=SR_PullATR & stale>=SR_StaleHours)":" (bounce)"));
      Print("CONFIG | S35 FRIDAY GREEN-STOP | UseFridayGreenStop=", UseFridayGreenStop,
            " hour=", FridayGuardHour, " offsetATR=", DoubleToString(FridayStopOffsetATR,3),
            " lockPct=", DoubleToString(FridayStopLockPct,2), " (green legs only; skipped while rescue/freeze armed)");
      {
         int _szh = FileOpen(SizingCSVFile, FILE_READ|FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_CSV|FILE_COMMON|FILE_ANSI, ',');
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
      Print("CONFIG | [S30] UseRegimeGate=", UseRegimeGate, " RegimeGateMinN=", RegimeGateMinN,
            " (regime-split WR when the DB carries mkt_state; thin cell -> all-regime fallback)");
   }
   return(INIT_SUCCEEDED);
}
string SigFile() { return "gridstat_signals_" + _Symbol + ".csv"; }
void LogSignal(int dir, string key, double wpr, double adx, double ang, bool bull, double wr, int ns, string decision)
{
   if(!UseSignalLog) return;
   if(MQLInfoInteger(MQL_TESTER)) return;   // S39: tester runs never pollute the shared live signal log
   int h = FileOpen(SigFile(), FILE_READ|FILE_WRITE|FILE_CSV|FILE_COMMON|FILE_ANSI, ',');
   if(h == INVALID_HANDLE) return;
   FileSeek(h, 0, SEEK_END);
   FileWrite(h, TimeToString(TimeCurrent(), TIME_DATE|TIME_MINUTES),
             (dir==ORDER_TYPE_BUY ? "BUY" : "SELL"), key,
             DoubleToString(wpr,1), DoubleToString(adx,1), DoubleToString(ang,1),
             (bull ? "1" : "0"), DoubleToString(wr,2), IntegerToString(ns), decision,
             IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN)));   // S39: 11th column = writer
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

// [S30] MKT-STATE: D1 5-day momentum sign (identical to the register's wrUp/wrDown axis) --
// the regime dimension of the 4-layer doctrine, computable at entry with zero lag assumptions.
// Binary v1 (UP/DOWN); the crash/spike state machine stays its own separate layer.
string MktState()
{
   double c1 = iClose(_Symbol, PERIOD_D1, 1), c6 = iClose(_Symbol, PERIOD_D1, 6);
   if(c1 <= 0 || c6 <= 0) return("UP");
   return((c1 >= c6) ? "UP" : "DOWN");
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
// [S28] derive the all-fires filename from StatsCSVFile: "x.csv" -> "x_allfires.csv"
string AllFiresFile()
{
   string base = StatsCSVFile;
   StringReplace(base, ".csv", "");
   return(base + "_allfires.csv");
}

void AddPendingSignal(string key, int dir, bool bigMove, double wpr,
                      double adx, double maAngle, double runup, int periodUsed, int barsInBand,
                      string skipReason, string mktState)
{
   if(pCount >= MAX_PENDING) return;
   if(skipReason != "" && MQLInfoInteger(MQL_OPTIMIZATION)) return;   // [S28] optimizations track gate-passers only (metric + speed unchanged)
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
   pSkip[pCount]=skipReason;
   pState[pCount]=mktState;
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
      pSkip[i]=pSkip[i+1];
      pState[i]=pState[i+1];
   }
   pCount--;
}

void WriteOutcome(int idx, string hit, double r)
{
   if(pSkip[idx]=="") g_shadowTotalR += r;        // [S28] optimizer metric stays GATE-PASSERS ONLY (unchanged semantics)
   if(MQLInfoInteger(MQL_OPTIMIZATION)) return;   // optimization: accumulate R only, no per-row CSV (avoids agent file contention)
   if(pSkip[idx]=="")                             // [S28] production research row: gate-passers only, byte-identical to pre-S28
   {
      int fh = FileOpen(StatsCSVFile, FILE_READ|FILE_WRITE|FILE_CSV|FILE_COMMON|FILE_ANSI, ',');
      if(fh != INVALID_HANDLE)
      {
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
            IntegerToString(pBarsInBand[idx]),
            pState[idx]);
         FileClose(fh);
      }
   }
   // [S28] all-fires row: EVERY fire (passed + skipped) with the skip reason as the trailing column
   int fh2 = FileOpen(AllFiresFile(), FILE_READ|FILE_WRITE|FILE_CSV|FILE_COMMON|FILE_ANSI, ',');
   if(fh2 == INVALID_HANDLE) return;
   FileSeek(fh2, 0, SEEK_END);
   FileWrite(fh2,
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
      IntegerToString(pBarsInBand[idx]),
      (pSkip[idx]=="" ? "PASS" : pSkip[idx]),
      pState[idx]);
   FileClose(fh2);
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
   else { ManageBreakEvenSL(); ManageGrid(); ManageFridayGreenStop(); ManageFridayBank(); }
   if(!newBar) return;

   if(UseSessionFilter)
   {
      int hr = BarHour(TimeCurrent());
      bool inSess = (hr >= SessionStartHour && hr < SessionEndHour);
      // fib C overlay (2026-08-05): the recovery hedge must work OUT of session -- the Aug-5 melt-up ran
      // 03:00-08:00 server and fib C's live hedge legs fired 03:30/05:25 while this gate slept. Out of
      // session, processing continues ONLY so the rescue can arm/ride; normal entries stay blocked below.
      g_outOfSession = !inSess;
      if(!inSess)
      {
         bool rescueLive = (g_rescueDir >= 0) ||
                           (RescueOnDrawdownPct > 0 && PortfolioFloat() <= -RescueOnDrawdownPct/100.0 * Bal_());
         if(!rescueLive) return;
      }
   }
   else g_outOfSession = false;

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
   bool rideRamp = false;   // fib C overlay: loss-gated ride legs ramp up the fib ladder (the OVERTAKE)
   if(UseFreezeHedge && g_freezeDir >= 0 && !FreezeAllowEntries) return;   // FROZEN: no new entries (unless [S34] FreezeAllowEntries)
   bool bookDeep = (!UseFreezeHedge && RescueOnDrawdownPct > 0 && PortfolioFloat() <= -RescueOnDrawdownPct/100.0 * Bal_());
   if(RescueTickArm) bookDeep = g_rideArm;   // [sub-8] the tick-armed state replaces signal-time sampling (fib C parity)
   else if(RescueRearmCooldownBars > 0 && TimeCurrent() < g_rescueCooldownUntil) bookDeep = false;  // cooldown composes standalone too
   if((g_rescueDir >= 0 || bookDeep) && PortfolioFloat() < RescueBookTargetUSD)
   {
      int loseDir  = (SameDirFloat(ORDER_TYPE_BUY) <= SameDirFloat(ORDER_TYPE_SELL)) ? (int)ORDER_TYPE_BUY : (int)ORDER_TYPE_SELL;
      int hedgeDir = (loseDir == (int)ORDER_TYPE_BUY) ? (int)ORDER_TYPE_SELL : (int)ORDER_TYPE_BUY;
      // [S36c] RIDE THE ARMED DIRECTION. With a 1:1 pin the two sides float symmetrically, so the float-based
      // loser flips on every pullback and the ride starts selling the dip it just hedged (09-03 smoke test:
      // pin BUY 0.04 -> pullback -> ride SELLS 0.03/0.05/0.08 into the overnight squeeze = -$418). Lock it.
      if(RescueLockDir && g_rescueDir >= 0)
      { hedgeDir = g_rescueDir; loseDir = (hedgeDir == (int)ORDER_TYPE_BUY) ? (int)ORDER_TYPE_SELL : (int)ORDER_TYPE_BUY; }
      // REGIME GATE: only arm the ride in a CONFIRMED move against the drowning side (fib C's win condition);
      // an already-armed ride (g_rescueDir>=0) continues to completion regardless.
      bool stateOK = !RescueOnlyInCrashState || g_rescueDir >= 0 ||
                     (loseDir == (int)ORDER_TYPE_SELL && g_crashUp) ||
                     (loseDir == (int)ORDER_TYPE_BUY  && g_crashDown);
      if(stateOK)
      {
         dir    = hedgeDir;   // ride the trend: force the winning (opposite-of-loser) side, override the signal's own dir
         rescue = true;
         rideRamp = true;     // fib C ladder on the ride legs (1,1,2,3,5...) so the winning side OVERTAKES
      }
   }
   else if(AllowOppositeWhenDeep &&
      PortfolioFloat() <= -OppositeWhenDeepPct/100.0 * Bal_() &&
      SameDirFloat(dir) >= 0)
      rescue = true;

   if(g_outOfSession && !rescue) return;   // out-of-session processing exists ONLY for the rescue (fib C parity)

   bool crashSell = UseCrashStateSells && !rescue &&
                    ((g_crashDown && dir==ORDER_TYPE_SELL) || (g_crashUp && dir==ORDER_TYPE_BUY));
   if(!rescue && !crashSell && UseDailyTrendFilter && ((dir==ORDER_TYPE_BUY && !bull) || (dir==ORDER_TYPE_SELL && bull)))
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
         double upPct   = CrashGuardPct;      // spike-UP threshold; halved while the cross-market flag is hot
         if(StringLen(CrossCrashSymbol) > 0 && GlobalVariableCheck("GSXS_DN_"+CrossCrashSymbol) &&
            GlobalVariableGet("GSXS_DN_"+CrossCrashSymbol) > 0.5)
            upPct *= 0.5;
         // anchors reset once price is back inside the normal band (episode fully over)
         if(px2 >= recHigh*(1.0-CrashGuardPct/100.0)) g_crashDownAnchor = 0;
         if(px2 <= recLow *(1.0+upPct/100.0)) g_crashUpAnchor   = 0;
         // ENTER crash state on the distance trigger (a real fall/spike, not a routine dip);
         // after a turn-exit, ONLY a NEW breakdown below the basing low re-enters (anti-churn anchor)
         if(!g_crashDown && px2 < recHigh*(1.0-CrashGuardPct/100.0) &&
            (g_crashDownAnchor==0 || px2 < g_crashDownAnchor))
            { g_crashDown=true; Print("CRASH-STATE DOWN entered (", DoubleToString(px2,2), " << ", DoubleToString(recHigh,2), "): BUYs off until a turn"); }
         if(!g_crashUp && px2 > recLow*(1.0+upPct/100.0) &&
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
            if(g_crashUp   && px2 <= recLow *(1.0+upPct/100.0)) g_crashUp=false;
         }
         if(skip=="" && !rescue && !CrashGuardGateOnly &&
            ((dir==ORDER_TYPE_BUY && g_crashDown) || (dir==ORDER_TYPE_SELL && g_crashUp)))
            skip = "crashState";
         GlobalVariableSet("GSXS_DN_"+_Symbol, g_crashDown ? 1.0 : 0.0);   // publish for cross-market consumers
         GlobalVariableSet("GSXS_UP_"+_Symbol, g_crashUp   ? 1.0 : 0.0);
      }
   }

   string mstate = MktState();                                          // [S30] regime axis at signal time
   double wr=0, wrS=0; int ns=0, nsS=0;
   bool known = LookupSetupStats(key, wr, ns, mstate, wrS, nsS);        // looked up for the log too

   if(StatsCollectionMode)
   {
      // [S28] ALL fires get barrier outcomes now (skip reason travels with the row -> _allfires.csv);
      // gate-passers alone still populate the production research CSV + the OnTester R metric.
      AddPendingSignal(key, dir, bigMove, wpr, adx, maAngle, runup, periodUsed, barsInBand, skip, mstate);
      LogSignal(dir, key, wpr, adx, maAngle, bull, wr, ns, (skip=="" ? "SHADOW_LOGGED" : "SHADOW_SKIP:"+skip));
      return;
   }

   // ===== STAGE 2: TRADE ENTRY (gates in the same order; behaviour unchanged, just records the reason) =====
   if(skip=="" && !rescue && !crashSell && StatsFilterEnabled)
   {
      // [S30] REGIME-GATED WR: when the promoted DB carries mkt_state and this fingerprint's cell in
      // the CURRENT regime is thick enough, judge it on THAT win rate (SELL|HR_OVL|ATR_EXP: 81% DOWN
      // = admitted / ~50% UP = blocked -- the data does both, no hand-coded rule). Thin cell -> fallback.
      bool useState = (UseRegimeGate && nsS >= RegimeGateMinN);
      double effWR  = useState ? wrS : wr;
      if(!known)                skip = "setupUnknown";
      else if(ns < MinSamples)  skip = "lowSamples(n="+IntegerToString(ns)+")";
      else if(effWR < MinWinRate)
         skip = (useState ? "regimeWR("+mstate+" " : "lowWinRate(")
                + DoubleToString(effWR,2)+"<"+DoubleToString(MinWinRate,2)+")";
   }
   if(skip=="" && !rescue && UseSignalStrengthGate)        // cut the weak signals (barely past the band)
   {
      double gmUp = (GM_UpperBand > 0) ? GM_UpperBand : (grisk + 67);
      double gmLo = (GM_LowerBand > 0) ? GM_LowerBand : (33 - grisk);
      double pen  = (dir==ORDER_TYPE_BUY) ? (wpr - gmUp) : (gmLo - wpr);   // penetration past the band
      if(pen < SignalStrengthMin) skip = "weakSignal(pen="+DoubleToString(pen,1)+"<"+DoubleToString(SignalStrengthMin,1)+")";
   }
   if(skip=="" && !rescue && IsOverextended()) skip = "overextended";
   if(skip=="" && !rescue && UseVelocityGuard)   // [S38] sit out the storm: no new baskets in a fast multi-day move
   {
      double vgC[];
      if(CopyClose(_Symbol, PERIOD_D1, VelocityGuardDays, 1, vgC)==1 && vgC[0] > 0)
      {
         double vgVel = (Bid_()/vgC[0] - 1.0)*100.0;
         if(MathAbs(vgVel) >= VelocityGuardPct) skip = "velocity("+DoubleToString(vgVel,1)+"%/"+IntegerToString(VelocityGuardDays)+"d)";
      }
   }
   if(skip=="" && !rescue && UseRangeGuard)      // [S37] don't buy the top of the range, don't sell the bottom of it
   {
      double rgH[], rgL[];
      if(CopyHigh(_Symbol, PERIOD_D1, 1, RangeGuardDays, rgH)==RangeGuardDays &&
         CopyLow(_Symbol,  PERIOD_D1, 1, RangeGuardDays, rgL)==RangeGuardDays)
      {
         double rgHigh=rgH[0], rgLow=rgL[0];
         for(int rgi=1; rgi<RangeGuardDays; rgi++){ if(rgH[rgi]>rgHigh) rgHigh=rgH[rgi]; if(rgL[rgi]<rgLow) rgLow=rgL[rgi]; }
         double rgPx = Bid_();
         if(dir==ORDER_TYPE_BUY  && rgPx >= rgHigh*(1.0 - RangeGuardPct/100.0)) skip = "rangeTop("+DoubleToString((rgPx/rgHigh-1)*100,1)+"%)";
         if(dir==ORDER_TYPE_SELL && rgPx <= rgLow *(1.0 + RangeGuardPct/100.0)) skip = "rangeBottom(+"+DoubleToString((rgPx/rgLow-1)*100,1)+"%)";
      }
   }
   double szMult = LookupSizing(key);                      // 1.0 if table off; 0 = negative/unknown setup
   if(skip=="" && !rescue && !crashSell && UseSizingTable && szMult <= 0) skip = "sizingZero";  // hedge + crash-state legs bypass
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
             (skip=="" ? (rescue ? "TRADE(rescue)" : (crashSell ? "TRADE(crashSell)" : "TRADE")) : "SKIP:"+skip));
   if(skip != "") return;                                  // any failed gate -> no trade (same as before)
   if(rescue) Print("OPPOSITE-WHEN-DEEP: opening ", (dir==(int)ORDER_TYPE_BUY?"BUY":"SELL"),
                    " rescue basket (book float ", DoubleToString(PortfolioFloat(),2), ")");

   g_clusterSizeMult = (rescue || crashSell || szMult <= 0) ? 1.0 : szMult;   // hedge/crash-state legs open at base size
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
   int lotLevel = 0;
   if(rideRamp) lotLevel = RescueRampByLegs ? CountSameDirLegs(dir) : CountSameDirBaskets(dir);   // fib C's overtake: each ride leg steps up the ladder ([S36] per LEG: baskets are always 1 in single mode)
   if(UseRiskNormalizedLots) { lot = RiskNormalizedLot(lotLevel); if(lot < 0) return; }
   else                       { lot = CalculateLot(lotLevel); }
   lot = NormalizeDouble(lot * g_clusterSizeMult, 2);      // per-setup bet sizing (1.0 when table off)
   double minLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   if(lot < minLot) lot = minLot;
   OpenSimpleSLTP(dir, lot, key, newBid, rideRamp);   // ride legs go naked (book-exit managed, fib C parity)
   if(rescue)
   {
      if(g_rescueDir < 0){ g_srArmPrice = Bid_(); g_srExt = g_srArmPrice; g_srExtTime = TimeCurrent(); }  // [S31] fresh arm -> start state tracking
      g_rescueDir = dir; g_rescuePeak = 0.0;   // arm the book-level rescue choreography (S24)
   }
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

// [S36] ride LEGS in one direction (the PIN excluded -> the first signal leg is ladder step 0)
int CountSameDirLegs(int dir)
{
   int n = 0;
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(tk==0 || !PositionSelectByTicket(tk)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      string cmt = PositionGetString(POSITION_COMMENT);
      if(StringFind(cmt, "_HEDGE") >= 0 || StringFind(cmt, "_FRZ") >= 0 || StringFind(cmt, "_PIN") >= 0) continue;
      if((int)PositionGetInteger(POSITION_TYPE) != dir) continue;
      n++;
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
// [S30] also returns the fingerprint's win rate IN curState (mkt_state column) when the DB
// carries it; a DB without the column -> samplesState=0 -> callers fall back to all-regime.
bool LookupSetupStats(string setupKey, double &winRate, int &samples,
                      string curState, double &winRateState, int &samplesState)
{
   winRateState=0; samplesState=0;
   int fh = FileOpen(StatsCSVFile, FILE_READ|FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_CSV|FILE_COMMON|FILE_ANSI, ',');
   if(fh == INVALID_HANDLE) { winRate=0; samples=0; return false; }
   int ncol=0, rIdx=-1, sIdx=-1;
   while(!FileIsEnding(fh))                       // header row -> column count + named indices
   {
      string c = FileReadString(fh);
      if(c == "r_multiple") rIdx = ncol;
      if(c == "mkt_state")  sIdx = ncol;
      ncol++;
      if(FileIsLineEnding(fh)) break;
   }
   if(rIdx < 0 || ncol <= 0) { FileClose(fh); winRate=0; samples=0; return false; }
   int wins=0, total=0, winsS=0, totalS=0;
   while(!FileIsEnding(fh))
   {
      string key=""; double r=0; string st=""; bool any=false;
      for(int c=0; c<ncol && !FileIsEnding(fh); c++)
      {
         string cell = FileReadString(fh); any=true;
         if(c==0)    key = cell;
         if(c==rIdx) r   = StringToDouble(cell);
         if(c==sIdx) st  = cell;
      }
      if(!any) break;
      if(key == setupKey)
      {
         total++; if(r > 0) wins++;
         if(sIdx >= 0 && st == curState) { totalS++; if(r > 0) winsS++; }
      }
   }
   FileClose(fh);
   samples = total;
   samplesState = totalS;
   if(totalS > 0) winRateState = (double)winsS / (double)totalS;
   if(total == 0) { winRate=0; return false; }
   winRate = (double)wins / (double)total;
   return true;
}

// per-setup size multiplier from SizingCSVFile (cols: setup_key,size_mult,...). 1.0 if table off.
// Returns 0 for negative-expectancy setups AND for unknown setups (=> caller skips the trade).
double LookupSizing(string setupKey)
{
   if(!UseSizingTable) return 1.0;
   int fh = FileOpen(SizingCSVFile, FILE_READ|FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_CSV|FILE_COMMON|FILE_ANSI, ',');
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
void OpenSimpleSLTP(int dir, double lot, string setupKey, int bid=-1, bool naked=false)
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
   if(naked) { sl = 0; tp = 0; }   // fib C parity: ride/hedge legs carry NO SL/TP -- the BOOK exit (+target/trail) manages them
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

//--- [S35b] Friday BANK: bank the WHOLE book on Friday if it is green. Never realizes a red book,
//    never leaves a naked leg (the defect that killed the per-leg version).
void ManageFridayBank()
{
   if(!UseFridayBank) return;
   MqlDateTime bdt; TimeToStruct(TimeCurrent(), bdt);
   if(bdt.day_of_week != 5) return;
   if(bdt.hour < FridayBankHour) return;
   int n = 0;
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(tk==0 || !PositionSelectByTicket(tk)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      n++;
   }
   if(n == 0) return;
   double bk = PortfolioFloat();
   if(bk < FridayBankMinUSD) return;            // red or not green enough -> LEAVE IT ALONE
   CloseEverything("FRIDAY BANK book +" + DoubleToString(bk,2));
   g_peakBasketFloat = 0.0; g_rescueDir = -1; g_freezeDir = -1;
}

//--- [S35] Friday green-stop: protect PROFIT on Fridays, never realize a red leg. See the input block.
void ManageFridayGreenStop()
{
   if(!UseFridayGreenStop) return;
   MqlDateTime fdt; TimeToStruct(TimeCurrent(), fdt);
   if(fdt.day_of_week != 5) return;                     // Friday only (server clock)
   if(fdt.hour < FridayGuardHour) return;
   if(g_rescueDir >= 0 || g_freezeDir >= 0) return;     // book-managed: never strip a leg

   double atr = ReadBuf(hATR_D1, 0, 1);
   if(atr <= 0) return;
   double off      = FridayStopOffsetATR * atr;
   double stopsLvl = (double)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * point;
   int    dgt      = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);

   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(tk==0 || !PositionSelectByTicket(tk)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetDouble(POSITION_PROFIT) <= 0) continue;   // GREEN ONLY -- never cut a red leg
      long   ptype = PositionGetInteger(POSITION_TYPE);
      double op    = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl    = PositionGetDouble(POSITION_SL);
      double tp    = PositionGetDouble(POSITION_TP);
      double vol   = PositionGetDouble(POSITION_VOLUME);
      double cur   = (ptype==POSITION_TYPE_BUY) ? Bid_() : Ask_();
      double want;
      if(ptype == POSITION_TYPE_BUY)
      {
         want = op + off;
         if(FridayStopLockPct > 0) want = MathMax(want, op + FridayStopLockPct*(cur-op));
         if(want >= cur - stopsLvl) continue;                 // too close to market to place
         if(sl != 0 && sl >= want)  continue;                 // never loosen an existing stop
      }
      else
      {
         want = op - off;
         if(FridayStopLockPct > 0) want = MathMin(want, op - FridayStopLockPct*(op-cur));
         if(want <= cur + stopsLvl) continue;
         if(sl != 0 && sl <= want)  continue;
      }
      want = NormalizeDouble(want, dgt);
      if(trade.PositionModify(tk, want, tp))
         PrintFormat("FRIDAY GREEN-STOP: #%I64u %s %.2f @ %.*f -> SL %.*f (locks +%.2f)",
                     tk, (ptype==POSITION_TYPE_BUY ? "BUY" : "SELL"), vol, dgt, op, dgt, want,
                     MathAbs(want-op) * vol * SymbolInfoDouble(_Symbol, SYMBOL_TRADE_CONTRACT_SIZE));
   }
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
//--- [S33 2026-08-26] FREEZE HEDGE extracted from the multi-basket path so SINGLE-BASKET engines
//    (gold/silver run MaxConcurrentBaskets=1) can use it too. Before this, ManageGrid delegated to
//    ManageOneBasket and RETURNED before reaching the freeze code, so the freeze was structurally
//    unreachable on gold at ANY trigger (8/5/3%% byte-identical, zero FREEZE lines -- journal-verified).
//    Body = the 07-29 block VERBATIM; its two bare returns become `return true` = frozen, stop managing.
//    Guarded by UseFreezeHedge -> OFF = byte-identical everywhere.
bool ManageFreezeHedge()
{
   if(!(UseFreezeHedge && RescueOnDrawdownPct > 0)) return false;
   // ---- FREEZE HEDGE (2026-07-29): neutralize 1:1 (tag _FRZ), HOLD flat, RELEASE the hedge legs on a
   //      confirmed bounce (FreezeReleaseATR x ATR(D1) off the adverse extreme) so the recovering side
   //      runs home. Never net-directional -> nothing to crush. Book-exit at +target still applies while frozen.
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
               g_freezeDir = loseDir; g_freezeExtreme = px; g_freezeExtremeTime = TimeCurrent();
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
         { if(px < g_freezeExtreme) { g_freezeExtreme = px; g_freezeExtremeTime = TimeCurrent(); } bounce = (px >= g_freezeExtreme + FreezeReleaseATR*atrD1f); }
         else                                          // frozen SHORTS: extreme = the high; release on a fall back
         { if(px > g_freezeExtreme) { g_freezeExtreme = px; g_freezeExtremeTime = TimeCurrent(); } bounce = (px <= g_freezeExtreme - FreezeReleaseATR*atrD1f); }
         if(FreezeReleaseMode == 1 && atrD1f > 0)     // [S34] EXHAUSTION release: the adverse move must be measurably dead
         {
            double fzPull  = MathAbs(px - g_freezeExtreme) / atrD1f;                 // pulled back off the adverse extreme
            double fzStale = (double)(TimeCurrent() - g_freezeExtremeTime) / 3600.0;  // hours since a new adverse extreme
            bounce = (fzPull >= SR_PullATR && fzStale >= SR_StaleHours);
         }

         if(PortfolioFloat() >= RescueBookTargetUSD)   // whole book green while frozen -> bank it all
         {
            CloseEverything("FREEZE BOOK EXIT +" + DoubleToString(PortfolioFloat(),2));
            g_freezeDir = -1; g_freezeAnchor = 0.0; g_peakBasketFloat = 0.0;
            return true;
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
         if(g_freezeDir >= 0) return true;              // frozen: no other book management this tick
      }
   return false;
}

//--- [S36b 2026-09-03] RESCUE BOOK MANAGER hoisted out of the multi-basket path. The 09-03 autopsy found
//    the SAME structural gate S33 found for the freeze: ManageGrid delegates to ManageOneBasket and RETURNS
//    when MaxConcurrentBaskets<=1, so on gold/silver the tick-arm (S27), deepest tracking, the +target/trail
//    book exit (S24) and the state-release (S31) were ALL unreachable -- the demo's 09-03 rescue closed on the
//    ordinary +ProfitTargetUSD basket exit and HRES5T/HPIN3 ran byte-identical to their controls. Body = the
//    block VERBATIM (bare returns -> return true = book closed, stop managing). Multi-basket path calls it
//    unconditionally (unchanged behaviour); the single-basket path only when RescueBookSingle=true (default
//    OFF -> every locked EA byte-identical).
bool ManageRescueBook()
{
   // ---- [sub-8] TICK-ARM + deepest tracking (2026-08-07, the C1 sweep-cliff re-engineering).
   // fib C parity: fib C evaluates its trigger EVERY TICK; the signal-path sampling let gold blow
   // through the 3-7% band between signals (all sub-8 configs armed at the same signal = the cliff).
   if((g_rescueDir >= 0 || g_rideArm))
      { double pfD = PortfolioFloat(); if(pfD < g_rescueDeepest) g_rescueDeepest = pfD; }
   if(RescueTickArm && RescueOnDrawdownPct > 0 && !UseFreezeHedge)
   {
      double pfT = PortfolioFloat();
      if(!g_rideArm && g_rescueDir < 0 && TimeCurrent() >= g_rescueCooldownUntil &&
         pfT <= -RescueOnDrawdownPct/100.0 * Bal_())
      {
         g_rideArm = true; g_rescueDeepest = pfT;
         Print("RESCUE TICK-ARM: book ", DoubleToString(pfT,2));
         if(RescueImmediateLeg)
         {
            // [S36] PIN: neutralize the book at the arm, no signal needed, any hour. The ride's fib ramp
            // then overtakes on the signal path (rescue=true while g_rescueDir>=0).
            int pinLose  = (SameDirFloat(ORDER_TYPE_BUY) <= SameDirFloat(ORDER_TYPE_SELL)) ? (int)ORDER_TYPE_BUY : (int)ORDER_TYPE_SELL;
            int pinHedge = (pinLose == (int)ORDER_TYPE_BUY) ? (int)ORDER_TYPE_SELL : (int)ORDER_TYPE_BUY;
            double pinNeed = SameDirLots(pinLose) * RescueImmediateRatio - SameDirLots(pinHedge);
            double pinMin  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
            if(pinNeed >= pinMin)
            {
               double pinLot = NormalizeDouble(pinNeed, 2);
               string pinCmt = CommentText + "_PIN";
               bool pinOk = (pinHedge==ORDER_TYPE_BUY) ? trade.Buy(pinLot,_Symbol,Ask_(),0,0,pinCmt)
                                                       : trade.Sell(pinLot,_Symbol,Bid_(),0,0,pinCmt);
               if(pinOk)
               {
                  g_srArmPrice = Bid_(); g_srExt = g_srArmPrice; g_srExtTime = TimeCurrent();   // [S31] state tracking from the pin
                  g_rescueDir = pinHedge; g_rescuePeak = 0.0;   // choreography live NOW: stop feeding the loser, book exit armed
                  Print("RESCUE PIN: ", (pinHedge==ORDER_TYPE_BUY?"BUY":"SELL"), " ", DoubleToString(pinLot,2),
                        " lots x", DoubleToString(RescueImmediateRatio,2), " (book ", DoubleToString(pfT,2),
                        " pinned at arm; ride ramps on signals)");
               }
               else Print("RESCUE PIN failed err=", trade.ResultRetcode());
            }
         }
      }
      else if(g_rideArm && g_rescueDir < 0 && pfT >= 0)   // self-recovered before any ride leg -> clean disarm
      {
         g_rideArm = false; g_rescueDeepest = 0.0;
         g_rescueCooldownUntil = (datetime)(TimeCurrent() + (long)RescueRearmCooldownBars * PeriodSeconds(PERIOD_CURRENT));
         Print("RESCUE TICK-DISARM: book self-recovered before a ride leg");
      }
   }

   // ---- RESCUE BOOK EXIT (S24, fib C's RecoveryTargetUSD): while a rescue basket is open,
   // close the WHOLE book (losers + rescue) together once combined float reaches the target.
   // (guard is g_rescueDir>=0 alone -- it's armed only by a rescue path, signal-gated OR loss-gated)
   if(g_rescueDir >= 0)
   {
      // [sub-8] exit target scaled to the book being rescued: flat $40 on an 8-11-leg book = crumbs
      double effTgt = RescueBookTargetUSD;
      if(RescueTargetPctDeepest > 0 && g_rescueDeepest < 0)
         effTgt = MathMax(effTgt, (RescueTargetPctDeepest/100.0) * (-g_rescueDeepest));
      if(CountSameDirBaskets(g_rescueDir) == 0)
      {
         g_rescueDir = -1; g_rescuePeak = 0.0;                 // rescue basket(s) gone -> disarm
         g_rideArm = false; g_rescueDeepest = 0.0;
         g_rescueCooldownUntil = (datetime)(TimeCurrent() + (long)RescueRearmCooldownBars * PeriodSeconds(PERIOD_CURRENT));
      }
      else if(RescueBookTargetUSD > 0 && PortfolioFloat() >= effTgt)
      {
         double pf = PortfolioFloat();
         if(RescueBookTrailPct > 0)                            // TRAIL: ride the move, bank near the bottom
         {
            if(pf > g_rescuePeak) g_rescuePeak = pf;           // track the book's peak profit
            if(pf <= g_rescuePeak * (1.0 - RescueBookTrailPct/100.0))
            {
               CloseEverything("RESCUE TRAIL EXIT +" + DoubleToString(pf,2) + " (peak +" + DoubleToString(g_rescuePeak,2) + ", tgt " + DoubleToString(effTgt,0) + ")");
               g_rescueDir = -1; g_rescuePeak = 0.0; g_peakBasketFloat = 0.0;
               g_rideArm = false; g_rescueDeepest = 0.0;
               g_rescueCooldownUntil = (datetime)(TimeCurrent() + (long)RescueRearmCooldownBars * PeriodSeconds(PERIOD_CURRENT));
               return true;
            }
         }
         else                                                 // fixed target (original behaviour)
         {
            CloseEverything("RESCUE BOOK EXIT +" + DoubleToString(pf,2));
            g_rescueDir = -1; g_rescuePeak = 0.0; g_peakBasketFloat = 0.0;
            g_rideArm = false; g_rescueDeepest = 0.0;
            g_rescueCooldownUntil = (datetime)(TimeCurrent() + (long)RescueRearmCooldownBars * PeriodSeconds(PERIOD_CURRENT));
            return true;
         }
      }
      // ---- [S31] STATE-RELEASE (fib C build P port): while the ride is live and the trail has not
      // armed, track the ride's post-arm extreme; at the first bad state, realize the whole book --
      // but ONLY while the loss is still small. Deep books ride on; the floor stays the backstop.
      else if(UseStateRelease && g_rescuePeak <= 0.0)
      {
         int srSign = (g_rescueDir == ORDER_TYPE_BUY) ? 1 : -1;
         double srPx = Bid_();
         if(g_srArmPrice <= 0){ g_srArmPrice = srPx; g_srExt = srPx; g_srExtTime = TimeCurrent(); }  // restart-mid-rescue fallback
         if((srPx - g_srExt) * srSign > 0){ g_srExt = srPx; g_srExtTime = TimeCurrent(); }
         double srAtr = ReadBuf(hATR_D1, 0, 1);
         if(srAtr > 0)
         {
            double srPull  = (g_srExt - srPx) * srSign / srAtr;
            double srPos   = (srPx - g_srArmPrice) * srSign / srAtr;
            double srStale = (double)(TimeCurrent() - g_srExtTime) / 3600.0;
            bool srBad = (srPull >= SR_PullATR && srStale >= SR_StaleHours) ||
                         (SR_UsePosLeg && srPos <= 0.0 && srPull >= SR_PullATR);
            double pfNow = PortfolioFloat();
            if(srBad && (StateReleaseMinMark >= 0.0 || pfNow >= StateReleaseMinMark))
            {
               CloseEverything("STATE RELEASE " + DoubleToString(pfNow,2) + " (pull " + DoubleToString(srPull,2) +
                               " stale " + DoubleToString(srStale,1) + "h pos " + DoubleToString(srPos,2) + ")");
               g_rescueDir = -1; g_rescuePeak = 0.0; g_peakBasketFloat = 0.0;
               g_rideArm = false; g_rescueDeepest = 0.0;
               g_srArmPrice = 0; g_srExt = 0; g_srExtTime = 0;
               g_rescueCooldownUntil = (datetime)(TimeCurrent() + (long)RescueRearmCooldownBars * PeriodSeconds(PERIOD_CURRENT));
               return true;
            }
         }
      }
   }

   return false;
}

void ManageGrid()
{
   int maxB = (MaxConcurrentBaskets < 1) ? 1 : MaxConcurrentBaskets;
   if(maxB <= 1)
   {
      if(ManageFreezeHedge()) return;              // [S33] gold/silver get the freeze organ too (OFF -> unchanged)
      if(RescueBookSingle && ManageRescueBook()) return;   // [S36b] tick-arm / pin / book-exit / state-release for single-basket engines (OFF -> unchanged)
      ManageOneBasket(-1); return;                 // untagged single pool = original behaviour, byte-for-byte
   }

   // ---- [S32] EPISODE TIME-CAP: whatever the book's shape, realize it at day N -- the
   // priced smoother (no multi-week sits; the floor still binds first on fast disasters).
   if(MaxEpisodeDays > 0)
   {
      datetime oldest = 0;
      for(int ti=PositionsTotal()-1; ti>=0; ti--)
      {
         ulong ttk = PositionGetTicket(ti);
         if(ttk==0 || !PositionSelectByTicket(ttk)) continue;
         if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
         if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
         datetime ot = (datetime)PositionGetInteger(POSITION_TIME);
         if(oldest == 0 || ot < oldest) oldest = ot;
      }
      if(oldest > 0 && (double)(TimeCurrent() - oldest) >= MaxEpisodeDays * 86400.0)
      {
         CloseEverything("EPISODE TIMECAP day " + DoubleToString((double)(TimeCurrent()-oldest)/86400.0,1) +
                         " book " + DoubleToString(PortfolioFloat(),2));
         g_peakBasketFloat = 0.0;
         g_rescueDir = -1; g_rescuePeak = 0.0; g_rideArm = false; g_rescueDeepest = 0.0;
         g_freezeDir = -1;
         return;
      }
   }

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

   if(ManageFreezeHedge()) return;   // [S33] freeze (multi-basket path, unchanged position)

   if(ManageRescueBook()) return;   // [S36b] rescue book manager (multi-basket path, unchanged behaviour)

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
   // [S36d 2026-09-04 BUG FIX] flat book => the rescue state MUST end. g_rescueDir was cleared only in the
   // multi-basket branch (unreachable on single-basket engines), so after the first arm the engine stayed in
   // "rescuing" forever: every signal, in or out of session, opened a naked leg toward whichever side floated
   // worse (demo 09-03/04: 21 legs, 17 rescue lines with the book green). Disarm here, where gold DOES run.
   if(nLevels==0)
   {
      g_peakBasketFloat=0.0; g_lockArmed=false;
      if(g_rescueDir >= 0 || g_rideArm)
      {
         Print("RESCUE DISARMED: book flat");
         g_rescueDir = -1; g_rescuePeak = 0.0; g_rideArm = false; g_rescueDeepest = 0.0;
         g_srArmPrice = 0; g_srExt = 0; g_srExtTime = 0;
         g_rescueCooldownUntil = (datetime)(TimeCurrent() + (long)RescueRearmCooldownBars * PeriodSeconds(PERIOD_CURRENT));
      }
      return;
   }
   // [S36d] rescue side fully gone (its legs banked/stopped) while the loser remains -> the rescue is over too
   if(g_rescueDir >= 0 && CountSameDirBaskets(g_rescueDir) == 0)
   {
      Print("RESCUE DISARMED: no rescue-side legs remain");
      g_rescueDir = -1; g_rescuePeak = 0.0; g_rideArm = false; g_rescueDeepest = 0.0;
      g_srArmPrice = 0; g_srExt = 0; g_srExtTime = 0;
      g_rescueCooldownUntil = (datetime)(TimeCurrent() + (long)RescueRearmCooldownBars * PeriodSeconds(PERIOD_CURRENT));
   }
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
   if(UseStagedFloor && !(RescueSuspendsStaged && (g_rescueDir >= 0 || g_rideArm)) &&   // [S36] no amputation mid-treatment
      nLevels >= 2 && iTime(_Symbol, PERIOD_CURRENT, 0) != g_lastStageBar &&
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
