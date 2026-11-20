#!/usr/bin/env python3
"""Offline checks for the SMA9 5-second ATR engine (no network, no broker).

Pins the rules that define this scanner after v1.1.0:
  * poll cadence is 5 seconds (checked in the deployed-runner dry run)
  * entry = SMA9 A and B and C (SMA9 rising), no LTP gate
  * initial stop = clamp(0.70 * ATR14, 5%, 30% of entry), filled at live LTP
  * trail = ATR width only, active once price is above entry; no BE lock
"""
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.sma9_5s_atr_engine import (  # noqa: E402
    Evaluation,
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
from app import live_sma9_5s_atr_scanner as live  # noqa: E402

BASE = datetime(2026, 11, 19, 9, 15)


def flat_candles(n=17, lo=95.0, hi=105.0, close=100.0):
    out = []
    for i in range(n):
        out.append({
            "start": BASE + timedelta(minutes=5 * i),
            "open": close, "high": hi, "low": lo, "close": close, "volume": 0,
        })
    return out


def rising_candles(n=17, step=1.0):
    out = []
    for i in range(n):
        c = 100.0 + i * step
        out.append({
            "start": BASE + timedelta(minutes=5 * i),
            "open": c - 1, "high": c + 2, "low": c - 2, "close": c, "volume": 0,
        })
    return out


def sma_flat_with_high_dropped():
    """A/B true but C false: 200 drops out, 110 comes in above the average."""
    closes = [200.0] + [100.0] * 8 + [110.0]
    rows = []
    for i, c in enumerate(closes):
        rows.append({
            "start": BASE + timedelta(minutes=5 * i),
            "open": c, "high": c + 1, "low": c - 1, "close": c, "volume": 0,
        })
    rows.append({"start": BASE + timedelta(minutes=5 * len(closes)),
                 "open": 120.0, "high": 121.0, "low": 119.0,
                 "close": 120.0, "volume": 0})
    return rows


failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"PASS {name}")
    else:
        failures.append(name)
        print(f"FAIL {name} {detail}")


# --- identity -------------------------------------------------------------
check("strategy_id", STRATEGY_ID == "sma9_5s_atr", STRATEGY_ID)
check("strategy_type", STRATEGY_TYPE == "SMA9_5S_ATR_STOP_BUY_ONLY",
      STRATEGY_TYPE)
check("strategy_version", STRATEGY_VERSION == "1.1.0", STRATEGY_VERSION)
check("poll_seconds", live.POLL_SECONDS == 5, live.POLL_SECONDS)

# --- ATR ------------------------------------------------------------------
atr = premium_atr(flat_candles())
check("atr_constant_range", atr is not None and abs(atr - 10.0) < 1e-9,
      f"atr={atr}")
check("atr_insufficient", premium_atr(flat_candles(10)) is None)

# --- stop distance bounds -------------------------------------------------
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

# --- entry: SMA9 A, B and C ----------------------------------------------
candles = rising_candles()
candles[-1]["open"] = 125.0
ev = evaluate_option(candles, "CE", ltp=125.0)
check("entry_A_and_B", ev.signal and ev.qualified, ev.reason)
check("entry_C_sma9_rising", ev.condition_c and ev.prev_sma9 is not None
      and ev.sma9 > ev.prev_sma9,
      f"sma9={ev.sma9} prev={ev.prev_sma9}")
ev_low = evaluate_option(candles, "CE", ltp=1.0)
check("entry_ignores_ltp_confirmation",
      ev_low.signal and ev_low.confirmation is False,
      f"confirmation={ev_low.confirmation}")

candles_b = rising_candles()
candles_b[-1]["open"] = 90.0                 # forming open below SMA9
ev_b = evaluate_option(candles_b, "CE", ltp=200.0)
check("no_entry_when_B_false",
      not ev_b.signal and ev_b.condition_a and not ev_b.condition_b,
      ev_b.reason)

ev_fall = evaluate_option(rising_candles(step=-1.0), "CE", ltp=200.0)
check("no_entry_when_A_false", not ev_fall.signal and not ev_fall.condition_a,
      ev_fall.reason)
check("falling_sma9_has_C_false", ev_fall.condition_c is False,
      f"sma9={ev_fall.sma9} prev={ev_fall.prev_sma9}")

