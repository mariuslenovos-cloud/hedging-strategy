"""
position_reader.py — Read open positions and account state from MT4 via CSV export.

The MQL4 EA writes a live_state.csv to its Files directory on every tick.
Python reads it here for monitoring and analytics.

CSV columns the EA should export (add ExportState() call to EA if not present):
  time, symbol, ticket, type, lots, open_price, sl, tp, profit, comment, magic
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from config import ARTIFACTS_DIR, MT4_FILES_DIR, EA_PARAMS

LIVE_STATE_PATH   = MT4_FILES_DIR / "hedger_live_state.csv"
SNAPSHOT_PATH     = ARTIFACTS_DIR / "position_snapshot.csv"
ACCOUNT_INFO_PATH = MT4_FILES_DIR / "hedger_account.csv"


def read_positions() -> pd.DataFrame:
    """
    Read current open positions from MT4 live state export.
    Returns empty DataFrame if file not found or unreadable.
    """
    if not LIVE_STATE_PATH.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(LIVE_STATE_PATH, on_bad_lines="skip")
        df["read_at_utc"] = datetime.now(timezone.utc).isoformat()
        # Filter to this EA's magic number
        magic = EA_PARAMS.get("magic_number", 0)
        if "magic" in df.columns and magic:
            df = df[df["magic"] == magic].copy()
        return df
    except Exception as exc:
        print(f"[pos_reader] Could not read live state: {exc}")
        return pd.DataFrame()


def read_account() -> dict:
    """Read account balance/equity from MT4 export."""
    if not ACCOUNT_INFO_PATH.exists():
        return {}
    try:
        df = pd.read_csv(ACCOUNT_INFO_PATH, on_bad_lines="skip")
        if df.empty:
            return {}
        row = df.iloc[-1]
        return {
            "balance":  float(row.get("balance",  0)),
            "equity":   float(row.get("equity",   0)),
            "margin":   float(row.get("margin",   0)),
            "free_margin": float(row.get("free_margin", 0)),
            "read_at":  datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        print(f"[pos_reader] Could not read account: {exc}")
        return {}


def snapshot_positions(positions: pd.DataFrame) -> None:
    """Append current positions to a rolling snapshot CSV for EOD review."""
    if positions.empty:
        return
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    positions.to_csv(
        SNAPSHOT_PATH, mode="a",
        header=not SNAPSHOT_PATH.exists(), index=False,
    )


def summarise(positions: pd.DataFrame) -> dict:
    """Return a quick P&L and position summary."""
    if positions.empty:
        return {"open_positions": 0, "total_lots": 0.0, "total_profit": 0.0,
                "buy_count": 0, "sell_count": 0}

    buy_mask  = positions["type"].str.upper().isin(["BUY", "0"])  if "type"  in positions.columns else pd.Series(False, index=positions.index)
    sell_mask = positions["type"].str.upper().isin(["SELL", "1"]) if "type"  in positions.columns else pd.Series(False, index=positions.index)

    return {
        "open_positions": len(positions),
        "total_lots":     float(positions["lots"].sum())   if "lots"   in positions.columns else 0.0,
        "total_profit":   float(positions["profit"].sum()) if "profit" in positions.columns else 0.0,
        "buy_count":      int(buy_mask.sum()),
        "sell_count":     int(sell_mask.sum()),
        "symbols":        positions["symbol"].unique().tolist() if "symbol" in positions.columns else [],
    }
