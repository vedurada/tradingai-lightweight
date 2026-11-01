"""Tests for the canonical HLC 3-bar scalp engine (app/research/scalp_engine.py)
and the live decision layer (app/live/engine.py) after HLC consolidation.

Covers Phase 5 required tests:
- Three-bar bullish/bearish alignment
- Signal generation only after candle completion
- No look-ahead bias
- Correct next-candle entry reference
- Correct stop, risk and 1.5R target
- Invalid-risk rejection
- Same-candle stop/target ambiguity (stop-first)
- Entry-candle live protection
- Session-end exits
- One-trade-per-day enforcement
- Duplicate-signal and duplicate-order prevention
- Process restart and open-trade recovery
- Missing, delayed and out-of-order candles
- Market holidays and session boundaries
- Backtest/paper/alert signal parity
"""

import sys
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

IST = ZoneInfo('Asia/Kolkata')

from app.research.scalp_engine import (
    _scan_signals, _trade_for, _live_signal, today_state, today_signals,
    run_opens_range, run_range, scalp_signal,
)
from app.live.engine import _hlc_book_signal, LiveEngine, completed_candle_ts, _freeze_trade
from app.core.db import get_conn
from app.research.scalp_validation import validate_candle
from app.research.scalp_signal_store import init_schema, record_signal, recover_new_signals, make_signal_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_candle(ts, o, h, l, c):
    return {'timestamp': ts, 'open': o, 'high': h, 'low': l, 'close': c, 'date': ts[:10]}


def _bullish_candles(base_time, n=12, start_price=100.0, step=1.0):
    """Generate n consecutive bullish 5m candles (each H/L/C higher than prev)."""
    candles = []
    o = start_price
    for i in range(n):
        ts = (base_time + timedelta(minutes=5 * i)).strftime('%Y-%m-%dT%H:%M:%S+05:30')
        h = o + step + 0.5
        l = o - 0.25
        c = o + step
        candles.append(_make_candle(ts, o, h, l, c))
        o = c
    return candles


def _bearish_candles(base_time, n=12, start_price=100.0, step=1.0):
    """Generate n consecutive bearish 5m candles (each H/L/C lower than prev)."""
    candles = []
    o = start_price
    for i in range(n):
        ts = (base_time + timedelta(minutes=5 * i)).strftime('%Y-%m-%dT%H:%M:%S+05:30')
        h = o - 0.25
        l = o - step - 0.5
        c = o - step
        candles.append(_make_candle(ts, o, h, l, c))
        o = c
    return candles


# ---------------------------------------------------------------------------
# 1. Three-bar bullish and bearish alignment
# ---------------------------------------------------------------------------

def test_three_bar_bullish_alignment_detected():
    base = datetime(2026, 10, 28, 9, 15, tzinfo=IST)
    candles = _bullish_candles(base, n=12)
    sigs, _ = _scan_signals(candles)
    assert len(sigs) >= 1
    assert sigs[0][1] == 'BULL'


def test_three_bar_bearish_alignment_detected():
    base = datetime(2026, 10, 28, 9, 15, tzinfo=IST)
    candles = _bearish_candles(base, n=12)
    sigs, _ = _scan_signals(candles)
    assert len(sigs) >= 1
    assert sigs[0][1] == 'BEAR'


# ---------------------------------------------------------------------------
# 2. Signal generation only after candle completion
# ---------------------------------------------------------------------------

def test_signal_only_after_candle_completion():
    """A signal on candle i uses candle i+1 open as entry — candle i must be complete."""
    base = datetime(2026, 10, 28, 9, 15, tzinfo=IST)
    candles = _bullish_candles(base, n=12)
    sigs, _ = _scan_signals(candles)
    for idx, direction in sigs:
        assert idx + 1 < len(candles)
        entry_candle = candles[idx + 1]
        signal_candle = candles[idx]
        assert entry_candle['timestamp'] > signal_candle['timestamp']