# C is not redundant with A: a high candle dropping out can lower the average
# even though the newest close is above it.
ev_c_false = evaluate_option(sma_flat_with_high_dropped(), "CE", ltp=120.0)
check("C_blocks_entry_when_A_and_B_true",
      ev_c_false.condition_a and ev_c_false.condition_b
      and not ev_c_false.condition_c and not ev_c_false.signal,
      f"A={ev_c_false.condition_a} B={ev_c_false.condition_b} "
      f"C={ev_c_false.condition_c} sma9={ev_c_false.sma9} "
      f"prev={ev_c_false.prev_sma9}")

# C is an explicit gate: an evaluation with C forced off must not enter even
# when A and B are true.
ev_no_c = Evaluation(
    option_type="CE", candle_start=candles[-1]["start"],
    candle_end=candles[-1]["start"] + timedelta(minutes=5),
    sma9=ev.sma9, prev_sma9=ev.prev_sma9, current_open=125.0,
    prev_close=ev.prev_close, ltp=125.0,
    condition_a=True, condition_b=True, condition_c=False,
    qualified=False, signal=False, ready=True,
    reason="forced C false")
sm_c = OptionStateMachine("CE")
check("no_entry_when_C_false",
      sm_c.try_entry(ev_no_c, BASE + timedelta(minutes=80), 25000,
                     "2026-11-23", 9, "NOC", BASE + timedelta(hours=6),
                     atr=10.0) is None)

check("entry_needs_10_completed_candles",
      evaluate_option(rising_candles(10), "CE", ltp=125.0).signal is False)

# --- entry stores the stop metadata ---------------------------------------
sm = OptionStateMachine("CE")
entry_time = BASE + timedelta(minutes=80)
market_close = datetime(2026, 11, 19, 15, 30)
pos = sm.try_entry(ev, entry_time, 25000, "2026-11-23", 1,
                   "NIFTY26NOV25000CE", market_close, atr=10.0)
check("entry_position", pos is not None and pos.stop_price is not None,
      "no position")
expected_stop = compute_stop(pos.entry_price, 10.0)[0]
expected_dist = compute_stop(pos.entry_price, 10.0)[1]
check("entry_stop_price", pos.stop_price == expected_stop,
      f"stop={pos.stop_price} entry={pos.entry_price} expected={expected_stop}")
check("entry_trail_distance", pos.trail_distance == expected_dist,
      f"trail_distance={pos.trail_distance}")
check("entry_stop_metadata",
      pos.atr_at_entry == 10.0 and pos.stop_source == "atr"
      and pos.stop_k == 0.70,
      f"{pos.atr_at_entry} {pos.stop_source} {pos.stop_k}")
check("entry_records_sma9_slope",
      pos.condition_c is True and pos.prev_sma9 == round(ev.prev_sma9, 2),
      f"C={pos.condition_c} prev_sma9={pos.prev_sma9}")

# Duplicate poll in the same 5-minute candle is rejected.
again = sm.try_entry(ev, entry_time + timedelta(seconds=5), 25000,
                     "2026-11-23", 1, "NIFTY26NOV25000CE", market_close,
                     atr=10.0)
check("duplicate_candle_guard", again is None)

# --- initial stop fills at the live LTP ----------------------------------
check("stop_not_hit", sm.check_stop_loss(pos.stop_price + 0.5) is None)
fill = sm.check_stop_loss(pos.stop_price - 1.5)
check("stop_fill_at_ltp", fill == round(pos.stop_price - 1.5, 2), f"fill={fill}")

# --- trail: ATR distance only, active above entry, no BE lock -------------
p = Position(
    option_type="CE", trade_id="T", strike=25000, expiry="2026-11-23",
    token=1, tradingsymbol="X", entry_timestamp=BASE,
    entry_candle_start=BASE, entry_candle_end=BASE + timedelta(minutes=5),
    entry_price=120.0, sma9=100.0, prev_close=110.0, current_open=115.0,
    condition_a=True, condition_b=True, condition_c=True, ltp_at_entry=120.0,
    atr_at_entry=10.0, stop_price=113.0, stop_k=0.7,
    stop_distance_pct=0.0583, stop_source="atr",
    trail_distance=7.0, hwm=120.0,
)
check("trail_inactive_at_entry", p.update_trail(119.5) is None and p.stop is None,
      f"stop={p.stop}")
check("trail_no_exit_after_new_high", p.update_trail(126.0) is None)
check("trail_uses_atr_distance_not_be_lock", p.stop == 119.0, f"stop={p.stop}")
check("trail_no_fixed_activation", p.be_locked is False)
check("trail_no_exit_above_stop", p.update_trail(121.0) is None,
      f"stop={p.stop}")
