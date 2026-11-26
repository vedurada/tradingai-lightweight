#!/usr/bin/env python3
"""Regression tests for the corrected legacy SMA9 package (BUY ONLY)."""

import os
import sys
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

CODE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if CODE_ROOT not in sys.path:
    sys.path.insert(0, CODE_ROOT)

from sma9_only.scanner import (  # noqa: E402
    Sma9Scanner, MarketData, build_sma9_signal, compute_sma9_signals,
    compute_previous_sma9,
)
from sma9_only import STRATEGY_TYPE, MAX_POSITIONS  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
START = datetime(2026, 11, 6, 10, 0, tzinfo=IST)


def make_candles(completed_closes, entry_open, entry_close):
    """9 completed candles plus one entry candle."""
    assert len(completed_closes) == 9
    rows = []
    prev = float(completed_closes[0])
    for i, close in enumerate(completed_closes):
        ts = START + timedelta(minutes=5 * i)
        rows.append({
            "timestamp": ts.isoformat(),
            "open": prev,
            "high": max(prev, close) + 1,
            "low": min(prev, close) - 1,
            "close": float(close),
        })
        prev = float(close)
    ts = START + timedelta(minutes=45)
    rows.append({
        "timestamp": ts.isoformat(),
        "open": float(entry_open),
        "high": float(entry_open) + 10,
        "low": float(entry_open) - 10,
        "close": float(entry_close),
    })
    return rows


class TestLegacySma9Package(unittest.TestCase):
    def test_strategy_metadata_is_buy_only(self):
        self.assertEqual(STRATEGY_TYPE, "SMA9_BUY_ONLY")
        self.assertEqual(MAX_POSITIONS, 2)
        info = Sma9Scanner().info
        self.assertEqual(info.strategy_type, "SMA9_BUY_ONLY")
        self.assertIn("BUY ONLY", info.scanner_name)

    def test_ce_signal_is_buy(self):
        candles = make_candles([100.0] * 9, 111.0, 120.0)
        signals = compute_sma9_signals(candles, 22950, "CE")
        self.assertEqual(len(signals), 1)
        s = signals[0]
        self.assertEqual(s["signal_direction"], "BUY")
        self.assertEqual(s["signal_type"], "SMA9_BUY")
        self.assertEqual(s["net_points"], 9.0)  # 120 - 111

    def test_pe_signal_is_buy_not_short(self):
        candles = make_candles([100.0] * 9, 111.0, 120.0)
        signals = compute_sma9_signals(candles, 22950, "PE")
        self.assertEqual(len(signals), 1)
        s = signals[0]
        self.assertEqual(s["signal_direction"], "BUY")
        self.assertEqual(s["signal_type"], "SMA9_BUY")
        # BUY arithmetic: +9, never short -9.
        self.assertEqual(s["net_points"], 9.0)

    def test_confirmation_below_sma9_blocks_entry(self):
        # prev_close > SMA9 but entry open <= SMA9 -> no entry.
        candles = make_candles([100.0] * 8 + [110.0], 95.0, 130.0)
        self.assertEqual(compute_sma9_signals(candles, 22950, "CE"), [])
        self.assertEqual(compute_sma9_signals(candles, 22950, "PE"), [])

    def test_no_lookahead_from_entry_candle_close(self):
        base = make_candles([100.0] * 9, 111.0, 120.0)
        altered = make_candles([100.0] * 9, 111.0, 999.0)
        a = compute_sma9_signals(base, 22950, "CE")
        b = compute_sma9_signals(altered, 22950, "CE")
        self.assertEqual(len(a), len(b))
        self.assertEqual(a[0]["scanner_metadata"]["sma9"],
                         b[0]["scanner_metadata"]["sma9"])
        # P&L legitimately changes because exit is the entry candle close.
        self.assertEqual(b[0]["net_points"], 888.0)

    def test_previous_sma9_excludes_entry_candle(self):
        closes = [float(x) for x in range(1, 12)]  # 1..11
        # At idx 9, use closes 0..8 = 1..9 -> mean 5.
        self.assertEqual(compute_previous_sma9(closes, 9), 5.0)

    def test_scanner_scan_market_emits_only_buy(self):
        candles = make_candles([100.0] * 9, 111.0, 120.0)
        market = [MarketData(
            timestamp=c["timestamp"], open=c["open"], high=c["high"],
            low=c["low"], close=c["close"]) for c in candles]
        scanner = Sma9Scanner()
        scanner.initialize()
        result = scanner.scan_market(market)
        self.assertEqual(result.market_state, "SIGNALS")
        self.assertEqual(len(result.signals), 2)  # one CE + one PE
        for sig in result.signals:
            self.assertEqual(sig["signal_direction"], "BUY")
            self.assertEqual(sig["signal_type"], "SMA9_BUY")
            self.assertGreater(sig["net_points"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
