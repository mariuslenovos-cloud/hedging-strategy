# TRANSCRIPT EVAL 01 — Chris Kmer (Robbins World Cup, MNQ intraday auction/order-flow)

**Evaluated against the project record as of 2026-08-21.** Purpose: decide what, if anything,
earns a Python first-order pilot under the standing method (*levers get a sim before any EA
build*). Written for Claude Code to action.

**Verdict up front:** the source is a discretionary intraday index framework. Component-by-component,
**~70% of it maps onto classes this project has already measured and killed.** Re-running weaker
versions of completed tests is theatre ([[capital-boundary-doctrine]], 08-21). Three items survive
triage; one is genuinely strong because it is the only *exogenous, non-price-derived* information
source in the whole transcript.

---

## PART 1 — DEAD ON ARRIVAL (do not build, do not re-litigate)

| Kmer component | Our record that already answers it | Status |
|---|---|---|
| **Session filter** (trade only first 90 min of NY) | 08-17 EOD: `GOLD SESS14` A/B was **byte-identical to control, to the cent**. The win-rate gate already blocks every HR_LDN fingerprint → the fingerprint gate *is* the session filter, learned from data. Oil replicates the AM/PM structure. | **ANSWERED. Inert.** |
| **Entry confirmation pattern** (absorption → second-test failure → flip) | Entry-side frontier CLOSED ×7: Goldminer-Single (walk-forward + session + day-rank, meanR −0.013, FAIL), fades dead (n=336, +0.034R pre-cost), features dead ×4 (wpr/runup/ma_angle/adx all died the within-cell control), ML RED ×2, regime dead at scale (1,848 sigs, splits dissolve). | **DEAD as a gate.** See Part 2C for the one legitimate re-framing. |
| **Consecutive-loss stop / hard time-stop** | Book Guard already caps the day (−8% + equity floor), live-proven 08-19. And the weekend lever kill-test was decisive: **entry-block-only was the WORST cell (−53% net)** — blocking entries carries an unbalanced book into the next session. fib C's iron law extends to *time-based* restraints. | **DEAD. Measured-negative.** |
| **Mid-trade thesis check → BE / cut** | Cut-class death **×9**. `delev_sim.py`: 23 of 30 cuts forfeited recoveries (−$3,866) vs 7 saves (+$1,824) = **net −$2,042**. ~77% of meaningfully-red legs recover, and *that recovery is the edge.* Melt-the-anchor killed at both granularities. N3B peak-bank killed (−53%). | **DEAD.** Textbook curb-class. |
| **Effort-vs-result trailing** | Same class. Every trail/curb lever on fib C lost (N2B brake −41%, N3B −53%, N4 −59%). Gold: "ride winners" rejected 4× (melt physics — median MFE ~0.4R then gives back). | **DEAD.** |
| **1.5–2R target / prop DD geometry** | Not applicable. Exits are fixed-$100 harvest + book-level rescue. Turnover law confirmed 5×: the engine earns by **more** $100 harvests, not better ones. | **N/A.** |
| **Naive GEX *levels* (call/put wall bounces)** | No record, but the source himself only uses it for regime. Level-trading a naive-GEX print is over-trusting the data. | **Do not build.** |

### Note on the order-flow layer specifically
Kmer's confirmation module needs **real exchange bid/ask delta**. XAUUSD and SpotCrude on
Pepperstone are CFDs — the "volume" is broker tick count, not centralised traded volume. A
footprint/absorption module built on it produces confident nonsense. The only honest version
would pull **GC / CL futures** as a reference feed. Given the entry-side frontier is already
closed on seven independent tests, that data-acquisition project has a low expected payoff.
**Recommend: do not pursue.**

---

## PART 2 — WHAT SURVIVES TRIAGE

Ranked. All three must be tested as **SIZING, not GATING** ([[rigor-drives-sizing-not-gating]] —
day-rank is the precedent: gating failed 3 ways, upsizing became the first gold config improvement
since FIBC8, +15% net at *lower* eqDD).

