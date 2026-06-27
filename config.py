"""
config.py — Central configuration for the hedging strategy system.

Two EA variants are supported:
  - v1.0  (H1+): pending-order hedging, 45-degree MA angle threshold
  - M5    (M5):  progressive lot multiplier, profit-threshold basket closure

Python layer monitors positions and provides analytics/alerting.
All execution remains in the MQL4 EA.
"""
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR      = Path(__file__).parent
ARTIFACTS_DIR = BASE_DIR / "artifacts"
EA_DIR        = BASE_DIR / "ea"  # local backup copies

# Live EA location — edit files here, then keep ea/ in sync as backup
MT4_EXPERTS_DIR = Path(
    r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal"
    r"\98A82F92176B73A2100FCD1F8ABD7255\MQL4\Experts"
)

# MT4 terminal Files directory — EA writes hedger_live_state.csv + hedger_account.csv here
MT4_FILES_DIR = Path(
    r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal"
    r"\98A82F92176B73A2100FCD1F8ABD7255\MQL4\Files"
)

# ── Strategy mode ────────────────────────────────────────────────────────────
# "v1"  → Marius Hedger v1.0  (H1 pending-order hedging)
# "m5"  → Marius Hedger M5 v1.0 (M5 progressive lot hedging)
ACTIVE_EA_VERSION = "m5"

# ── Instrument universe ──────────────────────────────────────────────────────
# Symbols the Python monitor tracks (must match broker symbol names exactly)
SYMBOLS = [
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "XAUUSD",
    "US30",
    "US100",
]

# ── EA parameters (mirrors MQL4 inputs — for analytics only) ─────────────────
# v1.0
V1_PARAMS = {
    "magic_number":          77701,
    "lot_size":              0.01,
    "ma_period":             20,
    "ma_angle_threshold":    45.0,
    "adx_period":            14,
    "adx_threshold":         20.0,
    "pending_trail":         100,       # points
    "pips_in_profit":        50,        # points
    "hedge_profit_threshold": 50,       # points
    "double_pending_lot":    True,
    "atr_period":            14,
    "atr_multiplier":        2.0,
}

# M5 v1.0
M5_PARAMS = {
    "magic_number":                   None,    # Auto-generated per symbol/period by EA (hash % 100000)
    "lot_size":                       0.02,
    "lot_multiplier":                 2,
    "ma_period":                      20,
    "ma_angle_threshold":             20.0,
    "adx_period":                     14,
    "adx_threshold":                  20.0,
    "close_previous_trade":           True,
    "use_buy_sell_profit_threshold":  True,
    "buy_sell_profit_threshold":      50,      # points
    "buy_sell_profit_in_currency":    0,       # 0 = use points
    "atr_period":                     14,
    "atr_multiplier":                 2.0,
    "trades_per_bar":                 1,
}

# Active params (selected by ACTIVE_EA_VERSION)
EA_PARAMS = M5_PARAMS if ACTIVE_EA_VERSION == "m5" else V1_PARAMS

# ── Monitor loop timings ──────────────────────────────────────────────────────
MONITOR_INTERVAL_SECONDS = 30     # how often Python reads position state
EOD_REVIEW_HOUR_UTC      = 22     # hour to run nightly review

# ── MT4 Common Files directory (for cross-terminal files like close_signal.json) ─
MT4_COMMON_FILES_DIR = Path(
    r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\Common\Files"
)

# ── 3-Layer Recovery Strategy parameters ─────────────────────────────────────
LAYER_CONFIG = {
    "atr_d_multiplier":    0.75,   # ATR(14) × this = trigger distance D (matches EA input)
    "min_d_points":        30,     # minimum D in points (noise filter)
    "max_d_points":        500,    # maximum D in points (volatility cap)
    "layer1_lot_mult":     2.0,    # Layer 1 lot = base × this
    "layer2_lot_mult":     3.0,    # Layer 2 lot = base × this
    "basket_profit_target_usd": 50.0,  # close all when basket P&L reaches this
    "max_simultaneous_baskets":  2,    # block new Layer 0 entry when this many baskets active
}

# Correlated pair groups — if two symbols in the same group both have active
# baskets in the same direction, block new entries on the second symbol.
CORRELATED_PAIRS = [
    ["EURUSD", "GBPUSD"],
    ["USDJPY", "USDCHF"],
    ["XAUUSD"],     # standalone
    ["US30", "US100"],
]

# ── Risk limits (Python-side safety) ─────────────────────────────────────────
# These are alerting thresholds only — Python does not execute trades.
MAX_OPEN_DRAWDOWN_USD    = 200.0  # alert if open P&L drops below this
MAX_DAILY_LOSS_USD       = 300.0  # alert if day's realised loss exceeds this
MAX_POSITIONS_PER_SYMBOL = 4      # alert if EA exceeds this (progressive lot)
