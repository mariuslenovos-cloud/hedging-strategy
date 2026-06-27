"""
Basket break-even, profit target and drawdown projections for the 3-layer hedge system.

Layer 0: trend entry         — lot=L,  direction=original
Layer 1: hedge counter       — lot=2L, direction=opposite,  entry = L0_entry ± D
Layer 2: recovery original   — lot=3L, direction=original,  entry = L1_entry ∓ D  (≈ L0_entry)

All prices in instrument price units (e.g. XAUUSD in USD/oz).
All P&L in account currency (uses pip_value parameter).
"""

from typing import List, Dict


def basket_pnl(positions: List[Dict], price: float) -> float:
    """
    Compute total basket P&L at a hypothetical closing price.

    positions: list of dicts with keys:
        type  : "buy" or "sell"
        lots  : float
        entry : float  (open price)
        pip_value : float  (account currency per 1-point move on 1 standard lot)
        digits    : int    (decimal places, used to compute point size)
    price: hypothetical close price
    """
    total = 0.0
    for p in positions:
        point = 10 ** (-p["digits"])
        direction = 1.0 if p["type"] == "buy" else -1.0
        pnl = direction * (price - p["entry"]) / point * p["pip_value"] * p["lots"]
        total += pnl
    return total


def compute_breakeven(positions: List[Dict]) -> float:
    """
    Return the price at which basket P&L == 0 via binary search.
    Returns None if basket has no net directional exposure (flat).
    """
    if not positions:
        return None

    lo = min(p["entry"] for p in positions) * 0.5
    hi = max(p["entry"] for p in positions) * 2.0

    pnl_lo = basket_pnl(positions, lo)
    pnl_hi = basket_pnl(positions, hi)

    if pnl_lo * pnl_hi > 0:
        return None  # no crossover in range — flat basket or unusual config

    for _ in range(60):
        mid = (lo + hi) / 2.0
        if basket_pnl(positions, mid) * pnl_lo > 0:
            lo = mid
        else:
            hi = mid

    return (lo + hi) / 2.0


def compute_profit_target_price(positions: List[Dict], target_usd: float) -> float:
    """
    Return the price at which basket P&L reaches target_usd.
    Scans in both directions from current range.
    Returns None if target is not reachable within 3× the basket range.
    """
    if not positions:
        return None

    entries = [p["entry"] for p in positions]
    mid_entry = sum(entries) / len(entries)

    # Expand search window exponentially until target is bracketed (max 20 doublings)
    for multiplier in [0.001 * (2 ** k) for k in range(20)]:
        lo_search = mid_entry * (1 - multiplier)
        hi_search = mid_entry * (1 + multiplier)
        pnl_lo = basket_pnl(positions, lo_search)
        pnl_hi = basket_pnl(positions, hi_search)

        for a, b, pa, pb in [
            (mid_entry, hi_search, basket_pnl(positions, mid_entry), pnl_hi),
            (lo_search, mid_entry, pnl_lo, basket_pnl(positions, mid_entry)),
        ]:
            if (pa - target_usd) * (pb - target_usd) < 0:
                for _ in range(60):
                    m = (a + b) / 2.0
                    if (basket_pnl(positions, m) - target_usd) * (pa - target_usd) > 0:
                        a = m
                    else:
                        b = m
                return (a + b) / 2.0
    return None


def compute_max_additional_drawdown(
    positions: List[Dict],
    next_layer_lots: float,
    next_layer_price: float,
    next_layer_type: str,
    stop_distance_points: float,
) -> float:
    """
    Estimate worst-case additional drawdown if the next layer is added and
    immediately hits a stop_distance_points adverse move.
    Returns USD loss (positive = loss).
    """
    if not positions:
        return 0.0
    p0 = positions[0]
    point = 10 ** (-p0["digits"])
    direction = 1.0 if next_layer_type == "buy" else -1.0
    loss = stop_distance_points * p0["pip_value"] * next_layer_lots
    return loss


def compute_pnl_curve(
    positions: List[Dict],
    price_lo: float,
    price_hi: float,
    steps: int = 200,
) -> List[Dict]:
    """
    Return a list of {price, pnl} dicts over the range [price_lo, price_hi].
    """
    step = (price_hi - price_lo) / max(steps - 1, 1)
    curve = []
    for i in range(steps):
        p = price_lo + i * step
        curve.append({"price": round(p, 5), "pnl": round(basket_pnl(positions, p), 2)})
    return curve


# ── Quick self-test ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    # BUY 0.01 at 1.1000, SELL 0.02 at 1.0990, BUY 0.03 at 1.1000
    # pip_value for EURUSD: ~$1 per 0.0001 per 0.01 lot → 1.0 per lot per point on 5-digit
    PV = 1.0  # $1 per point per standard lot on 5-digit broker
    positions = [
        {"type": "buy",  "lots": 0.01, "entry": 1.1000, "pip_value": PV, "digits": 5},
        {"type": "sell", "lots": 0.02, "entry": 1.0990, "pip_value": PV, "digits": 5},
        {"type": "buy",  "lots": 0.03, "entry": 1.1000, "pip_value": PV, "digits": 5},
    ]
    be = compute_breakeven(positions)
    target = compute_profit_target_price(positions, 5.0)
    print(f"Breakeven price : {be:.5f}  (expected ~1.10100)")
    print(f"Profit target $5: {target:.5f}")
    curve = compute_pnl_curve(positions, 1.098, 1.104, steps=10)
    for row in curve:
        print(f"  price={row['price']:.5f}  pnl=${row['pnl']:.2f}")
