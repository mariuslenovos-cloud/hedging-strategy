"""
signal_detector.py — Python reimplementation of the EA's trend detection logic.

Used for:
  - Analytics: compare what EA "should" be doing vs what it is doing
  - Logging: record signal states for EOD review
  - Future: feed into Python-side alert when trend activates on a new symbol

Mirrors the MQL4 logic:
  IsUptrend   = MA_Angle >= MA_Angle_Threshold
  IsDowntrend = MA_Angle <= -MA_Angle_Threshold
  IsADXTrend  = ADX > ADX_Threshold AND (+DI != -DI)
  TrendActive = IsADXTrend AND (IsUptrend OR IsDowntrend)
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

try:
    import MetaTrader5 as mt5
    _HAS_MT5 = False   # MT4-connected system — set True only if MT5 also available
except ImportError:
    _HAS_MT5 = False

from config import EA_PARAMS


# ── Indicator helpers ─────────────────────────────────────────────────────────

def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _ma_angle(close: pd.Series, period: int, lookback: int = 2) -> pd.Series:
    """
    Compute MA slope angle in degrees using price difference over `lookback` bars.
    Positive = upward slope, negative = downward.
    """
    ma = _ema(close, period)
    diff = ma.diff(lookback)
    # Normalise: treat 1 point of price change over `lookback` bars as reference
    angle = diff.apply(lambda d: math.degrees(math.atan(d)) if pd.notna(d) else 0.0)
    return angle


def _adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.DataFrame:
    """
    Compute ADX, +DI, -DI.
    Returns DataFrame with columns: adx, plus_di, minus_di.
    """
    # True range
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)

    # Directional movement
    up_move   = high - high.shift(1)
    down_move = low.shift(1) - low
    plus_dm   = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm  = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    # Smoothed
    atr_s     = tr.ewm(span=period, adjust=False).mean()
    plus_di   = 100 * plus_dm.ewm(span=period, adjust=False).mean() / atr_s
    minus_di  = 100 * minus_dm.ewm(span=period, adjust=False).mean() / atr_s

    dx = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1))
    adx_val = dx.ewm(span=period, adjust=False).mean()

    return pd.DataFrame({"adx": adx_val, "plus_di": plus_di, "minus_di": minus_di})


# ── Signal detection ──────────────────────────────────────────────────────────

def detect_trend(ohlcv: pd.DataFrame, params: Optional[dict] = None) -> pd.DataFrame:
    """
    Given an OHLCV DataFrame (columns: open, high, low, close, volume, time),
    compute trend activation columns mirroring the EA logic.

    Returns the same DataFrame with added columns:
      ma_angle, adx, plus_di, minus_di,
      is_uptrend, is_downtrend, is_adx_trend, trend_active, signal_side
    """
    if params is None:
        params = EA_PARAMS

    ma_period   = int(params.get("ma_period", 20))
    ma_thresh   = float(params.get("ma_angle_threshold", 20.0))
    adx_period  = int(params.get("adx_period", 14))
    adx_thresh  = float(params.get("adx_threshold", 20.0))

    df = ohlcv.copy()
    df["ma_angle"]  = _ma_angle(df["close"], ma_period)
    adx_df          = _adx(df["high"], df["low"], df["close"], adx_period)
    df["adx"]       = adx_df["adx"]
    df["plus_di"]   = adx_df["plus_di"]
    df["minus_di"]  = adx_df["minus_di"]

    df["is_uptrend"]   = df["ma_angle"] >= ma_thresh
    df["is_downtrend"] = df["ma_angle"] <= -ma_thresh
    df["is_adx_trend"] = (df["adx"] > adx_thresh) & (df["plus_di"] != df["minus_di"])
    df["trend_active"] = df["is_adx_trend"] & (df["is_uptrend"] | df["is_downtrend"])

    df["signal_side"] = "NONE"
    df.loc[df["trend_active"] & df["is_uptrend"],   "signal_side"] = "BUY"
    df.loc[df["trend_active"] & df["is_downtrend"], "signal_side"] = "SELL"

    return df


def latest_signal(ohlcv: pd.DataFrame, params: Optional[dict] = None) -> dict:
    """Return the most recent bar's trend signal as a dict."""
    df = detect_trend(ohlcv, params)
    if df.empty:
        return {"signal_side": "NONE", "trend_active": False}
    row = df.iloc[-1]
    return {
        "signal_side":   str(row["signal_side"]),
        "trend_active":  bool(row["trend_active"]),
        "ma_angle":      round(float(row["ma_angle"]), 2),
        "adx":           round(float(row["adx"]), 2),
        "plus_di":       round(float(row["plus_di"]), 2),
        "minus_di":      round(float(row["minus_di"]), 2),
        "computed_at":   datetime.now(timezone.utc).isoformat(),
    }
