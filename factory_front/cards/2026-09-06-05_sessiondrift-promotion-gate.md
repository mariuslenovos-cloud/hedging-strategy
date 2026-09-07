# Card 2026-09-06-05 - SessionDrift promotion hold + the live gate (written BEFORE the review)

Source: the user's note `Downloads\SESSIONDRIFT_PROMOTION_NOTE.md` (2026-09-06), adopted verbatim below; the
baseline section and the check procedure were added 2026-09-07 from the demo terminal's own records.

**Decision (2026-09-06):** SessionDrift stays on DEMO for another two weeks before any live attach.

| | |
|---|---|
| Demo start | 2026-08-25 |
| Demo record at decision | 9 episodes, 12 days |
| Earliest live attach | **2026-09-20** |
| Config under test | exit-4, 0.01 lot, magic 88231 |

## Live gate - written now, checked on 2026-09-20

Promote only if all hold over the full demo period (08-25 -> 09-20):

- [ ] >= 20 episodes
- [ ] Net R > 0 after measured cost
- [ ] No single episode worse than the largest demo loss seen by 09-06
- [ ] Demo P&L tracks the tester report for the same days (no unexplained divergence)

Any one fails -> hold another two weeks, re-check. Do not shorten the hold on a good week.

## At attach (if gate passes)

- Attach to both live gold charts at 0.01 lot - this is the **reduced-size step** of the promotion path, not full deployment
- Register magic 88231 in the live auditor map and framework watch list in the same change
- Write the live removal rule before the attach: what result takes it off

## Removal rule (live)

Remove if, over any rolling 4 weeks on live: net R < 0, or a single episode exceeds the demo worst by 1.5x.

*Sequencing: SessionDrift first. LongVol goes to demo now, and follows the same two-week-minimum hold before its own live attach.*

---

## Baseline frozen 2026-09-07 (the numbers the gate is judged against)

| item | value | source |
|---|---|---|
| running config (VERIFIED from the demo Experts log 09-04/05/06) | long 01:00->04:00 server, clock exit 04:00 + stop 1.50xATR(D1) (no target), FIXED 0.01 lots, magic 88231 | `SessionDrift GOLD v0.2 FWD` banner + two CONFIG lines |
| pre-switch record (old twin 61552687, 08-25 -> 08-31, no longer queryable) | 6 episodes, net +$3.67, worst -$22.00 | 08-29 scorecard (5 eps / -$15 / worst -$22) + the 08-31 Monday close +$18.67 |
| current twin 61586543 (09-01 -> 09-07) | 5 episodes, net -$8.85, 3 wins, worst -$18.64 (09-02) | deal history, magic 88231, incl. commission + swap |
| **largest demo loss seen by 09-06 (gate item 3 baseline)** | **-$22.00** | frozen in `sessiondrift_gate.py` as `BASELINE_WORST` |
| R unit for item 2 | the running stop: 1.5 x ATR(D1,14) x $1 per point at 0.01 lot (about $60-90 per episode) | computed per episode from D1 bars at run time |
| episode cadence | one per server day (entry 01:01, exit 04:00) -> ~19 trading days 08-25 -> 09-19; the 20-episode bar is reachable only if no day is skipped | deal times |

Interim read 2026-09-07 (12 days before the review, NOT a verdict): 11 episodes, net -$5.18, net R -0.06 on the current
twin, worst = baseline. Items 1 and 2 fail today as expected this early; item 3 passes; item 4 needs a tester run over
the demo window (see below). Verdict HOLD - and a PASS before 09-20 would not shorten the hold either.

Caveat on the ledger: `analysis_data/episode_ledger.csv` holds the 08-25 -> 09-04 SessionDrift episodes but its
`realized_net` column is 0.00 on rows written before the 2026-09-01 time-basis fix (Bug Log) - the nets above come
from the deal history and the documented 08-29/08-31 record, never from that column.

## How to check on 2026-09-20

```
python sessiondrift_gate.py --rerun        # tester over 08-25->today on the PEP runner, demo config forced by set file + asserted from the report, then all 4 items
python sessiondrift_gate.py --tester <report.htm>   # same, against an existing report covering the demo window
python sessiondrift_gate.py --live         # after a live attach: the rolling-28d removal rule on MAIN + DEON
```

Negative tests run 2026-09-07 (each fails for the reason the check exists): `--min-eps 100` -> item 1 FAIL;
`--baseline-worst -5` -> item 3 FAIL; `--tester sd_h4.htm` (a report that ends 08-20) -> item 4 FAIL "no overlapping
days"; `--tester retest_SESSDRIFT-demo-window.htm` from the FIRST rerun (report Inputs `ExitHour=5`) -> item 4
"wrong config, NOT scored". That fourth one is the bench-config trap found the same day: the runner's tester had
reused its cached inputs from the 08-23 exit-hour sweep because the job passed no set file, and the demo (exit 04:00)
read as diverging from a bench exiting at 05:00 (entries matched to within 0.5 points). The gate now writes an explicit
set file with the demo config and refuses to score item 4 unless the report's own Inputs line equals it. Item 4's
positive specimen = the second `--rerun` (2026-09-07, report Inputs `ExitHour=4`, History Quality 71% real
ticks, 100% from 08-28): 4 shared days 09-01..09-04, same sign 4/4, demo +$1.19 vs tester -$0.61, mean |diff| $0.49 a
day (entries within 0.5 pt, exits at the same 04:00 bar) -> item 4 PASS. The runner is a valid bench for this clock-exit
engine, as the 08-23 exit-hour work already showed (runner-demo ~1%).

## Verdict

ALIVE, gated. The gate is pre-committed and mechanical; the review date is the only trigger. What would kill the
candidate: a demo episode below -$22, a negative net at the review, or a demo record that diverges from the tester on
the same days (the sign that live fills or the feed differ from the bench).
