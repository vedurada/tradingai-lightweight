#!/usr/bin/env python3
"""Offline checks for the SMA9 1-minute ATR engine (no network, no broker).

Pins the three rules that define this scanner:
  * entry = SMA9 A and B only (same as sma9_1min_poll), no LTP gate
  * initial stop = clamp(0.70 * ATR14, 5%, 30% of entry), filled at live LTP
  * trail = same +5 / +6 shape, but the ratchet distance is that ATR distance
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.sma9_1min_atr_engine import (  # noqa: E402
    OptionStateMachine,
    Position,
    STRATEGY_ID,
    STRATEGY_TYPE,
    compute_stop,
    evaluate_option,
    make_trade_id,
    premium_atr,
)

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


failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"PASS {name}")
    else:
        failures.append(name)
        print(f"FAIL {name} {detail}")


# --- identity -------------------------------------------------------------
check("strategy_id", STRATEGY_ID == "sma9_1min_atr", STRATEGY_ID)
check("strategy_type", STRATEGY_TYPE == "SMA9_1MIN_ATR_STOP_BUY_ONLY",
      STRATEGY_TYPE)

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

# --- entry: SMA9 A and B only --------------------------------------------
candles = rising_candles()
candles[-1]["open"] = 125.0
ev = evaluate_option(candles, "CE", ltp=125.0)
check("entry_A_and_B", ev.signal and ev.qualified, ev.reason)
ev_low = evaluate_option(candles, "CE", ltp=1.0)
check("entry_ignores_ltp_confirmation",
      ev_low.signal and ev_low.confirmation is False,
      f"confirmation={ev_low.confirmation}")

candles = rising_candles()
candles[-1]["open"] = 90.0                 # forming open below SMA9
ev_b = evaluate_option(candles, "CE", ltp=200.0)
check("no_entry_when_B_false",
      not ev_b.signal and ev_b.condition_a and not ev_b.condition_b,
      ev_b.reason)

ev_a = evaluate_option(rising_candles(step=-1.0), "CE", ltp=200.0)
check("no_entry_when_A_false", not ev_a.signal and not ev_a.condition_a,
      ev_a.reason)

# --- entry stores the ATR stop and the ATR trail distance -----------------
sm = OptionStateMachine("CE")
entry_time = BASE + timedelta(minutes=80)
market_close = datetime(2026, 11, 19, 15, 30)
pos = sm.try_entry(ev, entry_time, 25000, "2026-11-23", 1,
                   "NIFTY26NOV25000CE", market_close, atr=10.0)
check("entry_position", pos is not None and pos.stop_price is not None,
      "no position")
expected_stop = compute_stop(pos.entry_price, 10.0)[0]
check("entry_stop_price", pos.stop_price == expected_stop,
      f"stop={pos.stop_price} entry={pos.entry_price} expected={expected_stop}")
check("entry_trail_distance", pos.trail_distance == 7.0,
      f"trail_distance={pos.trail_distance}")
check("entry_stop_metadata",
      pos.atr_at_entry == 10.0 and pos.stop_source == "atr"
      and pos.stop_k == 0.70,
      f"{pos.atr_at_entry} {pos.stop_source} {pos.stop_k}")

# Duplicate poll in the same 5-minute candle is rejected.
again = sm.try_entry(ev, entry_time + timedelta(seconds=60), 25000,
                     "2026-11-23", 1, "NIFTY26NOV25000CE", market_close,
                     atr=10.0)
check("duplicate_candle_guard", again is None)

# --- initial stop fills at the live LTP ----------------------------------
check("stop_not_hit", sm.check_stop_loss(pos.stop_price + 0.5) is None)
fill = sm.check_stop_loss(pos.stop_price - 1.5)
check("stop_fill_at_ltp", fill == round(pos.stop_price - 1.5, 2), f"fill={fill}")

# --- trail: +5 activates breakeven, ratchets at peak - ATR distance -------
p = Position(
    option_type="CE", trade_id="T", strike=25000, expiry="2026-11-23",
    token=1, tradingsymbol="X", entry_timestamp=BASE,
    entry_candle_start=BASE, entry_candle_end=BASE + timedelta(minutes=5),
    entry_price=120.0, sma9=100.0, prev_close=110.0, current_open=115.0,
    condition_a=True, condition_b=True, ltp_at_entry=120.0,
    atr_at_entry=10.0, stop_price=110.0, stop_k=0.7,
    stop_distance_pct=0.0833, stop_source="atr", trail_distance=7.0,
    hwm=120.0,
)
check("trail_inactive_below_plus5", p.update_trail(124.9) is None and p.stop is None)
check("trail_activate_breakeven", p.update_trail(125.0) is None and p.stop == 120.0,
      f"stop={p.stop}")
check("trail_no_exit_at_breakeven", p.update_trail(120.0) is None,
      f"stop={p.stop}")
check("trail_ratchets_at_atr_distance",
      p.update_trail(131.0) is None and p.stop == 124.0, f"stop={p.stop}")
check("trail_holds_above", p.update_trail(124.5) is None and p.stop == 124.0,
      f"stop={p.stop}")

# A single 60s poll that jumps past activation must ratchet in the same tick,
# not sit at breakeven until the next minute.
p1b = Position(
    option_type="CE", trade_id="T1b", strike=25000, expiry="2026-11-23",
    token=1, tradingsymbol="X", entry_timestamp=BASE,
    entry_candle_start=BASE, entry_candle_end=BASE + timedelta(minutes=5),
    entry_price=120.0, sma9=100.0, prev_close=110.0, current_open=115.0,
    condition_a=True, condition_b=True, ltp_at_entry=120.0,
    atr_at_entry=10.0, stop_price=110.0, stop_k=0.7,
    stop_distance_pct=0.0833, stop_source="atr", trail_distance=7.0,
    hwm=120.0,
)
check("trail_ratchets_on_first_jump",
      p1b.update_trail(133.0) is None and p1b.stop == 126.0, f"stop={p1b.stop}")
check("trail_exit_at_atr_stop", p.update_trail(123.9) == 124.0, f"stop={p.stop}")

# --- breakeven lock at +6 is unchanged -----------------------------------
p2 = Position(
    option_type="CE", trade_id="T2", strike=25000, expiry="2026-11-23",
    token=1, tradingsymbol="X", entry_timestamp=BASE,
    entry_candle_start=BASE, entry_candle_end=BASE + timedelta(minutes=5),
    entry_price=120.0, sma9=100.0, prev_close=110.0, current_open=115.0,
    condition_a=True, condition_b=True, ltp_at_entry=120.0,
    atr_at_entry=10.0, stop_price=110.0, stop_k=0.7,
    stop_distance_pct=0.0833, stop_source="atr", trail_distance=7.0,
    hwm=120.0,
)
check("be_lock_holds", p2.update_trail(126.0) is None)
check("be_lock_stop", p2.be_locked and p2.stop == 122.0, f"stop={p2.stop}")
check("be_lock_exit", p2.update_trail(121.9) == 122.0, f"stop={p2.stop}")

# A wide ATR trail must not undo the tighter breakeven lock.
p3 = Position(
    option_type="CE", trade_id="T3", strike=25000, expiry="2026-11-23",
    token=1, tradingsymbol="X", entry_timestamp=BASE,
    entry_candle_start=BASE, entry_candle_end=BASE + timedelta(minutes=5),
    entry_price=100.0, sma9=90.0, prev_close=95.0, current_open=97.0,
    condition_a=True, condition_b=True, ltp_at_entry=100.0,
    atr_at_entry=40.0, stop_price=70.0, stop_k=0.7,
    stop_distance_pct=0.30, stop_source="atr", trail_distance=30.0,
    hwm=100.0,
)
check("wide_trail_be_lock", p3.update_trail(106.0) is None and p3.stop == 102.0,
      f"stop={p3.stop}")
check("wide_trail_monotone",
      p3.update_trail(140.0) is None and p3.stop == 110.0, f"stop={p3.stop}")

# --- restart round-trip keeps stop + trail distance ----------------------
p4 = Position.from_dict(p.as_dict())
check("roundtrip_stop", p4.stop_price == 110.0 and p4.atr_at_entry == 10.0)
check("roundtrip_trail", p4.trail_distance == 7.0, f"{p4.trail_distance}")

# --- closed trade carries the stop metadata ------------------------------
trade = sm.close(BASE + timedelta(minutes=85), 108.5, "STOP_LOSS_ATR")
check("trade_metadata",
      trade["stop_price"] == pos.stop_price and trade["stop_k"] == 0.7
      and trade["stop_source"] == "atr"
      and trade["pnl_points"] == round(108.5 - pos.entry_price, 2),
      f"{trade.get('stop_price')} {trade.get('pnl_points')}")
check("close_clears_position", sm.position is None)

# --- ids ------------------------------------------------------------------
tid = make_trade_id("NIFTY", 25000, "PE", BASE)
check("trade_id_prefix", tid.startswith("S1A-") and len(tid) == 16, tid)
check("trade_id_stable", tid == make_trade_id("NIFTY", 25000, "PE", BASE))

if failures:
    print(f"\n{len(failures)} FAILED: {', '.join(failures)}")
    sys.exit(1)
print("\nall checks passed")
