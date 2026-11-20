#!/usr/bin/env python3
"""Offline checks for the sma9_1min_poll v1.1.0 ATR-stop engine.

No network, no broker, no live DB writes.  The identity stays
`sma9_1min_poll`; only the cadence and exits changed in v1.1.0.
"""
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import app.live_sma9_1min_poll_scanner as live  # noqa: E402
from app.sma9_1min_poll_engine import (  # noqa: E402
    OptionStateMachine,
    Position,
    STRATEGY_ID,
    STRATEGY_TYPE,
    STRATEGY_VERSION,
    compute_stop,
    evaluate_option,
    make_trade_id,
    premium_atr,
)

BASE = datetime(2026, 11, 19, 9, 15)


def candles(n=17, step=1.0, open_last=None):
    """Monotonic candles so prev close and forming open are above SMA9."""
    out = []
    for i in range(n):
        c = 100.0 + i * step
        out.append({
            "start": BASE + timedelta(minutes=5 * i),
            "open": c - 0.5, "high": c + 1.0, "low": c - 1.0,
            "close": c, "volume": 0,
        })
    if open_last is not None:
        out[-1]["open"] = open_last
    return out


def flat_candles(n=17, lo=95.0, hi=105.0, close=100.0):
    out = []
    for i in range(n):
        out.append({
            "start": BASE + timedelta(minutes=5 * i),
            "open": close, "high": hi, "low": lo, "close": close, "volume": 0,
        })
    return out


failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"PASS {name}")
    else:
        failures.append(name)
        print(f"FAIL {name} {detail}")


# --- identity and runner cadence -------------------------------------------
check("strategy_id", STRATEGY_ID == "sma9_1min_poll", STRATEGY_ID)
check("strategy_type", STRATEGY_TYPE == "SMA9_1MIN_POLL_BUY_ONLY", STRATEGY_TYPE)
check("strategy_version", STRATEGY_VERSION == "1.1.0", STRATEGY_VERSION)
check("poll_seconds", live.POLL_SECONDS == 5, live.POLL_SECONDS)
check("no_regime_gate", not hasattr(live, "compute_spot_regime"))

# --- entry rule: A and B, no LTP confirmation gate --------------------------
rows = candles(open_last=120.0)
ev = evaluate_option(rows, "CE", ltp=1.0)
check("entry_A_and_B", ev.signal and ev.qualified, ev.reason)
check("entry_ignores_ltp_confirmation",
      ev.signal and ev.confirmation is False, f"confirmation={ev.confirmation}")

rows = candles(open_last=90.0)
ev = evaluate_option(rows, "CE", ltp=120.0)
check("no_entry_when_B_false", not ev.signal and ev.condition_a
      and not ev.condition_b, ev.reason)

rows = candles(step=-1.0)
ev = evaluate_option(rows, "CE", ltp=120.0)
check("no_entry_when_A_false", not ev.signal and not ev.condition_a, ev.reason)

rows = candles(n=5)
ev = evaluate_option(rows, "CE", ltp=100.0)
check("insufficient_candles", not ev.ready and not ev.signal, ev.reason)

# --- ATR computation and stop bounds ---------------------------------------
atr = premium_atr(flat_candles())
check("atr_constant_range", atr is not None and abs(atr - 10.0) < 1e-9, f"atr={atr}")
check("atr_insufficient", premium_atr(flat_candles(10)) is None)

s, d, pct, src = compute_stop(200.0, 10.0)
check("stop_floor_5pct", (s, d, pct, src) == (190.0, 10.0, 0.05, "atr"),
      f"{(s, d, pct, src)}")
s, d, pct, src = compute_stop(40.0, 15.0)
check("stop_atr_mid", s == 29.5 and src == "atr", f"{(s, d, pct, src)}")
s, d, pct, src = compute_stop(30.0, 100.0)
check("stop_cap_30pct", s == 21.0 and pct == 0.3 and src == "atr",
      f"{(s, d, pct, src)}")