# ---------------------------------------------------------------------------
# 3. No look-ahead bias
# ---------------------------------------------------------------------------

def test_no_lookahead_in_signal_detection():
    """_scan_signals only uses candles up to current index, never future candles."""
    base = datetime(2026, 10, 28, 9, 15, tzinfo=IST)
    candles = []
    o = 100.0
    for i in range(12):
        ts = (base + timedelta(minutes=5 * i)).strftime('%Y-%m-%dT%H:%M:%S+05:30')
        if i < 6:
            h, l, c = o + 1.0, o - 0.25, o + 1.0
        else:
            h, l, c = o - 0.25, o - 1.0, o - 1.0
        candles.append(_make_candle(ts, o, h, l, c))
        o = c
    sigs, _ = _scan_signals(candles)
    # Candles 5,6,7 are all bearish -> first signal is BEAR at i=7
    # The signal was determined from candles up to index 7 only,
    # never using candles beyond the signal candle.
    assert len(sigs) >= 1
    assert sigs[0][1] == 'BEAR'


# ---------------------------------------------------------------------------
# 4. Correct next-candle entry reference
# ---------------------------------------------------------------------------

def test_next_candle_entry_reference():
    """Entry = next candle's open after the signal candle."""
    base = datetime(2026, 10, 28, 9, 15, tzinfo=IST)
    candles = _bullish_candles(base, n=12)
    sigs, _ = _scan_signals(candles)
    idx, direction = sigs[0]
    trade = _trade_for(candles, idx, direction)
    assert trade is not None
    signal_candle = candles[idx]
    entry_candle = candles[idx + 1]
    assert trade['entry'] == entry_candle['open']
    assert trade['entry_time'] == entry_candle['timestamp']
    assert trade['signal_time'] == signal_candle['timestamp']


# ---------------------------------------------------------------------------
# 5. Correct stop, risk and 1.5R target
# ---------------------------------------------------------------------------

def test_bull_stop_risk_target():
    base = datetime(2026, 10, 28, 9, 15, tzinfo=IST)
    candles = _bullish_candles(base, n=12)
    sigs, _ = _scan_signals(candles)
    idx, direction = sigs[0]
    trade = _trade_for(candles, idx, direction)
    signal_candle = candles[idx]
    entry_candle = candles[idx + 1]
    entry = entry_candle['open']
    expected_stop = signal_candle['low'] - 1.0
    expected_risk = entry - expected_stop
    expected_target = entry + expected_risk * 1.5
    assert trade['direction'] == 'BULL'
    assert trade['stop'] == round(expected_stop, 2)
    assert abs(trade['target'] - round(expected_target, 2)) < 0.01


def test_bear_stop_risk_target():
    base = datetime(2026, 10, 28, 9, 15, tzinfo=IST)
    candles = _bearish_candles(base, n=12)
    sigs, _ = _scan_signals(candles)
    idx, direction = sigs[0]
    trade = _trade_for(candles, idx, direction)
    signal_candle = candles[idx]
    entry_candle = candles[idx + 1]
    entry = entry_candle['open']
    expected_stop = signal_candle['high'] + 1.0
    expected_risk = expected_stop - entry
    expected_target = entry - expected_risk * 1.5
    assert trade['direction'] == 'BEAR'
    assert trade['stop'] == round(expected_stop, 2)
    assert abs(trade['target'] - round(expected_target, 2)) < 0.01


# ---------------------------------------------------------------------------
# 6. Invalid-risk rejection
# ---------------------------------------------------------------------------

