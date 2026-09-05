# Marius RevScalp MT5 - Strategy Specification v0.1

> **VERDICT (2026-09-05, Gate 0 + first-order pricing, deployment feed): NOT BUILT.**
> OIL_MOM: Gate 0 FAIL on both series (16mo M5 bid z=-0.70; 3.3mo M1 mid z=-1.70) - oil does not trend intraday, it mildly reverts.
> GOLD_MR: Gate 0 FAIL at M5 (16mo, VR(5)=1.005 z=+0.22, random walk) / PASS at M1 mid (3.3mo, VR(5)=0.957 z=-2.70) - the reversion is real inside
> 5 minutes and ~3% of a bar's move (~$0.05/oz per 1-sigma M1 bar vs $0.25 round-turn cost). Engine A's exact rule on the M1 mid series
> (revscalp_engineA_sim.py, pessimistic fills, C=0.25): 61 trades / 3.3mo, net +0.65/oz avg, t=1.42 (statistically zero), ~$20-25/mo at the
> spec's 0.25% risk on $2.4k = the 08-03 bank-adjacent class. Transplant candidates onto GridStat (gridstat_er_vwap_study.py, 2,486 fires):
> ER regime = NO separation (halves flip, within-cell contradicts itself); VWAP-z stretch = weak same-direction tilt (4/5 cells), halves soft -
> a sizing candidate at best, parked behind the DAYRANK precedent. Tools: vr_precheck.py (Gate 0), pull_m1_pep.py (M1 + mid from the live feed).

**Two engines, one framework, opposite signs.**
`GOLD_MR` fades stretch on XAUUSD. `OIL_MOM` rides thrust on WTI. Both are flat-single (no grid, no adds, no averaging) so they stay separable from GridStat in the shadow logger.

Status: **UNBUILT - pre-gate.** Nothing here goes to a live account until Section 7 gates pass on shadow-logged fires.

---

## 0. The cost reality (read this before anything else)

Scalping "a few pips" is a units problem before it is a strategy problem.

### XAUUSD (2-decimal quote, point = 0.01)

| Component | Typical raw-spread cost |
|---|---|
| Spread (London/NY, 1.00 lot) | $0.15 - $0.25 |
| Commission RT (~$7/lot) | $0.07 |
| Slippage allowance (market entry, 2 sides) | $0.04 - $0.10 |
| **Round-turn cost** | **~ $0.26 - $0.42** |

If "pip" = $0.01, a 5-pip target is **$0.05 - one fifth of your cost**. Dead on arrival at any win rate.
If "pip" = $0.10 (the common gold convention), 5 pips = $0.50, which is ~1.5x cost. Survivable but thin.

**Rule adopted here: every target is expressed as a multiple of measured round-turn cost `C`, never in absolute pips.** Minimum viable `TP = 3.0 x C`. On gold that lands at **$0.75 - $1.25** - roughly 8-12 "pips" in the $0.10 convention. That is the smallest number the arithmetic permits, not a preference.

### WTI / XTIUSD (2-decimal quote, point = 0.01)

| Component | Typical |
|---|---|
| Spread | $0.02 - $0.04 |
| Commission RT | ~$0.01 |
| Slippage allowance | $0.01 - $0.02 |
| **Round-turn cost `C`** | **~ $0.04 - $0.07** |

Minimum `TP = 3.0 x C` -> **$0.12 - $0.21**.

`C` is not assumed. It is measured live per symbol per hour bucket by the shadow logger (Section 6) and the EA reads it from the resulting table. Oil's spread widens 3-5x around 16:30 SAST Wednesdays (EIA) and at the 23:00-01:00 roll; a static `C` will lie to you exactly when it matters.

(Measured 2026-09-05 on Pepperstone: XAUUSD spread median 11 points, p90 18-20, flat across the day; SpotCrude spread 24 points fixed.)

---

## 1. Premise, and how it gets tested

