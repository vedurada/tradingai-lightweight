#!/usr/bin/env python3
"""Offline checks for the SMA9 1-minute-poll engine (no network, no broker).

The engine is a copy of the SMA9 engine; these checks pin the rules that must
stay identical and the poll-independent state machine behaviour.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.sma9_1min_poll_engine import (  # noqa: E402
    OptionStateMachine,
    STRATEGY_ID,
    STRATEGY_TYPE,
    evaluate_option,
    make_trade_id,
)

BASE = datetime(2026, 11, 19, 9, 15)


def candles(n=17, step=1.0, open_last=None):
    """Monotonic candles so prev close and forming open are above SMA9."""
    out = []
    for i in range(n):
        c = 100.0 + i * step
        row = {
            "start": BASE + timedelta(minutes=5 * i),
            "open": c - 0.5, "high": c + 1.0, "low": c - 1.0,
            "close": c, "volume": 0,
        }
        out.append(row)
    if open_last is not None:
        out[-1]["open"] = open_last
    return out


failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"PASS {name}")
    else:
        failures.append(name)
        print(f"FAIL {name} {detail}")


# --- constants ------------------------------------------------------------
check("strategy_id", STRATEGY_ID == "sma9_1min_poll", STRATEGY_ID)
check("strategy_type", STRATEGY_TYPE == "SMA9_1MIN_POLL_BUY_ONLY", STRATEGY_TYPE)

# --- entry rule: A and B, no LTP confirmation gate ------------------------
rows = candles(open_last=120.0)
ev = evaluate_option(rows, "CE", ltp=1.0)
check("entry_A_and_B", ev.signal and ev.qualified, ev.reason)
check("entry_ignores_ltp_confirmation",
      ev.signal and ev.confirmation is False, f"confirmation={ev.confirmation}")

rows = candles(open_last=90.0)          # forming open below SMA9
ev = evaluate_option(rows, "CE", ltp=120.0)
check("no_entry_when_B_false", not ev.signal and ev.condition_a
      and not ev.condition_b, ev.reason)

rows = candles(step=-1.0)               # falling series: prev close below SMA9
ev = evaluate_option(rows, "CE", ltp=120.0)
check("no_entry_when_A_false", not ev.signal and not ev.condition_a,
      ev.reason)

rows = candles(n=5)
ev = evaluate_option(rows, "CE", ltp=100.0)
check("insufficient_candles", not ev.ready and not ev.signal, ev.reason)

# --- state machine --------------------------------------------------------
sm = OptionStateMachine("CE")
ev = evaluate_option(candles(open_last=120.0), "CE", ltp=120.0)
entry_time = BASE + timedelta(minutes=80)
market_close = datetime(2026, 11, 19, 15, 30)
pos = sm.try_entry(ev, entry_time, 25250, "2026-11-23", 123, "NIFTY2525025250CE",
                   market_close)
check("entry_created", pos is not None and pos.entry_price == 120.0)

# Duplicate poll in the same 5-minute candle is rejected.
again = sm.try_entry(ev, entry_time + timedelta(seconds=60), 25250,
                     "2026-11-23", 123, "NIFTY2525025250CE", market_close)
check("duplicate_candle_guard", again is None)

# Fixed 5% stop price.
check("stop_loss_price", sm.check_stop_loss(113.99) == 114.0,
      str(sm.check_stop_loss(113.99)))
check("stop_loss_holds_above", sm.check_stop_loss(114.01) is None)

# Trail: +5 activates breakeven, then peak - 5.
check("trail_activates_at_plus5", sm.update_trail(125.0) is None)
check("trail_stop_breakeven", sm.position.stop == 120.0, str(sm.position.stop))
check("trail_ratchets", sm.update_trail(130.0) is None
      and sm.position.stop == 125.0, str(sm.position.stop))
check("trail_exit_at_stop", sm.update_trail(124.9) == 125.0,
      str(sm.update_trail(124.9)))

# Breakeven lock at +6 moves the stop to entry + 2.
sm2 = OptionStateMachine("CE")
sm2.try_entry(ev, entry_time, 25250, "2026-11-23", 123,
              "NIFTY2525025250CE", market_close)
check("be_lock_holds", sm2.update_trail(126.0) is None)
check("be_lock_stop", sm2.position.be_locked and sm2.position.stop == 122.0,
      str(sm2.position.stop))
check("be_lock_exit", sm2.update_trail(121.9) == 122.0,
      str(sm2.update_trail(121.9)))

# No candle-close time exit: the position stays open inside its candle.
sm3 = OptionStateMachine("CE")
sm3.try_entry(ev, entry_time, 25250, "2026-11-23", 123,
              "NIFTY2525025250CE", market_close)
check("no_time_exit_inside_candle",
      not sm3.needs_exit(entry_time + timedelta(minutes=4, seconds=59)))
check("candle_end_flag", sm3.needs_exit(entry_time + timedelta(minutes=5)))

# Close writes a BUY-only P&L and clears the position.
trade = sm3.close(entry_time + timedelta(minutes=2), 126.5, "TRAIL_STOP_EXIT")
check("close_pnl", trade["pnl_points"] == 6.5 and sm3.position is None,
      str(trade["pnl_points"]))
check("close_strategy", trade["strategy_id"] == STRATEGY_ID)

# --- ids ------------------------------------------------------------------
tid = make_trade_id("NIFTY", 25250, "PE", BASE)
check("trade_id_prefix", tid.startswith("S1M-") and len(tid) == 16, tid)
check("trade_id_stable", tid == make_trade_id("NIFTY", 25250, "PE", BASE))

if failures:
    print(f"\n{len(failures)} FAILED: {', '.join(failures)}")
    sys.exit(1)
print("\nall checks passed")