s, d, pct, src = compute_stop(50.0, None)
check("stop_fallback", s == 45.0 and pct == 0.1 and src == "fallback_pct",
      f"{(s, d, pct, src)}")

# --- state machine: ATR stop and ATR-only trail ----------------------------
sm = OptionStateMachine("CE")
ev = evaluate_option(candles(open_last=120.0), "CE", ltp=120.0)
entry_time = BASE + timedelta(minutes=80)
market_close = datetime(2026, 11, 19, 15, 30)
pos = sm.try_entry(ev, entry_time, 25250, "2026-11-23", 123,
                   "NIFTY2525025250CE", market_close, atr=10.0)
check("entry_created", pos is not None and pos.entry_price == 120.0)

again = sm.try_entry(ev, entry_time + timedelta(seconds=5), 25250,
                     "2026-11-23", 123, "NIFTY2525025250CE", market_close,
                     atr=10.0)
check("duplicate_candle_guard", again is None)

check("entry_stop_price", pos.stop_price == compute_stop(120.0, 10.0)[0],
      pos.stop_price)
check("entry_trail_distance", pos.trail_distance == compute_stop(120.0, 10.0)[1],
      pos.trail_distance)
check("stop_not_hit", sm.check_stop_loss(pos.stop_price + 0.5) is None)
fill = sm.check_stop_loss(pos.stop_price - 1.5)
check("stop_fill_at_ltp", fill == round(pos.stop_price - 1.5, 2), f"fill={fill}")

p = Position(
    option_type="CE", trade_id="T", strike=25000, expiry="2026-11-23",
    token=1, tradingsymbol="X", entry_timestamp=BASE,
    entry_candle_start=BASE, entry_candle_end=BASE + timedelta(minutes=5),
    entry_price=120.0, sma9=100.0, prev_close=110.0, current_open=115.0,
    condition_a=True, condition_b=True, ltp_at_entry=120.0,
    atr_at_entry=10.0, stop_price=113.0, stop_k=0.7,
    stop_distance_pct=0.0583, stop_source="atr",
    trail_distance=7.0, hwm=120.0,
)
check("trail_inactive_at_entry", p.update_trail(119.5) is None and p.stop is None,
      f"stop={p.stop}")
check("trail_no_fixed_activation", p.update_trail(121.0) is None and p.stop == 114.0,
      f"stop={p.stop}")
check("trail_uses_atr_distance", p.update_trail(126.0) is None and p.stop == 119.0,
      f"stop={p.stop}")
check("trail_exit_at_ratcheted_stop", p.update_trail(118.5) == 119.0,
      f"stop={p.stop}")
check("no_breakeven_lock", not p.be_locked)
check("trail_never_ratchets_down",
      p.update_trail(130.0) is None and p.stop == 123.0
      and p.update_trail(124.0) is None and p.stop == 123.0,
      f"stop={p.stop}")

p2 = Position.from_dict(p.as_dict())
check("roundtrip_stop",
      p2.stop_price == p.stop_price and p2.atr_at_entry == 10.0
      and p2.trail_distance == 7.0,
      f"stop={p2.stop_price} trail={p2.trail_distance}")

trade = sm.close(entry_time + timedelta(minutes=2), 108.5, "STOP_LOSS_ATR")
check("trade_metadata",
      trade["stop_price"] == pos.stop_price and trade["stop_k"] == 0.7
      and trade["stop_source"] == "atr"
      and trade["trail_distance"] == compute_stop(120.0, 10.0)[1]
      and trade["pnl_points"] == round(108.5 - pos.entry_price, 2),
      f"{trade.get('stop_price')} {trade.get('pnl_points')}")
check("close_strategy", trade["strategy_id"] == STRATEGY_ID)

# No candle-close time exit: the position stays open inside its candle.
sm3 = OptionStateMachine("CE")
sm3.try_entry(ev, entry_time, 25250, "2026-11-23", 123,
              "NIFTY2525025250CE", market_close, atr=10.0)