The design rests on: **XAUUSD intraday returns are negatively autocorrelated (mean-reverting); WTI intraday returns are positively autocorrelated (trending).**

This is horizon-dependent and probably regime-dependent, so it is a hypothesis, not a foundation:

- Gold mean-reverts around intraday value (VWAP) but **trends hard at the daily+ horizon** - the same instrument, opposite sign, different scale.
- Oil shows intraday continuation but mean-reverts at the multi-week inventory-cycle horizon.

**Pre-build test (`vr_precheck.py`):** compute per symbol:

1. **Variance ratio** `VR(q)` for q = 2, 5, 10, 30 bars, with the Lo-MacKinlay heteroskedasticity-robust z-statistic.
   - `VR < 1` with `z < -2` -> mean reversion. Expected for gold.
   - `VR > 1` with `z > +2` -> momentum. Expected for oil.
2. **Hurst exponent** (R/S), as a cross-check only - noisy on short intraday windows, never the deciding statistic.
3. **Lag-1 autocorrelation of returns, bucketed by hour (SAST)** - the one that pays. The premise may hold only in specific session buckets, which becomes the trading window rather than a filter bolted on later.
4. **Bid-ask bounce control**: recompute (1) and (3) on mid-price. Negative lag-1 autocorrelation on last/bid prices is partly microstructure artefact. **If gold's mean reversion vanishes on mid, the GOLD_MR engine is dead and does not get built.**

**Gate 0 (pre-committed): if gold's `VR(5) z-stat` on mid-price is not < -2.0, and oil's is not > +2.0, on >= 12 months of M1, this spec is killed before a line of MQL5 is written.** No re-specification of the test after seeing the result.

---

## 2. Shared framework

| Element | Setting |
|---|---|
| Context timeframe | M5 |
| Execution timeframe | M1 |
| Concurrent positions | 1 per engine, 2 total, never same-direction-correlated |
| Position sizing | 0.25% equity risk per trade (high frequency -> small unit) |
| Daily stop | -1.5% equity, or 4 consecutive losses -> engine sleeps until next session |
| News blackout | +/-3 min around high-impact USD/gold/oil events; oil additionally blacked out 16:25-16:45 SAST Wednesdays |
| Correlation guard | No new fire if the other engine already holds a position with >0.6 rolling 60-bar return correlation |
| Spread guard | Reject fire if current spread > 1.6 x the hour-bucket median. Non-negotiable |

**Regime classifier (shared, M5):** Efficiency Ratio over 10 bars, `ER = |C_t - C_{t-10}| / sum|C_i - C_{i-1}|`.
- `ER < 0.30` -> chop -> **GOLD_MR armed, OIL_MOM disarmed**
- `ER > 0.45` -> directional -> **OIL_MOM armed, GOLD_MR disarmed**
- `0.30 <= ER <= 0.45` -> dead zone, both disarmed

---

## 3. Engine A - `GOLD_MR` (XAUUSD, fade the stretch)

**Anchor:** session VWAP, reset at broker day open. Fallback: M1 EMA(20).

**Deviation:** `z = (Price - VWAP) / sigma_dev`, sigma_dev = stdev of `(Price - VWAP)` over the last 120 M1 bars.

### Entry (long; short is the mirror) - all true on the close of an M1 bar
1. `z <= -2.0`
2. `ER_M5(10) < 0.30`
3. No M5 trend: `|EMA20_M5 - EMA50_M5| < 0.25 x ATR14_M5`
4. Reversal trigger: the current M1 bar closes above its own open and above the previous bar's close, after a bar whose range exceeded `1.5 x ATR14_M1`.
5. Session window: **00:00-13:30 SAST**. Explicitly excludes 14:00-16:30 SAST.
6. Spread guard passes.

### Exit
| Exit | Rule |
|---|---|
| Take profit | `TP = max(0.6 x |deviation at entry|, 3.0 x C)`, never beyond VWAP |
| Stop loss | `1.8 x ATR14_M1` from entry |
| Time stop | market exit after 12 M1 bars |
| Regime stop | immediate exit if `ER_M5(10)` crosses above 0.45 while in position |

