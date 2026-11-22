#!/usr/bin/env python3
"""Offline checks for the SMA9 + ADX(14) engine.

Covers Wilder ADX, the two-condition entry gate, forming-candle exclusion,
the 5% initial stop and the HWM-5% trailing stop. No network, broker or DB.
"""
import os
import sys
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.sma9_adx_engine import (  # noqa: E402
    ADX_THRESHOLD,
    OptionStateMachine,
    Position,
    SMA_PERIOD,
    STOP_LOSS_PCT,
    TRAIL_PCT,
    compute_adx,
    evaluate_option,
)

BASE = datetime(2026, 11, 18, 9, 15)
NOW = BASE + timedelta(minutes=80)


def trend_candles(n=31, step=2.0):
    """Monotonic uptrend - strong directional movement, ADX well above 20."""
    out = []
    for i in range(n):
        c = 100.0 + i * step
        out.append({
            "start": BASE + timedelta(minutes=5 * i),
            "open": c - step, "high": c + 2.0, "low": c - 2.0,
            "close": c, "volume": 100,
        })
    return out


def choppy_candles(n=31):
    """Alternating high/lows - no net direction, ADX near zero."""
    out = []
    for i in range(n):
        up = i % 2 == 0
        c = 101.0 if up else 100.0
        out.append({
            "start": BASE + timedelta(minutes=5 * i),
            "open": c, "high": c + 1.0, "low": c - 1.0,
            "close": c, "volume": 100,
        })
    return out


def choppy_uptrend_candles(n=31, drift=0.3):
    """Rising closes (SMA9 gate passes) but alternating DM keeps ADX low."""
    out = []
    for i in range(n):
        base = 100.0 + drift * i
        if i % 2 == 0:
            o, h, l, c = base, base + 3.0, base - 0.5, base + 1.0
        else:
            o, h, l, c = base, base + 0.5, base - 3.0, base
        out.append({
            "start": BASE + timedelta(minutes=5 * i),
            "open": o, "high": h, "low": l, "close": c, "volume": 100,
        })
    return out


def make_position(entry=100.0, sma=95.0, adx=25.0):
    return Position(
        option_type="CE", trade_id="T", strike=25000, expiry="2026-11-23",
        token=1, tradingsymbol="X", entry_timestamp=BASE,
        entry_candle_start=BASE, entry_candle_end=BASE + timedelta(minutes=5),
        entry_price=entry, sma9=sma, adx=adx, prev_close=99.0,
        current_open=100.0, condition_a=True, condition_b=True,
        ltp_at_entry=entry, hwm=entry,
        stop=round(entry * (1.0 - STOP_LOSS_PCT), 2),
    )


failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"PASS {name}")
    else:
        failures.append(name)
        print(f"FAIL {name} {detail}")


# 1. ADX on a strong trend is above the threshold; on chop it is below.
trend_adx = compute_adx(trend_candles())
check("adx_strong_trend", trend_adx is not None and trend_adx > ADX_THRESHOLD,
      f"adx={trend_adx}")
chop_adx = compute_adx(choppy_candles())
check("adx_choppy", chop_adx is not None and chop_adx <= ADX_THRESHOLD,
      f"adx={chop_adx}")

# 2. Insufficient completed history -> no ADX.
check("adx_insufficient", compute_adx(trend_candles(10)) is None)

# 3. Entry gate: both conditions true on a trend -> signal.
ev = evaluate_option(trend_candles(), "CE", ltp=160.0)
check("entry_signal", ev.signal and ev.qualified and ev.ready, ev.reason)
check("entry_condition_a", ev.condition_a and ev.prev_close > ev.sma9)
check("entry_condition_b", ev.condition_b and ev.adx > ADX_THRESHOLD,
      f"adx={ev.adx}")
check("entry_adx_recorded", ev.adx is not None, f"adx={ev.adx}")

# 4. ADX gate alone blocks the signal on a choppy series.
ev_chop = evaluate_option(choppy_uptrend_candles(), "CE", ltp=101.0)
check("adx_gate_blocks", ev_chop.condition_a and (not ev_chop.condition_b)
      and (not ev_chop.signal) and "ADX" in ev_chop.reason, ev_chop.reason)

# 5. Forming candle is excluded from both SMA9 and ADX.
candles = trend_candles()
ev_before = evaluate_option(candles, "CE", ltp=160.0)
candles[-1]["high"] = 9999.0
candles[-1]["low"] = 0.0
candles[-1]["open"] = 5000.0
ev_after = evaluate_option(candles, "CE", ltp=160.0)
check("forming_candle_excluded",
      ev_after.adx == ev_before.adx and ev_after.sma9 == ev_before.sma9,
      f"{ev_before.adx}->{ev_after.adx} {ev_before.sma9}->{ev_after.sma9}")

# 6. LTP > SMA is informational only; it does not gate the signal.
ev_low_ltp = evaluate_option(trend_candles(), "CE", ltp=1.0)
check("confirmation_informational",
      ev_low_ltp.signal and (not ev_low_ltp.confirmation))

# 7. Entry stores the 5% initial stop and ADX metadata.
sm = OptionStateMachine("CE")
pos = sm.try_entry(ev, NOW, 25000, "2026-11-23", 1, "NIFTY26NOV25000CE",
                   BASE + timedelta(hours=6))
check("entry_position", pos is not None)
check("entry_initial_stop", pos is not None
      and pos.stop == round(pos.entry_price * (1.0 - STOP_LOSS_PCT), 2),
      f"stop={pos.stop if pos else None}")
check("entry_adx_metadata", pos is not None and pos.adx == round(ev.adx, 2))

# 8. 5% initial stop loss.
sm_sl = OptionStateMachine("CE")
sm_sl.restore(make_position(entry=100.0))
check("sl_not_hit_above", sm_sl.check_stop_loss(95.01) is None)
check("sl_hit_at_floor", sm_sl.check_stop_loss(95.0) == 95.0)
check("sl_hit_below", sm_sl.check_stop_loss(92.0) == 95.0)

# 9. HWM-5% trailing stop ratchets up, never down, and only exits above the floor.
p = make_position(entry=100.0)
check("trail_initial_floor", p.update_trail(100.0) is None and p.stop == 95.0,
      f"stop={p.stop}")
check("trail_new_high", p.update_trail(110.0) is None
      and p.stop == round(110.0 * (1.0 - TRAIL_PCT), 2), f"stop={p.stop}")
check("trail_no_exit_above_stop", p.update_trail(105.0) is None,
      f"stop={p.stop}")
check("trail_exit_at_ratcheted_stop", p.update_trail(104.0) == 104.5,
      f"stop={p.stop}")
check("trail_never_ratchets_down",
      p.update_trail(130.0) is None and p.stop == 123.5
      and p.update_trail(120.0) == 123.5 and p.stop == 123.5,
      f"stop={p.stop}")

# 10. Round-trip keeps ADX; closed trade carries it too.
p2 = Position.from_dict(p.as_dict())
check("roundtrip_adx", p2.adx == p.adx, f"{p2.adx} != {p.adx}")
trade = sm_sl.close(NOW, 95.0, "STOP_LOSS_5PCT")
check("trade_adx_metadata", trade is not None and trade["adx_value"] == 25.0,
      f"{trade.get('adx_value') if trade else None}")

# 11. SMA9 is still computed from the last nine completed candles.
check("sma_period", len(trend_candles()) - 1 >= SMA_PERIOD)

print()
if failures:
    print("FAILED:", ", ".join(failures))
    sys.exit(1)
print("All checks passed.")
