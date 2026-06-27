# Hedging Strategy — Solution Document

> **Created**: 2026-05-14
> **Project path**: `C:\Users\mariu\Downloads\hedging_strategy\`
> **Status**: Scaffold complete — EA modifications pending

---

## Overview

A trend-following hedging system built on two MQL4 expert advisors. The core idea: when a strong trend is confirmed (MA angle + ADX), enter in the trend direction and immediately protect the position with a hedge — either via a pending stop order (v1.0) or a progressive lot basket that closes on combined profit (M5).

---

## The Two EA Variants

### Marius Hedger v1.0
- **File**: `ea/Marius Hedger v1.0.mq4`
- **Target timeframe**: H1 and above
- **Trend filter**: MA angle ≥ 45° AND ADX > 20
- **Entry signal**: Goldminer indicator (ggreen > 0 = BUY, gred > 0 = SELL)
- **Hedge mechanism**: Pending STOP order placed opposite to the main trade on entry
  - BUY open → SELL STOP at `StepMA − PendingTrail (100 pts)`
  - SELL open → BUY STOP at `StepMA + PendingTrail (100 pts)`
  - Pending lot = base lot (× 2 if `DoublePendingLot = true`)
- **Exit**: Hedge basket closes when combined hedge profit ≥ `HedgeProfitThreshold (50 pts)`
- **Trailing**: ATR-based (`ATRPeriod=14`, `ATRMultiplier=2.0`)

### Marius Hedger M5 v1.0
- **File**: `ea/Marius Hedger M5 v1.0.mq4`
- **Target timeframe**: M5
- **Trend filter**: MA angle ≥ 20° AND ADX > 20 (relaxed for 5-min bars)
- **Entry signal**: Same Goldminer indicator
- **Hedge mechanism**: Progressive lot basket — no pending orders
  - Adds to position in same direction with `lot = base × LotMultiplier^count`
  - Closes all BUYs when count ≥ 2 AND buy profit ≥ threshold
  - Closes all SELLs independently on same logic
  - Closes 1 BUY + 1 SELL together if combined profit ≥ threshold
- **Lot sizing**: `0.02 × 2^n` → 0.02, 0.04, 0.08, 0.16 … (martingale-style)
- **Trades per bar**: 1 (prevents same-bar re-entry)

---

## Key Differences

| Aspect | v1.0 | M5 v1.0 |
|--------|------|---------|
| Timeframe | H1+ | M5 |
| MA angle threshold | 45° (strict) | 20° (relaxed) |
| Base lot | 0.01 | 0.02 |
| Hedge method | Pending STOP orders | Progressive lot basket |
| Max exposure | 1 main + 1 hedge | Unbounded (martingale depth) |
| Closure trigger | Hedge basket profit | Per-direction profit threshold |
| Currency threshold | No | Yes (alternative to points) |

---

## Architecture

```
MT4 Terminal
  └── Marius Hedger EA (MQL4)
        ├── Trend detection: Goldminer + MA angle + ADX
        ├── Hedge: pending orders (v1) or basket close (M5)
        ├── Writes: hedger_live_state.csv  → MT4 Files dir
        └── Writes: hedger_account.csv    → MT4 Files dir

Python monitor (this project)
  ├── config.py             all parameters mirroring EA inputs
  ├── position_reader.py    reads live state from MT4 Files dir
  ├── signal_detector.py    Python MA angle + ADX (analytics only)
  ├── hedge_analyser.py     basket health, alerts, EOD summary
  ├── hedger_monitor.py      30s loop + 22:00 UTC EOD cycle
  └── artifacts/
        ├── position_snapshot.csv
        ├── hedge_analysis_log.jsonl
        ├── hedge_alerts.json
        └── eod_reports/
