"""Backtest pattern replay must honour the live entry prerequisites.

The live engine needs at least three completed NIFTY spot candles before it
runs detection, and entries are confined to the 09:20-15:15 window. The 5m
backtest replay must apply the same guards, otherwise its PnL includes trades
the live scanner could never take.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scripts.backtest_all_scanners as bt  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
EXPIRY = "2026-11-20"
ATM = 25000


def at(hour, minute):
    return datetime(2026, 11, 18, hour, minute, tzinfo=IST)


def _spot(ts):
    return {
        "start": ts,
        "timestamp": ts.isoformat(),
        "session_date": ts.date().isoformat(),
        "open": 25000.0,
        "high": 25010.0,
        "low": 24990.0,
        "close": 25000.0,
        "volume": 0,
    }


def _option_bar(ts):
    return {
        "start": ts,
        "open": 100.0,
        "high": 100.0,
        "low": 100.0,
        "close": 100.0,
        "volume": 0,
    }


def _patch_detectors(monkeypatch):
    """Make every detection call return a bullish signal."""
    real_load = bt.load_module

    def fake_load(path, name):
        module = real_load(path, name)
        module.detect_bullish_patterns = (
            lambda seq, i, atr: [{"pattern_name": "TestBull", "direction": "BULLISH"}]
        )
        module.detect_bearish_patterns = lambda seq, i, atr: []
        return module

    monkeypatch.setattr(bt, "load_module", fake_load)


def test_no_entry_on_first_two_spot_candles(monkeypatch):
    _patch_detectors(monkeypatch)
    timestamps = [at(9, 15), at(9, 20), at(9, 25), at(9, 30)]
    key_ce = (EXPIRY, ATM, "CE")
    key_pe = (EXPIRY, ATM, "PE")
    universe = {
        key_ce: {"tradingsymbol": "TEST_CE"},
        key_pe: {"tradingsymbol": "TEST_PE"},
    }
    series = {
        key_ce: [_option_bar(ts) for ts in timestamps],
        key_pe: [_option_bar(ts) for ts in timestamps],
    }
    spot_by_ts = {ts: _spot(ts) for ts in timestamps}
    ce_pe_index = {ts: (EXPIRY, float(ATM)) for ts in timestamps}

    root = Path(__file__).resolve().parent.parent
    trades = bt.replay_pattern_scanner(
        root, universe, series, spot_by_ts, ce_pe_index,
        timestamps, timestamps[-1],
    )

    assert len(trades) == 1, trades
    # First valid detection is the third completed spot candle (09:25), never
    # the 09:15/09:20 bars that live cannot trade.
    assert trades[0]["entry_timestamp"] == at(9, 25).isoformat()
    assert trades[0]["exit_reason"] == "BACKTEST_END"


def test_backtest_end_exit_uses_bar_end_not_bar_start(monkeypatch):
    _patch_detectors(monkeypatch)
    timestamps = [at(9, 15), at(9, 20), at(9, 25), at(9, 30)]
    key_ce = (EXPIRY, ATM, "CE")
    key_pe = (EXPIRY, ATM, "PE")
    universe = {
        key_ce: {"tradingsymbol": "TEST_CE"},
        key_pe: {"tradingsymbol": "TEST_PE"},
    }
    series = {
        key_ce: [_option_bar(ts) for ts in timestamps],
        key_pe: [_option_bar(ts) for ts in timestamps],
    }
    spot_by_ts = {ts: _spot(ts) for ts in timestamps}
    ce_pe_index = {ts: (EXPIRY, float(ATM)) for ts in timestamps}

    root = Path(__file__).resolve().parent.parent
    trades = bt.replay_pattern_scanner(
        root, universe, series, spot_by_ts, ce_pe_index,
        timestamps, timestamps[-1],
    )

    assert len(trades) == 1
    # The final 09:30 bar closes at 09:35; a BACKTEST_END exit must not claim
    # it happened at the bar's 09:30 start.
    assert trades[0]["exit_timestamp"] == at(9, 35).isoformat()
