#!/usr/bin/env python3
"""Offline checks for the ATR-stop engine and the daily regime gate.

No network, no broker, no DB writes.
"""
import os
import sqlite3
import sys
import tempfile
from datetime import date, datetime, time as dtime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import app.live_sma9_atr_scanner as live  # noqa: E402
from app.live_sma9_atr_scanner import compute_spot_regime  # noqa: E402
from app.sma9_atr_engine import (  # noqa: E402
    OptionStateMachine,
    Position,
    compute_stop,
    evaluate_option,
    premium_atr,
)

BASE = datetime(2026, 11, 18, 9, 15)
NOW = datetime(2026, 11, 18, 9, 20, 5)


def flat_candles(n=17, lo=95.0, hi=105.0, close=100.0):
    out = []
    for i in range(n):
        out.append({
            "start": BASE + timedelta(minutes=5 * i),
            "open": close, "high": hi, "low": lo, "close": close, "volume": 0,
        })
    return out


def rising_candles(n=17):
    out = []
    for i in range(n):
        c = 100.0 + i
        out.append({
            "start": BASE + timedelta(minutes=5 * i),
            "open": c - 1, "high": c + 2, "low": c - 2, "close": c, "volume": 0,
        })
    return out


def spot_history(prev_closes, today, volume=0):
    """Completed 5m spot candles: prior session history + today's 09:15 bar."""
    rows = []
    prev_day = date(2026, 11, 17)
    for i, close in enumerate(prev_closes):
        start = datetime.combine(prev_day, dtime(9, 15)) + timedelta(minutes=5 * i)
        rows.append({
            "start": start, "open": close - 1.0, "high": close + 1.0,
            "low": close - 1.0, "close": close, "volume": volume,
        })
    rows.append({
        "start": datetime.combine(date(2026, 11, 18), dtime(9, 15)),
        "open": today["open"], "high": today["high"], "low": today["low"],
        "close": today["close"], "volume": volume,
    })
    return rows


failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"PASS {name}")
    else:
        failures.append(name)
        print(f"FAIL {name} {detail}")


# 1. ATR of a constant 10-point range is 10.
atr = premium_atr(flat_candles())
check("atr_constant_range", atr is not None and abs(atr - 10.0) < 1e-9, f"atr={atr}")

# 2. Not enough history -> None.
check("atr_insufficient", premium_atr(flat_candles(10)) is None)

# 3. Stop distance bounds.
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

# 4. Entry signal uses prev_close and forming open, both vs SMA9.
candles = rising_candles()
candles[-1]["open"] = 125.0
ev = evaluate_option(candles, "CE", ltp=125.0)
check("entry_signal", ev.signal and ev.ready, ev.reason)

# 5. Entry stores the ATR stop and trail distance; stop fills at actual LTP.
sm = OptionStateMachine("CE")
pos = sm.try_entry(ev, BASE + timedelta(minutes=80), 25000, "2026-11-23",
                   1, "NIFTY26NOV25000CE", BASE + timedelta(hours=6), atr=10.0)
check("entry_position", pos is not None and pos.stop_price is not None,
      "no position")
expected_stop, expected_dist, _, _ = compute_stop(pos.entry_price, 10.0)
check("entry_stop_price", pos.stop_price == expected_stop,
      f"stop={pos.stop_price} entry={pos.entry_price} expected={expected_stop}")
check("entry_trail_distance", pos.trail_distance == expected_dist,
      f"trail_distance={pos.trail_distance} expected={expected_dist}")
check("stop_not_hit", sm.check_stop_loss(pos.stop_price + 0.5) is None)
fill = sm.check_stop_loss(pos.stop_price - 1.5)
check("stop_fill_at_ltp", fill == round(pos.stop_price - 1.5, 2), f"fill={fill}")

# 6. ATR trail only: any new high ratchets by the ATR distance; no BE lock.
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
check("trail_no_exit_after_new_high", p.update_trail(126.0) is None)
check("trail_uses_atr_distance_not_be_lock", p.stop == 119.0, f"stop={p.stop}")
check("trail_no_exit_above_stop", p.update_trail(121.0) is None,
      f"stop={p.stop}")
check("trail_exit_at_ratcheted_stop", p.update_trail(118.5) == 119.0,
      f"stop={p.stop}")
check("trail_never_ratchets_down",
      p.update_trail(130.0) is None and p.stop == 123.0
      and p.update_trail(124.0) is None and p.stop == 123.0,
      f"stop={p.stop}")