No break-even move, no trailing stop.

---

## 4. Engine B - `OIL_MOM` (WTI, ride the thrust)

**Setup (M5):** close beyond the high/low of the prior 12 M5 bars by more than `0.15 x ATR14_M5`, on a bar whose true range exceeds `1.4 x ATR14_M5`.

### Entry (long; short is the mirror)
1. Breakout bar closed as above
2. `ER_M5(10) > 0.45`
3. Close above session VWAP
4. Session window: **15:00-21:00 SAST**
5. Spread guard passes, not in the EIA/roll blackout

**Fill:** M1 limit at 0.30 x (breakout bar range) back into the bar, valid 3 M1 bars, else cancel.

### Exit
| Exit | Rule |
|---|---|
| TP1 (60% of size) | `2.5 x C` |
| Runner (40%) | chandelier trail at `2.0 x ATR14_M1` from the running extreme, armed after TP1 |
| Stop loss | opposite extreme of the breakout bar, or `1.0 x ATR14_M5`, whichever is tighter |
| Time stop | if MFE < `1.0 x C` after 6 M5 bars, exit at market |

---

## 5. Parameter budget
**Total free parameters: 11.** **Pre-committed variant cap: 24 configurations tested, total, across both engines.** Every backtest run is logged to a variant ledger with a timestamp before its result is seen; the Deflated Sharpe Ratio in Gate B uses the ledger count.

## 6. Shadow-logging protocol
Extend the S28 all-fires logger with a `revscalp` channel. For every fire - taken, rejected, or filtered - record:
`timestamp, symbol, engine, direction, z, ER_M5, ATR_M1, ATR_M5, spread_at_fire, hour_bucket_SAST, filter_that_rejected, sim_entry, sim_TP, sim_SL, sim_exit_reason, MFE, MAE, bars_held, gross_R, cost_applied, net_R`
**Minimum shadow period: 8 weeks, or 300 fires per engine, whichever is later.** Run `painwindow_check.py` over the log with buckets by hour (SAST), day-of-week, ER decile, realised-volatility tercile.

## 7. Pre-committed gates
| Gate | Criterion |
|---|---|
| 0 - Premise | Section 1 variance-ratio test on mid-price. Gold `VR(5) z < -2.0`, oil `VR(5) z > +2.0`. Fail -> no build |
| A - Net edge | >= 300 shadow fires per engine, mean `net_R > 0`, t-stat > 2.0 after measured costs |
| B - Not luck | Deflated Sharpe Ratio > 0 at 95%, using the full variant-ledger count |
| C - Shape | GOLD_MR win rate >= 62% with RR >= 0.45. OIL_MOM win rate >= 38% with RR >= 1.6 |
| D - Cost robustness | edge survives spread x1.5 and +1 point slippage per side. Run first |
| E - Pain window | no bucket with >= 30 fires shows mean net R < -0.15. Max consecutive losses <= 9. Max shadow DD <= 6% |
| F - Decay | second-half mean net R >= 50% of first-half |

**Promotion path:** gates pass -> demo at 0.25% sizing for 4 weeks -> live at 0.10% sizing for 4 weeks -> full sizing.

## 8. Honest risks
- **Cost dominance.** At `3 x C` targets you need ~75% of gross edge to survive frictions.
- **Microstructure mirage.** Gold's negative lag-1 autocorrelation on bid prices is partly bid-ask bounce.
- **Regime fragility.** ER thresholds at 0.30/0.45 are the most fragile numbers in the spec.
- **Correlation with GridStat.** Both engines trade the symbols the existing EAs already hold.
- **Frequency and infrastructure.** M1 scalping makes execution quality a strategy parameter.

*v0.1 - design only. Gate 0 run 2026-09-05: see the verdict block at the top.*
