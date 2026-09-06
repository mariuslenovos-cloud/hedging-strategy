# Search Map — the factory's front half

The back half of the factory (gates, pain windows, shadow logger, variant ledger) decides what survives. This file decides what gets tested. A trading solution is a cell in the space below. Explored cells are marked. Everything else is the search space.

**Rule:** no cell enters Stage 2 without a hypothesis card (`HYPOTHESIS_CARD.md`). No card without a Stage 1 row from `stage1_harness.py`. No exceptions for ideas that feel obvious — those are the ones the ledger says die most.

---

## 1. Axes

| Axis | Values |
|---|---|
| **Instrument** | XAUUSD · XTIUSD · XAGUSD · US500 / NAS100 · EURUSD · GBPUSD · USDJPY · BTCUSD (CFD) |
| **Horizon** | M1 · M5 · M15 · H1 · H4 · D1 |
| **Signature** | mean reversion · momentum / continuation · breakout / range expansion · volatility (compression → expansion) · seasonality / time-of-day · carry (swap) |
| **Session / regime** | Asia (00–09 SAST) · London (09–15) · NY (15–23) · chop (ER < 0.30) · directional (ER > 0.45) · **event day** |
| **Position structure** | flat single · grid / basket · overlay / hedge on an existing leg · multi-instrument basket |
| **Objective** | standalone profit factor · **portfolio return-on-drawdown contribution** · tail reduction for an existing leg |

Six axes. The last two are where the unexplored edge most plausibly lives at a $2.4k balance, because return-on-drawdown is the scarce resource, not profit factor.

---

## 2. Explored region

Symbol names below are the Pepperstone feed names the exports carry (`XTIUSD` on the map = `SpotCrude` on the feed). GridStat's execution bar is **M5**; its context is **D1** (EMA50 trend filter, ATR(D1) barriers and grid spacing) plus an M5 ATR(20)/ATR(100) regime tag. There is no M15 anywhere in the deployed stack.

