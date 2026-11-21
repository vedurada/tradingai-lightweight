"""Pattern scanner pricing/timestamp correctness.

Covers:
  * entry timestamp was the signal candle's start, five minutes before the
    trade was actually placed
  * exits use the position's own option LTP after an ATM reband, never the
    opposite leg
  * exits are premium ATR(14) only: initial ATR stop plus ATR-width trail,
    managed on the position's own option tick
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone

import pytest

from app.research.pattern_scanner import (
    MAX_QUOTE_AGE_SEC,
    OptionPosition,
    PatternScanner,
    compute_atr_stop,
    premium_atr,
)

IST = timezone(timedelta(hours=5, minutes=30))

SCHEMA = """
CREATE TABLE pattern_scanner_positions (
    trade_id TEXT PRIMARY KEY,
    pattern_name TEXT NOT NULL,
    instrument TEXT NOT NULL,
    direction TEXT NOT NULL,
    entry_price REAL NOT NULL,
    initial_sl REAL NOT NULL,
    stop_loss REAL NOT NULL,
    entry_ts TEXT NOT NULL,
    exit_ts TEXT,
    exit_price REAL,
    exit_reason TEXT,
    pnl_points REAL,
    gross_pnl_points REAL,
    holding_minutes INTEGER,
    mfe_points REAL DEFAULT 0,
    mae_points REAL DEFAULT 0,
    trailing_update_cnt INTEGER DEFAULT 0,
    status TEXT DEFAULT 'active',
    session_date TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    hwm REAL, be_locked INTEGER DEFAULT 0, entry_spot REAL, lwm REAL
);
CREATE TABLE pattern_scanner_stop_changes (
    change_id TEXT PRIMARY KEY,
    trade_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    old_sl REAL NOT NULL,
    new_sl REAL NOT NULL,
    method TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def ts(h, m, s=0):
    return datetime(2026, 11, 18, h, m, s, tzinfo=IST)


def make_scanner(tmp_path):
    db = tmp_path / "pattern.db"
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()

    def get_conn():
        c = sqlite3.connect(db)
        c.row_factory = sqlite3.Row
        return c

    def bullish(candles, i, atr):
        return [{"pattern_name": "TestBull", "direction": "BULLISH"}]

    def bearish(candles, i, atr):
        return []

    ps = PatternScanner(get_conn, signal_engine=None,
                        detect_fn=bullish, detect_fn_bearish=bearish)
    ps.set_option_instruments("TEST_CE_OLD", "TEST_PE_OLD", 25300,
                              date(2026, 11, 23))
    return ps


def drive_to_entry(ps, entry_price=150.0):
    """Four spot ticks -> 3 completed candles -> one entry at 09:35."""
    ps.on_tick("TEST_CE_OLD", entry_price, ts(9, 20))
    ps.on_tick("NIFTY_SPOT", 25300.0, ts(9, 20))
    ps.on_tick("NIFTY_SPOT", 25300.0, ts(9, 25))
    ps.on_tick("NIFTY_SPOT", 25300.0, ts(9, 30))
    # Fresh option quote for the exact symbol, then the tick that closes the
    # 09:30 candle and places the trade.
    ps.on_tick("TEST_CE_OLD", entry_price, ts(9, 35))
    ps.on_tick("NIFTY_SPOT", 25300.0, ts(9, 35))


def one_position(ps):
    assert len(ps.positions) == 1
    return next(iter(ps.positions.values()))


def test_entry_timestamp_is_actual_entry_not_candle_start(tmp_path):
    ps = make_scanner(tmp_path)
    drive_to_entry(ps)
    pos = one_position(ps)

    # Signal candle started 09:30; trade was placed on the 09:35 tick.
    assert pos.entry_ts == ts(9, 35).isoformat()
    assert not pos.entry_ts.startswith("2026-11-18T09:30")
    assert pos.entry_price == 150.0
    assert pos.entry_spot == 25300.0
    # No completed option candles in this fixture, so the 10% fallback applies.
    assert pos.atr_at_entry is None
    assert pos.stop_price == 135.0
    assert pos.stop_source == "fallback_pct"

    status = ps.get_status()
    assert status["exit_model"] == "PREMIUM_ATR_ONLY"
    assert status["active_count"] == 1
    trade = status["active_trades"][0]
    assert trade["initial_sl"] == 135.0
    assert trade["stop_price"] == 135.0
    assert trade["stop_source"] == "fallback_pct"


def test_exit_uses_positions_own_option_after_atm_reband(tmp_path):
    ps = make_scanner(tmp_path)
    drive_to_entry(ps)
    pos = one_position(ps)

    # ATM moves up a strike: the old CE is no longer the current ATM.
    ps.set_option_instruments("TEST_CE_NEW", "TEST_PE_NEW", 25350,
                              date(2026, 11, 23))
    # Opposite leg and old leg both have live quotes; only the old leg's own
    # tick may manage this position.
    ps.on_tick("TEST_PE_NEW", 200.0, ts(9, 35, 10))
    ps.on_tick("TEST_CE_OLD", 134.0, ts(9, 35, 10))

    assert ps.positions == {}
    assert pos.exit_price == 134.0, "must use TEST_CE_OLD, not TEST_PE_NEW"
    assert pos.exit_reason == "STOP_LOSS_ATR"
    assert pos.pnl_points == -16.0


def test_stale_quote_does_not_create_a_trade(tmp_path):
    ps = make_scanner(tmp_path)
    ps.on_tick("TEST_CE_OLD", 150.0, ts(9, 20))
    ps.on_tick("NIFTY_SPOT", 25300.0, ts(9, 20))
    ps.on_tick("NIFTY_SPOT", 25300.0, ts(9, 25))
    ps.on_tick("NIFTY_SPOT", 25300.0, ts(9, 30))
    # Candle closes at 09:35 but the only CE quote is >20s old.
    ps.on_tick("NIFTY_SPOT", 25300.0, ts(9, 35))

    assert ps.positions == {}


def test_no_option_tick_means_no_premium_exit(tmp_path):
    ps = make_scanner(tmp_path)
    drive_to_entry(ps)
    pos = one_position(ps)

    # Spot cannot breach a premium stop, no matter how far it falls.
    later = ts(9, 35) + timedelta(seconds=MAX_QUOTE_AGE_SEC + 5)
    ps.on_tick("NIFTY_SPOT", 25287.0, later)
    assert ps.positions != {}
    assert pos.exit_price is None

    # A fresh tick on the position's own option at/below its ATR stop exits at
    # that sampled LTP.
    ps.on_tick("TEST_CE_OLD", 134.0, later + timedelta(seconds=5))
    assert ps.positions == {}
    assert pos.exit_price == 134.0
    assert pos.exit_reason == "STOP_LOSS_ATR"


def test_entry_uses_premium_atr_from_exact_option_buffer(tmp_path):
    ps = make_scanner(tmp_path)
    # Delay the entry until 10:30 so the option buffer has 15 completed 5m
    # candles; otherwise premium_atr correctly returns None.
    ps.detect_fn = lambda candles, i, atr: (
        [{"pattern_name": "TestBull", "direction": "BULLISH"}]
        if candles[i]["timestamp"].startswith("2026-11-18T10:25") else []
    )
    start = ts(9, 15)
    price = 100.0
    for i in range(16):
        tick_ts = start + timedelta(minutes=5 * i)
        premium = price if i % 2 == 0 else price + 2.0
        ps.on_tick("TEST_CE_OLD", premium, tick_ts)
        ps.on_tick("NIFTY_SPOT", 25300.0, tick_ts)

    pos = one_position(ps)
    # 15 completed option candles with a 2-point alternating TR give ATR=2.
    assert pos.atr_at_entry == 2.0
    # Entry LTP is 102 at 10:30. 0.70*2=1.4 is below the 5% floor (5.1),
    # so the floor sets the distance.
    assert pos.entry_price == 102.0
    assert pos.trail_distance == 5.1
    assert pos.stop_price == 96.9
    assert pos.stop_source == "atr"


def test_atr_stop_and_trail_are_premium_only():
    stop, distance, pct, source = compute_atr_stop(100.0, 10.0)
    assert (stop, distance, pct, source) == (93.0, 7.0, 0.07, "atr")

    pos = OptionPosition(
        trade_id="T1", pattern_name="TestBull", instrument="TEST_CE",
        direction="BULLISH", entry_price=100.0, entry_spot=25300.0,
        entry_ts=ts(9, 35).isoformat(), session_date="2026-11-18", atr=10.0,
    )
    # No trail before a new premium high: the initial ATR stop is the only exit.
    assert pos.update_trail(99.0, ts(9, 40).isoformat()) is None
    assert pos.stop_loss == 93.0

    # New high ratchets the stop to hwm - ATR distance (110 - 7 = 103).
    assert pos.update_trail(110.0, ts(9, 45).isoformat()) is None
    assert pos.stop_loss == 103.0
    assert pos.stop_changes[-1]["method"] == "ATR_TRAIL"
    assert pos.update_trail(101.0, ts(9, 50).isoformat()) == 103.0

    # Initial-stop breach returns the ACTUAL LTP, not the theoretical stop.
    pos2 = OptionPosition(
        trade_id="T2", pattern_name="TestBull", instrument="TEST_CE",
        direction="BULLISH", entry_price=100.0, entry_spot=25300.0,
        entry_ts=ts(9, 35).isoformat(), session_date="2026-11-18", atr=10.0,
    )
    assert pos2.check_stop_loss(92.5) == 92.5


def test_atr_stop_clamps_floor_cap_and_fallback():
    assert compute_atr_stop(100.0, 0.0) == (90.0, 10.0, 0.1, "fallback_pct")
    assert compute_atr_stop(100.0, 1.0)[1] == 5.0       # 5% floor
    assert compute_atr_stop(100.0, 100.0)[1] == 30.0    # 30% cap


def test_premium_atr_excludes_forming_candle():
    candles = [
        {"timestamp": f"t{i}", "open": 100.0, "high": 100.0,
         "low": 100.0, "close": 100.0}
        for i in range(15)
    ]
    candles.append({"timestamp": "forming", "open": 999.0, "high": 999.0,
                    "low": 999.0, "close": 999.0})
    assert premium_atr(candles) == 0.0


def test_legacy_open_position_is_migrated_to_atr(tmp_path):
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA)
    conn.execute(
        """INSERT INTO pattern_scanner_positions
           (trade_id, pattern_name, instrument, direction, entry_price,
            initial_sl, stop_loss, entry_ts, status, session_date,
            hwm, lwm, entry_spot, be_locked)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        ("LEGACY", "TestBull", "TEST_CE_OLD", "BULLISH", 150.0,
         25288.0, 25288.0, ts(9, 35).isoformat(), "active",
         "2026-11-18", 25310.0, 25290.0, 25300.0, 1),
    )
    conn.commit()
    conn.close()

    def get_conn():
        c = sqlite3.connect(db)
        c.row_factory = sqlite3.Row
        return c

    ps = PatternScanner(get_conn, signal_engine=None,
                        detect_fn=lambda candles, i, atr: [],
                        detect_fn_bearish=lambda candles, i, atr: [])
    pos = one_position(ps)
    assert pos.stop_source == "fallback_pct"
    assert pos.stop_price == 135.0
    assert pos.stop_loss == 135.0
    assert pos.hwm == 150.0, "legacy spot HWM must not survive migration"
    assert pos.be_locked is False