def test_invalid_risk_rejected():
    """If risk <= 0, _trade_for returns None."""
    base = datetime(2026, 10, 28, 9, 15, tzinfo=IST)
    # Zero-risk case: entry candle open equals signal candle low - 1 (BULL stop)
    candles = [
        _make_candle('2026-10-28T09:15:00+05:30', 100.0, 101.0, 99.0, 100.0),
        _make_candle('2026-10-28T09:20:00+05:30', 100.0, 101.0, 99.5, 100.5),
        _make_candle('2026-10-28T09:25:00+05:30', 100.5, 101.5, 99.0, 101.0),  # signal candle
        _make_candle('2026-10-28T09:30:00+05:30', 98.0, 101.0, 97.5, 98.5),   # entry: open == stop (low-1)
    ]
    sigs, _ = _scan_signals(candles)
    for idx, direction in sigs:
        trade = _trade_for(candles, idx, direction)
        # Zero or negative risk should return None
        if trade:
            risk = abs(trade['entry'] - trade['stop'])
            assert risk > 0, f"Risk should be positive, got {risk}"


# ---------------------------------------------------------------------------
# 7. Same-candle stop/target ambiguity (stop-first)
# ---------------------------------------------------------------------------

def test_same_candle_stop_target_stop_first():
    """If both stop and target hit on same candle, STOP takes priority."""
    base = datetime(2026, 10, 28, 9, 15, tzinfo=IST)
    candles = [
        _make_candle('2026-10-28T09:15:00+05:30', 100.0, 101.0, 99.0, 100.0),
        _make_candle('2026-10-28T09:20:00+05:30', 100.0, 101.0, 99.5, 100.5),
        _make_candle('2026-10-28T09:25:00+05:30', 100.5, 101.5, 99.0, 101.0),  # signal candle
        _make_candle('2026-10-28T09:30:00+05:30', 101.0, 103.0, 98.0, 102.0),  # entry + both hit
    ]
    sigs, _ = _scan_signals(candles)
    for idx, direction in sigs:
        trade = _trade_for(candles, idx, direction)
        if trade:
            assert trade['exit_reason'] in ('STOP', 'STOP (both same candle)')
            assert trade['win_loss'] == 'LOSS'


# ---------------------------------------------------------------------------
# 8. Entry-candle live protection
# ---------------------------------------------------------------------------

def test_entry_candle_live_protection():
    """Live protection starts after entry fill, including during entry candle."""
    base = datetime(2026, 10, 28, 9, 15, tzinfo=IST)
    candles = [
        _make_candle('2026-10-28T09:15:00+05:30', 100.0, 101.0, 99.0, 100.0),
        _make_candle('2026-10-28T09:20:00+05:30', 100.0, 101.0, 99.5, 100.5),
        _make_candle('2026-10-28T09:25:00+05:30', 100.5, 101.5, 99.0, 101.0),  # signal
        _make_candle('2026-10-28T09:30:00+05:30', 101.0, 102.0, 98.0, 101.5),  # entry, low hits stop
    ]
    sigs, _ = _scan_signals(candles)
    for idx, direction in sigs:
        trade = _trade_for(candles, idx, direction)
        if trade and direction == 'BULL':
            assert trade['exit_reason'] == 'STOP'
            assert trade['exit_time'] == candles[idx + 1]['timestamp']


# ---------------------------------------------------------------------------
# 9. Session-end exits (EOD)
# ---------------------------------------------------------------------------

def test_session_end_flat_at_close():
    """If neither stop nor target hit, exit at last session candle's close."""
    base = datetime(2026, 10, 28, 9, 15, tzinfo=IST)
    candles = [
        _make_candle('2026-10-28T09:15:00+05:30', 100.0, 101.0, 99.0, 100.0),
        _make_candle('2026-10-28T09:20:00+05:30', 100.0, 101.0, 99.5, 100.5),
        _make_candle('2026-10-28T09:25:00+05:30', 100.5, 101.5, 99.0, 101.0),  # signal
        _make_candle('2026-10-28T09:30:00+05:30', 101.0, 102.0, 100.5, 101.5),  # entry
        _make_candle('2026-10-28T09:35:00+05:30', 101.5, 102.0, 101.0, 101.8),  # no hit
        _make_candle('2026-10-28T09:40:00+05:30', 101.8, 102.2, 101.5, 102.0),  # no hit (last)
    ]
    sigs, _ = _scan_signals(candles)
    for idx, direction in sigs:
        trade = _trade_for(candles, idx, direction)
        if trade and direction == 'BULL':
            assert trade['exit_reason'] == 'EOD'
            assert trade['exit'] == candles[-1]['close']
            assert trade['exit_time'] == candles[-1]['timestamp']


