"""
Writes close_signal.json to the MT4 Common Files directory when the basket
hits its profit target.  The EA polls this file each tick and closes all
positions when it finds a matching symbol + close_all action.

Usage (from hedger_monitor.py or standalone):
    from close_signal_writer import CloseSignalWriter
    writer = CloseSignalWriter(mt4_common_files_dir)
    writer.write("XAUUSD", reason="profit_target")
    writer.clear()   # after EA confirms closure
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path


class CloseSignalWriter:
    def __init__(self, mt4_common_files_dir: str):
        self.dir = Path(mt4_common_files_dir)
        self.path = self.dir / "close_signal.json"

    def write(self, symbol: str, reason: str = "profit_target") -> None:
        payload = {
            "symbol": symbol,
            "action": "close_all",
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"[CloseSignal] Written: {payload}")

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()
            print(f"[CloseSignal] Cleared {self.path}")

    def exists(self) -> bool:
        return self.path.exists()

    def read(self) -> dict | None:
        if not self.path.exists():
            return None
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return None


def write_close_signal(mt4_common_files_dir: str, symbol: str, reason: str = "profit_target") -> None:
    CloseSignalWriter(mt4_common_files_dir).write(symbol, reason)