```

---

## EA Input Parameters

### v1.0 Parameters
| Parameter | Default | Purpose |
|-----------|---------|---------|
| `LotSize` | 0.01 | Base position size |
| `StopLoss` | 0 | Fixed SL in points (0 = disabled) |
| `TakeProfit` | 0 | Fixed TP in points (0 = disabled) |
| `MagicNumber` | 12345 | Trade identifier |
| `MA_Period` | 20 | Moving average period |
| `MA_Angle_Threshold` | 45.0° | Minimum MA slope to confirm trend |
| `ADX_Period` | 14 | ADX period |
| `ADX_Threshold` | 20.0 | Minimum ADX to confirm trend |
| `UseTrailOrder` | true | Enable pending order hedging |
| `PendingTrail` | 100 pts | Distance for pending hedge order |
| `PipsInProfit` | 50 pts | Profit level to switch to trailing |
| `HedgeProfitThreshold` | 50 pts | Profit to close hedge basket |
| `DoublePendingLot` | true | Double lot size for hedge order |
| `ATRPeriod` | 14 | ATR period for trailing |
| `ATRMultiplier` | 2.0 | ATR multiplier for trailing stop |
| `UseAtRTrail` | true | Enable ATR-based trailing |
| `UseMaStop` | false | Enable Step MA trailing |
| `UseAutoThreshold` | false | Enable breakeven-based trailing |

### M5 v1.0 Parameters
| Parameter | Default | Purpose |
|-----------|---------|---------|
| `LotSize` | 0.02 | Base position size |
| `LotMultiplier` | 2 | Progressive lot multiplier per position |
| `MA_Angle_Threshold` | 20.0° | Relaxed for M5 bars |
| `ClosePreiousTrade` | true | Close opposing trade on new signal |
| `UseByuSellProfitThreshold` | true | Enable profit-threshold basket closure |
| `BuySellProfitThreshold` | 50 pts | Profit to close all trades in a direction |
| `BuySellProfitThresholdInCurrency` | 0 | Use currency threshold instead (0 = use pts) |
| `tradesperbar` | 1 | Max new trades per bar |

---

## Risk Profile

### v1.0 Risk
- **Defined exposure**: 1 main position + 1 hedge = max 2× base lot at any time
- **Gap risk**: If price gaps through the pending order level, hedge fills at worse price
- **No hard SL by default** (`StopLoss = 0`) — relies on trailing stop only

### M5 v1.0 Risk (Martingale)
Lot exposure by depth with `base=0.02`, `multiplier=2`:

| Depth | New lot | Total exposure |
|-------|---------|----------------|
| 0 | 0.02 | 0.02 |
| 1 | 0.04 | 0.06 |
| 2 | 0.08 | 0.14 |
| 3 | 0.16 | 0.30 |
| 4 | 0.32 | 0.62 |
| 5 | 0.64 | 1.26 |

Python monitor alerts at depth > 4 (`MAX_POSITIONS_PER_SYMBOL = 4`).

---

## EA Modifications Log

Changes made to the MQL4 EA files (append every change — never delete).

| Date | File | Version | Change | Reason |
|------|------|---------|--------|--------|
| 2026-05-14 | `Marius Hedger v1.0.mq4` | v1.0 → v1.1 | Replaced `DisplayChartInfo()` with M5-style panel. Old: 2 labels (MA Angle, Trend Active) in upper-left, white text. New: 5 labels (Angle, Trend Active, Total Profit, Buy Profit, Sell Profit) in upper-right corner. Angle/Trend Active = Red, Total Profit = Green, Buy Profit = Blue, Sell Profit = Red. Updated `OnDeinit()` to delete new label names. | Visual parity with M5 EA — same display for both variants |
| 2026-05-14 | `Marius Hedger v1.0.mq4` | v1.1 → v1.2 | Added `ExportState()` function. Writes `hedger_live_state.csv` (all open positions: time, symbol, ticket, type, lots, open_price, sl, tp, profit, comment, magic) and `hedger_account.csv` (balance, equity, margin, free_margin) to MT4 Files dir every tick but throttled to max once per 5 seconds via `static datetime lastExport`. Called at end of `OnTick()`. | Required for Python monitoring layer to read position state |
| 2026-05-14 | `Marius Hedger M5 v1.0.mq4` | v1.0 → v1.1 | Added `ExportState()` function. Same CSV output as v1.2 above. Called at end of `OnTick()`. | Required for Python monitoring layer to read position state |
| 2026-05-14 | `Marius Hedger v1.0.mq4` | v1.3 → v1.4 | Added `TotalProfitTarget` input (default $200, 0 = disabled). `CheckTotalProfitTarget()` called as first line of `OnTick()` — sums `OrderProfit() + OrderSwap() + OrderCommission()` across all open positions. When total ≥ target: closes all BUYs at Bid, SELLs at Ask, deletes all pending orders, resets `buyPositionOpen`, `sellPositionOpen`, `hedgeActive`, `pendingOrderExists`, `lastPendingOrderPrice`. EA then re-enters on the next Goldminer + MA angle + ADX signal. | Close basket at profit target and restart cleanly |
| 2026-05-14 | `Marius Hedger v1.0.mq4` | v1.2 → v1.3 | Added `ExportBacktestResults()` — called from `OnDeinit()` only when `IsTesting()`. Writes `bt_SYMBOL_MPERIOD_trades.csv` (ticket, times, type, lots, prices, sl, tp, profit) and `bt_SYMBOL_MPERIOD_summary.csv` (trades, win rate, net profit, gross profit/loss, profit factor, expected payoff, Sharpe, recovery factor) to `[MT4]\tester\files\`. Fixed constants: `STAT_PROFIT_TRADES` (not STAT_WIN_TRADES), removed STAT_MAX_DD/MAX_PROFIT/MIN_PROFIT (unavailable in this build). Added version history block at top of file. | Allows Python/Excel analysis of Strategy Tester runs |
| 2026-05-15 | `Marius Hedger v1.0.mq4` | v1.9 → v2.0 | Six optimisation changes: (1) `MaxBasketPositions` 5→2 — caps exposure at 1 primary + 1 hedge; (2) `HedgeProfitThreshold` 50→150 pts — lets winning trends run instead of closing at $1; (3) `MA_Angle_Threshold` 45→55° — filters noise-driven entries; (4) `DoublePendingLot` true→false — keeps hedge lot equal to primary lot; (5) Added `UseATRStopLoss=true` + ATR hard SL computed at entry in `OpenBuyTrade`/`OpenSellTrade` (`ATRMultiplier * ATR(14)` from ask/bid, min-stop-level enforced); (6) Added `SessionStartHour=7` / `SessionEndHour=22` session filter wrapping `buySignal`/`sellSignal` — no new entries outside London/NY window; (7) Removed `OP_SELL` arm from `ManageTrailingPendingOrders` — one pending STOP hedge per original trade only, no recursive hedge-of-hedge chain. | Strategy review found: recursive hedging built martingale-style chains (341 SELL vs 95 BUY in backtest); $1.11 avg profit per trade eroded by spread; no defined risk per trade; 90 trades in 3 hours at thin margin. |
| 2026-05-15 | `Marius Hedger v1.0.mq4` | v1.8 → v1.9 | Removed `bothOpen` guard from `ManageTrailingPendingOrders()`. The guard was preventing `ManageSinglePendingOrder(OP_BUYSTOP)` from being called for an active SELL position after its SELL STOP hedge had triggered — so no BUY STOP was ever placed to protect the live SELL leg. The skip-only logic in `ManageSinglePendingOrder` (v1.8 fix) is sufficient to prevent the cascade without blocking legitimate hedge placement. | v1.8 `bothOpen` guard over-corrected: it blocked ALL pending order management when both sides were open as market positions, which prevented the BUY STOP hedge from being placed for the SELL. |
| 2026-05-15 | `Marius Hedger v1.0.mq4` | v1.7 → v1.8 | Changed error 130 handling from clamp-and-create to skip-and-return in both `OrderSend` and `OrderModify` paths inside `ManageSinglePendingOrder()`. Added `bothOpen` guard at the top of `ManageTrailingPendingOrders()`: when both a BUY and SELL market position are already open, the function returns immediately — no new pending order is placed until one side closes. | v1.7 clamped the pending price to just outside the stop level and placed the order anyway. In the Strategy Tester this price was immediately hit, the stop triggered, a new pending was placed on the next tick, immediately triggered again — cascading into hundreds of SELL positions per minute. Root cause: clamping replaced a safe failure (error 130, no order) with a guaranteed-to-trigger placement. |
| 2026-05-15 | `Marius Hedger v1.0.mq4` | v1.6 → v1.7 | Moved `lastEntryBar` from `static` local to global scope (static locals inside conditionals are unreliable in MT4 Strategy Tester). Changed per-bar guard to lock `lastEntryBar = thisBar` at the TOP of the if-block, before the basket check — ensures the bar is marked processed even when a trade is skipped due to basket full. Added error 130 stop-level validation in `ManageSinglePendingOrder()`: before both `OrderSend` (new order) and `OrderModify` (move existing pending), clamps pending price to `Bid/Ask ± MODE_STOPLEVEL × MODE_POINT` so pending orders are never within the broker's minimum stop distance. | v1.6 guard still produced 77 duplicate open-time groups (152 peak positions) because the static local scope was unreliable and the bar lock only fired in the else branch. Error 130 (`ERR_INVALID_STOPS`) fired when StepMA trail placed pending inside the broker's stop buffer. |
| 2026-05-15 | `Marius Hedger v1.0.mq4` | v1.5 → v1.6 | Added per-bar entry guard (`static datetime lastEntryBar`) — prevents tick-level position stacking that was accumulating 300 positions across 6 backtest days. Added `input int MaxBasketPositions = 5` hard ceiling enforced in same block. Added `CountBasketPositions()` helper. Added `ApplyEmergencyStopLoss(mainType)` — when `OrderSend` fails with `ERR_TRADE_TOO_MANY_ORDERS (148)`, applies ATR-based SL to all unhedged positions of the affected type via `OrderModify`. | Root cause of May 11 -$3,078 loss: stacking bug + error 148 cascade left 300 positions unprotected at backtest end |
| 2026-05-15 | `Marius Hedger v1.0.mq4` | v1.4 → v1.5 | Added `ManageProfitLockOnTrigger()` and `input bool UseProfitLockOnTrigger = true`. Called second in `OnTick()` (after `CheckTotalProfitTarget`). Logic: scans all live positions; when both a BUY and SELL are live with no pending orders, compares their open prices. If `sellEntry > buyEntry`: the trailing SELL STOP triggered above the BUY entry — BUY is in profit — identifies primary trade by open time and closes the profit leg. Inverse: if SELL was primary and BUY STOP triggered below SELL entry, closes the SELL. Resets the relevant `buyPositionOpen`/`sellPositionOpen` state variable on close. | Lock in profits when the hedge order triggers in the main trade's favour |

---

## Decisions Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-05-14 | Use M5 v1.0 as primary test EA | Generates more signals on M5; faster outcome accumulation |
| 2026-05-14 | Python is analytics-only, no trade execution | Avoids race conditions with MQL4 execution |
| 2026-05-14 | Magic number: v1=77701 (fixed input), M5=auto-generated | v1 default changed from 12345. M5 auto-generates hash("MyEA"+symbol+period) % 100000 — unique per chart, cannot clash with MT5 scanner (30032026 > 100000) |
| 2026-05-14 | Alert at martingale depth > 4 | Depth 4 = 0.62 lots total — significant margin risk |
| 2026-05-14 | EA CSV export not yet added | Build Python scaffold first; add ExportState() to EAs in next session |

---

## Pending Tasks

- [x] Add `ExportState()` function to both MQL4 EAs (writes `hedger_live_state.csv` + `hedger_account.csv` to MT4 Files dir) ✅ Done 2026-05-14
- [x] Set `MT4_FILES_DIR` in `config.py` to actual MT4 terminal path ✅ Done 2026-05-14 (`98A82F92176B73A2100FCD1F8ABD7255`)
- [ ] Set unique magic numbers in EA input parameters before live attach
- [x] Display panel for `Marius Hedger v1.0` updated to match M5 layout ✅ Done 2026-05-14
- [ ] Run `hedger_monitor.py` and verify `position_snapshot.csv` populates
- [ ] Define instrument list for each EA variant

---

## Bug Log

| Date | Severity | File | Root Cause | Symptom | Fix |
|------|----------|------|------------|---------|-----|
| — | — | — | — | — | — |

---

## Session Log

### Session 1 — 2026-05-14
- Read and analysed both MQL4 EA files in full
- Documented strategy logic, inputs, hedge mechanisms, and risk profiles
- Scaffolded Python project structure
- Created `CLAUDE.md` (agent memory) and `hedging.md` (this file — solution record)
- EA files copied to `ea/` subfolder; originals remain in project root

### Session 2 — 2026-05-14
- Added M5-style 5-label display panel to `Marius Hedger v1.0` (upper-right, colored labels: Angle/Trend=Red, Total Profit=Green, Buy/Sell Profit=Blue/Red)
- Added `ExportState()` to both EAs: throttled 5s write of `hedger_live_state.csv` + `hedger_account.csv` to MT4 Files dir
- Synced root and `ea/` copies for all 4 EA files — all now identical
- **Remaining before Python monitoring is live**: set `MT4_FILES_DIR` in `config.py` to actual MT4 terminal path, then run `hedger_monitor.py`