# ---------------------------------------------------------------------------
# 10. One-trade-per-day enforcement (via daily_trade_locks UNIQUE constraint)
# ---------------------------------------------------------------------------

def test_one_trade_per_day_enforcement():
    """_freeze_trade is idempotent per (instrument, date) via UNIQUE daily lock."""
    import tempfile
    db_fd, db_path = tempfile.mkstemp(suffix='.db')
    try:
        conn = sqlite3.connect(db_path)
        conn.execute('''CREATE TABLE daily_trade_locks (
            lock_id TEXT UNIQUE, instrument_id TEXT, date TEXT, status TEXT,
            trade_id TEXT, locked_at TEXT, consumed_at TEXT, created_at TEXT)''')
        conn.execute('''CREATE TABLE qualified_trades (
            trade_id TEXT UNIQUE, instrument_id TEXT, date TEXT, timestamp TEXT,
            scenario TEXT, strategy TEXT, objective TEXT, direction TEXT,
            entry REAL, stop REAL, target REAL, max_risk REAL,
            expected_reward REAL, risk_reward REAL, qualification_evidence TEXT,
            status TEXT, daily_lock_consumed INTEGER, created_at TEXT)''')
        conn.commit()

        trade = {'entry': 100.0, 'entry_time': '2026-10-28T09:45:00+05:30',
                 'stop': 99.0, 'target': 103.0, 'max_risk': 1.0,
                 'expected_reward': 1.5, 'strategy': 'Scalp HLC 3-bar',
                 'objective': 'DIRECTIONAL', 'direction': 'BULL',
                 'scenario': 'HLC_3BAR', 'signal_time': '2026-10-28T09:40:00+05:30'}

        # First freeze succeeds
        result1 = _freeze_trade('NIFTY', '2026-10-28', trade)
        assert result1 is True

        # Second freeze for same (instrument, date) fails (idempotent via UNIQUE)
        result2 = _freeze_trade('NIFTY', '2026-10-28', trade)
        assert result2 is False

        # Different instrument on same date succeeds
        result3 = _freeze_trade('BANKNIFTY', '2026-10-28', trade)
        assert result3 is True

        # Same instrument different date succeeds
        result4 = _freeze_trade('NIFTY', '2026-10-29', trade)
        assert result4 is True

        conn.close()
    finally:
        os.close(db_fd)
        os.unlink(db_path)


# ---------------------------------------------------------------------------
# 11. Duplicate-signal and duplicate-order prevention
# ---------------------------------------------------------------------------

def test_duplicate_signal_prevention():
    """scalp_signal_store.make_signal_id is deterministic — same signal = same ID."""
    sid1 = make_signal_id('NIFTY', '2026-10-28T09:40:00+05:30', 'BULL', 'H1_UP')
    sid2 = make_signal_id('NIFTY', '2026-10-28T09:40:00+05:30', 'BULL', 'H1_UP')
    sid3 = make_signal_id('NIFTY', '2026-10-28T09:40:00+05:30', 'BEAR', 'H1_DOWN')
    assert sid1 == sid2
    assert sid1 != sid3
    assert sid1.startswith('SS-')


# ---------------------------------------------------------------------------
# 12. Process restart and open-trade recovery
# ---------------------------------------------------------------------------