# 7. Round-trip through as_dict/from_dict keeps ATR + trail fields.
p2 = Position.from_dict(p.as_dict())
check("roundtrip_stop",
      p2.stop_price == p.stop_price and p2.atr_at_entry == 10.0
      and p2.trail_distance == 7.0,
      f"stop={p2.stop_price} trail={p2.trail_distance}")

# 8. Closed trade carries the stop + trail metadata.
trade = sm.close(BASE + timedelta(minutes=85), 108.5, "STOP_LOSS_ATR")
check("trade_metadata",
      trade["stop_price"] == pos.stop_price and trade["stop_k"] == 0.7
      and trade["stop_source"] == "atr"
      and trade["trail_distance"] == expected_dist
      and trade["pnl_points"] == round(108.5 - pos.entry_price, 2),
      f"{trade.get('stop_price')} {trade.get('pnl_points')}")

# 9. Daily regime: rising spot above VWAP/rising EMA9 -> CE only.
bull = compute_spot_regime(
    spot_history([100 + i for i in range(12)],
                 {"open": 113.0, "high": 115.0, "low": 112.0, "close": 114.0}),
    NOW)
check("regime_bullish",
      bull["bias"] == "BULLISH" and bull["allowed_option"] == "CE",
      f"{bull}")

# 10. Daily regime: falling spot below VWAP/falling EMA9 -> PE only.
bear = compute_spot_regime(
    spot_history([120 - i for i in range(12)],
                 {"open": 108.0, "high": 108.0, "low": 104.0, "close": 105.0}),
    NOW)
check("regime_bearish",
      bear["bias"] == "BEARISH" and bear["allowed_option"] == "PE",
      f"{bear}")

# 11. Mixed or insufficient data -> no entries.
mixed = compute_spot_regime(
    spot_history([100 + i for i in range(12)],
                 {"open": 112.0, "high": 116.0, "low": 111.0, "close": 112.0}),
    NOW)
check("regime_mixed", mixed["bias"] == "NEUTRAL"
      and mixed["allowed_option"] is None, f"{mixed}")
check("regime_insufficient",
      compute_spot_regime([], NOW)["bias"] == "NEUTRAL")

# 12. Zero-volume index candles fall back to typical-price VWAP.
zero_vol = spot_history([100 + i for i in range(12)],
                        {"open": 113.0, "high": 115.0, "low": 112.0, "close": 114.0},
                        volume=0)
zv = compute_spot_regime(zero_vol, NOW)
check("regime_zero_volume_vwap",
      zv["vwap"] == round((115.0 + 112.0 + 114.0) / 3.0, 2),
      f"vwap={zv['vwap']}")

# 13. Forming candle is never used by the regime gate.
future = compute_spot_regime(
    spot_history([120 - i for i in range(12)],
                 {"open": 108.0, "high": 108.0, "low": 104.0, "close": 105.0}),
    NOW)
check("regime_ignores_forming_candle", future["bias"] == "BEARISH")

# 14. A v1.0.0 open position is migrated to the ATR trail on restore.
fd, legacy_db = tempfile.mkstemp(suffix=".db")
os.close(fd)
old_db_path = live.DB_PATH
try:
    live.DB_PATH = legacy_db
    live.init_db()
    conn = sqlite3.connect(legacy_db)
    conn.execute(
        """INSERT INTO sma9_atr_open_positions
           (option_type, trade_id, strike, expiry, token, tradingsymbol,
            entry_timestamp, entry_candle_start, entry_candle_end, entry_price,
            sma9, prev_close, current_open, condition_a, condition_b,
            ltp_at_entry, atr_at_entry, stop_price, stop_k, stop_distance_pct,
            stop_source, hwm, trail_stop, be_locked, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        ("CE", "LEGACY", 25000, "2026-11-23", 1, "X",
         BASE.isoformat(), BASE.isoformat(),
         (BASE + timedelta(minutes=5)).isoformat(),
         120.0, 100.0, 110.0, 115.0, 1, 1, 120.0, 10.0, 113.0, 0.7, 0.0583,
         "atr", 126.0, 122.0, 1, BASE.isoformat()),
    )
    conn.commit()
    conn.close()
    legacy = live.load_open_positions()["CE"]
    expected_distance = compute_stop(120.0, 10.0)[1]
    check("legacy_restore_uses_atr_trail",
          legacy.trail_distance == expected_distance
          and legacy.stop == round(126.0 - expected_distance, 2)
          and legacy.be_locked is False,
          f"dist={legacy.trail_distance} stop={legacy.stop} be={legacy.be_locked}")
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
