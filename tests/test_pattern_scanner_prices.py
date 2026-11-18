"""Pattern scanner pricing/timestamp correctness.

Covers the live-market bugs found on 2026-11-18:
  * entry timestamp was the signal candle's start, five minutes before the
    trade was actually placed
  * exits were priced off the current ATM's opposite leg (or a stale quote)
    after the ATM strike moved, instead of the position's own option
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone

import pytest

from app.research.pattern_scanner import (
    MAX_QUOTE_AGE_SEC,
    PatternScanner,
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

    status = ps.get_status()
    assert status["active_count"] == 1
    assert status["active_trades"][0]["initial_sl"] == 25288.0


def test_exit_uses_positions_own_option_after_atm_reband(tmp_path):
    ps = make_scanner(tmp_path)
    drive_to_entry(ps)
    pos = one_position(ps)

    # ATM moves up a strike: the old CE is no longer the current ATM.
    ps.set_option_instruments("TEST_CE_NEW", "TEST_PE_NEW", 25350,
                              date(2026, 11, 23))
    # Opposite leg and the old leg both have live quotes.
    ps.on_tick("TEST_PE_NEW", 200.0, ts(9, 35, 10))
    ps.on_tick("TEST_CE_OLD", 145.0, ts(9, 35, 10))
    # Spot breaches the 12-point SL (25300 - 12 = 25288).
    ps.on_tick("NIFTY_SPOT", 25287.0, ts(9, 35, 20))

    assert ps.positions == {}
    assert pos.exit_price == 145.0, "must use TEST_CE_OLD, not TEST_PE_NEW"
    assert pos.exit_reason == "STOP_LOSS_SPOT"
    assert pos.pnl_points == -5.0


def test_stale_quote_does_not_create_a_trade(tmp_path):
    ps = make_scanner(tmp_path)
    ps.on_tick("TEST_CE_OLD", 150.0, ts(9, 20))
    ps.on_tick("NIFTY_SPOT", 25300.0, ts(9, 20))
    ps.on_tick("NIFTY_SPOT", 25300.0, ts(9, 25))
    ps.on_tick("NIFTY_SPOT", 25300.0, ts(9, 30))
    # Candle closes at 09:35 but the only CE quote is >20s old.
    ps.on_tick("NIFTY_SPOT", 25300.0, ts(9, 35))

    assert ps.positions == {}


def test_stale_quote_does_not_close_a_position(tmp_path):
    ps = make_scanner(tmp_path)
    drive_to_entry(ps)
    pos = one_position(ps)

    # SL breached, but no quote for the position's option for >20s.
    later = ts(9, 35) + timedelta(seconds=MAX_QUOTE_AGE_SEC + 5)
    ps.on_tick("NIFTY_SPOT", 25287.0, later)
    assert ps.positions != {}
    assert pos.exit_price is None

    # A fresh quote on the same option lets the exit happen at a real price.
    ps.on_tick("TEST_CE_OLD", 144.0, later + timedelta(seconds=5))
    ps.on_tick("NIFTY_SPOT", 25287.0, later + timedelta(seconds=6))
    assert ps.positions == {}
    assert pos.exit_price == 144.0
