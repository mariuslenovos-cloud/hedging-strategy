# Card 2026-09-06-04 - Cell D, the allocation layer at the live geometry

| Field | |
|---|---|
| Cell | all legs . daily P&L . composition / sizing . objective = book RF at $2,390 with the 0.01-lot floor |
| Input | deployment-feed tester reports: gold HPIN12 GUI (100% ticks), oil SOLID4 control (rmb3), LongVol GUI (100% ticks), SessionDrift exit-4 (sd_h4), fib C SR6 (fibc_sr_G, off live) |
| Author / date | Claude, 2026-09-06 |

## The edge
No new signal. The book's legs are near-uncorrelated on daily P&L (gold-oil +0.14, gold-sessdrift -0.11, longvol-sessdrift -0.26, everything else within +-0.2), so adding a leg raises net and pain-window earnings faster than it raises drawdown. The payer is the same as each leg's; the layer only decides what runs together.

## Normalisation (cell_d_allocation.py)
Flat-lot engines scaled to their live lot (gold per-0.01, LongVol 0.01, fib C per-0.02); risk-normed engines (oil, SessionDrift) scaled to a fixed $2,390 balance. Realized deal-level P&L only: floating drawdown is deeper (gold eqDD 12% vs $105 realized here), so the RANKING of compositions is the output, not the absolute DD.

## Result (common window 2025-12-11 -> 2026-08-20, 181 business days)
| book | net | maxDD (realized) | RF | worst day | pain-window sum |
|---|---|---|---|---|---|
| gold + oil x1 (LIVE TODAY) | 4,992 | 249 | 20.1 | -249 | 1,065 |
| gold + oil x1 + LongVol + SessionDrift | 5,943 | 253 | 23.5 | -253 | 1,647 |
| gold + oil x0.5 + LongVol + SessionDrift | 4,909 | 129 | 38.2 | -129 | 1,375 |
| gold alone | 2,925 | 105 | 27.9 | -105 | 522 |

Per leg at live geometry: gold $3,153 (pain +521), oil $1,996 (pain +543, but -218 in Jun-oil and -128 on Aug-3), LongVol $330 (pain +160), SessionDrift $648 (pain +345). Vol check: gold daily sd $33 vs oil $129 -> oil carries 4x gold's variance at the live 2.5% risk; vol parity would be oil x0.26.

## Verdict
ALIVE, two actions.
1. The two 0.01-lot sleeves already built and validated (SessionDrift exit-4: GUI $896 / PF 1.54 / RF 2.56 / eqDD 9.1%; LongVol: GUI $328 / PF 1.60, runner trade-for-trade) add +$950 net and +$582 of pain-window earnings to the live book for +$4 of realized drawdown. They belong on the live accounts beside gold+oil (SessionDrift after ANOTHER TWO WEEKS on the demo — user decision 2026-09-06, review ~2026-09-20 at ~20 closes; LongVol after its own demo forward). Rule 6 at attach: magics 88231/88241 into the LIVE auditor map + framework WATCH_EAS in the same change.
2. Oil at half risk is the RF-optimal book (38 vs 23) but cannot be set by turning RiskPct down: SOLID is a 3-unit calibration (%-triggers, fixed-$ levers, ATR structure) and scaling lots without the $-levers de-tunes it (07-30 lesson, K1-half lesson). It needs a scale-covariant cell (RiskPct 1.25, escape $50, rescue target $25, freeze/floor unchanged) on the 100%-tick tester before it is a setting. Queued, not done.
