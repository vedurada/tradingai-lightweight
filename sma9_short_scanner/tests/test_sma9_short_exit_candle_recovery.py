#!/usr/bin/env python3
"""Restart recovery for the sma9-short exit-candle re-entry block."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app")
if APP not in sys.path:
    sys.path.insert(0, APP)

TMP = tempfile.TemporaryDirectory()
OLD_DB_PATH = os.environ.get("SMA9_SHORT_DB_PATH")
os.environ["SMA9_SHORT_DB_PATH"] = os.path.join(TMP.name, "sma9_short.db")

import live_sma9_short_scanner as live  # noqa: E402

if OLD_DB_PATH is None:
    os.environ.pop("SMA9_SHORT_DB_PATH", None)
else:
    os.environ["SMA9_SHORT_DB_PATH"] = OLD_DB_PATH

IST = ZoneInfo("Asia/Kolkata")


def _trade(trade_id: str, exit_timestamp: str) -> dict:
    return {
        "trade_id": trade_id,
        "strategy_id": "sma9_short",
        "instrument": "NIFTY",
        "trade_date": "2026-11-27",
        "option_type": "CE",
        "strike": 25550.0,
        "expiry": "2026-12-22",
        "signal_timestamp": "2026-11-27T11:15:00+05:30",
        "entry_timestamp": "2026-11-27T11:15:05+05:30",
        "entry_price": 98.0,
        "exit_timestamp": exit_timestamp,
        "exit_price": 99.0,
        "exit_reason": "TRAIL_STOP_EXIT",
        "pnl_points": -1.0,
        "status": "CLOSED",
        "created_at": "2026-11-27T11:15:05+05:30",
        "updated_at": exit_timestamp,
        "dataset": "LIVE",
        "entry_candle_start": "2026-11-27T11:15:00+05:30",
        "entry_candle_end": "2026-11-27T11:20:00+05:30",
    }


class TestSma9ShortExitCandleRecovery(unittest.TestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        TMP.cleanup()

    def test_recover_open_positions_restores_last_exit_candle(self):
        live.init_db()
        trades = [
            _trade("RECOVERY-CE-OLD", "2026-11-27T09:33:45+05:30"),
            _trade("RECOVERY-CE-NEW", "2026-11-27T11:23:45+05:30"),
        ]
        cols = [c.strip() for c in live.TRADE_COLUMNS.split(",")]
        placeholders = ",".join("?" for _ in cols)
        conn = live.db_conn()
        try:
            for trade in trades:
                conn.execute(
                    f"INSERT OR REPLACE INTO sma9_short_trades "
                    f"({','.join(cols)}) VALUES ({placeholders})",
                    tuple(trade.get(c) for c in cols),
                )
            conn.commit()
        finally:
            conn.close()

        scanner = live.Sma9ShortLiveScanner(object())
        scanner.recover_open_positions()

        self.assertEqual(
            scanner.states["CE"].exited_candle,
            datetime(2026, 11, 27, 11, 20, tzinfo=IST),
        )
        self.assertIsNone(scanner.states["PE"].exited_candle)


if __name__ == "__main__":
    unittest.main()
