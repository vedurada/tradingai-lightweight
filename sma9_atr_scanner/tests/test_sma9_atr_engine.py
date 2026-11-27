#!/usr/bin/env python3
"""Offline checks for the ATR-stop engine and the daily regime gate.

No network, no broker, no DB writes.
"""
import os
import sqlite3
import sys
import tempfile
from datetime import date, datetime, time as dtime, timedelta
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import app.live_sma9_atr_scanner as live  # noqa: E402
from app.live_sma9_atr_scanner import compute_spot_regime  # noqa: E402
from app.sma9_atr_engine import (  # noqa: E402
    EXIT_POLICY_LEGACY,
    EXIT_POLICY_SL_TARGET,
    STOP_LOSS_INITIAL_REASON,
    TARGET_1_2_REASON,
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

# 5. Entry freezes the ATR stop/target; both new-policy exits fill at the level.
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
expected_target = round(pos.entry_price + 2.0 * (pos.entry_price - expected_stop), 2)
check("entry_policy_and_target",
      pos.exit_policy == EXIT_POLICY_SL_TARGET
      and pos.initial_stop == expected_stop
      and pos.target_price == expected_target,
      f"policy={pos.exit_policy} stop={pos.initial_stop} target={pos.target_price}")
check("stop_not_hit", sm.check_sl_target_exit(pos.initial_stop + 0.5) is None)
sl_fill = sm.check_sl_target_exit(pos.initial_stop - 1.5)
check("sl_fill_at_initial_stop", sl_fill == (expected_stop, STOP_LOSS_INITIAL_REASON),
      f"fill={sl_fill}")
check("target_not_hit", sm.check_sl_target_exit(pos.target_price - 0.5) is None)
target_fill = sm.check_sl_target_exit(pos.target_price + 1.5)
check("target_fill_at_level", target_fill == (expected_target, TARGET_1_2_REASON),
      f"fill={target_fill}")

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

# 8. Closed new-policy trade carries the frozen stop/target metadata.
sl_hit = sm.check_sl_target_exit(pos.initial_stop - 2.0)
trade = sm.close(BASE + timedelta(minutes=85), sl_hit[0], sl_hit[1])
check("trade_metadata",
      trade["stop_price"] == pos.stop_price and trade["stop_k"] == 0.7
      and trade["stop_source"] == "atr"
      and trade["trail_distance"] == expected_dist
      and trade["exit_policy"] == EXIT_POLICY_SL_TARGET
      and trade["initial_stop"] == pos.initial_stop
      and trade["target_price"] == pos.target_price
      and trade["exit_reason"] == STOP_LOSS_INITIAL_REASON
      and trade["exit_price"] == pos.initial_stop
      and trade["pnl_points"] == round(pos.initial_stop - pos.entry_price, 2),
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
    check("legacy_db_defaults",
          legacy.exit_policy == EXIT_POLICY_LEGACY
          and legacy.initial_stop is None
          and legacy.target_price is None,
          f"policy={legacy.exit_policy} stop={legacy.initial_stop} "
          f"target={legacy.target_price}")
    live.save_open_position(pos)
    reloaded = live.load_open_positions()["CE"]
    check("new_db_roundtrip",
          reloaded.exit_policy == EXIT_POLICY_SL_TARGET
          and reloaded.initial_stop == pos.initial_stop
          and reloaded.target_price == pos.target_price,
          f"policy={reloaded.exit_policy} stop={reloaded.initial_stop} "
          f"target={reloaded.target_price}")
finally:
    live.DB_PATH = old_db_path
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(legacy_db + suffix)
        except FileNotFoundError:
            pass

# 15. Exact wall-clock 5-second polling, with no offset/alignment leftovers.
check("poll_seconds_five", live.POLL_SECONDS == 5, f"poll={live.POLL_SECONDS}")
check("no_offset_constants",
      not any(hasattr(live, name) for name in (
          "POLL_OFFSET_SECONDS", "POLL_OFFSET_SEC", "POLL_OFFSET",
          "next_poll_time", "poll_alignment")))
for sample, expected_delay in (
    (datetime(2026, 11, 18, 10, 0, 3, 700000, tzinfo=live.IST), 1.3),
    (datetime(2026, 11, 18, 10, 0, 5, 0, tzinfo=live.IST), 5.0),
    (datetime(2026, 11, 18, 10, 0, 59, 500000, tzinfo=live.IST), 0.5),
):
    with patch.object(live, "now_ist", return_value=sample), \
            patch.object(live.time, "sleep") as sleep:
        live.sleep_to_next_tick()
    delay = sleep.call_args[0][0]
    check(f"sleep_exact_5s_{sample.second}_{sample.microsecond}",
          abs(delay - expected_delay) < 1e-6,
          f"delay={delay} expected={expected_delay}")
status_now = datetime(2026, 11, 18, 10, 0, 5, tzinfo=live.IST)
with patch.object(live, "today_stats", return_value={}):
    status = live.Sma9AtrLiveScanner(object())._status(status_now, {})
check("status_has_no_alignment",
      status["poll_seconds"] == 5
      and not any(k in status for k in ("poll_offset", "poll_offset_seconds",
                                        "poll_alignment", "next_poll_time")))

# 16. New policy never trails / EOD-recovers; legacy still does both.
new_sm = OptionStateMachine("CE")
new_pos = new_sm.try_entry(ev, BASE + timedelta(minutes=80), 25000, "2026-11-23",
                           1, "NIFTY26NOV25000CE", BASE + timedelta(hours=6),
                           atr=10.0)
hwm_before, stop_before = new_pos.hwm, new_pos.stop
check("new_policy_no_trail",
      new_sm.update_trail(new_pos.entry_price + 20) is None
      and new_pos.hwm == hwm_before and new_pos.stop == stop_before)
check("new_policy_no_legacy_sl",
      new_sm.check_stop_loss(new_pos.initial_stop - 5.0) is None)
check("new_policy_no_recovery_exit",
      new_sm.needs_exit(new_pos.entry_candle_end + timedelta(hours=2)) is False)

legacy_d = pos.as_dict()
legacy_d["exit_policy"] = EXIT_POLICY_LEGACY
legacy_pos = Position.from_dict(legacy_d)
legacy_sm = OptionStateMachine("CE")
legacy_sm.restore(legacy_pos)
check("legacy_still_trails",
      legacy_sm.update_trail(legacy_pos.entry_price + 15.0) is None
      and legacy_pos.stop is not None
      and legacy_pos.stop > legacy_pos.stop_price,
      f"stop={legacy_pos.stop} stop_price={legacy_pos.stop_price}")
check("legacy_sl_fills_at_ltp",
      legacy_sm.check_stop_loss(legacy_pos.stop_price - 2.5)
      == round(legacy_pos.stop_price - 2.5, 2),
      f"stop_price={legacy_pos.stop_price}")
check("legacy_recovery_exit_unchanged",
      legacy_sm.needs_exit(legacy_pos.entry_candle_end + timedelta(seconds=1))
      is True)

# 17. Round-trip and legacy defaults for the new persisted fields.
restored = Position.from_dict(new_pos.as_dict())
check("roundtrip_exit_fields",
      restored.exit_policy == EXIT_POLICY_SL_TARGET
      and restored.initial_stop == new_pos.initial_stop
      and restored.target_price == new_pos.target_price,
      f"{restored.exit_policy} {restored.initial_stop} {restored.target_price}")
legacy_from_dict = Position.from_dict({
    k: v for k, v in new_pos.as_dict().items()
    if k not in ("exit_policy", "initial_stop", "target_price")
})
check("from_dict_legacy_defaults",
      legacy_from_dict.exit_policy == EXIT_POLICY_LEGACY
      and legacy_from_dict.initial_stop is None
      and legacy_from_dict.target_price is None,
      f"{legacy_from_dict.exit_policy} {legacy_from_dict.initial_stop} "
      f"{legacy_from_dict.target_price}")

# 18. Live scan closes a new-policy position at the frozen stop level.
class _ScannerFeed:
    def __init__(self):
        self.kite = type("Kite", (), {
            "historical_data": lambda self, *a, **k: [],
        })()

    def quote(self, symbols):
        out = {}
        for sym in symbols:
            if sym == "NSE:NIFTY 50":
                out[sym] = {"last_price": 25000.0}
            elif sym.endswith("CE"):
                out[sym] = {"last_price": pos_scan.initial_stop - 2.5}
            else:
                out[sym] = {"last_price": 200.0}
        return out

    def candles(self, token, force=False):
        return rising_candles()


fd_live, db_live = tempfile.mkstemp(suffix=".db")
os.close(fd_live)
old_db_live = live.DB_PATH
try:
    live.DB_PATH = db_live
    live.init_db()
    scan_now = BASE + timedelta(minutes=80, seconds=5)
    scan_ev = evaluate_option(rising_candles(), "CE", ltp=125.0)
    scan_sm = OptionStateMachine("CE")
    pos_scan = scan_sm.try_entry(
        scan_ev, scan_now, 25000, "2026-11-23", 1, "NIFTY26NOV25000CE",
        BASE + timedelta(hours=6), atr=10.0)
    live.save_open_position(pos_scan)
    scanner = live.Sma9AtrLiveScanner(_ScannerFeed())
    scanner.states["CE"].restore(pos_scan)
    scanner.contracts = {
        "CE": {"tradingsymbol": "NIFTY26NOV25000CE", "instrument_token": 1,
               "strike": 25000.0, "expiry": date(2026, 11, 23)},
        "PE": {"tradingsymbol": "NIFTY26NOV25000PE", "instrument_token": 2,
               "strike": 25000.0, "expiry": date(2026, 11, 23)},
    }
    scanner.atm_strike = 25000
    scanner.expiry = date(2026, 11, 23)
    scanner.regime_state = {"bias": "BULLISH", "allowed_option": "CE",
                            "error": None}
    scanner.regime_evaluated_at = scan_now
    with patch.object(live, "now_ist", return_value=scan_now):
        scan_status = scanner.scan()
    conn = sqlite3.connect(db_live)
    try:
        row = conn.execute(
            "SELECT exit_reason, exit_price FROM sma9_atr_trades"
        ).fetchone()
        open_left = conn.execute(
            "SELECT COUNT(*) FROM sma9_atr_open_positions WHERE option_type='CE'"
        ).fetchone()[0]
    finally:
        conn.close()
    check("live_frozen_stop_exit",
          row == (STOP_LOSS_INITIAL_REASON, pos_scan.initial_stop),
          f"row={row} stop={pos_scan.initial_stop}")
    check("live_exit_clears_position",
          scan_status["options"]["CE"]["position"] is None and open_left == 0,
          f"open_left={open_left}")
finally:
    live.DB_PATH = old_db_live
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(db_live + suffix)
        except FileNotFoundError:
            pass

print()
if failures:
    print("FAILED:", ", ".join(failures))
    sys.exit(1)
print("All checks passed.")