---

### 🟢 A. GAMMA REGIME AS GOLD'S MISSING **PREVENT** LAYER — the one strong idea

**Why this is not just "dead feature dim #5":** every feature dimension this project has killed
was **derived from price** — wpr (oscillator extremity), runup, ma_angle, adx, bars_in_band, and
the S30 mkt_state (D1 5-day momentum). GEX is **exogenous**: it is derived from the options market's
open positioning, not from the gold price series. That is a categorically different information
source, and it is the only one in the entire transcript.

**Why it fits a documented hole.** The cross-EA doctrine (08-06) states plainly that gold **lacks
Layer 2 (PREVENT)**: distance-from-extreme works on oil (crashes >> noise) but *fails on gold*
(breakouts ≈ noise amplitude; the 2% guard halved profit). The queued substitute is a **velocity
spike-state** detector — but velocity is *reactive*, and the Sentinel's documented blind spot
(08-19) is exactly this: it read gold **INSIDE at vel p66 straight through the melt-up**, because
V-turns net to ~zero 3-day velocity. A vol-regime read that is **forward-looking and positioning-based**
is the natural complement.

**Mechanism fit is direct.** The whole book is short-volatility / mean-reversion:
- **Positive gamma** → dealers sell rips, buy dips → vol *suppressed* → the grid's ideal habitat.
- **Negative gamma** → dealers buy rips, sell dips → vol *amplified* → sustained one-way verticals.
That second state is precisely the Aug-4/5 melt-up (−$1,237 on GridStat gold), the Aug-5/6 whipsaw
floor (−$451 XM), and the 08-19 demo floor (−$1,306). These are not random tails — they are all
**one regime**, and the book currently has no ex-ante read on it.

**Precedent for how to build it:** identical in shape to `gold_macro_flag()` (morning_check ①b) —
an **advisory** flag, printed in the brief, appended to a history CSV, and **measured against the
episode ledger before anyone trusts it**. That discipline is already installed. Reuse it exactly.

#### Pilot (Python only, zero EA build)
```
1. Data: daily naive GEX for gold.
   - Cheapest path: GLD option chain (liquid, retrievable free). Second: CME GC options (LO/OG).
   - Compute: sum over strikes of gamma * OI * contract_multiplier, signed by the standard
     dealer-position assumption (calls long / puts short). Naive is fine — regime only.
   - Output per day: {gamma_state: POS|NEG, flip_level, net_gex, gex_percentile}
2. Join to what already exists:
   - analysis_data/episode_ledger.csv        (per-episode deepest float, budget consumed, verdict)
   - analysis_data/xauusd_m5_export.csv      (15mo M5, May-2025 → Aug-2026, live PEP feed)
   - the known floor-event dates (Apr-14, May-12, Aug-4/5, Aug-5/6, 08-19)
3. Pre-committed test:
   Do FLOOR events and KNIFE-EDGE episodes cluster in negative-gamma / low-percentile days
   at a rate materially above base rate? Report as a 2x2 + a per-state expectancy split.
4. GATE (commit before running):
   PASS = negative-gamma days carry >= 2x the floor/knife-edge rate of positive-gamma days,
          with n >= 8 events, AND the split survives on both halves of the window.
   FAIL = drop it. Do not tune. Do not lower the bar.
```

#### If it passes → how it deploys (and how it must NOT)
- **Not a gate.** The 2% distance-guard already proved that blocking gold entries halves profit,
  and run B of the FIBC overlay (guard-blocking) sat out verticals entirely for half the net.
- **As a size/compounding modulator.** The correct lever is the one the record already identifies
  as the tail governor: **`MaxCompoundScale`**. Negative-gamma regime → derate compounding scale
  by one step for new baskets. This converts a proportional tail into a smaller absolute one
  precisely in the regime that produces the tail, and it composes cleanly with the scale-covariant
  $-lever doctrine (08-14) provided every $-lever is halved in lockstep.
