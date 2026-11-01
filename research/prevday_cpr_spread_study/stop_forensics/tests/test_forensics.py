"""Unit tests for stop-loss forensics."""
from __future__ import annotations

from research.prevday_cpr_spread_study.stop_forensics.src import execution, data


def test_stop_target():
    s, t = execution.stop_target('BEAR', 55000.0, 0.005, 0.02)
    assert abs(s - 55275.0) < 1e-6
    assert abs(t - 53900.0) < 1e-6
    s, t = execution.stop_target('BULL', 25000.0, 0.005, 0.02)
    assert abs(s - 24875.0) < 1e-6
    assert abs(t - 25500.0) < 1e-6


def test_simulate_exit_stop_checked_first():
    candles = [
        {'timestamp': '2026-07-06 09:20', 'open': 100.0},
        {'timestamp': '2026-07-06 09:25', 'open': 100.5},
    ]
    res = execution.simulate_exit('BEAR', 100.0, candles, 0, 0.005, 0.02)
    assert res is not None
    assert res['exit_reason'] == 'STOP'


def test_simulate_exit_target():
    candles = [
        {'timestamp': '2026-07-06 09:20', 'open': 100.0},
        {'timestamp': '2026-07-06 09:25', 'open': 97.0},
    ]
    res = execution.simulate_exit('BEAR', 100.0, candles, 0, 0.005, 0.02)
    assert res is not None
    assert res['exit_reason'] == 'TARGET'
    assert res['realized_r'] > 0


def test_simulate_exit_missing_eod():
    candles = [
        {'timestamp': '2026-07-06 09:20', 'open': 100.0},
        {'timestamp': '2026-07-06 09:25', 'open': 100.0},
    ]
    res = execution.simulate_exit('BEAR', 100.0, candles, 0, 0.005, 0.02)
    assert res is None


def test_scan_candles_cutoff():
    candles = [
        {'timestamp': '2026-07-06 15:20', 'open': 1},
        {'timestamp': '2026-07-06 15:25', 'open': 1},
    ]
    s = data.scan_candles(candles)
    assert len(s) == 1
    assert s[0]['timestamp'][11:16] == '15:20'


def test_level_key_mapping():
    assert data.LEVEL_KEY['PDH'] == 'pdh'
    assert data.LEVEL_KEY['BRK_TC'] == 'tc'
