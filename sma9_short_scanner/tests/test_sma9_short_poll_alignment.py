#!/usr/bin/env python3
"""Regression tests for sma9-short exact 5-second boundary polling."""
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


class TestSma9ShortFiveSecondPolling(unittest.TestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        TMP.cleanup()

    def test_poll_constants_have_no_offset_or_alignment(self):
        self.assertEqual(live.POLL_SECONDS, 5)
        for name in ("POLL_OFFSET_SECONDS", "POLL_OFFSET_SEC", "POLL_OFFSET",
                     "next_poll_time", "poll_alignment"):
            self.assertFalse(hasattr(live, name), name)
        self.assertFalse(hasattr(live, "TRAIL_INTERVAL_SECONDS"))
        self.assertFalse(hasattr(live, "SL_INTERVAL_SECONDS"))

    def test_sleep_targets_exact_wall_clock_boundaries(self):
        cases = [
            (datetime(2026, 11, 27, 8, 56, 30, tzinfo=IST), 5.0),
            (datetime(2026, 11, 27, 9, 0, 3, 700000, tzinfo=IST), 1.3),
            (datetime(2026, 11, 27, 9, 0, 5, tzinfo=IST), 5.0),
            (datetime(2026, 11, 27, 9, 59, 59, 500000, tzinfo=IST), 0.5),
        ]
        for now, expected in cases:
            with self.subTest(now=now.isoformat()):
                with patch.object(live, "now_ist", return_value=now), \
                        patch.object(live.time, "sleep") as sleep:
                    live.sleep_to_next_tick()
                sleep.assert_called_once()
                self.assertAlmostEqual(sleep.call_args[0][0], expected, places=6)

    def test_status_exposes_five_seconds_without_alignment(self):
        live.init_db()
        scanner = live.Sma9ShortLiveScanner(object())
        status = scanner._status(
            datetime(2026, 11, 27, 9, 0, 5, tzinfo=IST), {})
        self.assertEqual(status["poll_seconds"], 5)
        self.assertNotIn("poll_alignment", status)
        self.assertNotIn("poll_offset", status)
        self.assertNotIn("trail_interval_seconds", status)
        self.assertNotIn("sl_interval_seconds", status)


if __name__ == "__main__":
    unittest.main()
