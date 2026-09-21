# PEP-STAGE — week of 2026-08-17 → 08-22: what actually happened

**Scope:** the two EAs that floored on the demo twin (`C54C4DDE…` / PEP-STAGE, "MT5 Pepperstone
Instance 2"): `Marius Hedger fib C LOCKED` (XAUUSD) and `Marius GridStat MT5 OIL SOLID LOCKED`
(SpotCrude). Five EAs are live on that terminal: those two plus `GOLD LOCKED`, `GOLD DAYRANK`,
`OIL DAYRANK`.

**Headline:** the trading layer behaved close to design. **The observability layer is broken —
and it broke four days before the fib C floor.** That is the finding that matters.

---

## 1. Only ONE of the two actually lost money

From `analysis_data/episode_ledger.csv`:

| stream | closed | hours | legs | deepest | % of bal | floor | margin | realized_net | verdict |
|---|---|---|---|---|---|---|---|---|---|
| DEMO fibC | 08-19 15:18 | 42.0 | 6 | −1,281.98 | **20.52%** | 20.0 | −0.52pp | 0.00 *(see §4)* | **FLOOR** |
| DEMO oil-SOLID | 08-21 13:28 | **311.5** | 8 | −579.51 | 10.94% | 10.0 | −0.94pp | **+938.49** | **FLOOR** |

**Oil SOLID's floored episode was profitable.** It ran 13 days (opened 08-08 13:59), never once had
a green open float (`peak_float = −64.70`), and still banked **+$938.49 realized** across the episode.
The floor cut itself took −$584.46 off the demo balance on 08-21 — the harvests along the way paid
for it several times over.

That is the turnover law doing exactly what the record says it does: the engine earns from *harvest
count*, not from the book looking healthy. Adjusting oil SOLID to avoid that floor forfeits the
$938. It would be cut-class attempt **#10**, and `delev_sim.py` already priced this class at
**net −$2,042** (23 cuts forfeited recoveries −$3,866 vs 7 saves +$1,824; ~77% of meaningfully-red
legs recover).

**Recommendation: do not touch OIL SOLID.** The machinery all fired correctly on the way down —
`CRASH-STATE UP` every session (74.55 → 86.97 reference), five `OPPOSITE-WHEN-DEEP` rescue baskets,
`SAMEDIR TAPER` at ×0.13 and ×0.25, `FREEZE HEDGE` at −366. A sustained one-way oil rally against a
mean-reversion grid is the known cost of the edge, not a defect.

**fib C is the genuine loss.** Demo balance dropped **−1,213.22** overnight into 08-20.

---

## 2. fib C floored on DEMO but survived on LIVE and DEON — same episode

All three accounts opened the same episode at **2026-08-17 21:21**:

| account | closed | legs | deepest | % of bal | budget used | verdict |
|---|---|---|---|---|---|---|
| DEON | 08-18 22:48 | 5 | −84.32 | 4.01% | 0.20 | healthy |
| LIVE | 08-19 14:58 | 5 | −309.42 | 12.86% | 0.64 | KNIFE-EDGE (net +6.03) |
| **DEMO** | 08-19 15:18 | **6** | **−1,281.98** | **20.52%** | **1.03** | **FLOOR** |

Same strategy, same signals, same window. DEMO took a **sixth leg** and went ~60% deeper *as a
percentage of balance* while running ~2.6× the capital (~$6.2k vs LIVE ~$2.4k).

The demo twin's stated job is to be the **gap-meter**. It cannot serve that purpose if it is not
scale-matched — and per the scale-covariance doctrine (08-14), $-denominated levers must move in
lockstep with capital. Until that divergence is explained, **the demo floor is not evidence about
the live book.**

> Open question worth one session: why 6 legs on DEMO vs 5 on LIVE/DEON off identical signals?
> That is either compounding-off-balance behaving as designed at higher capital, or a genuine
> config drift between the terminals. It is answerable by diffing the fib C LOCKED inputs across
> the four terminals.

Separately, on **LIVE** the same day: Book Guard tripped correctly — WARNING at −144.40 (75% of
limit) 15:39, then `DAILY LOSS LIMIT TRIPPED: today −192.82 (−8.0% of day-start 2405.55) →
FLATTENING ALL`. The guard worked.

---

## 3. 🔴 THE ROLLING RE-TEST ENGINE IS DEAD AND SILENTLY SERVING STALE RESULTS

This is the real defect of the week.

`analysis_data/rolling_retest.csv` — the 2026-08-22 rows are **byte-identical to 2026-08-15**
across all three jobs:

```
2026-08-15,fibC-XC,56,355.78,1.69,0.6,18.59,25.0,baseline-building
2026-08-22,fibC-XC,56,355.78,1.69,0.6,18.59,25.0,baseline-building
2026-08-15,GOLD-FIBC8,56,-1211.86,0.94,-0.5,58.28,659.0,NEGATIVE — watch
2026-08-22,GOLD-FIBC8,56,-1211.86,0.94,-0.5,58.28,659.0,NEGATIVE — watch
2026-08-15,OIL-SOLID,56,415.24,1.7,1.19,9.85,27.0,baseline-building
2026-08-22,OIL-SOLID,56,415.24,1.7,1.19,9.85,27.0,baseline-building
```

A trailing 56-day window that has advanced 7 days cannot reproduce identical net, PF, RF, eqDD
**and identical trade counts (25 / 659 / 27)** to the cent.

### Proof

| evidence | value |
|---|---|
| `retest_fibC-XC.htm` mtime | **2026-08-15 07:00:10** |
| `retest_GOLD-FIBC8.htm` mtime | **2026-08-15 07:00:17** |
| `retest_OIL-SOLID.htm` mtime | **2026-08-15 07:00:24** |
| `tester_ini/retest_*.ini` mtime | **2026-08-22 07:00:01 → 07:00:04** |
| runner `Tester/logs/20260822.log` | **108 bytes** (empty stub) |

The `.ini` files were written today, so `run_job()` executed. The three runs finished **~1.3 seconds
apart** — a 56-day M5 backtest producing 659 trades cannot complete in 1.3s. (On 08-15 the same
jobs took ~7s each and *did* produce reports.) The tester launched, did nothing, and exited.

### Root cause

`rolling_retest.py`, end of `run_job()`:

```python
for ext in (".html", ".htm"):
    rp = os.path.join(RUNNER_DATA, report + ext)
    if os.path.exists(rp):
        return parse_report(rp)
```

**There is no freshness check.** When the tester produces no report, last week's file is still on
disk, so it is parsed and written to the CSV as this week's result. A silent failure is rendered
as a confident number.

### Likely trigger

The `[Experts]` block at the top of the ini, added **2026-08-18** per its own comment
(*"never launch a terminal with armed chart EAs unguarded"*):

```python
"[Experts]\nEnabled=0\nAllowLiveTrading=0\n\n"
```

`Enabled=0` disables experts terminal-wide. Combined with `ShutdownTerminal=1`, the tester expert
never runs and the terminal exits immediately. Timeline fits exactly: 08-15 (pre-patch) produced
reports; 08-22 (first weekly run post-patch) produces none.

**So the safety patch disarmed the early-warning system, and the missing staleness check hid it.**

### Consequence

- The engine went blind on **08-18**. fib C floored on **08-19**.
- `GOLD-FIBC8: NEGATIVE — watch` has appeared in every morning brief since 08-20 — it is a
  **7-day-old verdict being reprinted**, not a current reading.
- Any *new* degradation in any of the three jobs would be invisible right now.

### Fix (correctness, not a curb — nothing to A/B)

1. **Freshness guard.** Capture `t0 = time.time()` (or delete the report) before `subprocess.run`.
   After it returns, require `os.path.getmtime(rp) > t0`; otherwise `return None` and raise a **RED**
   alert. Never parse a report the run did not produce.
2. **Restore the tester.** Verify whether `[Experts] Enabled=0` suppresses the tester expert on this
   build. Keep the 08-18 safety intent by launching the runner on a **profile with no armed chart
   EAs**, rather than globally disabling experts.
3. **Re-run** to get a genuine 08-22 reading on GOLD-FIBC8 — then decide whether it is really
   degrading, on real numbers.

---

## 4. 🟠 The episode ledger's `realized_net` column is unreliable

**19 of 22 rows read `0.00`** — including the fib C FLOOR that demonstrably cost **−1,213.22** of
demo balance (visible in the 08-20 morning brief).

`episode_auditor.py :: realized_since()` builds its `position_id → magic` map only from entry deals
inside the window `[start_ts − 60s, now]`. But `ep["start"]` is set when the auditor **first sampled**
open positions, not when they opened — the auditor runs on a schedule, so early legs' entry deals
fall outside a 60-second lookback and never enter `pm`. Out-deals then fall back to `d.magic`, which
does not resolve for most streams.

**Why it matters:** the ledger currently records *depth* accurately and *outcome* not at all — and
the fragility governor is accumulating toward its "8 episodes" threshold on a column that mostly
reads zero. Widen the lookback to the true position-open time (or resolve magic via
`history_deals_get` by position_id without a window), then backfill.

---

## 5. The Sentinel blind spot reproduced, exactly as documented

Gold velocity percentile through the week:

| date | 08-17 | 08-18 | **08-19** | 08-20 | 08-21 | 08-22 |
|---|---|---|---|---|---|---|
| velocity | p31 | p33 | **p27** | p76 | p88 | **p96** |
| verdict | INSIDE | INSIDE | **INSIDE** | INSIDE | INSIDE | **STRETCHED** |

On the morning fib C floored, the Sentinel read gold at **velocity p27 — its calmest of the week** —
and flagged `STRETCHED` only three days later. This is the V-turn netting problem in the record
(V-turns cancel over the 3-day window), now with a second live instance costing $1,213.

This is the strongest empirical argument yet for the **exogenous vol-regime read** proposed in
`research_transcripts/01_kmer_eval.md` §2A: a *positioning-based* signal (naive GEX on GLD/GC, or
COT managed-money net) does not net to zero the way a price-derived velocity measure does. Two
documented misses now sit behind that proposal.

---

## 6. Housekeeping surfaced along the way

- **Gate DBs stale:** GOLD **73 days**, SILVER 71, OIL 21. The selection core is running on a
  73-day-old gold DB.
- **SLOT-QUALITY** flag has appeared since 08-21: *"2 higher-WR signals skipped behind a lower-WR
  seat"* — queued, not actioned.
- `fibc_equity.csv` in `Common\Files` was locked (permission denied) while the terminal was running —
  expected, noted only so a future script doesn't mistake it for a missing file.

---

## Bottom line on "adjust them so they don't make losses"

**The trading layer is not where this week's defect is.**

- **OIL SOLID:** leave it alone. Its floored episode netted **+$938.49**. Curbing it is cut-class
  #10 against a 9-0 record and a −$2,042 simulated price tag.
- **fib C:** the loss is real, but the demo floored where LIVE and DEON survived the same episode —
  so the first question is the **twin's scale correspondence**, not a tighter floor.
- **What actually failed:** the re-test engine (dead since 08-18, serving stale numbers), the
  ledger's outcome column (reads 0.00), and the velocity sentinel (read p27 on the day of the floor).

Fix the instruments before adjusting the engine. Right now there is no trustworthy measurement
saying either EA is broken — and the one signal that *would* tell you, GOLD-FIBC8's rolling re-test,
has not actually run since 2026-08-15.

### Suggested order
1. Freshness guard + restore the tester in `rolling_retest.py`; re-run all three jobs. *(hours)*
2. Fix `realized_since()`; backfill the ledger. *(hours)*
3. Diff fib C LOCKED inputs across DEMO / LIVE / DEON to explain 6 legs vs 5. *(one session)*
4. Refresh the gold gate DB (73d).
5. Only then ask whether GOLD-FIBC8 is degrading — on numbers that are actually current.
