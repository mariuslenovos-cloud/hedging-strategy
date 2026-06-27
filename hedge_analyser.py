"""
hedge_analyser.py — Analytics layer for the hedging EA.

Reads position snapshots and computes:
  - Hedge basket health (buy vs sell balance, combined P&L)
  - Progressive lot exposure (M5 version: how deep into the martingale)
  - Drawdown alerts
  - Daily P&L summary

Does NOT execute any trades. All execution stays in the MQL4 EA.
"""
from __future__ import annotations

import json
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from config import (
    ARTIFACTS_DIR, EA_PARAMS, ACTIVE_EA_VERSION,
    MAX_OPEN_DRAWDOWN_USD, MAX_DAILY_LOSS_USD, MAX_POSITIONS_PER_SYMBOL,
)

ANALYSIS_LOG_PATH = ARTIFACTS_DIR / "hedge_analysis_log.jsonl"
ALERTS_PATH       = ARTIFACTS_DIR / "hedge_alerts.json"


# ── Basket analysis ───────────────────────────────────────────────────────────

def analyse_basket(positions: pd.DataFrame) -> dict:
    """
    Compute hedge basket metrics from current open positions.
    Mirrors the EA's internal basket logic for monitoring.
    """
    if positions.empty:
        return _empty_basket()

    result: dict = {"timestamp": datetime.now(timezone.utc).isoformat()}

    for symbol in positions["symbol"].unique() if "symbol" in positions.columns else []:
        sym_pos = positions[positions["symbol"] == symbol]

        buy_pos  = sym_pos[sym_pos["type"].str.upper().isin(["BUY",  "0"])] if "type" in sym_pos.columns else sym_pos.iloc[0:0]
        sell_pos = sym_pos[sym_pos["type"].str.upper().isin(["SELL", "1"])] if "type" in sym_pos.columns else sym_pos.iloc[0:0]

        buy_lots   = float(buy_pos["lots"].sum())   if "lots"   in buy_pos.columns   else 0.0
        sell_lots  = float(sell_pos["lots"].sum())  if "lots"   in sell_pos.columns  else 0.0
        buy_profit = float(buy_pos["profit"].sum()) if "profit" in buy_pos.columns   else 0.0
        sell_profit= float(sell_pos["profit"].sum())if "profit" in sell_pos.columns  else 0.0

        net_profit = buy_profit + sell_profit
        hedge_depth = max(len(buy_pos), len(sell_pos))

        result[symbol] = {
            "buy_count":    len(buy_pos),
            "sell_count":   len(sell_pos),
            "buy_lots":     round(buy_lots,  2),
            "sell_lots":    round(sell_lots, 2),
            "buy_profit":   round(buy_profit,  2),
            "sell_profit":  round(sell_profit, 2),
            "net_profit":   round(net_profit,  2),
            "hedge_depth":  hedge_depth,
            "is_hedged":    len(buy_pos) > 0 and len(sell_pos) > 0,
        }

    return result


def _empty_basket() -> dict:
    return {"timestamp": datetime.now(timezone.utc).isoformat(), "open_positions": 0}


# ── Alert logic ───────────────────────────────────────────────────────────────

def check_alerts(positions: pd.DataFrame, account: dict) -> list[dict]:
    """
    Check risk thresholds. Returns list of active alerts (empty = all clear).
    """
    alerts: list[dict] = []
    now = datetime.now(timezone.utc).isoformat()

    if not positions.empty and "profit" in positions.columns:
        open_pnl = float(positions["profit"].sum())
        if open_pnl < -MAX_OPEN_DRAWDOWN_USD:
            alerts.append({
                "level":   "HIGH",
                "type":    "open_drawdown",
                "value":   round(open_pnl, 2),
                "limit":   -MAX_OPEN_DRAWDOWN_USD,
                "message": f"Open P&L ${open_pnl:.2f} exceeds drawdown limit ${MAX_OPEN_DRAWDOWN_USD:.2f}",
                "at":      now,
            })

    if not positions.empty and "symbol" in positions.columns:
        for sym in positions["symbol"].unique():
            sym_count = len(positions[positions["symbol"] == sym])
            if sym_count > MAX_POSITIONS_PER_SYMBOL:
                alerts.append({
                    "level":   "MEDIUM",
                    "type":    "position_count",
                    "symbol":  sym,
                    "count":   sym_count,
                    "limit":   MAX_POSITIONS_PER_SYMBOL,
                    "message": f"{sym} has {sym_count} open positions (limit {MAX_POSITIONS_PER_SYMBOL})",
                    "at":      now,
                })

    return alerts


def save_alerts(alerts: list[dict]) -> None:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    ALERTS_PATH.write_text(
        json.dumps({"alerts": alerts, "updated_at": datetime.now(timezone.utc).isoformat()},
                   indent=2),
        encoding="utf-8",
    )


# ── Logging ───────────────────────────────────────────────────────────────────

def log_analysis(basket: dict, alerts: list[dict]) -> None:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    entry = {"basket": basket, "alert_count": len(alerts), "alerts": alerts}
    with ANALYSIS_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


# ── EOD summary ───────────────────────────────────────────────────────────────

def build_eod_summary(snapshot_path: Path) -> dict:
    """Read today's position snapshots and build a daily P&L summary."""
    if not snapshot_path.exists():
        return {"status": "no_data"}

    df = pd.read_csv(snapshot_path, on_bad_lines="skip")
    if df.empty or "profit" not in df.columns:
        return {"status": "no_data"}

    today = date.today().isoformat()
    if "read_at_utc" in df.columns:
        df["date"] = pd.to_datetime(df["read_at_utc"], utc=True, errors="coerce").dt.date.astype(str)
        df = df[df["date"] == today]

    if df.empty:
        return {"status": "no_data_today"}

    return {
        "date":           today,
        "total_snapshots":len(df),
        "max_open_profit":round(float(df["profit"].max()), 2),
        "min_open_profit":round(float(df["profit"].min()), 2),
        "avg_open_profit":round(float(df["profit"].mean()), 2),
        "symbols_active": df["symbol"].unique().tolist() if "symbol" in df.columns else [],
    }
