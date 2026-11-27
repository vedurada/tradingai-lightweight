#!/usr/bin/env python3
"""Regression tests for the 5-minute sma9-short poll/trail/SL intervals."""
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


class TestSma9ShortIntervals(unittest.TestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        TMP.cleanup()

    def test_all_intervals_are_five_minutes(self):
        self.assertEqual(live.POLL_SECONDS, 300)
        self.assertEqual(live.TRAIL_INTERVAL_SECONDS, 300)
        self.assertEqual(live.SL_INTERVAL_SECONDS, 300)

    def test_interval_due_respects_elapsed_time(self):
        self.assertTrue(live._interval_due(None, 100.0, 300))
        self.assertFalse(live._interval_due(100.0, 399.9, 300))
        self.assertTrue(live._interval_due(100.0, 400.0, 300))

    def test_sleep_aligns_to_wall_clock_five_minute_boundary(self):
        now = datetime(2026, 11, 27, 8, 56, 30, tzinfo=IST)
        with patch.object(live, "now_ist", return_value=now), \
                patch.object(live.time, "sleep") as sleep:
            live.sleep_to_next_tick()
        sleep.assert_called_once_with(210.0)

    def test_status_exposes_poll_trail_and_sl_intervals(self):
        live.init_db()
        scanner = live.Sma9ShortLiveScanner(object())
        status = scanner._status(
            datetime(2026, 11, 27, 9, 0, tzinfo=IST), {})
        self.assertEqual(status["poll_seconds"], 300)
        self.assertEqual(status["trail_interval_seconds"], 300)
        self.assertEqual(status["sl_interval_seconds"], 300)


if __name__ == "__main__":
    unittest.main()
