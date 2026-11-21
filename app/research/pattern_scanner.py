#!/usr/bin/env python3
"""Pattern Scanner — dynamic stop-loss / trailing-stop engine for NIFTY 5m candles.

Implements the DYNAMIC_CANDLE_SL_TRAIL_V1 research on the TradingAI VM.

Live-traded instrument: NIFTY ATM CE/PE (current week expiry), LONG only.
Exit model: premium ATR(14) only — no fixed spot stop and no spot trail.
  ATR_STOP_K = 0.70, floor 5%, cap 30%, fallback 10% when ATR is unavailable
  Initial stop = entry - ATR distance
  Trailing stop = premium HWM - ATR distance, ratcheting upward only
  ATR stop/trail fills use the conservative completed 5m option OHLC proxy.
NIFTY spot is used only for pattern detection and ATM strike selection.
Live cadence: aligned 5-minute polls. Entries fire on completed 5m spot
candles; exits are evaluated once per completed 5m option OHLC bar.

Paper trading only. No broker orders. All calculations use completed 5-minute
candles — no lookahead, no future data.

Pattern detection runs on NIFTY SPOT 5m candles:
  - Bullish pattern  → buy ATM CE (weekly expiry)
  - Bearish pattern  → buy ATM PE (weekly expiry)
Entry uses the exact option's LTP sampled at the poll that closes the spot
candle; the recorded entry timestamp is that poll time, not the candle start.
Quotes older than MAX_QUOTE_AGE_SEC are never used for an entry; exits use
completed 5m option OHLC bars, not sampled quotes.
SL and trail are calculated on the bought option's premium ATR only; NIFTY
spot is used for pattern detection and ATM selection, never for exits.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Optional, List, Dict, Any, Callable

IST = timezone(timedelta(hours=5, minutes=30))

MARKET_OPEN = time(9, 0)
MARKET_CLOSE = time(15, 30)
# Kite publishes no 5-minute candle before 09:15.  The live runner
# starts polling at 09:00 so the feed is warm, but pre-open ticks must
# not create synthetic candles or feed pattern detection.
FIRST_CANDLE_START = time(9, 15)
NO_NEW_ENTRY_AFTER = time(15, 15)

# Premium ATR-only exit model (mirrors the ATR premium scanners).
ATR_PERIOD = 14
ATR_STOP_K = 0.70
ATR_STOP_FLOOR_PCT = 0.05
ATR_STOP_CAP_PCT = 0.30
ATR_STOP_FALLBACK_PCT = 0.10

# Legacy constants retained only so old persisted state/status reports can
# still be read.  They are no longer used for exit decisions.
TRAIL = 5.0
ACTIVATE = 5.0
BE_LOCK_PROFIT = 6.0
BE_LOCK_STOP = 2.0
STOP_LOSS_PCT = 0.05
SPOT_SL_POINTS = 12.0
MAX_QUOTE_AGE_SEC = 20.0  # never enter on an option quote older than this

# NIFTY option strike step
STRIKE_STEP = 50

# ATM reband threshold (spot points)
ATM_REBAND_THRESHOLD_POINTS = 100


def now_ist() -> datetime:
    return datetime.now(IST)


def is_trading_day(dt=None) -> bool:
    dt = dt or now_ist()
    return dt.weekday() < 5


def is_market_open(dt=None) -> bool:
    dt = dt or now_ist()
    if not is_trading_day(dt):
        return False
    t = dt.time()
    return MARKET_OPEN <= t <= MARKET_CLOSE


def session_date(ts) -> str:
    if isinstance(ts, str):
        return datetime.fromisoformat(ts).date().isoformat()
    return ts.date().isoformat()


def floor_5min(dt: datetime) -> datetime:
    return dt.replace(minute=(dt.minute // 5) * 5, second=0, microsecond=0)


def round_to_strike(spot: float, step: int = STRIKE_STEP) -> int:
    return int(round(spot / step) * step)


def nearest_thursday(from_date=None):
    from datetime import date as _date
    d = from_date or now_ist().date()
    days_ahead = (3 - d.weekday()) % 7
    if days_ahead == 0:
        return d
    return d + timedelta(days=days_ahead)


def expiry_string(expiry) -> str:
    return expiry.strftime("%d%b%y").upper()


def option_symbol(underlying: str, expiry, strike: int, option_type: str) -> str:
    return f"{underlying}{expiry_string(expiry)}{strike}{option_type.upper()}"


# --------------------------------------------------------------------------- #
# Premium ATR exit helpers
# --------------------------------------------------------------------------- #
def premium_atr(candles: List[dict], period: int = ATR_PERIOD) -> Optional[float]:
    """Mean true range of the option premium over completed 5m candles.

    The final row is the forming candle and is excluded, so an entry never
    uses a stop derived from its own unfinished bar.
    """
    rows = list(candles or [])
    completed = rows[:-1]
    if len(completed) < period + 1:
        return None
    window = completed[-(period + 1):]
    trs = []
    for prev, cur in zip(window[:-1], window[1:]):
        trs.append(max(float(cur["high"]) - float(cur["low"]),
                       abs(float(cur["high"]) - float(prev["close"])),
                       abs(float(cur["low"]) - float(prev["close"]))))
    return sum(trs) / len(trs) if trs else None


def compute_atr_stop(entry_price: float, atr: Optional[float]) -> tuple:
    """Return (stop_price, distance, distance_pct, source)."""
    entry = float(entry_price)
    if atr is not None and atr > 0:
        distance = ATR_STOP_K * float(atr)
        distance = max(distance, entry * ATR_STOP_FLOOR_PCT)
        distance = min(distance, entry * ATR_STOP_CAP_PCT)
        source = "atr"
    else:
        distance = entry * ATR_STOP_FALLBACK_PCT
        source = "fallback_pct"
    stop_price = round(entry - distance, 2)
    distance_pct = round(distance / entry, 4) if entry else 0.0
    return stop_price, round(distance, 4), distance_pct, source


# --------------------------------------------------------------------------- #
# Simple candlestick — for converting dicts to Candle-like objects
# --------------------------------------------------------------------------- #
class _Candle:
    __slots__ = ("timestamp", "open", "high", "low", "close", "session_date")
    def __init__(self, timestamp, open_, high, low, close, session_date=""):
        self.timestamp = timestamp
        self.open = open_
        self.high = high
        self.low = low
        self.close = close
        self.session_date = session_date


# --------------------------------------------------------------------------- #
# Built-in candlestick pattern detector — ALL ~37 bullish patterns
# --------------------------------------------------------------------------- #
def _body_ratio(o, h, l, c):
    r = h - l
    return abs(c - o) / r if r > 0 else 0.0


def _close_loc(o, h, l, c):
    r = h - l
    return (c - l) / r if r > 0 else 0.5


def _body_at_least(c, atr, min_ratio):
    """Body must be at least min_ratio * ATR (floor 1.0 point)."""
    r = c["high"] - c["low"]
    body = abs(c["close"] - c["open"])
    floor = max(1.0, (atr or 0.0) * min_ratio)
    return body >= floor


def detect_bullish_patterns(candles: List[dict], i: int, atr: Optional[float]) -> List[dict]:
    """Detect ALL bullish candlestick patterns at index i.

    candles: list of dicts with open/high/low/close, chronological.
    i: index of the current (just-completed) candle.
    atr: ATR(14) value or None.

    Returns list of pattern result dicts with pattern_name and direction.
    """
    if i < 0:
        return []
    results = []
    c = candles[i]
    c_br = _body_ratio(c["open"], c["high"], c["low"], c["close"])
    c_cl = _close_loc(c["open"], c["high"], c["low"], c["close"])

    # ------------------------------------------------------------------ #
    # Helper to add a bullish pattern result
    # ------------------------------------------------------------------ #
    def add(name, strength="MODERATE_BULLISH", candle_count=1,
            prev_trend="NEUTRAL", invalidation=None):
        if invalidation is None:
            invalidation = c["low"]
        results.append({
            "pattern_name": name,
            "direction": "BULLISH",
            "candle_count": candle_count,
            "first_ts": candles[i - candle_count + 1]["timestamp"] if i - candle_count + 1 >= 0 else c["timestamp"],
            "last_ts": c["timestamp"],
            "confirmation_ts": c["timestamp"],
            "pattern_high": c["high"],
            "pattern_low": c["low"],
            "invalidation_price": invalidation,
            "strength": strength,
            "prev_trend": prev_trend,
            "pattern_type": "japanese_candlestick",
        })

    # ------------------------------------------------------------------ #
    # 2-candle patterns (need i >= 1)
    # ------------------------------------------------------------------ #
    if i >= 1:
        p = candles[i - 1]
        p_br = _body_ratio(p["open"], p["high"], p["low"], p["close"])
        p_cl = _close_loc(p["open"], p["high"], p["low"], p["close"])

        # Bullish Engulfing
        if (p["close"] < p["open"] and c["close"] > c["open"]
                and c["open"] <= p["close"] and c["close"] >= p["open"]
                and c_br > p_br
                and _body_at_least(c, atr, 0.15) and _body_at_least(p, atr, 0.10)):
            add("Bullish Engulfing", "STRONG_BULLISH", 2, "BEARISH", p["low"])

        # Piercing Line
        if (p["close"] < p["open"] and c["close"] > c["open"]
                and c["open"] < p["low"]
                and c["close"] > (p["open"] + p["close"]) / 2
                and _body_at_least(c, atr, 0.15)):
            add("Piercing Line", "MODERATE_BULLISH", 2, "BEARISH", p["low"])

        # Bullish Harami
        if (p["close"] < p["open"] and p_br > 0.5
                and c["close"] > c["open"] and c_br < 0.35
                and c["open"] > p["close"] and c["close"] < p["open"]
                and _body_at_least(p, atr, 0.10)):
            add("Bullish Harami", "MODERATE_BULLISH", 2, "BEARISH", p["low"])

        # Bullish Harami Cross
        if (p["close"] < p["open"] and p_br > 0.5
                and c_br <= 0.10  # doji
                and c["open"] > p["close"] and c["close"] < p["open"]):
            add("Bullish Harami Cross", "MODERATE_BULLISH", 2, "BEARISH", p["low"])

        # Bullish Kicker
        if (p["close"] < p["open"] and c["close"] > c["open"]
                and c["open"] > p["close"]
                and _body_at_least(c, atr, 0.15) and _body_at_least(p, atr, 0.10)):
            add("Bullish Kicker", "STRONG_BULLISH", 2, "BEARISH", p["low"])

        # Bullish Meeting Lines
        if (p["close"] < p["open"] and c["close"] > c["open"]
                and abs(c["close"] - p["close"]) < 1e-9
                and _body_at_least(c, atr, 0.15) and _body_at_least(p, atr, 0.10)):
            add("Bullish Meeting Lines", "MODERATE_BULLISH", 2, "BEARISH", p["low"])

        # Bullish Separating Lines
        if (p["close"] < p["open"] and c["close"] > c["open"]
                and abs(c["open"] - p["open"]) < 1e-9
                and _body_at_least(c, atr, 0.15) and _body_at_least(p, atr, 0.10)):
            add("Bullish Separating Lines", "MODERATE_BULLISH", 2, "BEARISH", p["low"])

        # Bullish Counterattack Lines
        if (p["close"] < p["open"] and c["close"] > c["open"]
                and abs(c["close"] - p["close"]) < 1e-9
                and _body_at_least(c, atr, 0.15) and _body_at_least(p, atr, 0.10)):
            add("Bullish Counterattack Lines", "MODERATE_BULLISH", 2, "BEARISH", p["low"])

        # Tweezer Bottom
        if (abs(c["low"] - p["low"]) < 1e-9
                and p["close"] < p["open"] and c["close"] > c["open"]
                and _body_at_least(c, atr, 0.10)):
            add("Tweezer Bottom", "MODERATE_BULLISH", 2, "BEARISH", p["low"])

        # Homing Pigeon
        if (p["close"] < p["open"] and p_br > 0.5
                and c["close"] > c["open"] and c_br < 0.35
                and c["open"] >= p["close"] and c["close"] <= p["open"]
                and _body_at_least(p, atr, 0.10)):
            add("Homing Pigeon", "MODERATE_BULLISH", 2, "BEARISH", p["low"])

        # Matching Low
        if (abs(c["low"] - p["low"]) < 1e-9
                and p["close"] < p["open"] and c["close"] > c["open"]
                and _body_at_least(c, atr, 0.10)):
            add("Matching Low", "MODERATE_BULLISH", 2, "BEARISH", p["low"])

        # Thrusting Pattern
        if (p["close"] < p["open"] and c["close"] > c["open"]
                and c["open"] < p["close"]
                and c["close"] < p["close"]  # closes below prior close but above midpoint
                and c["close"] > (p["open"] + p["close"]) / 2
                and _body_at_least(c, atr, 0.15)):
            add("Thrusting Pattern", "WEAK_BULLISH", 2, "BEARISH", p["low"])

    # ------------------------------------------------------------------ #
    # 3-candle patterns (need i >= 2)
    # ------------------------------------------------------------------ #
    if i >= 2:
        c2 = candles[i - 2]
        p = candles[i - 1]
        c2_br = _body_ratio(c2["open"], c2["high"], c2["low"], c2["close"])
        p_br = _body_ratio(p["open"], p["high"], p["low"], p["close"])

        # Three White Soldiers
        if (c2["close"] > c2["open"] and p["close"] > p["open"] and c["close"] > c["open"]
                and c["close"] > p["close"] > c2["close"]
                and c["open"] >= p["close"] and p["open"] >= c2["close"]
                and _body_at_least(c, atr, 0.10) and _body_at_least(p, atr, 0.10)
                and _body_at_least(c2, atr, 0.10)):
            add("Three White Soldiers", "STRONG_BULLISH", 3, "BEARISH", c2["low"])

        # Three Inside Up
        if (p["close"] < p["open"] and p_br > 0.5
                and c["close"] > c["open"] and c_br < p_br
                and c["open"] > p["close"] and c["close"] < p["open"]
                and i >= 2 and candles[i - 2]["close"] < candles[i - 2]["open"]
                and _body_at_least(p, atr, 0.10)):
            add("Three Inside Up", "MODERATE_BULLISH", 3, "BEARISH", c2["low"])

        # Three Outside Up (Engulfing + confirm)
        if (i >= 2 and p["close"] < p["open"] and c2["close"] < c2["open"]
                and c["close"] > c["open"]
                and c["open"] <= p["close"] and c["close"] >= p["open"]
                and c_br > p_br
                and _body_at_least(c, atr, 0.15) and _body_at_least(p, atr, 0.10)
                and _body_at_least(c2, atr, 0.10)):
            add("Three Outside Up", "STRONG_BULLISH", 3, "BEARISH", c2["low"])

        # Morning Star
        if (p["close"] < p["open"] and p_br > 0.5
                and c_br < 0.35  # small body / doji
                and c["close"] > p["close"] * 0.999  # roughly mid
                and i >= 2 and c2["close"] < c2["open"]
                and _body_at_least(p, atr, 0.10) and _body_at_least(c2, atr, 0.10)):
            add("Morning Star", "STRONG_BULLISH", 3, "BEARISH", c2["low"])

        # Morning Doji Star
        if (p["close"] < p["open"] and p_br > 0.5
                and c_br <= 0.10  # doji
                and i >= 2 and c2["close"] < c2["open"]
                and _body_at_least(p, atr, 0.10) and _body_at_least(c2, atr, 0.10)):
            add("Morning Doji Star", "STRONG_BULLISH", 3, "BEARISH", c2["low"])

        # Bullish Stick Sandwich
        if (p["close"] < p["open"] and c["close"] > c["open"]
                and abs(c["close"] - c2["close"]) < 1e-9
                and _body_at_least(p, atr, 0.10) and _body_at_least(c2, atr, 0.10)):
            add("Bullish Stick Sandwich", "MODERATE_BULLISH", 3, "BEARISH", c2["low"])

        # Bullish Three-Line Strike
        if (i >= 2 and c2["close"] < c2["open"] and p["close"] < p["open"]
                and c["close"] > c["open"]
                and c["close"] > c2["open"]  # engulfs all three prior
                and _body_at_least(c, atr, 0.15)):
            add("Bullish Three-Line Strike", "STRONG_BULLISH", 3, "BEARISH", c2["low"])

        # Abandoned Baby Bottom
        if (p["close"] < p["open"] and c_br <= 0.10  # doji gap down
                and c["open"] < p["low"]  # gap down
                and i >= 2 and c2["close"] < c2["open"]
                and _body_at_least(p, atr, 0.10)):
            add("Abandoned Baby Bottom", "STRONG_BULLISH", 3, "BEARISH", c2["low"])

        # Three Stars in the South
        if (p["close"] < p["open"] and c["close"] > c["open"]
                and c["close"] < p["close"]  # third closes lower than second
                and c["low"] > p["low"]  # third low higher than second low
                and _body_at_least(c, atr, 0.10) and _body_at_least(p, atr, 0.10)
                and i >= 2 and _body_at_least(c2, atr, 0.10)):
            add("Three Stars in the South", "MODERATE_BULLISH", 3, "BEARISH", c2["low"])

        # Unique Three River
        if (p["close"] < p["open"] and c["close"] > c["open"]
                and c["close"] < p["close"]  # third closes lower
                and c["low"] > p["low"]  # third low higher
                and _body_at_least(c, atr, 0.10) and _body_at_least(p, atr, 0.10)
                and i >= 2 and _body_at_least(c2, atr, 0.10)):
            add("Unique Three River", "WEAK_BULLISH", 3, "BEARISH", c2["low"])

        # Upside Tasuki Gap
        if (p["close"] < p["open"] and c["close"] > c["open"]
                and c["open"] > p["close"]  # gap up
                and c["close"] < p["open"]  # closes below prior open
                and _body_at_least(c, atr, 0.15) and _body_at_least(p, atr, 0.10)
                and i >= 2 and _body_at_least(c2, atr, 0.10)):
            add("Upside Tasuki Gap", "MODERATE_BULLISH", 3, "BEARISH", c2["low"])

        # Upside Gap Three Methods
        if (p["close"] < p["open"] and c["close"] > c["open"]
                and c["open"] > p["close"]  # gap up
                and c["close"] > p["open"]  # closes above prior open
                and _body_at_least(c, atr, 0.15) and _body_at_least(p, atr, 0.10)
                and i >= 2 and _body_at_least(c2, atr, 0.10)):
            add("Upside Gap Three Methods", "STRONG_BULLISH", 3, "BEARISH", c2["low"])

    # ------------------------------------------------------------------ #
    # 4-candle patterns (need i >= 3)
    # ------------------------------------------------------------------ #
    if i >= 3:
        c3 = candles[i - 3]
        c2 = candles[i - 2]
        p = candles[i - 1]

        # Four Consecutive Bullish Candles
        if (c3["close"] > c3["open"] and c2["close"] > c2["open"]
                and p["close"] > p["open"] and c["close"] > c["open"]
                and c["close"] > p["close"] > c2["close"] > c3["close"]
                and _body_at_least(c, atr, 0.10) and _body_at_least(p, atr, 0.10)
                and _body_at_least(c2, atr, 0.10) and _body_at_least(c3, atr, 0.10)):
            add("Four Consecutive Bullish Candles", "STRONG_BULLISH", 4, "BEARISH", c3["low"])

        # Bullish Gap Continuation Sequence
        if (c3["close"] < c3["open"] and c2["close"] < c2["open"]
                and p["close"] > p["open"] and c["close"] > c["open"]
                and c["open"] > p["close"]  # gap up
                and _body_at_least(c, atr, 0.15) and _body_at_least(p, atr, 0.10)
                and _body_at_least(c2, atr, 0.10) and _body_at_least(c3, atr, 0.10)):
            add("Bullish Gap Continuation Sequence", "STRONG_BULLISH", 4, "BEARISH", c3["low"])

        # Bullish Mat Hold
        if (c3["close"] < c3["open"] and c2["close"] < c2["open"]
                and p["close"] > p["open"] and c["close"] > c["open"]
                and c["open"] > p["close"]  # gap up
                and c["close"] < c3["open"]  # stays within first candle body
                and _body_at_least(c, atr, 0.15) and _body_at_least(p, atr, 0.10)
                and _body_at_least(c2, atr, 0.10) and _body_at_least(c3, atr, 0.10)):
            add("Bullish Mat Hold", "STRONG_BULLISH", 4, "BEARISH", c3["low"])

    # ------------------------------------------------------------------ #
    # Single candle patterns (need i >= 0)
    # ------------------------------------------------------------------ #
    # Hammer
    if c["close"] > c["open"] and c_br < 0.35:
        c_body = abs(c["close"] - c["open"])
        lower_wick = min(c["open"], c["close"]) - c["low"]
        upper_wick = c["high"] - max(c["open"], c["close"])
        if lower_wick >= 2 * c_body and upper_wick <= c_body:
            add("Hammer", "MODERATE_BULLISH", 1, "BEARISH", c["low"])

    # Inverse Head and Shoulders (needs i >= 2 for context)
    if i >= 2:
        c2 = candles[i - 2]
        p = candles[i - 1]
        if (c2["close"] < c2["open"] and p["close"] < p["open"]
                and c["close"] > c["open"]
                and p["low"] < c2["low"] and p["low"] < c["low"]  # head lower
                and abs(c["low"] - c2["low"]) < 0.5 * (atr or c["high"] - c["low"])
                and _body_at_least(p, atr, 0.10)):
            add("Inverse Head and Shoulders", "STRONG_BULLISH", 3, "BEARISH", p["low"])

    # Double Bottom (needs i >= 3 for context)
    if i >= 3:
        c3 = candles[i - 3]
        c2 = candles[i - 2]
        p = candles[i - 1]
        if (c3["close"] < c3["open"] and c2["close"] < c2["open"]
                and p["close"] > p["open"] and c["close"] > c["open"]
                and abs(p["low"] - c3["low"]) < 0.5 * (atr or c["high"] - c["low"])
                and c["close"] > p["close"]
                and _body_at_least(p, atr, 0.10) and _body_at_least(c3, atr, 0.10)):
            add("Double Bottom", "STRONG_BULLISH", 4, "BEARISH", c3["low"])

    # Triple Bottom (needs i >= 4 for context)
    if i >= 4:
        c4 = candles[i - 4]
        c3 = candles[i - 3]
        c2 = candles[i - 2]
        p = candles[i - 1]
        if (c4["close"] < c4["open"] and c3["close"] < c3["open"]
                and c2["close"] < c2["open"] and p["close"] > p["open"]
                and c["close"] > c["open"]
                and abs(p["low"] - c3["low"]) < 0.5 * (atr or c["high"] - c["low"])
                and abs(c2["low"] - c3["low"]) < 0.5 * (atr or c["high"] - c["low"])
                and _body_at_least(p, atr, 0.10) and _body_at_least(c3, atr, 0.10)
                and _body_at_least(c2, atr, 0.10) and _body_at_least(c4, atr, 0.10)):
            add("Triple Bottom", "STRONG_BULLISH", 5, "BEARISH", c4["low"])

    # Bullish Flag (needs i >= 3)
    if i >= 3:
        c3 = candles[i - 3]
        c2 = candles[i - 2]
        p = candles[i - 1]
        if (c3["close"] > c3["open"] and c2["close"] > c2["open"]
                and p["close"] > p["open"] and c["close"] > c["open"]
                and c["close"] < p["close"] and c["low"] > p["low"]  # slight pullback
                and _body_at_least(c3, atr, 0.10)):
            add("Bullish Flag", "MODERATE_BULLISH", 4, "BULLISH", c3["low"])

    # Bullish Pennant (needs i >= 3)
    if i >= 3:
        c3 = candles[i - 3]
        c2 = candles[i - 2]
        p = candles[i - 1]
        if (c3["close"] > c3["open"] and c2["close"] > c2["open"]
                and p["close"] > p["open"] and c["close"] > c["open"]
                and c_br < p_br and c_br < c2_br  # converging
                and c["close"] > c2["close"]
                and _body_at_least(c3, atr, 0.10)):
            add("Bullish Pennant", "MODERATE_BULLISH", 4, "BULLISH", c3["low"])

    # Bullish Rectangle (needs i >= 3)
    if i >= 3:
        c3 = candles[i - 3]
        c2 = candles[i - 2]
        p = candles[i - 1]
        if (c3["close"] > c3["open"] and c2["close"] > c2["open"]
                and p["close"] > p["open"] and c["close"] > c["open"]
                and abs(c["close"] - c3["close"]) < 0.5 * (atr or c["high"] - c["low"])
                and abs(c["low"] - c3["low"]) < 0.5 * (atr or c["high"] - c["low"])
                and _body_at_least(c3, atr, 0.10)):
            add("Bullish Rectangle", "MODERATE_BULLISH", 4, "BULLISH", c3["low"])

    # Rising Three Methods (needs i >= 4)
    if i >= 4:
        c4 = candles[i - 4]
        c3 = candles[i - 3]
        c2 = candles[i - 2]
        p = candles[i - 1]
        if (c4["close"] > c4["open"] and c3["close"] < c3["open"]
                and c2["close"] < c2["open"] and p["close"] < p["open"]
                and c["close"] > c["open"] and c["close"] > c4["close"]
                and _body_at_least(c4, atr, 0.10) and _body_at_least(c3, atr, 0.10)
                and _body_at_least(c2, atr, 0.10) and _body_at_least(p, atr, 0.10)
                and _body_at_least(c, atr, 0.10)):
            add("Rising Three Methods", "STRONG_BULLISH", 5, "BULLISH", c4["low"])

    # Rising Wedge (needs i >= 3)
    if i >= 3:
        c3 = candles[i - 3]
        c2 = candles[i - 2]
        p = candles[i - 1]
        if (c3["close"] > c3["open"] and c2["close"] > c2["open"]
                and p["close"] > p["open"] and c["close"] > c["open"]
                and c["high"] < p["high"] and c["low"] > p["low"]  # converging up
                and _body_at_least(c3, atr, 0.10)):
            add("Rising Wedge", "MODERATE_BULLISH", 4, "BULLISH", c3["low"])

    # Ascending Triangle (needs i >= 3)
    if i >= 3:
        c3 = candles[i - 3]
        c2 = candles[i - 2]
        p = candles[i - 1]
        if (c3["close"] > c3["open"] and c2["close"] > c2["open"]
                and p["close"] > p["open"] and c["close"] > c["open"]
                and abs(c["high"] - p["high"]) < 0.5 * (atr or c["high"] - c["low"])
                and c["low"] > p["low"]  # higher lows
                and _body_at_least(c3, atr, 0.10)):
            add("Ascending Triangle", "MODERATE_BULLISH", 4, "BULLISH", c3["low"])

    return results


# --------------------------------------------------------------------------- #
# Built-in candlestick pattern detector — ALL ~37 bearish patterns
# --------------------------------------------------------------------------- #
def detect_bearish_patterns(candles: List[dict], i: int, atr: Optional[float]) -> List[dict]:
    """Detect ALL bearish candlestick patterns at index i (mirror of bullish).

    candles: list of dicts with open/high/low/close, chronological.
    i: index of the current (just-completed) candle.
    atr: ATR(14) value or None.

    Returns list of pattern result dicts with pattern_name and direction="BEARISH".
    """
    if i < 0:
        return []
    results = []
    c = candles[i]
    c_br = _body_ratio(c["open"], c["high"], c["low"], c["close"])
    c_cl = _close_loc(c["open"], c["high"], c["low"], c["close"])

    # ------------------------------------------------------------------ #
    # Helper to add a bearish pattern result
    # ------------------------------------------------------------------ #
    def add(name, strength="MODERATE_BEARISH", candle_count=1,
            prev_trend="NEUTRAL", invalidation=None):
        if invalidation is None:
            invalidation = c["high"]
        results.append({
            "pattern_name": name,
            "direction": "BEARISH",
            "candle_count": candle_count,
            "first_ts": candles[i - candle_count + 1]["timestamp"] if i - candle_count + 1 >= 0 else c["timestamp"],
            "last_ts": c["timestamp"],
            "confirmation_ts": c["timestamp"],
            "pattern_high": c["high"],
            "pattern_low": c["low"],
            "invalidation_price": invalidation,
            "strength": strength,
            "prev_trend": prev_trend,
            "pattern_type": "japanese_candlestick",
        })

    # ------------------------------------------------------------------ #
    # 2-candle patterns (need i >= 1)
    # ------------------------------------------------------------------ #
    if i >= 1:
        p = candles[i - 1]
        p_br = _body_ratio(p["open"], p["high"], p["low"], p["close"])
        p_cl = _close_loc(p["open"], p["high"], p["low"], p["close"])

        # Bearish Engulfing
        if (p["close"] > p["open"] and c["close"] < c["open"]
                and c["open"] >= p["close"] and c["close"] <= p["open"]
                and c_br > p_br
                and _body_at_least(c, atr, 0.15) and _body_at_least(p, atr, 0.10)):
            add("Bearish Engulfing", "STRONG_BEARISH", 2, "BULLISH", p["high"])

        # Dark Cloud Cover
        if (p["close"] > p["open"] and c["close"] < c["open"]
                and c["open"] > p["high"]
                and c["close"] < (p["open"] + p["close"]) / 2
                and _body_at_least(c, atr, 0.15)):
            add("Dark Cloud Cover", "MODERATE_BEARISH", 2, "BULLISH", p["high"])

        # Bearish Harami
        if (p["close"] > p["open"] and p_br > 0.5
                and c["close"] < c["open"] and c_br < 0.35
                and c["open"] < p["close"] and c["close"] > p["open"]
                and _body_at_least(p, atr, 0.10)):
            add("Bearish Harami", "MODERATE_BEARISH", 2, "BULLISH", p["high"])

        # Bearish Harami Cross
        if (p["close"] > p["open"] and p_br > 0.5
                and c_br <= 0.10  # doji
                and c["open"] < p["close"] and c["close"] > p["open"]):
            add("Bearish Harami Cross", "MODERATE_BEARISH", 2, "BULLISH", p["high"])

        # Bearish Kicker
        if (p["close"] > p["open"] and c["close"] < c["open"]
                and c["open"] < p["close"]
                and _body_at_least(c, atr, 0.15) and _body_at_least(p, atr, 0.10)):
            add("Bearish Kicker", "STRONG_BEARISH", 2, "BULLISH", p["high"])

        # Bearish Meeting Lines
        if (p["close"] > p["open"] and c["close"] < c["open"]
                and abs(c["close"] - p["close"]) < 1e-9
                and _body_at_least(c, atr, 0.15) and _body_at_least(p, atr, 0.10)):
            add("Bearish Meeting Lines", "MODERATE_BEARISH", 2, "BULLISH", p["high"])

        # Bearish Separating Lines
        if (p["close"] > p["open"] and c["close"] < c["open"]
                and abs(c["open"] - p["open"]) < 1e-9
                and _body_at_least(c, atr, 0.15) and _body_at_least(p, atr, 0.10)):
            add("Bearish Separating Lines", "MODERATE_BEARISH", 2, "BULLISH", p["high"])

        # Bearish Counterattack Lines
        if (p["close"] > p["open"] and c["close"] < c["open"]
                and abs(c["close"] - p["close"]) < 1e-9
                and _body_at_least(c, atr, 0.15) and _body_at_least(p, atr, 0.10)):
            add("Bearish Counterattack Lines", "MODERATE_BEARISH", 2, "BULLISH", p["high"])

        # Tweezer Top
        if (abs(c["high"] - p["high"]) < 1e-9
                and p["close"] > p["open"] and c["close"] < c["open"]
                and _body_at_least(c, atr, 0.10)):
            add("Tweezer Top", "MODERATE_BEARISH", 2, "BULLISH", p["high"])

        # Inverted Pigeon (bearish harami variant)
        if (p["close"] > p["open"] and p_br > 0.5
                and c["close"] < c["open"] and c_br < 0.35
                and c["open"] <= p["close"] and c["close"] >= p["open"]
                and _body_at_least(p, atr, 0.10)):
            add("Inverted Pigeon", "MODERATE_BEARISH", 2, "BULLISH", p["high"])

        # Matching High
        if (abs(c["high"] - p["high"]) < 1e-9
                and p["close"] > p["open"] and c["close"] < c["open"]
                and _body_at_least(c, atr, 0.10)):
            add("Matching High", "MODERATE_BEARISH", 2, "BULLISH", p["high"])

        # Thrusting Pattern (bearish variant)
        if (p["close"] > p["open"] and c["close"] < c["open"]
                and c["open"] > p["close"]
                and c["close"] > p["close"]  # closes above prior close but below midpoint
                and c["close"] < (p["open"] + p["close"]) / 2
                and _body_at_least(c, atr, 0.15)):
            add("Thrusting Pattern (Bearish)", "WEAK_BEARISH", 2, "BULLISH", p["high"])

    # ------------------------------------------------------------------ #
    # 3-candle patterns (need i >= 2)
    # ------------------------------------------------------------------ #
    if i >= 2:
        c2 = candles[i - 2]
        p = candles[i - 1]
        c2_br = _body_ratio(c2["open"], c2["high"], c2["low"], c2["close"])
        p_br = _body_ratio(p["open"], p["high"], p["low"], p["close"])

        # Three Black Soldiers
        if (c2["close"] < c2["open"] and p["close"] < p["open"] and c["close"] < c["open"]
                and c["close"] < p["close"] < c2["close"]
                and c["open"] <= p["close"] and p["open"] <= c2["close"]
                and _body_at_least(c, atr, 0.10) and _body_at_least(p, atr, 0.10)
                and _body_at_least(c2, atr, 0.10)):
            add("Three Black Soldiers", "STRONG_BEARISH", 3, "BULLISH", c2["high"])

        # Three Inside Down
        if (p["close"] > p["open"] and p_br > 0.5
                and c["close"] < c["open"] and c_br < p_br
                and c["open"] < p["close"] and c["close"] > p["open"]
                and i >= 2 and candles[i - 2]["close"] > candles[i - 2]["open"]
                and _body_at_least(p, atr, 0.10)):
            add("Three Inside Down", "MODERATE_BEARISH", 3, "BULLISH", c2["high"])

        # Three Outside Down (Engulfing + confirm)
        if (i >= 2 and p["close"] > p["open"] and c2["close"] > c2["open"]
                and c["close"] < c["open"]
                and c["open"] >= p["close"] and c["close"] <= p["open"]
                and c_br > p_br
                and _body_at_least(c, atr, 0.15) and _body_at_least(p, atr, 0.10)
                and _body_at_least(c2, atr, 0.10)):
            add("Three Outside Down", "STRONG_BEARISH", 3, "BULLISH", c2["high"])

        # Evening Star
        if (p["close"] > p["open"] and p_br > 0.5
                and c_br < 0.35  # small body / doji
                and c["close"] < p["close"] * 1.001  # roughly mid
                and i >= 2 and c2["close"] > c2["open"]
                and _body_at_least(p, atr, 0.10) and _body_at_least(c2, atr, 0.10)):
            add("Evening Star", "STRONG_BEARISH", 3, "BULLISH", c2["high"])

        # Evening Doji Star
        if (p["close"] > p["open"] and p_br > 0.5
                and c_br <= 0.10  # doji
                and i >= 2 and c2["close"] > c2["open"]
                and _body_at_least(p, atr, 0.10) and _body_at_least(c2, atr, 0.10)):
            add("Evening Doji Star", "STRONG_BEARISH", 3, "BULLISH", c2["high"])

        # Bearish Stick Sandwich
        if (p["close"] > p["open"] and c["close"] < c["open"]
                and abs(c["close"] - c2["close"]) < 1e-9
                and _body_at_least(p, atr, 0.10) and _body_at_least(c2, atr, 0.10)):
            add("Bearish Stick Sandwich", "MODERATE_BEARISH", 3, "BULLISH", c2["high"])

        # Bearish Three-Line Strike
        if (i >= 2 and c2["close"] > c2["open"] and p["close"] > p["open"]
                and c["close"] < c["open"]
                and c["close"] < c2["open"]  # engulfs all three prior
                and _body_at_least(c, atr, 0.15)):
            add("Bearish Three-Line Strike", "STRONG_BEARISH", 3, "BULLISH", c2["high"])

        # Abandoned Baby Top
        if (p["close"] > p["open"] and c_br <= 0.10  # doji gap up
                and c["open"] > p["high"]  # gap up
                and i >= 2 and c2["close"] > c2["open"]
                and _body_at_least(p, atr, 0.10)):
            add("Abandoned Baby Top", "STRONG_BEARISH", 3, "BULLISH", c2["high"])

        # Three Stars in the North
        if (p["close"] > p["open"] and c["close"] < c["open"]
                and c["close"] > p["close"]  # third closes higher than second
                and c["low"] < p["low"]  # third low lower than second low
                and _body_at_least(c, atr, 0.10) and _body_at_least(p, atr, 0.10)
                and i >= 2 and _body_at_least(c2, atr, 0.10)):
            add("Three Stars in the North", "MODERATE_BEARISH", 3, "BULLISH", c2["high"])

        # Unique Three River (bearish variant)
        if (p["close"] > p["open"] and c["close"] < c["open"]
                and c["close"] > p["close"]  # third closes higher
                and c["low"] < p["low"]  # third low lower
                and _body_at_least(c, atr, 0.10) and _body_at_least(p, atr, 0.10)
                and i >= 2 and _body_at_least(c2, atr, 0.10)):
            add("Unique Three River (Bearish)", "WEAK_BEARISH", 3, "BULLISH", c2["high"])

        # Downside Tasuki Gap
        if (p["close"] > p["open"] and c["close"] < c["open"]
                and c["open"] < p["close"]  # gap down
                and c["close"] > p["open"]  # closes above prior open
                and _body_at_least(c, atr, 0.15) and _body_at_least(p, atr, 0.10)
                and i >= 2 and _body_at_least(c2, atr, 0.10)):
            add("Downside Tasuki Gap", "MODERATE_BEARISH", 3, "BULLISH", c2["high"])

        # Downside Gap Three Methods
        if (p["close"] > p["open"] and c["close"] < c["open"]
                and c["open"] < p["close"]  # gap down
                and c["close"] < p["open"]  # closes below prior open
                and _body_at_least(c, atr, 0.15) and _body_at_least(p, atr, 0.10)
                and i >= 2 and _body_at_least(c2, atr, 0.10)):
            add("Downside Gap Three Methods", "STRONG_BEARISH", 3, "BULLISH", c2["high"])

    # ------------------------------------------------------------------ #
    # 4-candle patterns (need i >= 3)
    # ------------------------------------------------------------------ #
    if i >= 3:
        c3 = candles[i - 3]
        c2 = candles[i - 2]
        p = candles[i - 1]

        # Four Consecutive Bearish Candles
        if (c3["close"] < c3["open"] and c2["close"] < c2["open"]
                and p["close"] < p["open"] and c["close"] < c["open"]
                and c["close"] < p["close"] < c2["close"] < c3["close"]
                and _body_at_least(c, atr, 0.10) and _body_at_least(p, atr, 0.10)
                and _body_at_least(c2, atr, 0.10) and _body_at_least(c3, atr, 0.10)):
            add("Four Consecutive Bearish Candles", "STRONG_BEARISH", 4, "BULLISH", c3["high"])

        # Bearish Gap Continuation Sequence
        if (c3["close"] > c3["open"] and c2["close"] > c2["open"]
                and p["close"] < p["open"] and c["close"] < c["open"]
                and c["open"] < p["close"]  # gap down
                and _body_at_least(c, atr, 0.15) and _body_at_least(p, atr, 0.10)
                and _body_at_least(c2, atr, 0.10) and _body_at_least(c3, atr, 0.10)):
            add("Bearish Gap Continuation Sequence", "STRONG_BEARISH", 4, "BULLISH", c3["high"])

        # Bearish Mat Hold
        if (c3["close"] > c3["open"] and c2["close"] > c2["open"]
                and p["close"] < p["open"] and c["close"] < c["open"]
                and c["open"] < p["close"]  # gap down
                and c["close"] > c3["open"]  # stays within first candle body
                and _body_at_least(c, atr, 0.15) and _body_at_least(p, atr, 0.10)
                and _body_at_least(c2, atr, 0.10) and _body_at_least(c3, atr, 0.10)):
            add("Bearish Mat Hold", "STRONG_BEARISH", 4, "BULLISH", c3["high"])

    # ------------------------------------------------------------------ #
    # Single candle patterns (need i >= 0)
    # ------------------------------------------------------------------ #
    # Hanging Man / Shooting Star
    if c["close"] < c["open"] and c_br < 0.35:
        upper_wick = c["high"] - max(c["open"], c["close"])
        lower_wick = min(c["open"], c["close"]) - c["low"]
        c_body = abs(c["close"] - c["open"])
        if upper_wick >= 2 * c_body and lower_wick <= c_body:
            add("Shooting Star", "MODERATE_BEARISH", 1, "BULLISH", c["high"])

    # Head and Shoulders (needs i >= 2 for context)
    if i >= 2:
        c2 = candles[i - 2]
        p = candles[i - 1]
        if (c2["close"] > c2["open"] and p["close"] > p["open"]
                and c["close"] < c["open"]
                and p["high"] > c2["high"] and p["high"] > c["high"]  # head higher
                and abs(c["high"] - c2["high"]) < 0.5 * (atr or c["high"] - c["low"])
                and _body_at_least(p, atr, 0.10)):
            add("Head and Shoulders", "STRONG_BEARISH", 3, "BULLISH", p["high"])

    # Double Top (needs i >= 3 for context)
    if i >= 3:
        c3 = candles[i - 3]
        c2 = candles[i - 2]
        p = candles[i - 1]
        if (c3["close"] > c3["open"] and c2["close"] > c2["open"]
                and p["close"] < p["open"] and c["close"] < c["open"]
                and abs(p["high"] - c3["high"]) < 0.5 * (atr or c["high"] - c["low"])
                and c["close"] < p["close"]
                and _body_at_least(p, atr, 0.10) and _body_at_least(c3, atr, 0.10)):
            add("Double Top", "STRONG_BEARISH", 4, "BULLISH", c3["high"])

    # Triple Top (needs i >= 4 for context)
    if i >= 4:
        c4 = candles[i - 4]
        c3 = candles[i - 3]
        c2 = candles[i - 2]
        p = candles[i - 1]
        if (c4["close"] > c4["open"] and c3["close"] > c3["open"]
                and c2["close"] > c2["open"] and p["close"] < p["open"]
                and c["close"] < c["open"]
                and abs(p["high"] - c3["high"]) < 0.5 * (atr or c["high"] - c["low"])
                and abs(c2["high"] - c3["high"]) < 0.5 * (atr or c["high"] - c["low"])
                and _body_at_least(p, atr, 0.10) and _body_at_least(c3, atr, 0.10)
                and _body_at_least(c2, atr, 0.10) and _body_at_least(c4, atr, 0.10)):
            add("Triple Top", "STRONG_BEARISH", 5, "BULLISH", c4["high"])

    # Bearish Flag (needs i >= 3)
    if i >= 3:
        c3 = candles[i - 3]
        c2 = candles[i - 2]
        p = candles[i - 1]
        if (c3["close"] < c3["open"] and c2["close"] < c2["open"]
                and p["close"] < p["open"] and c["close"] < c["open"]
                and c["close"] > p["close"] and c["high"] < p["high"]  # slight pullback
                and _body_at_least(c3, atr, 0.10)):
            add("Bearish Flag", "MODERATE_BEARISH", 4, "BEARISH", c3["high"])

    # Bearish Pennant (needs i >= 3)
    if i >= 3:
        c3 = candles[i - 3]
        c2 = candles[i - 2]
        p = candles[i - 1]
        if (c3["close"] < c3["open"] and c2["close"] < c2["open"]
                and p["close"] < p["open"] and c["close"] < c["open"]
                and c_br < p_br and c_br < c2_br  # converging
                and c["close"] < c2["close"]
                and _body_at_least(c3, atr, 0.10)):
            add("Bearish Pennant", "MODERATE_BEARISH", 4, "BEARISH", c3["high"])

    # Bearish Rectangle (needs i >= 3)
    if i >= 3:
        c3 = candles[i - 3]
        c2 = candles[i - 2]
        p = candles[i - 1]
        if (c3["close"] < c3["open"] and c2["close"] < c2["open"]
                and p["close"] < p["open"] and c["close"] < c["open"]
                and abs(c["close"] - c3["close"]) < 0.5 * (atr or c["high"] - c["low"])
                and abs(c["high"] - c3["high"]) < 0.5 * (atr or c["high"] - c["low"])
                and _body_at_least(c3, atr, 0.10)):
            add("Bearish Rectangle", "MODERATE_BEARISH", 4, "BEARISH", c3["high"])

    # Falling Three Methods (needs i >= 4)
    if i >= 4:
        c4 = candles[i - 4]
        c3 = candles[i - 3]
        c2 = candles[i - 2]
        p = candles[i - 1]
        if (c4["close"] < c4["open"] and c3["close"] > c3["open"]
                and c2["close"] > c2["open"] and p["close"] > p["open"]
                and c["close"] < c["open"] and c["close"] < c4["close"]
                and _body_at_least(c4, atr, 0.10) and _body_at_least(c3, atr, 0.10)
                and _body_at_least(c2, atr, 0.10) and _body_at_least(p, atr, 0.10)
                and _body_at_least(c, atr, 0.10)):
            add("Falling Three Methods", "STRONG_BEARISH", 5, "BEARISH", c4["high"])

    # Falling Wedge (needs i >= 3)
    if i >= 3:
        c3 = candles[i - 3]
        c2 = candles[i - 2]
        p = candles[i - 1]
        if (c3["close"] < c3["open"] and c2["close"] < c2["open"]
                and p["close"] < p["open"] and c["close"] < c["open"]
                and c["high"] > p["high"] and c["low"] < p["low"]  # converging down
                and _body_at_least(c3, atr, 0.10)):
            add("Falling Wedge", "MODERATE_BEARISH", 4, "BEARISH", c3["high"])

    # Descending Triangle (needs i >= 3)
    if i >= 3:
        c3 = candles[i - 3]
        c2 = candles[i - 2]
        p = candles[i - 1]
        if (c3["close"] < c3["open"] and c2["close"] < c2["open"]
                and p["close"] < p["open"] and c["close"] < c["open"]
                and abs(c["low"] - p["low"]) < 0.5 * (atr or c["high"] - c["low"])
                and c["high"] < p["high"]  # lower highs
                and _body_at_least(c3, atr, 0.10)):
            add("Descending Triangle", "MODERATE_BEARISH", 4, "BEARISH", c3["high"])

    return results


# --------------------------------------------------------------------------- #
# Candle buffer — holds completed 5m candles + one in-progress candle
# --------------------------------------------------------------------------- #
class CandleBuffer:
    def __init__(self, symbol: str, instrument_type: str):
        self.symbol = symbol
        self.instrument_type = instrument_type  # "SPOT", "CE", "PE"
        self.candles: List[dict] = []       # completed candles, chronological
        self.current: Optional[dict] = None
        self.current_start: Optional[datetime] = None
        self.last_atr: Optional[float] = None

    def on_tick(self, price: float, ts: datetime):
        """Process a tick. Returns the completed candle dict if a bucket rolled."""
        key = floor_5min(ts)
        if key.time() < FIRST_CANDLE_START:
            return None
        completed = None
        if self.current_start is None:
            self.current_start = key
            self.current = {
                "timestamp": key.isoformat(), "open": price, "high": price,
                "low": price, "close": price, "session_date": session_date(key),
            }
        elif key > self.current_start:
            completed = dict(self.current)
            completed["is_complete"] = True
            self.candles.append(completed)
            if len(self.candles) > 200:
                self.candles = self.candles[-200:]
            self.current_start = key
            self.current = {
                "timestamp": key.isoformat(), "open": price, "high": price,
                "low": price, "close": price, "session_date": session_date(key),
            }
        else:
            c = self.current
            c["high"] = max(c["high"], price)
            c["low"] = min(c["low"], price)
            c["close"] = price
        return completed

    def on_completed_bar(self, bar: dict) -> dict:
        """Append an externally supplied completed 5m OHLC candle.

        Used by the 5-minute live runner, which fetches the previous completed
        option bar once per aligned poll instead of forming candles from 5s
        ticks. A forming tick candle with the same start is discarded.
        """
        start = bar["start"]
        if not isinstance(start, datetime):
            start = datetime.fromisoformat(str(start))
        if start.tzinfo is None:
            start = start.replace(tzinfo=IST)
        start = start.astimezone(IST)
        row = {
            "timestamp": start.isoformat(),
            "open": float(bar["open"]),
            "high": float(bar["high"]),
            "low": float(bar["low"]),
            "close": float(bar["close"]),
            "session_date": session_date(start),
            "is_complete": True,
        }
        if self.current_start == start:
            self.current = None
            self.current_start = None
        self.candles.append(row)
        if len(self.candles) > 200:
            self.candles = self.candles[-200:]
        return row

    def get_recent(self, limit: int = 60) -> List[dict]:
        return self.candles[-limit:]


# --------------------------------------------------------------------------- #
# Option position with dynamic SL management
# --------------------------------------------------------------------------- #
class OptionPosition:
    """Long CE/PE position using a premium ATR(14) stop and ATR-width trail."""

    def __init__(self, trade_id: str, pattern_name: str, instrument: str,
                 direction: str, entry_price: float, entry_spot: float,
                 entry_ts: str, session_date: str,
                 atr: Optional[float] = None):
        self.trade_id = trade_id
        self.pattern_name = pattern_name
        self.instrument = instrument
        self.direction = direction  # "BULLISH" (long CE) or "BEARISH" (long PE)
        self.entry_price = float(entry_price)  # option LTP at entry
        self.entry_spot = float(entry_spot)    # NIFTY spot at entry (context only)
        self.entry_ts = entry_ts
        self.session_date = session_date

        # Premium ATR-only exit.  Long CE and long PE both profit when the
        # premium rises, so direction does not affect stop/trail arithmetic.
        self.atr_at_entry = round(float(atr), 4) if atr is not None else None
        stop_price, distance, distance_pct, source = compute_atr_stop(entry_price, atr)
        self.stop_price = stop_price
        self.trail_distance = distance
        self.stop_distance_pct = distance_pct
        self.stop_source = source

        # Legacy spot-named fields are retained for DB/status compatibility.
        # They now hold premium stop values, not NIFTY spot levels.
        self.sl_spot = stop_price
        self.initial_sl = stop_price
        self.stop_loss = stop_price
        self.hwm = float(entry_price)
        self.lwm = float(entry_price)
        self.trail_stop = stop_price
        self.be_locked = False

        self.status = "active"
        self.exit_ts = None
        self.exit_price = None
        self.exit_reason = None
        self.pnl_points = None
        self.gross_pnl_points = None
        self.holding_minutes = None
        self.mfe_points = 0.0
        self.mae_points = 0.0
        self.trailing_update_count = 0
        self.stop_changes: List[dict] = []

        self.stop_changes.append({
            "change_id": uuid.uuid4().hex,
            "trade_id": trade_id,
            "timestamp": entry_ts,
            "old_sl": round(float(entry_price), 2),
            "new_sl": stop_price,
            "method": "ATR_STOP",
            "reason": f"initial_sl_{source}",
        })

    def update_mfe_mae(self, premium_high: float, premium_low: float):
        """Track option-premium extremes. Both long CE and long PE profit when
        the premium rises, so direction never changes this arithmetic."""
        if premium_high is None or premium_low is None:
            return
        high, low = float(premium_high), float(premium_low)
        entry = self.entry_price
        self.hwm = max(self.hwm, high)
        self.lwm = min(self.lwm, low)
        self.mfe_points = max(self.mfe_points, high - entry)
        self.mae_points = min(self.mae_points, low - entry)

    def update_trail(self, premium_ltp: float, timestamp: str) -> Optional[float]:
        """Ratchet the premium ATR-width trail; return a fill price if hit.

        The trail activates as soon as the premium makes a new high above the
        entry (no fixed +5 activation threshold), uses the ATR distance fixed
        at entry, and can never ratchet down. Before a new premium high the
        initial ATR stop is the only exit, so a loss is never labelled as a
        trail exit. There is no breakeven lock.
        """
        if premium_ltp is None:
            return None
        ltp = float(premium_ltp)
        old_stop = self.stop_loss
        self.hwm = max(self.hwm, ltp)
        if self.hwm <= self.entry_price:
            return None

        if self.trail_distance is not None and self.trail_distance > 0:
            distance = float(self.trail_distance)
        else:
            distance = compute_atr_stop(self.entry_price, self.atr_at_entry)[1]

        candidate = round(self.hwm - distance, 2)
        if candidate > self.stop_loss:
            self.stop_loss = candidate
            self.trail_stop = candidate

        if self.stop_loss != old_stop:
            self.trailing_update_count += 1
            self.stop_changes.append({
                "change_id": uuid.uuid4().hex,
                "trade_id": self.trade_id,
                "timestamp": timestamp,
                "old_sl": round(old_stop, 2),
                "new_sl": round(self.stop_loss, 2),
                "method": "ATR_TRAIL",
                "reason": "atr_trail_ratchet",
            })

        if ltp <= self.stop_loss:
            return round(self.stop_loss, 2)
        return None

    def check_stop_loss(self, premium_ltp: float) -> Optional[float]:
        """Return the ACTUAL exit LTP when it breaches the initial ATR stop."""
        if premium_ltp is None:
            return None
        stop = self.stop_price
        if stop is None:
            stop = compute_atr_stop(self.entry_price, self.atr_at_entry)[0]
            self.stop_price = stop
            self.initial_sl = stop
            self.sl_spot = stop
        if float(premium_ltp) <= stop:
            return round(float(premium_ltp), 2)
        return None

    def evaluate_bar(self, bar_high: float, bar_low: float,
                     timestamp: str) -> Optional[tuple]:
        """Evaluate ATR trail/stop from a completed 5m option OHLC bar.

        Shared by the 5-minute live runner and the 5m backtest replay so both
        use identical timing and fill rules. Returns (exit_price, reason), or
        None when the bar does not breach either stop.
        """
        if bar_high is None or bar_low is None:
            return None
        high, low = float(bar_high), float(bar_low)
        self.update_mfe_mae(high, low)

        trail_hit = self.update_trail(high, timestamp)
        if trail_hit is None and self.hwm > self.entry_price \
                and low <= self.stop_loss:
            trail_hit = round(self.stop_loss, 2)
        sl_hit = self.check_stop_loss(low)

        candidates: List[tuple] = []
        if trail_hit is not None:
            candidates.append((float(trail_hit), "TRAIL_STOP_EXIT"))
        if sl_hit is not None:
            candidates.append((float(sl_hit), "STOP_LOSS_ATR"))
        if not candidates:
            return None
        exit_px, reason = min(candidates, key=lambda item: item[0])
        return round(exit_px, 2), reason

    def close(self, exit_reason: str, exit_ts: str,
              exit_price: Optional[float] = None,
              brokerage: float = 0.0, slippage: float = 0.0):
        entry = self.entry_price
        if exit_price is not None:
            px = exit_price
        else:
            px = self.stop_loss
        # Long CE and long PE both use exit − entry for PnL.
        # Direction only affects which spot move makes the option premium
        # profitable — not the PnL arithmetic itself.
        gross_pnl = px - entry
        self.pnl_points = round(gross_pnl - brokerage - slippage, 2)
        self.exit_ts = exit_ts
        self.exit_price = round(px, 2)
        self.exit_reason = exit_reason
        self.status = "closed"
        entry_dt = datetime.fromisoformat(self.entry_ts)
        exit_dt = datetime.fromisoformat(exit_ts)
        self.holding_minutes = max(0, int((exit_dt - entry_dt).total_seconds() // 60))


# --------------------------------------------------------------------------- #
# Pattern Scanner engine
# --------------------------------------------------------------------------- #
class PatternScanner:
    """Pattern scanner engine: detects bullish & bearish patterns on NIFTY SPOT 5m candles.
    Bullish  → buy ATM CE (weekly expiry); Bearish → buy ATM PE (weekly expiry).
    Entry uses the latest sampled option LTP at the spot candle close.
    Spot price is used only for ATM strike determination and rebanding."""

    def __init__(self, db_get_conn, signal_engine=None,
                 detect_fn: Optional[Callable] = None,
                 detect_fn_bearish: Optional[Callable] = None):
        self.get_conn = db_get_conn
        self.signal_engine = signal_engine
        self.detect_fn = detect_fn or detect_bullish_patterns
        self.detect_fn_bearish = detect_fn_bearish or detect_bearish_patterns

        # Candle buffers
        self.buffers: Dict[str, CandleBuffer] = {}
        self._ensure_buffer("NIFTY_SPOT", "SPOT")

        # ATM instruments
        self.current_expiry = None
        self.current_atm_strike: Optional[int] = None
        self.ce_symbol: Optional[str] = None
        self.pe_symbol: Optional[str] = None

        # Latest sampled option LTPs (used as entry price for spot-signal trades)
        self.last_ce_ltp: Optional[float] = None
        self.last_pe_ltp: Optional[float] = None
        # Exact per-symbol quotes: symbol -> (price, quote timestamp).
        # The ATM strike moves during the day, so a position's option is often
        # no longer the current ATM CE/PE. Never price an exit off the other
        # leg or off a stale quote.
        self.last_ltp: Dict[str, tuple] = {}
        self._stale_warned: Dict[str, datetime] = {}

        # Active positions: key = f"{pattern_name}:{instrument}"
        self.positions: Dict[str, OptionPosition] = {}
        self.closed_positions: List[OptionPosition] = []

        # State
        self.status = "STOPPED"
        self.last_spot: Optional[float] = None
        self.last_update: Optional[str] = None
        self._last_option_refresh = None

        # Restore open positions: paper positions hold across candles,
        # overnight and service restarts.
        self._ensure_schema()
        self._load_open_positions()

    # ---- instrument / ATM ----
    def _ensure_buffer(self, symbol: str, instrument_type: str) -> CandleBuffer:
        if symbol not in self.buffers:
            self.buffers[symbol] = CandleBuffer(symbol, instrument_type)
        return self.buffers[symbol]

    def _refresh_option_instruments(self, spot: float):
        expiry = nearest_thursday()
        atm = round_to_strike(spot)
        changed = (self.current_expiry != expiry or self.current_atm_strike != atm)
        if changed:
            self.current_expiry = expiry
            self.current_atm_strike = atm
            self.ce_symbol = option_symbol("NIFTY", expiry, atm, "CE")
            self.pe_symbol = option_symbol("NIFTY", expiry, atm, "PE")
            self._ensure_buffer(self.ce_symbol, "CE")
            self._ensure_buffer(self.pe_symbol, "PE")
            self._last_option_refresh = now_ist()
        if self.ce_symbol:
            self._ensure_buffer(self.ce_symbol, "CE")
        if self.pe_symbol:
            self._ensure_buffer(self.pe_symbol, "PE")
        return changed

    def set_option_instruments(self, ce_symbol: str, pe_symbol: str, atm_strike: int, expiry):
        """Set option instruments from external source (e.g., Kite instruments lookup)."""
        changed = (self.ce_symbol != ce_symbol or self.pe_symbol != pe_symbol)
        self.current_atm_strike = atm_strike
        self.current_expiry = expiry
        self.ce_symbol = ce_symbol
        self.pe_symbol = pe_symbol
        self._ensure_buffer(ce_symbol, "CE")
        self._ensure_buffer(pe_symbol, "PE")
        self._last_option_refresh = now_ist()
        return changed

    # ---- tick / bar processing ----
    def record_quote(self, symbol: str, price: float, ts: Optional[datetime] = None):
        """Record a fresh option LTP without triggering an exit.

        Entries and status use the sampled LTP at the aligned 5m poll, while
        exits are evaluated once from the completed 5m option OHLC bar.
        """
        if symbol == "NIFTY_SPOT" or price is None:
            return
        ts = ts or now_ist()
        self.last_ltp[symbol] = (float(price), ts)
        if symbol == self.ce_symbol:
            self.last_ce_ltp = float(price)
        elif symbol == self.pe_symbol:
            self.last_pe_ltp = float(price)

    def on_option_bar(self, symbol: str, bar: dict,
                      ts: Optional[datetime] = None):
        """Append a completed 5m option bar and evaluate ATR exits from it."""
        if symbol == "NIFTY_SPOT" or not bar:
            return
        ts = ts or now_ist()
        buffer = self.buffers.get(symbol)
        if buffer is None:
            buffer = self._ensure_buffer(symbol, "OPT")
        buffer.on_completed_bar(bar)
        self._manage_positions_bar(symbol, bar, ts)

    def on_tick(self, symbol: str, price: float, ts: Optional[datetime] = None):
        """Process a sampled tick.

        Option ticks only refresh the forming candle and entry quote; premium
        ATR exits are managed from completed 5m bars via ``on_option_bar``.
        Spot ticks still drive candle completion and pattern detection.
        """
        ts = ts or now_ist()
        if symbol != "NIFTY_SPOT":
            self.record_quote(symbol, price, ts)

        buffer = self.buffers.get(symbol)
        if buffer is None:
            buffer = self._ensure_buffer(symbol, "OPT")
        completed = buffer.on_tick(price, ts)
        if completed is not None:
            self._on_candle_completed(buffer, completed, ts)
        if symbol == "NIFTY_SPOT":
            self.last_spot = price
            self.last_update = ts.isoformat()

    def _fresh_ltp(self, symbol: Optional[str], now: datetime,
                   max_age: float = MAX_QUOTE_AGE_SEC) -> Optional[float]:
        """Latest quote for exactly `symbol`, or None if missing/stale."""
        if not symbol:
            return None
        item = self.last_ltp.get(symbol)
        if not item:
            return None
        price, ts = item
        try:
            age = (now - ts).total_seconds()
        except TypeError:
            return None
        if age < 0:
            age = 0.0
        if age > max_age:
            return None
        return float(price)

    def _warn_stale(self, kind: str, symbol: Optional[str], now: datetime):
        """Rate-limited warning so a feed outage does not flood the log."""
        key = f"{kind}:{symbol}"
        last = self._stale_warned.get(key)
        if last is not None and (now - last).total_seconds() < 60:
            return
        self._stale_warned[key] = now
        item = self.last_ltp.get(symbol) if symbol else None
        age = None
        if item:
            try:
                age = round((now - item[1]).total_seconds(), 1)
            except TypeError:
                age = None
        print(f"[pattern_scanner] SKIP {kind} {symbol}: no fresh quote "
              f"(age={age}s)")

    def _on_candle_completed(self, buffer: CandleBuffer, completed: dict,
                             tick_ts: Optional[datetime] = None):
        ts = completed["timestamp"]
        instrument_type = buffer.instrument_type
        symbol = buffer.symbol

        # SPOT: track spot price, refresh ATM instruments, run pattern detection
        if instrument_type == "SPOT":
            self.last_spot = float(completed["close"])
            self.last_update = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
            if self.current_atm_strike is None or \
               abs(self.last_spot - round_to_strike(self.last_spot)) > ATM_REBAND_THRESHOLD_POINTS:
                self._refresh_option_instruments(self.last_spot)
            elif self.current_atm_strike is not None and self._last_option_refresh is None:
                self._refresh_option_instruments(self.last_spot)

            # Pattern detection runs on SPOT candles only
            self._detect_and_enter(buffer.candles, ts, entry_ts=tick_ts)
            return

        # CE or PE: buffer candles only; pattern detection now runs on SPOT.
        # Keep the buffer for completeness but do not enter from option candles.
        if instrument_type not in ("CE", "PE"):
            return

    def _detect_and_enter(self, candles: List[dict], ts: str,
                          entry_ts: Optional[datetime] = None):
        """Run bullish + bearish pattern detection on SPOT candles.

        Bullish  → buy ATM CE (weekly), entry at latest CE LTP.
        Bearish  → buy ATM PE (weekly), entry at latest PE LTP.
        Entry price uses the live option LTP sampled at the spot candle close,
        not the spot close itself.

        `ts` is the completed signal candle's start; `entry_ts` is the tick
        time at which the candle actually closed and the trade was placed.
        The trade timestamp is the real entry time, not the candle start.
        """
        if len(candles) < 3:
            return
        if not self.ce_symbol or not self.pe_symbol:
            return

        if entry_ts is None:
            entry_ts = now_ist()
        if isinstance(entry_ts, datetime):
            entry_dt = entry_ts
        else:
            entry_dt = datetime.fromisoformat(str(entry_ts))
        entry_ts_s = entry_dt.isoformat()

        i = len(candles) - 1
        atr_list = self._compute_atr_list(candles)
        atr = atr_list[i] if i < len(atr_list) else None

        results = []
        try:
            if self.signal_engine is not None:
                candle_objs = [_Candle(cc["timestamp"], cc["open"], cc["high"],
                                       cc["low"], cc["close"], cc.get("session_date", ""))
                               for cc in candles]
                bullish = self.signal_engine.detect_all_at(candle_objs, i, atr)
                bearish = self.signal_engine.detect_all_at(candle_objs, i, atr)
                # Normalise signal_engine results (same as _on_candle_completed)
                norm = []
                for r in bullish:
                    norm.append({
                        "pattern_name": getattr(r, "pattern_name", r.get("pattern_name", "unknown")),
                        "direction": getattr(r, "direction", r.get("direction", "BULLISH")),
                        "candle_count": getattr(r, "candle_count", r.get("candle_count", 1)),
                        "first_ts": getattr(r, "first_ts", r.get("first_ts", candles[0]["timestamp"])),
                        "last_ts": getattr(r, "last_ts", r.get("last_ts", candles[-1]["timestamp"])),
                        "confirmation_ts": getattr(r, "confirmation_ts", r.get("confirmation_ts", candles[-1]["timestamp"])),
                        "pattern_high": getattr(r, "pattern_high", r.get("pattern_high", candles[-1]["high"])),
                        "pattern_low": getattr(r, "pattern_low", r.get("pattern_low", candles[-1]["low"])),
                        "invalidation_price": getattr(r, "invalidation_price", r.get("invalidation_price", candles[-1]["low"])),
                        "strength": getattr(r, "strength", r.get("strength", "")),
                        "prev_trend": getattr(r, "prev_trend", r.get("prev_trend", "")),
                        "pattern_type": getattr(r, "pattern_type", r.get("pattern_type", "japanese_candlestick")),
                    })
                for r in bearish:
                    norm.append({
                        "pattern_name": getattr(r, "pattern_name", r.get("pattern_name", "unknown")),
                        "direction": getattr(r, "direction", r.get("direction", "BEARISH")),
                        "candle_count": getattr(r, "candle_count", r.get("candle_count", 1)),
                        "first_ts": getattr(r, "first_ts", r.get("first_ts", candles[0]["timestamp"])),
                        "last_ts": getattr(r, "last_ts", r.get("last_ts", candles[-1]["timestamp"])),
                        "confirmation_ts": getattr(r, "confirmation_ts", r.get("confirmation_ts", candles[-1]["timestamp"])),
                        "pattern_high": getattr(r, "pattern_high", r.get("pattern_high", candles[-1]["high"])),
                        "pattern_low": getattr(r, "pattern_low", r.get("pattern_low", candles[-1]["low"])),
                        "invalidation_price": getattr(r, "invalidation_price", r.get("invalidation_price", candles[-1]["low"])),
                        "strength": getattr(r, "strength", r.get("strength", "")),
                        "prev_trend": getattr(r, "prev_trend", r.get("prev_trend", "")),
                        "pattern_type": getattr(r, "pattern_type", r.get("pattern_type", "japanese_candlestick")),
                    })
                results = norm
            else:
                results = self.detect_fn(candles, i, atr) + self.detect_fn_bearish(candles, i, atr)
        except Exception as e:
            print(f"[pattern_scanner] detection error on SPOT: {e}")
            results = []

        for res in results or []:
            direction = res.get("direction", "BULLISH")
            if direction not in ("BULLISH", "BEARISH"):
                continue
            pattern = res.get("pattern_name", "unknown")

            if not self._can_enter(ts):
                continue

            # Select option instrument and entry price by direction.
            # Price the exact symbol being bought, never a stale quote or the
            # opposite leg left over from a previous ATM strike.
            if direction == "BULLISH":
                symbol = self.ce_symbol
                opt_type = "CE"
            else:
                symbol = self.pe_symbol
                opt_type = "PE"

            entry_price = self._fresh_ltp(symbol, entry_dt)
            if not symbol or entry_price is None:
                # No live quote for this exact option — do not invent a price.
                self._warn_stale("entry", symbol, entry_dt)
                continue

            key = f"{pattern}:{symbol}"
            if key in self.positions:
                continue

            # ATR is derived from the exact option being bought, not from
            # NIFTY spot. The buffer's completed candles plus its current
            # forming candle are passed in; premium_atr() excludes the final
            # forming row, so the stop is knowable at entry time.
            buffer = self.buffers.get(symbol)
            option_rows = list(buffer.candles) if buffer else []
            forming = (buffer.current if buffer and buffer.current is not None else {
                "timestamp": entry_ts_s,
                "open": float(entry_price),
                "high": float(entry_price),
                "low": float(entry_price),
                "close": float(entry_price),
            })
            option_rows.append(forming)
            option_atr = premium_atr(option_rows)

            pos = OptionPosition(
                trade_id=uuid.uuid4().hex,
                pattern_name=pattern,
                instrument=symbol,
                direction=direction,
                entry_price=float(entry_price),
                entry_spot=float(self.last_spot),
                entry_ts=entry_ts_s,
                session_date=session_date(entry_ts_s),
                atr=option_atr,
            )
            self.positions[key] = pos
            self._persist_position(pos, db_pattern=f"{pattern}:{opt_type}")
            print(f"[pattern_scanner] ENTRY {direction} {symbol} "
                  f"pattern={pattern} entry={pos.entry_price:.2f} "
                  f"atr={pos.atr_at_entry} stop={pos.stop_price:.2f} "
                  f"source={pos.stop_source} ts={entry_ts_s}")

    def _manage_positions_bar(self, symbol: str, bar: dict, ts: datetime):
        """Premium ATR exits from a completed 5m option OHLC bar.

        This is the live counterpart of the 5m backtest replay. Only the
        position's own option bar can manage it, only completed bars are used,
        and a position entered on this bar's close is first evaluated on the
        next poll's bar.
        """
        if not bar or symbol == "NIFTY_SPOT":
            return
        ts = ts or now_ist()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=IST)
        start = bar.get("start")
        if isinstance(start, datetime):
            bar_start = start
        elif start:
            bar_start = datetime.fromisoformat(str(start))
        else:
            return
        if bar_start.tzinfo is None:
            bar_start = bar_start.replace(tzinfo=IST)
        bar_start = bar_start.astimezone(IST)
        bar_end = bar_start + timedelta(minutes=5)
        # At an aligned 5m poll the previous bar is complete. Never evaluate a
        # forming bar or a bar that started before the 09:15 exchange open.
        if bar_end > ts or bar_start.time() < FIRST_CANDLE_START:
            return
        bar_end_iso = bar_end.isoformat()

        for key in list(self.positions.keys()):
            pos = self.positions[key]
            if pos.instrument != symbol:
                continue
            # Entry happened at this bar's close poll (or later): skip it.
            if pos.entry_ts:
                try:
                    entry_dt = datetime.fromisoformat(pos.entry_ts)
                    if entry_dt.tzinfo is None and bar_end.tzinfo is not None:
                        entry_dt = entry_dt.replace(tzinfo=bar_end.tzinfo)
                    if entry_dt >= bar_end:
                        continue
                except (TypeError, ValueError):
                    pass

            old_stop = pos.stop_loss
            old_mfe = pos.mfe_points
            old_mae = pos.mae_points
            result = pos.evaluate_bar(bar["high"], bar["low"], bar_end_iso)
            if (pos.stop_loss != old_stop or pos.mfe_points != old_mfe
                    or pos.mae_points != old_mae):
                self._persist_trailing(pos)
            if result is None:
                continue

            exit_px, reason = result
            pos.close(reason, bar_end_iso, exit_price=exit_px)
            self.closed_positions.append(pos)
            del self.positions[key]
            self._persist_exit(pos)
            print(f"[pattern_scanner] {reason} {pos.instrument} "
                  f"entry_opt={pos.entry_price:.2f} exit_opt={pos.exit_price:.2f} "
                  f"atr={pos.atr_at_entry} stop={pos.stop_price:.2f} "
                  f"pnl={pos.pnl_points:.2f}")

    def _compute_atr_list(self, candles: List[dict]) -> List[Optional[float]]:
        """Simple ATR(14) over completed candles — no lookahead."""
        if len(candles) < 2:
            return [None] * len(candles)
        trs = []
        for i in range(1, len(candles)):
            cur = candles[i]
            prev = candles[i - 1]
            tr = max(
                cur["high"] - cur["low"],
                abs(cur["high"] - prev["close"]),
                abs(cur["low"] - prev["close"]),
            )
            trs.append(tr)
        atrs = [None]  # index 0 has no TR
        period = 14
        for i in range(len(trs)):
            if i < period - 1:
                atrs.append(None)
            elif i == period - 1:
                atrs.append(sum(trs[:period]) / period)
            else:
                prev_atr = atrs[-1]
                if prev_atr is None:
                    prev_atr = sum(trs[-period:]) / period
                atrs.append((prev_atr * (period - 1) + trs[i]) / period)
        return atrs

    def _can_enter(self, ts: str) -> bool:
        t = datetime.fromisoformat(ts).time()
        return t < NO_NEW_ENTRY_AFTER

    # ---- persistence ----
    def _ensure_schema(self):
        """Idempotent migration for legacy and premium-ATR exit columns."""
        try:
            conn = self.get_conn()
            cols = {r[1] for r in conn.execute(
                "PRAGMA table_info(pattern_scanner_positions)").fetchall()}
            additions = {
                "hwm": "REAL",
                "lwm": "REAL",
                "entry_spot": "REAL",
                "be_locked": "INTEGER DEFAULT 0",
                "atr_at_entry": "REAL",
                "stop_price": "REAL",
                "trail_distance": "REAL",
                "stop_distance_pct": "REAL",
                "stop_source": "TEXT",
            }
            for column, declaration in additions.items():
                if column not in cols:
                    conn.execute(
                        f"ALTER TABLE pattern_scanner_positions "
                        f"ADD COLUMN {column} {declaration}")
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[pattern_scanner] schema check error: {e}")

    def _load_open_positions(self):
        """Restore active positions so paper trades survive restarts."""
        try:
            conn = self.get_conn()
            rows = conn.execute(
                "SELECT * FROM pattern_scanner_positions WHERE status='active'"
            ).fetchall()
            change_rows = conn.execute(
                "SELECT * FROM pattern_scanner_stop_changes ORDER BY rowid"
            ).fetchall()
            conn.close()
        except Exception as e:
            print(f"[pattern_scanner] load positions error: {e}")
            return

        by_trade: Dict[str, List[dict]] = {}
        for r in change_rows:
            d = dict(r)
            by_trade.setdefault(d["trade_id"], []).append(d)

        for r in rows:
            d = dict(r)
            entry_price = float(d["entry_price"])
            entry_spot = (float(d["entry_spot"])
                          if d.get("entry_spot") is not None else entry_price)
            atr = (float(d["atr_at_entry"])
                   if d.get("atr_at_entry") is not None else None)
            pos = OptionPosition(
                trade_id=d["trade_id"],
                pattern_name=d["pattern_name"],
                instrument=d["instrument"],
                direction=d["direction"],
                entry_price=entry_price,
                entry_spot=entry_spot,
                entry_ts=d["entry_ts"],
                session_date=(d.get("session_date")
                              or session_date(d["entry_ts"])),
                atr=atr,
            )

            if not d.get("stop_source"):
                # Legacy row from the spot-stop era. Its stored hwm/lwm and
                # stop are NIFTY spot values and cannot be reused. Migrate it
                # to the ATR-only model using the fallback premium distance.
                pos.stop_price, distance, pct, source = compute_atr_stop(
                    entry_price, None)
                pos.stop_loss = pos.stop_price
                pos.trail_distance = distance
                pos.stop_distance_pct = pct
                pos.stop_source = source
                pos.hwm = entry_price
                pos.lwm = entry_price
                pos.trail_stop = pos.stop_price
                pos.be_locked = False
                pos.sl_spot = pos.stop_price
                pos.initial_sl = pos.stop_price
            else:
                pos.stop_price = (float(d["stop_price"])
                                  if d.get("stop_price") is not None
                                  else pos.stop_price)
                pos.stop_loss = (float(d["stop_loss"])
                                 if d.get("stop_loss") is not None
                                 else pos.stop_loss)
                pos.trail_distance = (float(d["trail_distance"])
                                      if d.get("trail_distance") is not None
                                      else pos.trail_distance)
                pos.stop_distance_pct = (float(d["stop_distance_pct"])
                                         if d.get("stop_distance_pct") is not None
                                         else pos.stop_distance_pct)
                pos.stop_source = str(d["stop_source"])
                pos.hwm = (float(d["hwm"]) if d.get("hwm") is not None
                           else entry_price)
                pos.lwm = (float(d["lwm"]) if d.get("lwm") is not None
                           else entry_price)
                pos.trail_stop = pos.stop_loss
                pos.be_locked = False
                pos.sl_spot = pos.stop_price
                pos.initial_sl = pos.stop_price

            pos.trailing_update_count = int(d.get("trailing_update_cnt") or 0)
            pos.mfe_points = float(d.get("mfe_points") or 0.0)
            pos.mae_points = float(d.get("mae_points") or 0.0)
            changes = by_trade.get(pos.trade_id)
            if changes:
                pos.stop_changes = changes
            key = f"{pos.pattern_name}:{pos.instrument}"
            self.positions[key] = pos
            print(f"[pattern_scanner] recovered {key} "
                  f"entry_opt={pos.entry_price:.2f} atr={pos.atr_at_entry} "
                  f"stop={pos.stop_price:.2f} effective_stop={pos.stop_loss:.2f} "
                  f"hwm={pos.hwm:.2f} source={pos.stop_source}")

    def _persist_position(self, pos: OptionPosition, db_pattern: str):
        try:
            conn = self.get_conn()
            conn.execute(
                """INSERT OR IGNORE INTO pattern_scanner_positions
                   (trade_id, pattern_name, instrument, direction, entry_price,
                    entry_spot, initial_sl, stop_loss, entry_ts, status,
                    session_date, hwm, lwm, be_locked,
                    atr_at_entry, stop_price, trail_distance,
                    stop_distance_pct, stop_source)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (pos.trade_id, pos.pattern_name, pos.instrument, pos.direction,
                 pos.entry_price, pos.entry_spot, pos.sl_spot, pos.stop_loss,
                 pos.entry_ts, "active", pos.session_date,
                 round(pos.hwm, 2), round(pos.lwm, 2),
                 1 if pos.be_locked else 0,
                 pos.atr_at_entry, pos.stop_price, pos.trail_distance,
                 pos.stop_distance_pct, pos.stop_source))
            # Log initial SL as first stop change
            sc = pos.stop_changes[0]
            conn.execute(
                """INSERT OR IGNORE INTO pattern_scanner_stop_changes
                   (change_id, trade_id, timestamp, old_sl, new_sl, method, reason)
                   VALUES (?,?,?,?,?,?,?)""",
                (sc["change_id"], pos.trade_id, sc["timestamp"],
                 sc["old_sl"], sc["new_sl"], sc["method"], sc["reason"]))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[pattern_scanner] persist position error: {e}")

    def _persist_trailing(self, pos: OptionPosition):
        """Persist updated trail/SL/MFE/MAE state and new stop changes."""
        try:
            conn = self.get_conn()
            conn.execute(
                """UPDATE pattern_scanner_positions
                   SET stop_loss=?, hwm=?, lwm=?, be_locked=?,
                       trailing_update_cnt=?, mfe_points=?, mae_points=?,
                       stop_price=?, trail_distance=?, stop_distance_pct=?,
                       stop_source=?, updated_at=datetime('now')
                   WHERE trade_id=?""",
                (round(pos.stop_loss, 2), round(pos.hwm, 2), round(pos.lwm, 2),
                 1 if pos.be_locked else 0, pos.trailing_update_count,
                 round(pos.mfe_points, 2), round(pos.mae_points, 2),
                 pos.stop_price, pos.trail_distance, pos.stop_distance_pct,
                 pos.stop_source, pos.trade_id))
            for sc in pos.stop_changes[1:]:
                conn.execute(
                    """INSERT OR IGNORE INTO pattern_scanner_stop_changes
                       (change_id, trade_id, timestamp, old_sl, new_sl, method, reason)
                       VALUES (?,?,?,?,?,?,?)""",
                    (sc["change_id"], pos.trade_id, sc["timestamp"],
                     sc["old_sl"], sc["new_sl"], sc["method"], sc["reason"]))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[pattern_scanner] persist trailing error: {e}")

    def _persist_exit(self, pos: OptionPosition):
        try:
            conn = self.get_conn()
            conn.execute(
                """UPDATE pattern_scanner_positions
                   SET exit_ts=?, exit_price=?, exit_reason=?, pnl_points=?,
                       gross_pnl_points=?, holding_minutes=?, status='closed',
                       stop_loss=?, hwm=?, lwm=?, be_locked=?,
                       trailing_update_cnt=?, mfe_points=?, mae_points=?,
                       stop_price=?, trail_distance=?, stop_distance_pct=?,
                       stop_source=?, updated_at=datetime('now')
                   WHERE trade_id=?""",
                (pos.exit_ts, pos.exit_price, pos.exit_reason,
                 pos.pnl_points, pos.gross_pnl_points,
                 pos.holding_minutes, round(pos.stop_loss, 2),
                 round(pos.hwm, 2), round(pos.lwm, 2),
                 1 if pos.be_locked else 0,
                 pos.trailing_update_count, round(pos.mfe_points, 2),
                 round(pos.mae_points, 2), pos.stop_price,
                 pos.trail_distance, pos.stop_distance_pct,
                 pos.stop_source, pos.trade_id))
            # Persist trailing stop changes
            for sc in pos.stop_changes[1:]:  # skip initial (already saved)
                conn.execute(
                    """INSERT OR IGNORE INTO pattern_scanner_stop_changes
                       (change_id, trade_id, timestamp, old_sl, new_sl, method, reason)
                       VALUES (?,?,?,?,?,?,?)""",
                    (sc["change_id"], pos.trade_id, sc["timestamp"],
                     sc["old_sl"], sc["new_sl"], sc["method"], sc["reason"]))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[pattern_scanner] persist exit error: {e}")

    # ---- status ----
    def get_status(self) -> dict:
        active = []
        for key, pos in self.positions.items():
            active.append({
                "trade_id": pos.trade_id,
                "pattern_name": pos.pattern_name,
                "instrument": pos.instrument,
                "direction": pos.direction,
                "entry_price": pos.entry_price,
                "initial_sl": pos.stop_price,
                "stop_price": pos.stop_price,
                "stop_loss": pos.stop_loss,
                "atr_at_entry": pos.atr_at_entry,
                "trail_distance": pos.trail_distance,
                "stop_distance_pct": pos.stop_distance_pct,
                "stop_source": pos.stop_source,
                "hwm": round(pos.hwm, 2),
                "be_locked": pos.be_locked,
                "entry_ts": pos.entry_ts,
                "trailing_update_count": pos.trailing_update_count,
                "mfe_points": pos.mfe_points,
                "mae_points": pos.mae_points,
            })
        closed = []
        for p in self.closed_positions[-20:]:
            closed.append({
                "trade_id": p.trade_id,
                "pattern_name": p.pattern_name,
                "instrument": p.instrument,
                "direction": p.direction,
                "entry_price": p.entry_price,
                "exit_price": p.exit_price,
                "exit_reason": p.exit_reason,
                "atr_at_entry": p.atr_at_entry,
                "stop_price": p.stop_price,
                "stop_source": p.stop_source,
                "pnl_points": p.pnl_points,
                "gross_pnl_points": p.gross_pnl_points,
                "entry_ts": p.entry_ts,
                "exit_ts": p.exit_ts,
                "holding_minutes": p.holding_minutes,
            })
        total_pnl = sum(p.pnl_points or 0 for p in self.closed_positions)
        return {
            "scanner": "pattern_scanner",
            "instrument": "NIFTY ATM CE/PE (current week expiry)",
            "timeframe": "5 minutes",
            "mode": "paper",
            "exit_model": "PREMIUM_ATR_ONLY",
            "status": self.status,
            "market_open": is_market_open(),
            "last_spot": self.last_spot,
            "last_update": self.last_update,
            "atm_strike": self.current_atm_strike,
            "expiry": self.current_expiry.isoformat() if self.current_expiry else None,
            "ce_symbol": self.ce_symbol,
            "pe_symbol": self.pe_symbol,
            "active_trades": active,
            "active_count": len(active),
            "recent_closed": closed,
            "total_closed_pnl": round(total_pnl, 2),
            "server_time_ist": now_ist().isoformat(),
        }

    def start(self):
        self.status = "RUNNING"
        print("[pattern_scanner] started")

    def stop(self):
        # Positions are held across restarts; do not force a time-based exit.
        self.status = "STOPPED"
        print("[pattern_scanner] stopped")
