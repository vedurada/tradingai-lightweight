#!/usr/bin/env python3
"""Regression tests for sma9-short 5m boundary+10s polling."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch
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


class TestSma9ShortPollAlignment(unittest.TestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        TMP.cleanup()

    def test_poll_constants_match_sma9_5min(self):
        self.assertEqual(live.POLL_SECONDS, 300)
        self.assertEqual(live.POLL_OFFSET_SEC, 10)
        self.assertFalse(hasattr(live, "TRAIL_INTERVAL_SECONDS"))
        self.assertFalse(hasattr(live, "SL_INTERVAL_SECONDS"))

    def test_next_poll_time_uses_boundary_plus_ten_seconds(self):
        cases = [
            (datetime(2026, 11, 27, 8, 56, 30, tzinfo=IST),
             datetime(2026, 11, 27, 9, 0, 10, tzinfo=IST)),
            (datetime(2026, 11, 27, 9, 0, 9, 500000, tzinfo=IST),
             datetime(2026, 11, 27, 9, 0, 10, tzinfo=IST)),
            (datetime(2026, 11, 27, 9, 0, 10, tzinfo=IST),
             datetime(2026, 11, 27, 9, 5, 10, tzinfo=IST)),
        ]
        for now, expected in cases:
            with self.subTest(now=now.isoformat()):
                self.assertEqual(live.next_poll_time(now), expected)

    def test_sleep_targets_next_boundary_plus_ten_seconds(self):
        now = datetime(2026, 11, 27, 8, 56, 30, tzinfo=IST)
        with patch.object(live, "now_ist", return_value=now), \
                patch.object(live.time, "sleep") as sleep:
            live.sleep_to_next_tick()
        sleep.assert_called_once_with(220.0)

    def test_status_exposes_poll_alignment(self):
        live.init_db()
        scanner = live.Sma9ShortLiveScanner(object())
        status = scanner._status(
            datetime(2026, 11, 27, 9, 0, 10, tzinfo=IST), {})
        self.assertEqual(status["poll_seconds"], 300)
        self.assertEqual(status["poll_alignment"], "5m_boundary_plus_10s")
        self.assertNotIn("trail_interval_seconds", status)
        self.assertNotIn("sl_interval_seconds", status)


if __name__ == "__main__":
    unittest.main()
