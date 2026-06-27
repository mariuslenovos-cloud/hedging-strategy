"""
system_runner.py — Main monitoring loop for the hedging strategy.

Runs continuously. Every MONITOR_INTERVAL_SECONDS:
  1. Read open positions from MT4 live state export
  2. Read account info
  3. Analyse hedge basket health
  4. Check risk alerts
  5. Snapshot positions for EOD review
  6. Log analysis

At EOD_REVIEW_HOUR_UTC (22:00 UTC daily):
  7. Build EOD summary
  8. Save daily report to artifacts/

Python does NOT place or close trades.
All execution stays in the MQL4 EA.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from config import (
    ARTIFACTS_DIR, MONITOR_INTERVAL_SECONDS, EOD_REVIEW_HOUR_UTC,
    ACTIVE_EA_VERSION, LAYER_CONFIG,
)
from position_reader import read_positions, read_account, snapshot_positions, summarise
from hedge_analyser import analyse_basket, check_alerts, save_alerts, log_analysis, build_eod_summary
from basket_calculator import compute_breakeven, compute_profit_target_price

ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

EOD_REPORTS_DIR = ARTIFACTS_DIR / "eod_reports"
EOD_REPORTS_DIR.mkdir(parents=True, exist_ok=True)

_last_eod_date: str = ""


def run_monitor_cycle() -> None:
    """Single monitoring cycle."""
    positions = read_positions()
    account   = read_account()

    summary = summarise(positions)
    print(
        f"[monitor] {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC | "
        f"EA={ACTIVE_EA_VERSION} | "
        f"positions={summary['open_positions']} "
        f"(buy={summary['buy_count']}, sell={summary['sell_count']}) | "
        f"P&L=${summary['total_profit']:.2f}"
    )

    basket = analyse_basket(positions)
    alerts = check_alerts(positions, account)

    if alerts:
        for a in alerts:
            print(f"  [ALERT {a['level']}] {a['message']}")

    # ── Basket calculator: break-even and profit-target display ──────────────
    if not positions.empty and "type" in positions.columns and "lots" in positions.columns:
        try:
            digits = 5  # default; adjust if symbol known
            pip_val = 1.0  # rough default — needs per-symbol pip_value
            pos_list = [
                {
                    "type":      "buy" if str(row.get("type", "")).upper() in ("BUY", "0") else "sell",
                    "lots":      float(row.get("lots", 0)),
                    "entry":     float(row.get("open_price", 0)),
                    "pip_value": pip_val,
                    "digits":    digits,
                }
                for _, row in positions.iterrows()
                if row.get("lots", 0)
            ]
            if pos_list:
                be = compute_breakeven(pos_list)
                target_usd = LAYER_CONFIG["basket_profit_target_usd"]
                target_px = compute_profit_target_price(pos_list, target_usd)
                be_str = f"{be:.5f}" if be else "N/A"
                tgt_str = f"{target_px:.5f}" if target_px else "N/A"
                print(f"  [basket] breakeven={be_str}  profit_target_${target_usd:.0f}={tgt_str}")
        except Exception as bc_exc:
            print(f"  [basket_calc] {bc_exc}")

    save_alerts(alerts)
    log_analysis(basket, alerts)
    snapshot_positions(positions)


def run_eod_cycle(today: str) -> None:
    """Nightly EOD summary — runs once per calendar day at EOD_REVIEW_HOUR_UTC."""
    from config import ARTIFACTS_DIR
    snapshot_path = ARTIFACTS_DIR / "position_snapshot.csv"
    summary = build_eod_summary(snapshot_path)

    report_path = EOD_REPORTS_DIR / f"eod_report_{today}.json"
    report_path.write_text(
        json.dumps({"date": today, "summary": summary,
                    "generated_at": datetime.now(timezone.utc).isoformat()},
                   indent=2),
        encoding="utf-8",
    )
    print(f"[EOD] Report saved → {report_path.name}")


def main() -> None:
    print(f"[system_runner] Hedging monitor started — EA version: {ACTIVE_EA_VERSION}")
    print(f"[system_runner] Monitor interval: {MONITOR_INTERVAL_SECONDS}s | EOD: {EOD_REVIEW_HOUR_UTC}:00 UTC")

    global _last_eod_date

    while True:
        try:
            run_monitor_cycle()
        except Exception as exc:
            print(f"[system_runner] Monitor cycle error: {exc}")

        # EOD: once per day at EOD_REVIEW_HOUR_UTC
        now = datetime.now(timezone.utc)
        if now.hour == EOD_REVIEW_HOUR_UTC:
            today = now.strftime("%Y-%m-%d")
            if today != _last_eod_date:
                try:
                    run_eod_cycle(today)
                    _last_eod_date = today
                except Exception as exc:
                    print(f"[system_runner] EOD cycle error: {exc}")

        time.sleep(MONITOR_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