check("trail_exit_at_ratcheted_stop", p.update_trail(118.5) == 119.0,
      f"stop={p.stop}")
check("trail_never_ratchets_down",
      p.update_trail(130.0) is None and p.stop == 123.0
      and p.update_trail(124.0) is None and p.stop == 123.0,
      f"stop={p.stop}")

# A wide ATR trail is not overridden by a fixed breakeven lock.
p_wide = Position(
    option_type="CE", trade_id="W", strike=25000, expiry="2026-11-23",
    token=1, tradingsymbol="X", entry_timestamp=BASE,
    entry_candle_start=BASE, entry_candle_end=BASE + timedelta(minutes=5),
    entry_price=100.0, sma9=90.0, prev_close=95.0, current_open=97.0,
    condition_a=True, condition_b=True, condition_c=True, ltp_at_entry=100.0,
    atr_at_entry=40.0, stop_price=70.0, stop_k=0.7,
    stop_distance_pct=0.30, stop_source="atr",
    trail_distance=30.0, hwm=100.0,
)
check("wide_trail_uses_atr_only",
      p_wide.update_trail(106.0) is None and p_wide.stop == 76.0
      and p_wide.be_locked is False,
      f"stop={p_wide.stop} be={p_wide.be_locked}")

# --- restart round-trip ---------------------------------------------------
p2 = Position.from_dict(p.as_dict())
check("roundtrip_stop",
      p2.stop_price == p.stop_price and p2.atr_at_entry == 10.0
      and p2.trail_distance == 7.0
      and p2.prev_sma9 == p.prev_sma9 and p2.condition_c is True,
      f"stop={p2.stop_price} trail={p2.trail_distance}")

# --- closed trade carries the stop metadata ------------------------------
trade = sm.close(BASE + timedelta(minutes=85), 108.5, "STOP_LOSS_ATR")
check("trade_metadata",
      trade["stop_price"] == pos.stop_price and trade["stop_k"] == 0.7
      and trade["stop_source"] == "atr"
      and trade["trail_distance"] == expected_dist
      and trade["condition_c"] == 1
      and trade["pnl_points"] == round(108.5 - pos.entry_price, 2),
      f"{trade.get('stop_price')} {trade.get('pnl_points')}")
check("close_clears_position", sm.position is None)

# --- legacy v1.0.0 restore migrates the BE-locked trail -------------------
fd, legacy_db = tempfile.mkstemp(suffix=".db")
os.close(fd)
old_db_path = live.DB_PATH
try:
    live.DB_PATH = legacy_db
    live.init_db()
    conn = sqlite3.connect(legacy_db)
    conn.execute(
        """INSERT INTO sma9_5s_atr_open_positions
           (option_type, trade_id, strike, expiry, token, tradingsymbol,
            entry_timestamp, entry_candle_start, entry_candle_end, entry_price,
            sma9, prev_close, current_open, condition_a, condition_b,
            ltp_at_entry, atr_at_entry, stop_price, stop_k, stop_distance_pct,
            stop_source, trail_distance, hwm, trail_stop, be_locked, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        ("CE", "LEGACY", 25000, "2026-11-23", 1, "X",
         BASE.isoformat(), BASE.isoformat(),
         (BASE + timedelta(minutes=5)).isoformat(),
         120.0, 100.0, 110.0, 115.0, 1, 1, 120.0, 10.0, 113.0, 0.7, 0.0583,
         "atr", 7.0, 126.0, 122.0, 1, BASE.isoformat()),
    )
    conn.commit()
    conn.close()
    legacy = live.load_open_positions()["CE"]
    check("legacy_restore_uses_atr_trail",
          legacy.trail_distance == compute_stop(120.0, 10.0)[1]
          and legacy.stop == round(126.0 - compute_stop(120.0, 10.0)[1], 2)
          and legacy.be_locked is False
          and legacy.condition_c is False,
          f"dist={legacy.trail_distance} stop={legacy.stop} "
          f"be={legacy.be_locked}")
finally:
    live.DB_PATH = old_db_path
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(legacy_db + suffix)
        except FileNotFoundError:
            pass

# --- ids ------------------------------------------------------------------
tid = make_trade_id("NIFTY", 25000, "PE", BASE)
check("trade_id_prefix", tid.startswith("S1A-") and len(tid) == 16, tid)
check("trade_id_stable", tid == make_trade_id("NIFTY", 25000, "PE", BASE))

if failures:
    print(f"\n{len(failures)} FAILED: {', '.join(failures)}")
    sys.exit(1)
print("\nall checks passed")
