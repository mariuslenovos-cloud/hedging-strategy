# Capital Re-Validation Recipe — deploying the book on $10k / $20k

> Purpose: confirm the locked EAs keep their validated **%drawdown** and scale their **dollars**
> proportionally at a bigger starting deposit, BEFORE any real money goes in.
> Written 2026-07-01. Run every test **Every tick**, **Hedging** account, History Quality ≥90%.

## The one principle
- **Risk-normalized streams (silver, oil)** size to %-of-balance → their **%DD is the same at any deposit**;
  net just scales with capital. → *confirmation only* (does margin/stop-out hold at the bigger lots?).
- **Compounding streams (gold)** size = `LotSize × floor(balance/3000)` → base/balance stays ~constant →
  **%DD also deposit-invariant**. → *confirmation only* + margin check.
- **fib C** has `MaxCompoundScale=3` → its base lot **caps at ~0.06 around a $9k balance**. This is the ONLY
  stream that must be re-tuned for $10–20k. Everything else should pass trivially.

---

## PART 1 — GridStat gold / silver / oil  (CONFIRMATION runs)

For each stream: run its **locked config unchanged**, only change the tester **Initial Deposit**.
Use the SAME date window as the original lock so it's apples-to-apples.

| Stream | Symbol (XM / Pepperstone) | Reference (@ $3k) | Locked config essentials |
|---|---|---|---|
| GOLD | GOLD / XAUUSD | PF 3.92 · **eqDD 20%** | grisk=4, MinWinRate=0.55, UseEntrySL=true, BasketMaxLossPct=20, PT=100, MaxConcurrentBaskets=1, risk-norm OFF, compounding ON |
| SILVER | SILVER / XAGUSD | PF 2.60 · **eqDD 8.7%** | grisk=14, MinWinRate=0.5, PT=75, UseRiskNormalizedLots=true/RiskPct=2, MaxConcurrentBaskets=4, BasketMaxLossPct=20, UseEntrySL=true |
| OIL | OILCash / SpotCrude | PF 2.29 · **eqDD 14.9%** | grisk=4, StatsFilterEnabled=false, RiskPct=2.5, MaxConcurrentBaskets=3, PT=100, UseEntrySL=false, BasketMaxLossPct=10, UseSizingTable=true, MaxSizeMult=2.0 |

**Runs per stream:** Initial Deposit = **$10,000**, then **$20,000**.

**PASS if ALL of:**
1. Equity DD% within **~+2pp** of the reference (gold ≤~22%, silver ≤~11%, oil ≤~17%).
2. Net profit ≈ **scales with the deposit** (roughly 3.3× the $3k figure at $10k, 6.7× at $20k).
3. **No margin call / stop-out** — check the report has zero "stop out"; equity never dives toward 0.
   (This is the real thing to watch at $20k: gold runs ~0.12 base lots and oil runs 3 concurrent baskets
   of bigger lots — confirm the account has margin headroom for the deepest simultaneous stack.)
4. Trade count ≈ unchanged vs the $3k run (same signals; only lot size changed).

**FAIL → action:** if only the margin/stop-out fails at $20k (DD% fine), the edge is intact — you're just
over-levered for that balance: drop the stream's risk (silver/oil `RiskPctPerTrade` down a notch, or gold
won't over-lever since it's flat-lot) OR give the stream more of the $20k slice. If DD% blows out, stop and
report the run — that would mean a compounding/margin interaction to investigate (not expected).

---

## PART 2 — fib C  (GENUINE re-tune — the deposit-sensitive one)

fib C MT5, locked config (grisk=7, HedgeTriggerPctBal=3, RecoveryTargetUSD=40, UseRecoveryTrail=true,
RecoveryTargetPct=10, UseVolRegimeFilter=true, UseBasketStop=true/30, UseOverextFilter=false).
Reference @ $3k over 2.5yr: net ~$11.1k, **PF 1.72, eqDD 14.5%**.
Use the **same 2.5yr window** (from 2024-01-01) for every fib C run.

### 2a. fib C on $10,000  (its natural sweet spot)
`MaxCompoundScale=3` means base lot maxes at 0.06 around a $9k balance — so a **fresh $10k account trades
0.06 from day one**, which IS the intended mature size. Expect it to just work.
- **Run A** — Initial Deposit $10,000, locked config **unchanged**. Read net / PF / eqDD%.
- **Run B** — same, but `HedgeTriggerPctBal = 4` (we saw the optimal trigger drift 3%→4% from $3k→$10k).
- **Pick** the trigger (3 vs 4) with the better DD-per-dollar; PASS if eqDD ≤ ~15% and net scales ~3×.

### 2b. fib C on $20,000  (choose utilization vs safety)
On $20k the cap=3 holds base at 0.06 → fib C runs at **half intensity** (~7% DD, ~half the %return). Two options:
- **Option SAFE** — leave `MaxCompoundScale=3`. Run Initial Deposit $20,000, locked. Expect ~7% eqDD,
  same *dollars* as the $10k run (capital half-idle, but very safe). PASS = eqDD ~7%, no stop-out.