- **Honest caveats to state in the brief:** gold options OI is far smaller relative to futures
  volume than SPX/NDX, so dealer hedging flow dominates *less*; naive GEX ignores charm/vanna and
  dealer-position assumptions; GLD is a proxy for GC. Expect a weaker effect than the index
  literature claims. The gate above is set high for exactly this reason.

#### Free adjacent variable worth adding to the same pilot
**CFTC COT — managed-money net positioning** (gold and WTI, weekly, free). This is the direct
exogenous measure of *crowding* — i.e. "am **I** the trapped participant?", which is the inversion
of Kmer's entire thesis and the structurally correct question for a grid that becomes the trapped
side when a move sustains. Weekly granularity is coarse, but episodes run days-to-weeks, so the
resolution is adequate. Same advisory treatment, same episode-ledger validation, near-zero cost.

---

### 🟡 B. EVENT-PROXIMITY DERATE — oil first

Kmer's framework has no scheduled-catalyst module because MNQ doesn't need one. **Oil does:**
EIA crude inventories (Wed 10:30 ET), API (Tue 16:30 ET), OPEC, weekly rig count. Gold: CPI, FOMC, NFP.

**What's already answered vs what isn't.** The Candidate-B study (08-18) tested *trading* post-release
drift → killed (+$0.92/trade over 34 events, t≈0.2). **Derating around events is a different question
and is untested.** The event-timestamp machinery from that study is already built and reusable.

**The warning that shapes the design:** entry-blocking was the worst weekend-lever cell (−53%).
So this must be a **size derate, never a block**. Oil SOLID is also structurally friendlier to this
than fib C — it runs **single positions, always** (the 07-30 discovery: `MaxBasketLotsTotal=0.30`
vs risk-norm base lot 0.38-0.47 → grid legs never fire on oil), so derating a single entry has no
book-balance side effects. That is a meaningfully different mechanism from the fib C weekend result,
which is why the extrapolation is not automatic in either direction.

#### Pilot
```
1. Reuse the Candidate-B calendar builder (CPI/FOMC/NFP + EIA/API/OPEC, DST-aware ET->server).
2. Tag every episode in the SOLID control-run deals + episode_ledger.csv with
   minutes_to_nearest_tier1_event (signed).
3. Test: are net-negative episodes / worst-episode magnitudes concentrated within +/-T of events?
   Sweep T in {15, 30, 60, 120}.
4. GATE: a monotonic, both-halves-stable concentration with n >= 10 adverse episodes inside the
   window. Anything ragged = noise at this n. Drop it.
5. If PASS: implement as `EventProximityDerate` (default 1.0 = OFF), size multiplier on FIRST
   entries only, regime/rescue/crash legs untouched -- exactly the shape of the day-rank patch.
```
**Honest prior:** moderate for oil (EIA is a genuine scheduled vol event), low for gold.

---

### 🟡 C. PARTICIPATION / VOLUME AS A SIZING DIMENSION

Kmer's hard filter is `< 20,000 contracts per 5-min MNQ bar → stand down`. The absolute number is
worthless off-instrument; the **generalised form is a relative participation ratio**:
```
participation = bar_volume / rolling_median(volume, same time-of-day, N sessions)
```

**Why it is worth one afternoon despite the feature-dims graveyard:** the four dimensions that died
the within-cell control (wpr, runup, ma_angle, adx) and the fifth that died at scale (mkt_state)
were all **price-derived**. **Volume was never among them.** The current fingerprint is
`DIR | session | ATR-regime` — a volatility dimension but no *participation* dimension. Day-rank
proved a 4th dimension can survive when it captures something structurally new.

