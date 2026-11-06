#!/usr/bin/env python3
"""Pure SMA9 strategy engine for ATM NIFTY CE and PE options.

BUY-ONLY rules (identical for CE and PE):
  Qualification at a 5-minute candle boundary:
    A) previous completed candle CLOSE > SMA9 of the 9 completed candles
       ending at that previous candle
    OR
    B) current (forming) candle OPEN > the same SMA9
  Execution confirmation:
    live option LTP > the same SMA9
  Entry:
    paper BUY immediately when qualified and confirmed
  Exit:
    at the CLOSE of the entry 5-minute candle (no carry forward)

SMA9 is always computed from the option's own 5-minute closes.  Only
completed candles are used, so no future data can leak into a decision.

This module has no broker / database / network dependencies and is safe to
unit test with synthetic fixtures.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence

SMA_PERIOD = 9
CANDLE_MINUTES = 5
STRATEGY_ID = "sma9_only"
STRATEGY_VERSION = "2.0.0"
STRATEGY_TYPE = "SMA9_BUY_ONLY"


# ---------------------------------------------------------------------------
# Candle helpers
# ---------------------------------------------------------------------------
def _as_dt(value) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        # Accept ISO strings with or without timezone.
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise TypeError(f"Unsupported timestamp type: {type(value)!r}")


def normalize_candles(candles: Sequence[dict]) -> List[dict]:
    """Return candles sorted ascending, de-duplicated by start timestamp."""
    cleaned: Dict[datetime, dict] = {}
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


def candle_end(start: datetime) -> datetime:
    return start + timedelta(minutes=CANDLE_MINUTES)


def make_trade_id(instrument: str, strike: float, option_type: str,
                  entry_candle_start, prefix: str = "S9-") -> str:
    ts = _as_dt(entry_candle_start).isoformat()
    raw = f"SMA9|{STRATEGY_ID}|{instrument}|{strike}|{option_type}|{ts}"
    return prefix + hashlib.sha1(raw.encode()).hexdigest()[:12].upper()


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------
@dataclass
class Evaluation:
    option_type: str
    candle_start: Optional[datetime] = None
    candle_end: Optional[datetime] = None
    sma9: Optional[float] = None
    prev_close: Optional[float] = None
    current_open: Optional[float] = None
    ltp: Optional[float] = None
    condition_a: bool = False
    condition_b: bool = False
    qualified: bool = False
    confirmation: bool = False
    signal: bool = False
    ready: bool = False
    reason: str = ""

    def as_dict(self) -> dict:
        return {
            "option_type": self.option_type,
            "candle_start": self.candle_start.isoformat() if self.candle_start else None,
            "candle_end": self.candle_end.isoformat() if self.candle_end else None,
            "sma9": round(self.sma9, 2) if self.sma9 is not None else None,
            "prev_close": self.prev_close,
            "current_open": self.current_open,
            "ltp": self.ltp,
            "condition_a": self.condition_a,
            "condition_b": self.condition_b,
            "qualified": self.qualified,
            "confirmation": self.confirmation,
            "signal": self.signal,
            "ready": self.ready,
            "reason": self.reason,
        }


def evaluate_option(candles: Sequence[dict], option_type: str,
                    ltp: Optional[float] = None) -> Evaluation:
    """Evaluate one option at the current (last, still forming) candle.

    ``candles`` must include completed candles plus the current forming
    candle as the final element.  The forming candle only contributes its
    OPEN.  Its close/high/low are ignored for SMA9 and qualification.
    """
    if option_type not in ("CE", "PE"):
        raise ValueError("option_type must be CE or PE")

    rows = normalize_candles(candles)
    ev = Evaluation(option_type=option_type, ltp=ltp)

    if len(rows) < SMA_PERIOD + 1:
        ev.reason = f"insufficient candles ({len(rows)}); need {SMA_PERIOD + 1}"
        return ev

    completed = rows[:-1]
    forming = rows[-1]
    window = completed[-SMA_PERIOD:]
    if len(window) < SMA_PERIOD:
        ev.reason = "insufficient completed candles for SMA9"
        return ev

    sma9 = sum(c["close"] for c in window) / SMA_PERIOD
    prev = completed[-1]

    ev.candle_start = forming["start"]
    ev.candle_end = candle_end(forming["start"])
    ev.sma9 = sma9
    ev.prev_close = prev["close"]
    ev.current_open = forming["open"]
    ev.ready = True

    ev.condition_a = prev["close"] > sma9
    ev.condition_b = forming["open"] > sma9
    ev.qualified = ev.condition_a or ev.condition_b

    if ltp is not None:
        ev.confirmation = ltp > sma9
    else:
        ev.confirmation = False

    ev.signal = bool(ev.qualified and ev.confirmation)

    if not ev.qualified:
        ev.reason = "not qualified: prev_close<=SMA9 and current_open<=SMA9"
    elif not ev.confirmation:
        ev.reason = "qualified but LTP not above SMA9"
    else:
        why = []
        if ev.condition_a:
            why.append("prev_close>SMA9")
        if ev.condition_b:
            why.append("current_open>SMA9")
        ev.reason = "BUY signal: " + " OR ".join(why) + "; LTP>SMA9"
    return ev


# ---------------------------------------------------------------------------
# Per-option state machine
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
    sma9: float
    prev_close: float
    current_open: float
    condition_a: bool
    condition_b: bool
    ltp_at_entry: float

    def as_dict(self) -> dict:
        d = self.__dict__.copy()
        for k in ("entry_timestamp", "entry_candle_start", "entry_candle_end"):
            d[k] = d[k].isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Position":
        data = dict(d)
        for k in ("entry_timestamp", "entry_candle_start", "entry_candle_end"):
            data[k] = _as_dt(data[k])
        return cls(**data)


class OptionStateMachine:
    """Independent CE or PE state machine.

    Guarantees:
      * at most one open position for this option
      * at most one entry per 5-minute candle (duplicate-poll guard)
      * no entry whose candle would end after market close
      * exit is tied to the entry candle's end timestamp
    """

    def __init__(self, option_type: str):
        if option_type not in ("CE", "PE"):
            raise ValueError("option_type must be CE or PE")
        self.option_type = option_type
        self.position: Optional[Position] = None
        self.entered_candles: set = set()

    # -- entry -----------------------------------------------------------
    def try_entry(self, ev: Evaluation, now: datetime, strike: float,
                  expiry: str, token: Optional[int], tradingsymbol: str,
                  market_close: datetime) -> Optional[Position]:
        if self.position is not None:
            return None
        if not ev.signal or ev.ltp is None or ev.candle_start is None:
            return None
        if ev.candle_start in self.entered_candles:
            return None
        if candle_end(ev.candle_start) > market_close:
            return None

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
            entry_price=round(float(ev.ltp), 2),
            sma9=round(float(ev.sma9), 2),
            prev_close=float(ev.prev_close),
            current_open=float(ev.current_open),
            condition_a=bool(ev.condition_a),
            condition_b=bool(ev.condition_b),
            ltp_at_entry=round(float(ev.ltp), 2),
        )
        self.position = pos
        self.entered_candles.add(ev.candle_start)
        return pos

    # -- exit ------------------------------------------------------------
    def needs_exit(self, now: datetime) -> bool:
        return self.position is not None and now >= self.position.entry_candle_end

    def close(self, exit_timestamp: datetime, exit_price: float,
              exit_reason: str = "SAME_CANDLE_EXIT",
              candle_high: Optional[float] = None,
              candle_low: Optional[float] = None) -> Optional[dict]:
        pos = self.position
        if pos is None:
            return None
        entry = pos.entry_price
        exit_px = round(float(exit_price), 2)
        pnl = round(exit_px - entry, 2)  # BUY-only: always long
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
            "sma9_value": pos.sma9,
            "candle_open": pos.current_open,
            "candle_high": candle_high,
            "candle_low": candle_low,
            "candle_close": exit_px,
            "created_at": pos.entry_timestamp.isoformat(),
            "updated_at": exit_timestamp.isoformat(),
            "dataset": "LIVE",
            "prev_close": pos.prev_close,
            "condition_a": 1 if pos.condition_a else 0,
            "condition_b": 1 if pos.condition_b else 0,
            "ltp_at_entry": pos.ltp_at_entry,
            "entry_candle_start": pos.entry_candle_start.isoformat(),
            "entry_candle_end": pos.entry_candle_end.isoformat(),
        }
        self.position = None
        return trade

    def restore(self, position: Position) -> None:
        self.position = position
        self.entered_candles.add(position.entry_candle_start)