- **Option FULL** — `MaxCompoundScale = 6` (so at $20k, lotScale 6 → 0.12 base = proportional to the
  $10k/cap-3 case). Run Initial Deposit $20,000. Target: ~**2× the dollars of the SAFE run at ~14.5% eqDD**.
  Also test `HedgeTriggerPctBal ∈ {3,4,5}` here — bigger baskets, the trigger may want to move again.
  **This is the run that MUST pass before you put $20k in fib C at full size.**

**PASS (fib C) if ALL of:**
1. eqDD% ≤ ~15% (Option FULL) / ~7% (Option SAFE).
2. **No margin call** and the **catastrophe floor (BasketMaxLossPct=30) never fires** in the window
   (it's the last-resort ruin cap; if it fires repeatedly at the bigger size, the sizing is too hot).
3. Journal shows the **recovery hedge arming and closing in profit** (`RECOVERY … ARMED` → closed +),
   not churning (many arm/close cycles = trigger too tight for the new size).
4. Net scales sensibly vs the $3k reference (≈3× at $10k full; ≈6× at $20k full).

**FAIL → action:** if eqDD > 15% or the floor fires at $20k-full → step `MaxCompoundScale` back toward 4–5
(or raise `HedgeTriggerPctBal` to 4–5 so recovery arms later) and re-run until DD is in budget.

---

## PART 3 — ONE SHARED ACCOUNT (the actual plan: GridStat + fib C together)
> The user runs **all EAs on ONE account**. This is the decisive constraint — it changes the sizing.

**Three shared-account facts to size around:**
1. **Every EA reads the FULL shared balance** → on one account they collectively risk ~N× the intended
   per-stream amount. You MUST size each one down or the book is over-levered.
2. **Gold is DOUBLED and CORRELATED:** GridStat-gold (magic 57502) + fib C (magic 3168) trade the SAME
   instrument → they draw down **together** in a gold move → their drawdowns **ADD** (no diversification
   between them). Treat the two as **one gold bucket**, not two independent streams.
3. **The tester is single-symbol → it CANNOT show the combined shared-account DD.** Parts 1–2 only validate
   each stream alone. The **combined book DD can only be confirmed by a DEMO FORWARD-RUN** (all EAs live on
   one demo account) watched via the dashboard's **combined-DD + GOLD-vs-fibC-correlation** panel — that is
   the real arbiter, and exactly why those panels exist. Position isolation itself is fine (magics separate).

**Shared-account SIZING (set these BEFORE the Part 1–2 tester runs, so you validate the real live size):**
- **Kill compounding-on-the-shared-pool for both gold strategies:** set `CompoundingBase` ≈ the full account
  (e.g. $10k) or `UseCompounding=false` on **GridStat-gold AND fib C** → each runs BASE lot (0.02) instead of
  compounding up to 0.06 on the shared balance. (This alone cuts each gold stream ~3× on a $10k account and
  stops the two gold grids from stacking to a margin spike together.)
- **Divide the risk-% streams by the stream count:** silver `RiskPctPerTrade` 2 → ~0.7, oil 2.5 → ~0.85.
- **fib C:** because gold is already carried by GridStat-gold, keep fib C conservative — `MaxCompoundScale=1`
  (no compound-up) on the shared account, and its %-triggers (`HedgeTriggerPctBal`, `BasketMaxLossPct`) are
  already %-of-balance so they self-scale; just confirm the combined gold exposure in the demo run.

**Revised expectation:** the diversified "~9.4% combined DD" assumed *separate/uncorrelated* accounts. With
**two correlated gold streams sharing one balance**, realistic combined equity DD is **~20–25%** even after
sizing down. So on a shared account, budget for ~20–25% (~$2–2.5k on $10k, ~$4–5k on $20k), and let the
demo forward-run's combined-DD reading confirm it before scaling capital.

**Sequence:** set the shared-account sizing above → run Parts 1–2 at that reduced size to confirm each stream
still behaves → deploy ALL EAs on ONE demo account → watch the dashboard combined-DD + gold/fibC correlation
for 2–4 weeks → that combined number (not the single-symbol tester) decides the real size and capital.

## Bottom line
- **$10k** is the natural size — GridStat scales, fib C sits right at its designed cap. Lowest-friction start.
- **$20k** works too but fib C needs `MaxCompoundScale=6` + a re-validate to use the extra capital;
  GridStat just needs the margin confirmation.
- **Dollar drawdown to accept:** ~15% of the deposit on the compounding streams = ~$1.5k on $10k, ~$3k on $20k,
  and fib C's tail can dip toward the 30% floor before it catches. Make sure that number is comfortable.
- Recommended path: **validate at $10k → demo forward-run → go live at $10k → scale to $20k** (re-run Part 2b
  Option FULL first) once it's proven on real fills.