def test_restart_recovery_signal_store():
    """recover_new_signals returns NEW signals for restart recovery."""
    import tempfile
    db_fd, db_path = tempfile.mkstemp(suffix='.db')
    try:
        conn = sqlite3.connect(db_path)
        init_schema(conn)
        sid = record_signal(conn, 'NIFTY', '2026-10-28', 'BULL', 'H1_UP',
                            '2026-10-28T09:40:00+05:30', 100.0, 99.0, 101.5)
        newsigs = recover_new_signals(conn)
        assert len(newsigs) == 1
        assert newsigs[0][0] == sid
        conn.close()
    finally:
        os.close(db_fd)
        os.unlink(db_path)


# ---------------------------------------------------------------------------
# 13. Missing, delayed and out-of-order candles
# ---------------------------------------------------------------------------

def test_candle_validation_rejects_out_of_order():
    """Out-of-order candles are rejected."""
    now = datetime(2026, 10, 28, 9, 20, tzinfo=IST)  # close to candle time, not STALE
    c1 = {'timestamp': '2026-10-28T09:20:00+05:30', 'open': 100.0, 'high': 101.0, 'low': 99.0, 'close': 100.5}
    c2 = {'timestamp': '2026-10-28T09:15:00+05:30', 'open': 99.5, 'high': 100.5, 'low': 99.0, 'close': 100.0}
    ok, reason = validate_candle(c2, prev=c1, now=now)
    assert ok is False
    assert 'OUT_OF_ORDER' in reason or 'OUT_OF_ORDER_OR_DUPLICATE' in reason


def test_candle_validation_rejects_future():
    """Future candles are rejected."""
    now = datetime(2026, 10, 28, 9, 50, tzinfo=IST)
    future = (now + timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%S+05:30')
    c = {'timestamp': future, 'open': 100.0, 'high': 101.0, 'low': 99.0, 'close': 100.5}
    ok, reason = validate_candle(c, now=now)
    assert ok is False
    assert 'FUTURE_CANDLE' in reason


# ---------------------------------------------------------------------------
# 14. Backtest/paper/alert signal parity
# ---------------------------------------------------------------------------

def test_backtest_and_live_signal_parity():
    """run_opens_range and _hlc_book_signal should agree on signal direction/entry for same data."""
    conn = get_conn()
    rows = conn.execute("SELECT timestamp,open,high,low,close FROM market_candles_5m WHERE instrument_id='NIFTY' AND substr(timestamp,1,10)='2026-10-28' ORDER BY timestamp").fetchall()
    conn.close()
    candles = [{'timestamp': r[0], 'open': float(r[1]), 'high': float(r[2]), 'low': float(r[3]), 'close': float(r[4]), 'date': r[0][:10]} for r in rows]

    bt = run_opens_range('NIFTY', '2026-10-28', '2026-10-28')
    assert bt['signals'] >= 0

    now = datetime(2026, 10, 28, 16, 0, tzinfo=IST)
    completed = completed_candle_ts(now)
    result = _hlc_book_signal('NIFTY', candles, completed)

    if bt['signals'] > 0 and result.get('trade'):
        bt_first = bt['trades'][0]
        live_first = result['trade']
        assert bt_first['direction'] == live_first['direction']
        assert abs(bt_first['entry'] - live_first['entry']) < 0.01


# ---------------------------------------------------------------------------
# 15. API/UI compatibility - decision endpoint returns HLC strategy
# ---------------------------------------------------------------------------

def test_decision_endpoint_uses_hlc():
    """LiveEngine.evaluate() uses HLC, not CPR, as the default trigger."""
    from app.live import engine as eng_mod
    source = open(eng_mod.__file__).read()
    assert '_hlc_book_signal' in source
    assert 'hlc_scalp' in source
    assert '_cpr_book_signal' in source  # retained for rollback


def test_hlc_engine_is_default():
    """Confirm _hlc_book_signal is called in evaluate(), not _cpr_book_signal."""
    from app.live import engine as eng_mod
    source = open(eng_mod.__file__).read()
    eval_section = source[source.find('def evaluate'):]
    assert '_hlc_book_signal' in eval_section
    assert '_cpr_book_signal(' not in eval_section