check("no_time_exit_inside_candle",
      not sm3.needs_exit(entry_time + timedelta(minutes=4, seconds=59)))
check("candle_end_flag", sm3.needs_exit(entry_time + timedelta(minutes=5)))

# --- ids ------------------------------------------------------------------
tid = make_trade_id("NIFTY", 25250, "PE", BASE)
check("trade_id_prefix", tid.startswith("S1M-") and len(tid) == 16, tid)
check("trade_id_stable", tid == make_trade_id("NIFTY", 25250, "PE", BASE))

# --- v1.0.0 open position is migrated to the ATR trail on restore ---------
fd, legacy_db = tempfile.mkstemp(suffix=".db")
os.close(fd)
old_db_path = live.DB_PATH
try:
    live.DB_PATH = legacy_db
    conn = sqlite3.connect(legacy_db)
    conn.executescript(
        """CREATE TABLE sma9_1min_poll_open_positions (
               option_type TEXT PRIMARY KEY, trade_id TEXT, strike REAL,
               expiry TEXT, token INTEGER, tradingsymbol TEXT,
               entry_timestamp TEXT, entry_candle_start TEXT,
               entry_candle_end TEXT, entry_price REAL, sma9 REAL,
               prev_close REAL, current_open REAL, condition_a INTEGER,
               condition_b INTEGER, ltp_at_entry REAL, hwm REAL,
               stop_price REAL, be_locked INTEGER, updated_at TEXT);
           CREATE TABLE sma9_1min_poll_trades (trade_id TEXT PRIMARY KEY,
               strategy_id TEXT, trade_date TEXT, trade_timestamp TEXT,
               option_type TEXT, strike REAL, expiry TEXT, signal_timestamp TEXT,
               entry_timestamp TEXT, entry_price REAL, exit_timestamp TEXT,
               exit_price REAL, exit_reason TEXT, pnl_points REAL, status TEXT,
               sma9_value REAL, candle_open REAL, candle_high REAL,
               candle_low REAL, candle_close REAL, created_at TEXT,
               updated_at TEXT, dataset TEXT, prev_close REAL,
               condition_a INTEGER, condition_b INTEGER, ltp_at_entry REAL,
               entry_candle_start TEXT, entry_candle_end TEXT);
           CREATE TABLE sma9_1min_poll_scan_state (key TEXT PRIMARY KEY,
               value TEXT, updated_at TEXT);""")
    conn.execute(
        """INSERT INTO sma9_1min_poll_open_positions
           (option_type, trade_id, strike, expiry, token, tradingsymbol,
            entry_timestamp, entry_candle_start, entry_candle_end, entry_price,
            sma9, prev_close, current_open, condition_a, condition_b,
            ltp_at_entry, hwm, stop_price, be_locked, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        ("CE", "LEGACY", 25000, "2026-11-23", 1, "X",
         BASE.isoformat(), BASE.isoformat(),
         (BASE + timedelta(minutes=5)).isoformat(),
         120.0, 100.0, 110.0, 115.0, 1, 1, 120.0, 126.0, 122.0, 1,
         BASE.isoformat()),
    )
    conn.commit()
    conn.close()

    live.init_db()
    legacy = live.load_open_positions()["CE"]
    expected_distance = compute_stop(120.0, None)[1]
    check("legacy_restore_uses_atr_trail",
          legacy.stop_price == compute_stop(120.0, None)[0]
          and legacy.trail_distance == expected_distance
          and legacy.stop == round(126.0 - expected_distance, 2)
          and legacy.be_locked is False,
          f"stop={legacy.stop} dist={legacy.trail_distance} be={legacy.be_locked}")
finally:
    live.DB_PATH = old_db_path
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(legacy_db + suffix)
        except FileNotFoundError:
            pass

print()
if failures:
    print("FAILED:", ", ".join(failures))
    sys.exit(1)
print("All checks passed.")