**The honest discount:** MT5 CFD "volume" is **tick count**, not traded volume. On liquid gold it
correlates acceptably with real activity, but it is broker-specific and not comparable across feeds.
This is a real fidelity haircut — state it in the result, and require the finding to reproduce on
both `xauusd_m5_export.csv` (PEP live feed) and `xm_gold_m30_export.csv` before believing it.

#### Pilot
```
1. Data already on disk: analysis_data/xauusd_m5_export.csv, spotcrude_m5_export.csv,
   gridstat_setups_gold_research.csv, and the S28 all-fires DB (~2,350 fires, Common\Files).
2. Compute participation ratio at each signal bar. Bucket into terciles/quartiles.
3. MANDATORY: the within-cell control that killed wpr/runup/angle and that day-rank survived --
   condition INSIDE each session x ATR cell. A gradient that dissolves under conditioning is a
   proxy, not a dimension.
4. Also check the entanglement day-rank had: is participation just a proxy for session? (It will
   correlate with NY hours.) If the effect vanishes within-session, it is dead.
5. If it survives: test as a SIZE MULTIPLIER on first entries (a `ParticipationSizeMult` mirroring
   `DayRankSizeMultK3`), swept for a monotonic plateau with a cliff -- the fingerprint of every
   real lever locked so far (MaxCompoundScale 3->4, FIBC8 8->7, DayRank 1.5 vs the 2.0 cliff).
```
**Honest prior:** low-moderate. Genuinely new axis; poor data fidelity; and the base rate for new
feature dimensions in this project is 1 for 6 (day-rank).

---

## PART 3 — THE ONE PROCESS IDEA WORTH TAKING

Kmer's strongest claim isn't a setup, it's **back-end optimisation**: you don't control how many
A+ setups appear; you control the unforced errors. He grades every session A/B/C on **execution
quality independent of P&L**, and treats *a winning trade taken in violation of the rules as a C* —
because it reinforces the behaviour that eventually empties the account.

Most of this is moot here — the book is automated, so there is no per-trade human execution to grade.
**But the operator layer is not automated, and the record shows it costs real money:**
- Oil: 4 of 5 completed baskets **hand-closed at +$1–$6 against a +$100 target** (07-21).
- Aug-5: two manual closes, **−$279**.
- 08-05: hand-closed drowned legs, −$550 (magic 0).
- The documented counter-lesson: *"manual cutting = the documented interference mistake."*

There is already `analysis_data/fingerprint_decisions.csv` for fingerprint lifecycle actions.
**Extend the same pattern to an operator-action ledger** — every manual intervention (hand-close,
AutoTrading off, config change outside the manifest, stand-down) logged with: timestamp, action,
stated rationale, the machine's counterfactual (what the EA would have done), and the realised
delta once the episode resolves.

The KPI is not P&L. It is **interference frequency and its cumulative cost**. Every entry either
proves the operator added value or proves the machine should have been left alone — and, critically,
it makes the *correct* interventions visible too (the 08-05 stand-down was framework-driven and
right; the +$1 oil closes were not). This is the cheapest build in the document and the only one
with no market-data dependency at all.

---

## PART 4 — BUILD ORDER

1. **Operator-action ledger** (Part 3) — hours, no data dependency, immediate.
2. **GEX pilot, gold** (Part 2A) — Python only, gated, reuses `gold_macro_flag` scaffolding + the
   existing episode ledger. Add COT to the same pilot.
3. **Event-proximity pilot, oil** (Part 2B) — reuses the Candidate-B calendar builder.
4. **Participation-dimension pilot** (Part 2C) — data already on disk; run last, lowest prior.
5. Only a pilot that **passes its pre-committed gate** earns an EA lever, default-OFF, then the
   tester A/B on the PEP-STAGE bench, then demo-twin forward, then the manifest promote path.

**Nothing in this document touches a locked build, and nothing here is a gate.** Every survivor is
either advisory (GEX, COT), a size multiplier (event derate, participation), or pure observability
(operator ledger) — which is the only shape of change that has ever won on this book.