| Cell | What was tried | Outcome |
|---|---|---|
| XAUUSD · M5 (D1 context) · MR-ish grid · standalone PF | GridStat GOLD HPIN12 PT50 | **Live.** PF 3.87, RF 6.55, 12% eqDD, ~140 baskets / 9 mo (PEP GUI, 100% ticks) |
| XAUUSD · M5 · scalp-mode exits | PT25, PT35 | Killed 09-05 — exit speed doesn't create trades; basket count is signal-gated |
| XAUUSD · M1 · MR fade | RevScalp Gate 0 (mid, 3.3 mo M1) | **Run and killed 09-05** — VR(5) z −2.7 is real but the predictable move is $0.03/bar vs $0.25 cost (parity needs lag-1 0.139 = 2.4× the best hour). Outsized-bar fade t=0.83. Cost-term kill. |
| XAUUSD · H1 · breakout | TrendBreak (H1 Donchian), GoldTrend H1 | Killed 08-17 / 06-20 on pre-committed gates; pain windows negative |
| XAUUSD · intraday · counter-move MR | Counter-Thrust, ADX<20 fade, VWAP-z | Killed on the 2,350-fire all-fires DB |
| XAUUSD · M5 · signal density | five variants, one week | Killed — none clear the spread |
| XAUUSD · H1 (01–04 SAST) · time-of-day drift · flat single | SessionDrift GOLD | Demo sleeve (magic 88231), ~$100/mo class, corr 0.35 to the grid |
| **XAUUSD · D1 · momentum · flat single (Tier-1 A)** | `gold_d1_momentum_screen.py` 09-06, 11y, real PEP swap | **Screened and shelved** — TSMOM60/120 Sharpe ~0.8 at zero swap, both halves >0.4; at the real −6.6%/yr long swap h1 falls to 0.1–0.3; at the 0.01-lot floor on $2,390 the DD is 47–52% of balance. Re-opens at ~$10k. |
| **XAUUSD · event day · long-vol bracket overlay (Tier-1 B)** | `Marius LongVol Bracket MT5 v1.0`, 09-06 | **Passed all three pre-committed gates** (tester = 60–77% of the sim's net; pain-window sum +$461; worst −$63; 100%-tick GUI run identical to the runner trade-for-trade). Demo forward beside the book = the out-of-sample. Magic 88241. |
| SpotCrude · M5 (D1 context) · grid · standalone PF | GridStat OIL SOLID4 | Live. 7 cut-class levers killed; freeze + regime sells + crash-guard locked |
| SpotCrude · time-of-day | SessionDrift screen 08-23 | Killed — best hour 2:1 edge-to-cost, 84% of it in the recent half |
| XAGUSD · M5 · GridStat grid | SILVER LOCKED (PF 2.60 / 8.7% DD, conc 4) | Locked 06-12, live 07-14, **paused 07-20** — 0.01-lot = 3.3%/trade at $3k, venue prefers XM. **Event-day correlation with gold MEASURED 09-06: daily +0.90, 5-min +0.83, beta 1.53; all five documented event days same-sign; top-decile gold days 8/8 same sign at 1.37×.** Silver = a 1.4× levered copy of gold on the days that matter. Tier-1 C closed. |
| XAUUSD · hedge structure | Hedger fib C (SR6F) | Demo (magic 4902); live return = a sub-account decision at ~$10k family |
| Allocation layer (Tier-1 D) | `portfolio_allocator.py` (equal-weight vs HRP), margin governor (morning_check ⑤), **`cell_d_allocation.py` (09-06)** | Built 06-18 / 08-14; combined floating DD ~9.4% vs gold-alone 20%. **Measured 09-06 at the live geometry ($2,390, 0.01 floor, realized daily P&L, Dec→Aug): legs near-uncorrelated; adding the two built 0.01-lot sleeves (SessionDrift, LongVol) to gold+oil = net +$950, pain-sum +$582, realized DD +$4 (RF 20→23.5); oil ×0.5 = RF 38 but needs a scale-covariant SOLID cell before it is a setting.** |
| Macro event day (gold) | CPI/NFP/FOMC post-release drift, 34 events | Killed 08-18 — t≈0.2; CPI pops fade on this feed. EIA/oil never tested (Tier-2 E stays open). |
| FX · rollover fade / Asian drift | FXFade (11 FX), AUDUSD 01→06 | Killed on rollover spread / commission; shelf at $10k |
| Indices | US30 grid (rejected), ON-4 overnight (shelved at $3k) | ORB (Tier-2 F) never tested |

Everything explored is **gold or oil, intraday, tested on standalone PF, on a spread-paying CFD venue** — with two exceptions logged this weekend: the D1 momentum cell (shelved on the capital wall, not the signature) and the event-day overlay (alive, demo-forward). This table matches the `EXPLORED` dict in the harness.

**First Stage-1 pass on the Pepperstone feed (2026-09-06; `stage1_m1_20260906.csv` = M1 mid ×3, 05-27→09-04, SAST; `stage1_m5long_20260906.csv` = 16-mo M5 bid, H1/H4/D1 rows only). Costs measured from each export's spread + Razor commission: XAUUSD $0.18, SpotCrude $0.024, XAGUSD $0.032.**
- **Cards: none.** Every M1 cell on all three instruments shows a real MR signature (|t_ac| 3.4–10.8) that is unbuyable: predictable part of one bar 0.04–0.53 of a round-turn (gold London 0.53 = the best on the feed). The shipped gate (sig/C only) had called seven of them feasible; the `pred_per_cost` term was added and the re-run dropped all seven = the negative test. Friday's Gate 0 ($0.03 vs $0.25) reproduced on three instruments.
- **Slow cells (H1/H4/D1, 16 mo):** nothing at |stat| ≥ 3 on z_vr/t_ac. Gold D1 t_ac −2.0 (n=412), gold H1 Asia/NY t_ac −2.2/−2.3 = below gate, consistent with the D1 momentum screen (real at zero cost, thin).
- **The oil Asia look, carded and killed (card 2026-09-06-03):** the first-pass SpotCrude H1 Asia t_m20 −4.49 was a HARNESS ARTEFACT — the session mask was applied before the 20-bar lag, so "the prior 20 hours" were Asian bars strung across days. Fixed 09-06 PM (lag on the full series, mask on the target bar; momentum columns now in the gate with their own pred/C term; M1 regression = 0 cards unchanged). The corrected cell still reads t −3.35 / feasible, but the replay of the tradeable form (`oil_asia_card.py`) is negative before cost (t −0.55), every adjacent arm hour sits within |t| < 1.5 with sign flips, and its correlation with SOLID's daily P&L is −0.03 to −0.35. Not "already monetised": not there. Rule from it: an H1 past-k statistic is labelling-sensitive; only the replay of the tradeable form decides.
- **Limits:** M1 cells = 3.3 months (the terminal's 100k-bar cap); D1 cells built from M1 have ~70 bars; the long-horizon run is bid (irrelevant at H1+). Tier 2/3 cells (FX, indices) have no export yet — the next pass needs `pull_m1_pep.py SYM=file` for them.

## 3. Unexplored region, ranked by prior

Priority = (economic reason an edge exists) × (cost friendliness at that horizon) × (contribution to portfolio RF). Not by how interesting it sounds.

### Tier 1 — a payer can be named, and cost is small relative to the move

**A. XAUUSD · D1 / H4 · momentum · flat single · standalone + portfolio RF**
The other half of your own asymmetry. Gold mean-reverts intraday and trends at daily horizon. Payer: slow-moving allocators and central-bank buyers who don't chase, so trends extend. Cost at D1 is ~1% of a typical move (harness `sig/C` ≈ 170 on synthetic; measure on your feed). Same instrument, opposite sign. **Screened 09-06 — see Section 2: the signature is real, the CFD swap and the 0.01-lot floor kill it at $2,390. Re-tested the same evening with the proper instrument (`stage1_tsmom.py`, 23 years of live-terminal D1, swap in the cost term): L=120/250 × h=10/20 clear t 2.0–2.2 with both halves > 1 when swap is averaged, but charging the side actually held (long −$0.797/oz/day, short +$0.296 credit) leaves $3–32/yr at the 0.01 lot and the short leg has been negative since 2016. Card closed; re-opens at ~$10k.**

**B. XAUUSD · event day · breakout overlay on the GridStat leg · objective = tail reduction**
5 August cost $1,195. The grid was structurally short a melt-up. An overlay that buys range expansion beyond N × ATR and is allowed to lose a little on ordinary days is not TrendBreak re-tested — it is a different objective: does it cut the grid's worst month by more than it costs across the year? Payer: the grid itself, and every other grid on the feed getting stopped in the same move. **Built as the long-vol bracket 09-06, all gates passed, demo forward running next — see Section 2.**

**C. XAGUSD · M5–M15 · same GridStat logic · portfolio breadth**
Silver is gold with more variance and a different tail. The question is one number: correlation with gold on the two event days. If it's below ~0.7 there, it's a third leg. If it's 0.9, it's the same bet in a different wrapper and the card dies at Stage 1. **Measured 09-06 (M1 mid, 73 server days): +0.90 daily, 5/5 event days same sign, 8/8 top-decile gold days same sign, silver/gold move ratio 1.37. It is the same bet in a different wrapper; the card died at Stage 1. A silver leg on any gold engine (grid, bracket) is a size lever on the gold bet, not breadth.**

**D. Allocation layer · all legs · vol-targeted sizing · objective = portfolio RF**
No new signal. Size each of gold, oil and fib C to a target contribution to portfolio drawdown rather than to balance alone. Fib C and oil made $473 in the month gold lost $1,195 — the data to calibrate this already exists in the three ledgers. Cost: zero. This is the cheapest RF gain on the map. **Measured 09-06 (`cell_d_allocation.py`, card 2026-09-06-04): the cheapest RF gain on the map is real and already built — SessionDrift + LongVol beside gold+oil lift the live book's net by $950 and its pain-window earnings by $582 for $4 of realized drawdown; oil at half risk is the RF-optimal composition (38 vs 23) but is a tester cell, not a dial, because SOLID's $-levers must scale with its lots.**

### Tier 2 — plausible payer, needs a Stage 1 row first

**E. XTIUSD · H1–H4 · post-EIA continuation (Wed 16:30 SAST) · flat single**
Inventory surprise is a scheduled information shock; continuation for hours after is a known pattern in futures literature. Payer: positioned hedgers unwinding. Harness: run `--zcrit 2.5` on the NY session and look at H1 specifically.

**F. US500 / NAS100 · M15–H1 · session-open range breakout · NY**
Index opens are where retail stops cluster. Different instrument class, so diversifying by construction. Cost on index CFDs is lower relative to move than on gold.

**G. EURUSD · H4 · momentum · London**
Deepest market you can reach; the tightest spread-to-move ratio on the platform. Edge is thin and well-arbitraged; worth one Stage 1 row precisely because the cost term is so friendly.

### Tier 3 — no clear payer; test only if the harness volunteers it

Carry/swap on any pair (small at this balance), BTC CFD (cost and weekend gaps), time-of-day seasonality on gold beyond the session buckets already in the harness.

### Explicitly closed

Denser intraday gold signals on this venue. Scalp targets below 3 × cost on any instrument. Both are cost-term failures, not signal failures, and no signal fixes a cost term.

---

## 4. Funnel — test in cost order

| Stage | Question | Tool | Cost per cell | Expected survival |
|---|---|---|---|---|
| **0 — Card** | Which cell, what's the edge, who pays, what kills it | `HYPOTHESIS_CARD.md` | 10 min | ~50% |
| **1 — Signature** | Does the return signature exist on my feed, net of cost, in this session? | `stage1_harness.py` | minutes per instrument, all cells at once | ~20% |
| **2 — Signal** | Does a simple rule capture it? Fires/month, gross edge per fire vs measured `C` | vectorised Python on bars | hours | ~30% |
| **3 — Execution** | Every-tick MT5, shadow logger, pain windows, variant ledger | existing back half | days | ~30% |
| **4 — Promotion** | Demo → live, live-vs-backtest tracking gate | existing | weeks | — |

Compound survival ≈ 1%. That's the base rate for a working factory. The point of Stages 0–1 is that you can push twenty cells a week through them, which is how one survivor a quarter happens.

**Stage 1 pass criteria (pre-committed; `pred_per_cost` term added 09-06 after the first run):** `|z_vr|` or `|t_ac|` ≥ 3.0 on **mid** price, `sig_per_cost` ≥ 1.0, `pred_per_cost` = |ac1|·σ/C ≥ 1.0 (the predictable part of one bar must cover one round-turn; the card rule is 3×), and the signature has the same sign in at least two adjacent sessions or two adjacent horizons. A cell that passes in one session and fails in both neighbours is a look, not a card.

---

## 5. The ledger

Every card gets a row in `FUNNEL_LEDGER.csv` **before** its first test, with the stage it reached and why it died. Two reasons:

1. It is the variant count for the Deflated Sharpe gate. An untracked test is a free draw against the DSR, and free draws are how curve-fits get promoted.
2. In six months it shows which axes produce survivors and which never do. The map redraws itself from evidence instead of from taste.

---

*Keep the `EXPLORED` dict in `stage1_harness.py` in sync with Section 2. When a cell moves from Section 3 to Section 2, it moves with its ledger row and its kill reason.*
