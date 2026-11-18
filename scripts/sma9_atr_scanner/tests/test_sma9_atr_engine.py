#!/usr/bin/env python3
"""Offline checks for the ATR-stop engine (no network, no broker)."""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.sma9_atr_engine import (  # noqa: E402
    OptionStateMachine,
    Position,
    compute_stop,
    evaluate_option,
    premium_atr,
)

BASE = datetime(2026, 11, 18, 9, 15)


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

# 5. Entry stores the ATR stop; stop fills at the actual LTP.
sm = OptionStateMachine("CE")
pos = sm.try_entry(ev, BASE + timedelta(minutes=80), 25000, "2026-11-23",
                   1, "NIFTY26NOV25000CE", BASE + timedelta(hours=6), atr=10.0)
check("entry_position", pos is not None and pos.stop_price is not None,
      "no position")
expected_stop = compute_stop(pos.entry_price, 10.0)[0]
check("entry_stop_price", pos.stop_price == expected_stop,
      f"stop={pos.stop_price} entry={pos.entry_price} expected={expected_stop}")
check("stop_not_hit", sm.check_stop_loss(pos.stop_price + 0.5) is None)
fill = sm.check_stop_loss(pos.stop_price - 1.5)
check("stop_fill_at_ltp", fill == round(pos.stop_price - 1.5, 2), f"fill={fill}")

# 6. Trail is unchanged: +6 locks +2, then exits at +2.
p = Position(
    option_type="CE", trade_id="T", strike=25000, expiry="2026-11-23",
    token=1, tradingsymbol="X", entry_timestamp=BASE,
    entry_candle_start=BASE, entry_candle_end=BASE + timedelta(minutes=5),
    entry_price=120.0, sma9=100.0, prev_close=110.0, current_open=115.0,
    condition_a=True, condition_b=True, ltp_at_entry=120.0,
    atr_at_entry=10.0, stop_price=110.0, stop_k=0.7,
    stop_distance_pct=0.0833, stop_source="atr", hwm=120.0,
)
check("trail_no_exit", p.update_trail(126.0) is None)
check("trail_be_lock", p.stop == 122.0, f"stop={p.stop}")
check("trail_exit", p.update_trail(121.0) == 122.0, f"stop={p.stop}")

# 7. Round-trip through as_dict/from_dict keeps the ATR fields.
p2 = Position.from_dict(p.as_dict())
check("roundtrip_stop", p2.stop_price == 110.0 and p2.atr_at_entry == 10.0)

# 8. Closed trade carries the stop metadata.
trade = sm.close(BASE + timedelta(minutes=85), 108.5, "STOP_LOSS_ATR")
check("trade_metadata",
      trade["stop_price"] == pos.stop_price and trade["stop_k"] == 0.7
      and trade["stop_source"] == "atr"
      and trade["pnl_points"] == round(108.5 - pos.entry_price, 2),
      f"{trade.get('stop_price')} {trade.get('pnl_points')}")

print()
if failures:
    print("FAILED:", ", ".join(failures))
    sys.exit(1)
print("All checks passed.")
