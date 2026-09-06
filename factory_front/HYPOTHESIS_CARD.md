# Hypothesis Card

One card per cell. Ten minutes. Filled in **before** any data is touched beyond the Stage 1 row. A card that can't be completed is a kill at Stage 0 — that's the cheapest kill in the factory.

Copy this file to `cards/<id>_<short-name>.md` and add a row to `FUNNEL_LEDGER.csv` at the same time.

---

## Identity

| Field | |
|---|---|
| **Card ID** | `YYYY-MM-DD-NN` |
| **Cell** | instrument · horizon · signature · session/regime · structure · objective |
| **Stage 1 row** | paste the harness line for this cell (z_vr, t_ac, sig/C, tail1%) |
| **Author / date** | |

## The edge, in one paragraph

What is the return signature, in plain words, and at what horizon does it live? Not "gold mean-reverts" — *"after a 2σ deviation from session VWAP during Asia, the next 12 bars retrace on average 0.6 of the deviation."* If you can't say the horizon and the magnitude, you don't have a hypothesis yet; you have a mood.

## Who is on the other side, and why do they pay?

Name the counterparty and the reason they accept a worse price. Hedgers rolling. Stops clustering at a level. Forced flows at a fix. A grid getting squeezed. Inventory being unwound. Retail chasing a print.

**If this box is empty, the statistic you are about to find is probably noise.** Edges without a payer are the ones that vanish at Stage 3 and are never seen again.

## Why hasn't it been arbitraged away?

Capacity too small for institutions, venue-specific, requires holding through something uncomfortable, needs a regime that comes and goes. One sentence. "Nobody's noticed" is not an answer.

## Cost term

| | |
|---|---|
| Measured round-turn cost `C` in this session (from the shadow logger's hour-bucket table, not assumed) | |
| Expected gross edge per fire, in units of `C` | |
| Minimum acceptable: **gross ≥ 3 × C** | pass / fail |

If gross edge per fire is below 3 × C, the card dies here regardless of the statistic. That's the cost-term rule, and no signal fixes a cost term.

## Objective

- [ ] Standalone profit factor (must earn on its own)
- [ ] Portfolio return-on-drawdown contribution (may lose a little alone; must lift portfolio RF)
- [ ] Tail reduction for an existing leg (must cut leg's worst month by more than its annual cost)

Pick one. A card tested against the wrong objective produces the wrong kill.

## Pre-committed kill criteria — written now, not after the result

| Stage | Kill if |
|---|---|
| **1** | `|stat|` < 3.0 on mid, or `sig/C` < 1.0, or sign flips in adjacent session/horizon |
| **2** | fewer than ___ fires/month, or gross edge per fire < 3 × C, or edge disappears when the signal threshold moves ±20% |
| **3** | any Section 7 gate in the existing governance; plus the objective-specific gate above |

Fill the blank before running Stage 2. A kill criterion decided after the result is a rationalisation with a number on it.

## Parameter budget

Free parameters this card is allowed: ___ (default 4). Variants this card is allowed to test in total: ___ (default 8). Both go in the ledger. Exceeding either invalidates the DSR gate for this card rather than improving the strategy.

## Relationship to existing legs

| Leg | Expected correlation of daily P&L | On event days specifically |
|---|---|---|
| GridStat GOLD | | |
| GridStat OIL | | |
| Hedger fib C | | |

A card that is >0.8 correlated with an existing leg on event days is the same bet in a different wrapper. That's a Stage 1 kill under the breadth objective.

## Outcome (filled in when it dies or promotes)

| | |
|---|---|
| **Stage reached** | |
| **Kill reason (one line, specific)** | |
| **What it taught about the map** | e.g. "H1 gold momentum has no signature on this feed — closes cell A-H1, cell A-D1 still open" |

---

*A card that dies well is a factory asset. A card that dies vaguely is a wasted test. Write the kill reason so that the next person — or you in six months — cannot re-run the same idea by accident.*
