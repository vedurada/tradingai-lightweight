#!/usr/bin/env python3
"""Pure SMA9 HIGH Trail strategy engine for ATM NIFTY CE and PE options.

BUY-ONLY rules (identical for CE and PE):
  Entry: consumed from the base sma9_high scanner (same contract, price
         and entry candle); this module's evaluate_option is kept only for
         diagnostics/tests.
  Exit: TRAILING STOP -- stop = peak - 5.0 pts, activates at +5.0 pts
        (breakeven at activation), ratchets up only.
        Exit at the stop ONLY if the stop is above entry price (profitable lock).
        Breakeven or loss stops are ignored -- the trade runs to candle close.
        Fixed stop loss: exit when LTP reaches entry - 5% of entry premium.
        Otherwise exit at the CLOSE of the entry 5-minute candle.

No carry forward.  No broker / database / network dependencies -- safe to
unit test with synthetic fixtures.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence

SMA_PERIOD = 9
CANDLE_MINUTES = 5
TRAIL = 5.0
ACTIVATE = 5.0
BE_LOCK_PROFIT = 6.0
BE_LOCK_STOP = 2.0
STOP_LOSS_PCT = 0.05
STRATEGY_ID = "sma9_high_trail"
STRATEGY_VERSION = "2.1.0"
STRATEGY_TYPE = "SMA_HIGH_BUY_ONLY"
ENTRY_TYPE = "sma_high"


# ---------------------------------------------------------------------------
# Candle helpers
# ---------------------------------------------------------------------------
def _as_dt(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise TypeError(f"Unsupported timestamp type: {type(value)!r}")


def normalize_candles(candles):
    cleaned = {}
    for c in candles:
        start = _as_dt(c.get("start", c.get("date", c.get("timestamp"))))
        cleaned[start] = {
            "start": start,
            "open": float(c["open"]),
            "high": float(c["high"]),
            "low": float(c["low"]),
            "close": float(c["close"]),
            "volume": int(c.get("volume", 0) or 0),
        }
    return [cleaned[k] for k in sorted(cleaned)]


def candle_end(start):
    return start + timedelta(minutes=CANDLE_MINUTES)


def compute_sma(closes, period):
    if period <= 0 or len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def make_trade_id(instrument, strike, option_type, entry_candle_start,
                  prefix="S9HT-"):
    ts = _as_dt(entry_candle_start).isoformat()
    raw = f"SMA9_HIGH_TRAIL|{STRATEGY_ID}|{instrument}|{strike}|{option_type}|{ts}"
    return prefix + hashlib.sha1(raw.encode()).hexdigest()[:12].upper()


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------
@dataclass
class Evaluation:
    option_type: str
    candle_start: Optional[datetime] = None
    candle_end: Optional[datetime] = None
    sma: Optional[float] = None
    prev_close: Optional[float] = None
    prev_high: Optional[float] = None
    current_open: Optional[float] = None
    ltp: Optional[float] = None
    condition_a: bool = False
    condition_b: bool = False
    condition_c: bool = False
    qualified: bool = False
    confirmation: bool = False
    breakout: bool = False
    signal: bool = False
    ready: bool = False
    reason: str = ""

    def as_dict(self):
        d = {
            "option_type": self.option_type,
            "candle_start": self.candle_start.isoformat() if self.candle_start else None,
            "candle_end": self.candle_end.isoformat() if self.candle_end else None,
            "sma": round(self.sma, 2) if self.sma is not None else None,
            "prev_close": self.prev_close,
            "prev_high": self.prev_high,
            "current_open": self.current_open,
            "ltp": self.ltp,
            "condition_a": self.condition_a,
            "condition_b": self.condition_b,
            "condition_c": self.condition_c,
            "qualified": self.qualified,
            "confirmation": self.confirmation,
            "breakout": self.breakout,
            "signal": self.signal,
            "ready": self.ready,
            "reason": self.reason,
        }
        return d


def evaluate_option(candles, option_type, ltp=None):
    """Evaluate one option at the current (last, still forming) candle.

    ``candles`` must include completed candles plus the current forming
    candle as the final element.  The forming candle's high/close are
    ignored for entry qualification, so the previous candle values always
    come from a completed candle.
    """
    if option_type not in ("CE", "PE"):
        raise ValueError("option_type must be CE or PE")

    rows = normalize_candles(candles)
    ev = Evaluation(option_type=option_type, ltp=ltp)

    if len(rows) < 2:
        ev.reason = f"insufficient candles ({len(rows)}); need 2"
        return ev

    completed = rows[:-1]
    forming = rows[-1]
    prev = completed[-1]

    ev.candle_start = forming["start"]
    ev.candle_end = candle_end(forming["start"])
    ev.current_open = forming["open"]
    ev.ready = True

    sma = None
    if SMA_PERIOD > 0 and len(completed) >= SMA_PERIOD:
        sma = compute_sma([c["close"] for c in completed], SMA_PERIOD)
    ev.sma = sma
    ev.prev_close = prev["close"]
    ev.prev_high = prev["high"]

    entry_type = "sma_high"
    if entry_type == "prev_high":
        ev.breakout = ltp is not None and ltp > prev["high"]
        ev.signal = bool(ev.breakout)
        ev.reason = ("BUY signal: LTP>prev_high" if ev.signal
                     else "waiting for LTP>prev_high")
    elif entry_type == "sma":
        ev.condition_a = sma is not None and prev["close"] > sma
        ev.condition_b = sma is not None and forming["open"] > sma
        ev.qualified = ev.condition_a and ev.condition_b
        ev.confirmation = ev.qualified
        ev.signal = bool(ev.qualified)
        if not ev.condition_a:
            ev.reason = "not qualified: prev_close<=SMA"
        elif not ev.condition_b:
            ev.reason = "not qualified: current_open<=SMA"
        else:
            ev.reason = "BUY signal: prev_close>SMA and current_open>SMA"
    elif entry_type == "sma_high":
        ev.condition_a = sma is not None and prev["close"] > sma
        ev.condition_b = ltp is not None and ltp > prev["high"]
        ev.condition_c = sma is not None and forming["open"] > sma
        ev.qualified = ev.condition_a and ev.condition_c
        ev.confirmation = ev.condition_b
        ev.signal = bool(ev.qualified and ev.confirmation)
        if ltp is None:
            ev.reason = "LTP unavailable"
        elif not ev.condition_a:
            ev.reason = f"not qualified: prev_close<=SMA"
        elif not ev.condition_c:
            ev.reason = f"not qualified: current_open<=SMA"
        elif not ev.condition_b:
            ev.reason = f"prev_close and current_open above SMA; waiting for LTP>prev_high"
        else:
            ev.reason = f"BUY signal: prev_close>SMA and current_open>SMA and LTP>prev_high"
    else:
        ev.reason = f"unknown entry_type: {entry_type}"

    if ltp is None:
        ev.reason = "LTP unavailable"
    return ev


# ---------------------------------------------------------------------------
# Per-option state machine (with trailing stop)
# ---------------------------------------------------------------------------
@dataclass
class Position:
    option_type: str
    trade_id: str
    strike: float
    expiry: str
    token: Optional[int]
    tradingsymbol: str
    entry_timestamp: datetime
    entry_candle_start: datetime
    entry_candle_end: datetime
    entry_price: float
    prev_high: float
    current_open: float
    breakout: bool
    ltp_at_entry: float
    hwm: float = 0.0
    stop: Optional[float] = None
    be_locked: bool = False

    def as_dict(self):
        d = self.__dict__.copy()
        for k in ("entry_timestamp", "entry_candle_start", "entry_candle_end"):
            d[k] = d[k].isoformat()
        return d

    @classmethod
    def from_dict(cls, d):
        data = dict(d)
        for k in ("entry_timestamp", "entry_candle_start", "entry_candle_end"):
            data[k] = _as_dt(data[k])
        return cls(**data)

    def update_trail(self, ltp):
        """Update high-water mark and check trail stop.

        Only triggers an exit if the stop is strictly above entry price
        (a profitable lock).  If the stop is at or below entry
        (breakeven / loss), we do NOT exit -- the trade runs to candle
        close instead.

        Trail sequence:
          * inactive until hwm - entry >= ACTIVATE (+5): stop = entry
            (breakeven), then stop = max(stop, hwm - TRAIL) ratcheting up.
          * one-time breakeven lock: when hwm - entry >= BE_LOCK_PROFIT (+6)
            and not already locked, set stop = max(stop, entry + BE_LOCK_STOP)
            (+2) exactly once, then let the normal trail continue from there.
        """
        if ltp is None:
            return None
        if ltp > self.hwm:
            self.hwm = ltp
        # Existing trail activation at +ACTIVATE (breakeven at entry).
        if self.hwm - self.entry_price >= ACTIVATE:
            if self.stop is None:
                self.stop = self.entry_price  # breakeven at activation
            else:
                self.stop = max(self.stop, self.hwm - TRAIL)
        # One-time breakeven lock at +BE_LOCK_PROFIT: lock in +BE_LOCK_STOP.
        if (not self.be_locked
                and self.hwm - self.entry_price >= BE_LOCK_PROFIT):
            base_stop = self.stop if self.stop is not None else self.entry_price
            self.stop = max(base_stop, self.entry_price + BE_LOCK_STOP)
            self.be_locked = True
        # Only exit when the stop itself is profitable (stop > entry).
        # Breakeven or loss stops are ignored; hold until candle close.
        if (self.stop is not None
                and self.stop > self.entry_price
                and ltp <= self.stop):
            return round(self.stop, 2)
        return None


class OptionStateMachine:
    """Independent CE or PE state machine with trailing-stop exit.

    Guarantees:
      * at most one open position for this option
      * at most one entry per 5-minute candle (duplicate-poll guard)
      * no entry whose candle would end after market close
      * exit at trail stop if hit, otherwise at entry candle's end
    """

    def __init__(self, option_type):
        if option_type not in ("CE", "PE"):
            raise ValueError("option_type must be CE or PE")
        self.option_type = option_type
        self.position = None
        self.entered_candles = set()

    def try_entry(self, ev, now, strike, expiry, token, tradingsymbol,
                  market_close):
        if self.position is not None:
            return None
        if not ev.signal or ev.ltp is None or ev.candle_start is None:
            return None
        if ev.candle_start in self.entered_candles:
            return None
        if candle_end(ev.candle_start) > market_close:
            return None

        entry_px = round(float(ev.ltp), 2)
        pos = Position(
            option_type=self.option_type,
            trade_id=make_trade_id("NIFTY", strike, self.option_type,
                                   ev.candle_start),
            strike=float(strike),
            expiry=expiry,
            token=token,
            tradingsymbol=tradingsymbol,
            entry_timestamp=now,
            entry_candle_start=ev.candle_start,
            entry_candle_end=candle_end(ev.candle_start),
            entry_price=entry_px,
            prev_high=float(ev.prev_high) if ev.prev_high is not None else 0.0,
            current_open=float(ev.current_open),
            breakout=bool(ev.breakout),
            ltp_at_entry=entry_px,
            hwm=entry_px,
            stop=None,
        )
        self.position = pos
        self.entered_candles.add(ev.candle_start)
        return pos

    def update_trail(self, ltp):
        if self.position is None:
            return None
        return self.position.update_trail(ltp)

    def check_stop_loss(self, ltp):
        """Fixed 5% stop: exit when LTP reaches entry - 5% of entry premium."""
        if self.position is None or ltp is None:
            return None
        sl_price = round(self.position.entry_price * (1.0 - STOP_LOSS_PCT), 2)
        if ltp <= sl_price:
            return sl_price
        return None

    def needs_exit(self, now):
        return self.position is not None and now >= self.position.entry_candle_end

    def close(self, exit_timestamp, exit_price, exit_reason="SAME_CANDLE_EXIT",
              candle_high=None, candle_low=None):
        pos = self.position
        if pos is None:
            return None
        entry = pos.entry_price
        exit_px = round(float(exit_price), 2)
        pnl = round(exit_px - entry, 2)
        trade = {
            "trade_id": pos.trade_id,
            "strategy_id": STRATEGY_ID,
            "instrument": "NIFTY",
            "trade_date": pos.entry_candle_start.date().isoformat(),
            "option_type": pos.option_type,
            "strike": pos.strike,
            "expiry": pos.expiry,
            "signal_timestamp": pos.entry_candle_start.isoformat(),
            "entry_timestamp": pos.entry_timestamp.isoformat(),
            "entry_price": entry,
            "exit_timestamp": exit_timestamp.isoformat(),
            "exit_price": exit_px,
            "exit_reason": exit_reason,
            "pnl_points": pnl,
            "status": "CLOSED",
            "candle_open": pos.current_open,
            "candle_high": candle_high,
            "candle_low": candle_low,
            "candle_close": exit_px,
            "created_at": pos.entry_timestamp.isoformat(),
            "updated_at": exit_timestamp.isoformat(),
            "dataset": "LIVE",
            "prev_high": pos.prev_high,
            "breakout": 1 if pos.breakout else 0,
            "ltp_at_entry": pos.ltp_at_entry,
            "entry_candle_start": pos.entry_candle_start.isoformat(),
            "entry_candle_end": pos.entry_candle_end.isoformat(),
        }
        self.position = None
        return trade

    def restore(self, position):
        self.position = position
        self.entered_candles.add(position.entry_candle_start)
