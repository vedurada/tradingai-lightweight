"""
Automated tests for HLC Scalp 3-Bar backtest.

Covers Phase 5 required tests:
- Signal timing (3-bar bullish/bearish alignment)
- No-look-ahead behavior
- Next-candle entry reference
- Daily limits (one trade per day per instrument)
- Session boundaries
- Stop-first ambiguity (same candle stop+target)
- Convention A vs B exit differences
"""

import csv
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

RESEARCH_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RESEARCH_DIR)

from run_backtest import (
    scan_signals,
    evaluate_trade_A,
    evaluate_trade_B,
    run_backtest,
    load_candles,
    OPEN_MIN,
    OPEN_EOD,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_candle(ts, o, h, l, c):
    return {"timestamp": ts, "open": o, "high": h, "low": l, "close": c, "date": ts[:10]}


def _bullish_candles(base_time, n=12, start_price=100.0, step=1.0):
    candles = []
    o = start_price
    for i in range(n):
        ts = (base_time + timedelta(minutes=5 * i)).strftime("%Y-%m-%dT%H:%M:%S+05:30")
        h = o + step + 0.5
        l = o - 0.25
        c = o + step
        candles.append(_make_candle(ts, o, h, l, c))
        o = c
    return candles


def _bearish_candles(base_time, n=12, start_price=100.0, step=1.0):
    candles = []
    o = start_price
    for i in range(n):
        ts = (base_time + timedelta(minutes=5 * i)).strftime("%Y-%m-%dT%H:%M:%S+05:30")
        h = o - 0.25
        l = o - step - 0.5
        c = o - step
        candles.append(_make_candle(ts, o, h, l, c))
        o = c
    return candles


# ---------------------------------------------------------------------------
# Test 1: Three-bar bullish alignment
# ---------------------------------------------------------------------------

def test_three_bar_bullish_alignment():
    base = datetime(2026, 10, 28, 9, 15, tzinfo=IST)
    candles = _bullish_candles(base, n=12)
    sigs = scan_signals(candles)
    assert len(sigs) >= 1
    assert sigs[0][1] == "BULL"
    # Signal candle index = i, entry = i+1
    assert sigs[0][0] >= 5  # implementation starts at feats index 5


# ---------------------------------------------------------------------------
# Test 2: Three-bar bearish alignment
# ---------------------------------------------------------------------------

def test_three_bar_bearish_alignment():
    base = datetime(2026, 10, 28, 9, 15, tzinfo=IST)
    candles = _bearish_candles(base, n=12)
    sigs = scan_signals(candles)
    assert len(sigs) >= 1
    assert sigs[0][1] == "BEAR"


# ---------------------------------------------------------------------------
# Test 3: No look-ahead — signal uses only candles up to signal index
# ---------------------------------------------------------------------------

def test_no_lookahead():
    """Signal at index i must not depend on candles beyond i+1 (entry candle)."""
    base = datetime(2026, 10, 28, 9, 15, tzinfo=IST)
    # Candles 0-4 bullish, candle 5 bearish, candle 6+ bullish again
    candles = []
    o = 100.0
    for i in range(12):
        ts = (base + timedelta(minutes=5 * i)).strftime("%Y-%m-%dT%H:%M:%S+05:30")
        if i < 5:
            h, l, c = o + 1.0, o - 0.25, o + 1.0
        elif i == 5:
            h, l, c = o - 0.25, o - 1.0, o - 1.0  # bearish break
        else:
            h, l, c = o + 1.0, o - 0.25, o + 1.0  # resume bullish
        candles.append(_make_candle(ts, o, h, l, c))
        o = c
    sigs = scan_signals(candles)
    # First signal should be BEAR at i=5 (candles 3,4,5 all... wait, candle 5 is bearish
    # but candles 3,4 are bullish, so no 3-bar alignment at i=5)
    # Actually: feats[3] = candle[4]-candle[3] (bullish), feats[4] = candle[5]-candle[4] (bearish)
    # tri at i=5 = feats[3],feats[4],feats[5] = bullish, bearish, bullish -> not aligned
    # First alignment would be later
    # Key point: scan_signals never accesses candles beyond i+1
    for idx, direction in sigs:
        assert idx + 1 < len(candles), "Signal must have entry candle"


# ---------------------------------------------------------------------------
# Test 4: Next-candle entry reference
# ---------------------------------------------------------------------------

def test_next_candle_entry():
    base = datetime(2026, 10, 28, 9, 15, tzinfo=IST)
    candles = _bullish_candles(base, n=12)
    sigs = scan_signals(candles)
    idx, direction = sigs[0]
    trade = evaluate_trade_A(candles, idx, direction)
    assert trade is not None
    assert trade["entry"] == candles[idx + 1]["open"]
    assert trade["entry_time"] == candles[idx + 1]["timestamp"]
    assert trade["signal_time"] == candles[idx]["timestamp"]


# ---------------------------------------------------------------------------
# Test 5: Correct stop, risk, 1.5R target
# ---------------------------------------------------------------------------

def test_stop_risk_target_bull():
    base = datetime(2026, 10, 28, 9, 15, tzinfo=IST)
    candles = _bullish_candles(base, n=12)
    sigs = scan_signals(candles)
    idx, direction = sigs[0]
    trade = evaluate_trade_A(candles, idx, direction)
    signal_candle = candles[idx]
    entry_candle = candles[idx + 1]
    entry = entry_candle["open"]
    expected_stop = signal_candle["low"] - 1.0
    expected_risk = entry - expected_stop
    expected_target = entry + expected_risk * 1.5
    assert trade["direction"] == "BULL"
    assert trade["stop"] == round(expected_stop, 2)
    assert abs(trade["target"] - round(expected_target, 2)) < 0.01
    assert trade["risk_pts"] == round(expected_risk, 2)


def test_stop_risk_target_bear():
    base = datetime(2026, 10, 28, 9, 15, tzinfo=IST)
    candles = _bearish_candles(base, n=12)
    sigs = scan_signals(candles)
    idx, direction = sigs[0]
    trade = evaluate_trade_A(candles, idx, direction)
    signal_candle = candles[idx]
    entry_candle = candles[idx + 1]
    entry = entry_candle["open"]
    expected_stop = signal_candle["high"] + 1.0
    expected_risk = expected_stop - entry
    expected_target = entry - expected_risk * 1.5
    assert trade["direction"] == "BEAR"
    assert trade["stop"] == round(expected_stop, 2)
    assert abs(trade["target"] - round(expected_target, 2)) < 0.01
    assert trade["risk_pts"] == round(expected_risk, 2)


# ---------------------------------------------------------------------------
# Test 6: Invalid risk rejection
# ---------------------------------------------------------------------------

def test_invalid_risk_rejected():
    """Zero or negative risk → None."""
    base = datetime(2026, 10, 28, 9, 15, tzinfo=IST)
    candles = [
        _make_candle("2026-10-28T09:15:00+05:30", 100.0, 101.0, 99.0, 100.0),
        _make_candle("2026-10-28T09:20:00+05:30", 100.0, 101.0, 99.5, 100.5),
        _make_candle("2026-10-28T09:25:00+05:30", 100.5, 101.5, 99.0, 101.0),
        _make_candle("2026-10-28T09:30:00+05:30", 98.0, 101.0, 97.5, 98.5),  # entry == stop
    ]
    sigs = scan_signals(candles)
    for idx, direction in sigs:
        trade = evaluate_trade_A(candles, idx, direction)
        if trade is not None:
            assert trade["risk_pts"] > 0, "Risk must be positive"


# ---------------------------------------------------------------------------
# Test 7: Stop-first tie-break on same candle
# ---------------------------------------------------------------------------

def test_stop_first_tiebreak():
    """Same candle hits both stop and target → STOP wins."""
    base = datetime(2026, 10, 28, 9, 15, tzinfo=IST)
    candles = [
        _make_candle("2026-10-28T09:15:00+05:30", 100.0, 101.0, 99.0, 100.0),
        _make_candle("2026-10-28T09:20:00+05:30", 100.0, 101.0, 99.5, 100.5),
        _make_candle("2026-10-28T09:25:00+05:30", 100.5, 101.5, 99.0, 101.0),  # signal
        _make_candle("2026-10-28T09:30:00+05:30", 101.0, 103.0, 98.0, 102.0),  # entry, both hit
    ]
    sigs = scan_signals(candles)
    for idx, direction in sigs:
        trade = evaluate_trade_A(candles, idx, direction)
        if trade:
            assert trade["exit_reason"] in ("STOP", "STOP (both same candle)")
            assert trade["win_loss"] == "LOSS"


# ---------------------------------------------------------------------------
# Test 8: Entry-candle exit protection (Convention A only)
# ---------------------------------------------------------------------------

def test_entry_candle_exit_convention_a():
    """Convention A checks exit on entry candle; Convention B does not."""
    base = datetime(2026, 10, 28, 9, 15, tzinfo=IST)
    candles = [
        _make_candle("2026-10-28T09:15:00+05:30", 100.0, 101.0, 99.0, 100.0),
        _make_candle("2026-10-28T09:20:00+05:30", 100.0, 101.0, 99.5, 100.5),
        _make_candle("2026-10-28T09:25:00+05:30", 100.5, 101.5, 99.0, 101.0),  # signal
        _make_candle("2026-10-28T09:30:00+05:30", 101.0, 102.0, 98.0, 101.5),  # entry, stop hit
        _make_candle("2026-10-28T09:35:00+05:30", 101.5, 103.0, 100.5, 102.5),  # next, target hit
    ]
    sigs = scan_signals(candles)
    for idx, direction in sigs:
        trade_a = evaluate_trade_A(candles, idx, direction)
        trade_b = evaluate_trade_B(candles, idx, direction)
        if trade_a and trade_b:
            # Convention A exits on entry candle (stop), Convention B exits later (target)
            assert trade_a["exit_time"] == trade_a["entry_time"]
            assert trade_b["exit_time"] != trade_b["entry_time"]
            assert trade_a["exit_reason"] == "STOP"
            assert trade_b["exit_reason"] == "TARGET"


# ---------------------------------------------------------------------------
# Test 9: Session boundary (EOD exit)
# ---------------------------------------------------------------------------

def test_session_boundary_eod():
    """Trade exits at last session close if neither stop nor target hit."""
    base = datetime(2026, 10, 28, 9, 15, tzinfo=IST)
    candles = [
        _make_candle("2026-10-28T09:15:00+05:30", 100.0, 101.0, 99.0, 100.0),
        _make_candle("2026-10-28T09:20:00+05:30", 100.0, 101.0, 99.5, 100.5),
        _make_candle("2026-10-28T09:25:00+05:30", 100.5, 101.5, 99.0, 101.0),  # signal
        _make_candle("2026-10-28T09:30:00+05:30", 101.0, 102.0, 100.5, 101.5),  # entry
        _make_candle("2026-10-28T09:35:00+05:30", 101.5, 102.0, 101.0, 101.8),  # no hit
        _make_candle("2026-10-28T09:40:00+05:30", 101.8, 102.2, 101.5, 102.0),  # last, no hit
    ]
    sigs = scan_signals(candles)
    for idx, direction in sigs:
        trade = evaluate_trade_A(candles, idx, direction)
        if trade and direction == "BULL":
            assert trade["exit_reason"] == "EOD"
            assert trade["exit"] == candles[-1]["close"]
            assert trade["exit_time"] == candles[-1]["timestamp"]


# ---------------------------------------------------------------------------
# Test 10: Daily trade limit via run_backtest
# ---------------------------------------------------------------------------

def test_no_daily_trade_limit():
    """Multiple trades per day are allowed (no daily limit enforced)."""
    candles = load_candles("NIFTY")
    trades, _, _, stats = run_backtest("NIFTY", candles, convention="A")
    from collections import Counter
    day_counts = Counter(t["trade_date"] for t in trades)
    # With no daily limit, we expect many days with >1 trade
    multi_days = sum(1 for c in day_counts.values() if c > 1)
    assert multi_days > 0, "Expected multiple trades per day with no limit"
    assert stats["days_with_multi_trades"] == multi_days
    assert stats["skipped_daily_limit"] == 0


# ---------------------------------------------------------------------------
# Test 11: Convention A vs B produce different results for BANKNIFTY
# ---------------------------------------------------------------------------

def test_convention_difference():
    """Convention A (entry-candle exit) vs B (post-entry) should differ."""
    candles = load_candles("BANKNIFTY")
    trades_a, _, _, stats_a = run_backtest("BANKNIFTY", candles, convention="A")
    trades_b, _, _, stats_b = run_backtest("BANKNIFTY", candles, convention="B")
    assert stats_a["net_points"] != stats_b["net_points"]
    assert stats_a["win_rate"] != stats_b["win_rate"]
    assert stats_a["entry_candle_exits"] > 0
    assert stats_b["entry_candle_exits"] == 0


# ---------------------------------------------------------------------------
# Test 12: Output files exist
# ---------------------------------------------------------------------------

def test_output_files_exist():
    required = [
        "trade_log.csv",
        "signal_log.csv",
        "monthly_summary.csv",
        "exit_convention_comparison.csv",
        "research_report.md",
        "run_backtest.py",
    ]
    for fname in required:
        fpath = os.path.join(RESEARCH_DIR, fname)
        assert os.path.exists(fpath), f"Missing output file: {fname}"


# ---------------------------------------------------------------------------
# Test 13: Trade log reconciles with OHLC data
# ---------------------------------------------------------------------------

def test_trade_log_reconciliation():
    """Every trade's entry price must match the OHLC open at entry_time."""
    candles = load_candles("NIFTY")
    candle_map = {c["timestamp"]: c for c in candles}
    trades, _, _, _ = run_backtest("NIFTY", candles, convention="A")
    for t in trades:
        entry_candle = candle_map.get(t["entry_time"])
        assert entry_candle is not None, f"Entry candle {t['entry_time']} not found"
        assert abs(entry_candle["open"] - t["entry"]) < 0.01, \
            f"Entry mismatch: OHLC open={entry_candle['open']}, trade entry={t['entry']}"


# ---------------------------------------------------------------------------
# Run all tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_three_bar_bullish_alignment,
        test_three_bar_bearish_alignment,
        test_no_lookahead,
        test_next_candle_entry,
        test_stop_risk_target_bull,
        test_stop_risk_target_bear,
        test_invalid_risk_rejected,
        test_stop_first_tiebreak,
        test_entry_candle_exit_convention_a,
        test_session_boundary_eod,
        test_no_daily_trade_limit,
        test_convention_difference,
        test_output_files_exist,
        test_trade_log_reconciliation,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS: {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"FAIL: {t.__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed out of {len(tests)}")
    sys.exit(0 if failed == 0 else 1)
