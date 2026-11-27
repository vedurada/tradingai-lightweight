#!/usr/bin/env python3
"""Pure SMA9 strategy engine for ATM NIFTY CE and PE options.

BUY-ONLY rules (identical for CE and PE):
  Entry at a 5-minute candle boundary:
    A) previous completed candle CLOSE > SMA9
    AND
    B) current (forming) candle OPEN > SMA9
  Entry: paper BUY at the live LTP as soon as A and B are true

Exit policies (selected by the persisted Position.exit_policy):
  * 'LEGACY' (default for every pre-existing open row): unchanged behavior.
    TRAIL once HWM - entry >= 5.0 pts with a one-time +2.0 lock, then a fixed
    5% stop; restart recovers a position older than its entry candle at that
    candle's close.
  * 'SL_TARGET_1_2' (all new entries): fixed 5% initial stop, persisted at
    entry and never ratcheted, plus a 1:2 target. The only exits are
    STOP_LOSS_INITIAL and TARGET_1_2, both filled at the persisted level.
    No trailing stops, EOD exit, restart same-candle recovery or stale exit.

Only completed 5-minute candles are used for the entry signal, so no future
data can leak into a decision.  No broker / database / network dependencies.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence

SMA_PERIOD = 9
CANDLE_MINUTES = 5
STRATEGY_ID = "sma9_only"
STRATEGY_VERSION = "2.7.0"
STRATEGY_TYPE = "SMA9_BUY_ONLY"
STOP_LOSS_PCT = 0.05
TRAIL = 5.0
ACTIVATE = 5.0
BE_LOCK_PROFIT = 6.0
BE_LOCK_STOP = 2.0

LEGACY_EXIT_POLICY = "LEGACY"
SL_TARGET_EXIT_POLICY = "SL_TARGET_1_2"
EXIT_POLICIES = (LEGACY_EXIT_POLICY, SL_TARGET_EXIT_POLICY)
TARGET_MULTIPLE = 2.0


def initial_stop_for_entry(entry_price: float, direction: str = "LONG") -> float:
    """Fixed 5% initial stop for the current scanners' SL basis."""
    if direction not in ("LONG", "SHORT"):
        raise ValueError("direction must be LONG or SHORT")
    pct = STOP_LOSS_PCT if direction == "LONG" else -STOP_LOSS_PCT
    return round(float(entry_price) * (1.0 - pct), 2)


def target_for_entry(entry_price: float, initial_stop: float,
                     direction: str = "LONG") -> float:
    """1:2 reward:risk target; supports both long and short arithmetic."""
    if direction not in ("LONG", "SHORT"):
        raise ValueError("direction must be LONG or SHORT")
    entry = float(entry_price)
    stop = float(initial_stop)
    if direction == "SHORT":
        return round(entry - TARGET_MULTIPLE * (stop - entry), 2)
    return round(entry + TARGET_MULTIPLE * (entry - stop), 2)


def _as_dt(value) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
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
    current_open: Optional[float] = None
    prev_close: Optional[float] = None
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
            "current_open": self.current_open,
            "prev_close": self.prev_close,
            "ltp": self.ltp,
            "condition_a": self.condition_a,
            "condition_b": self.condition_b,
            "qualified": self.qualified,
            "confirmation": self.confirmation,
            "signal": self.signal,
            "ready": self.ready,
            "reason": self.reason,
        }


def completed_window(rows: List[dict]) -> Optional[List[dict]]:
    """Return the last SMA_PERIOD completed candles (excludes forming)."""
    completed = rows[:-1]
    if len(completed) < SMA_PERIOD:
        return None
    return completed[-SMA_PERIOD:]


def evaluate_option(candles: Sequence[dict], option_type: str,
                    ltp: Optional[float] = None) -> Evaluation:
    """Evaluate one option at the current (last, still forming) candle."""
    if option_type not in ("CE", "PE"):
        raise ValueError("option_type must be CE or PE")

    rows = normalize_candles(candles)
    ev = Evaluation(option_type=option_type, ltp=ltp)

    if len(rows) < SMA_PERIOD + 1:
        ev.reason = f"insufficient candles ({len(rows)}); need {SMA_PERIOD + 1}"
        return ev

    window = completed_window(rows)
    if window is None:
        ev.reason = "insufficient completed candles for SMA9"
        return ev

    sma = sum(c["close"] for c in window) / SMA_PERIOD

    completed = rows[:-1]
    forming = rows[-1]
    prev = completed[-1]

    ev.candle_start = forming["start"]
    ev.candle_end = candle_end(forming["start"])
    ev.sma9 = sma
    ev.prev_close = prev["close"]
    ev.current_open = forming["open"]
    ev.ready = True

    ev.condition_a = prev["close"] > sma
    ev.condition_b = forming["open"] > sma
    ev.qualified = bool(ev.condition_a and ev.condition_b)
    # informational only - the requested rule does not gate on LTP>SMA
    ev.confirmation = ltp is not None and ltp > sma
    ev.signal = bool(ev.qualified)

    if not ev.condition_a:
        ev.reason = "not qualified: prev_close<=SMA9"
    elif not ev.condition_b:
        ev.reason = "not qualified: current_open<=SMA9"
    else:
        ev.reason = "BUY signal: prev_close>SMA9 and current_open>SMA9"

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
    hwm: float = 0.0
    stop: Optional[float] = None
    be_locked: bool = False
    exit_policy: str = LEGACY_EXIT_POLICY
    initial_stop: Optional[float] = None
    target_price: Optional[float] = None

    def as_dict(self) -> dict:
        d = self.__dict__.copy()
        for k in ("entry_timestamp", "entry_candle_start", "entry_candle_end"):
            d[k] = d[k].isoformat()
        d["exit_policy"] = self.exit_policy
        d["initial_stop"] = self.initial_stop
        d["target_price"] = self.target_price
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Position":
        data = dict(d)
        for k in ("entry_timestamp", "entry_candle_start", "entry_candle_end"):
            data[k] = _as_dt(data[k])
        data.setdefault("exit_policy", LEGACY_EXIT_POLICY)
        data.setdefault("initial_stop", None)
        data.setdefault("target_price", None)
        if data["exit_policy"] not in EXIT_POLICIES:
            data["exit_policy"] = LEGACY_EXIT_POLICY
        return cls(**data)

    @property
    def is_sl_target(self) -> bool:
        return self.exit_policy == SL_TARGET_EXIT_POLICY

    def update_trail(self, ltp: Optional[float]) -> Optional[float]:
        """Update high-water mark and return a trail-stop exit price.

        Trail activates once the peak is `ACTIVATE` above entry (stop -> breakeven),
        then ratchets at peak - TRAIL.  One-time breakeven lock at +BE_LOCK_PROFIT
        moves the stop to entry + BE_LOCK_STOP.  Only a strictly profitable stop
        (stop > entry) may trigger an exit; a breakeven stop is not an exit.
        """
        if self.exit_policy != LEGACY_EXIT_POLICY:
            return None
        if ltp is None:
            return None
        if ltp > self.hwm:
            self.hwm = ltp
        if self.hwm - self.entry_price >= ACTIVATE:
            if self.stop is None:
                self.stop = self.entry_price
            else:
                self.stop = max(self.stop, self.hwm - TRAIL)
        if (not self.be_locked
                and self.hwm - self.entry_price >= BE_LOCK_PROFIT):
            base_stop = self.stop if self.stop is not None else self.entry_price
            self.stop = max(base_stop, self.entry_price + BE_LOCK_STOP)
            self.be_locked = True
        if (self.stop is not None
                and self.stop > self.entry_price
                and ltp <= self.stop):
            return round(self.stop, 2)
        return None


class OptionStateMachine:
    """Independent CE or PE state machine.

    Guarantees:
      * at most one open position for this option
      * at most one entry per 5-minute candle (duplicate-poll guard)
      * no entry whose candle would end after market close
      * LEGACY rows keep the trail/5% stop and entry-candle-close recovery
      * SL_TARGET_1_2 rows have a fixed initial stop and a 1:2 target only
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

        entry_price = round(float(ev.ltp), 2)
        initial_stop = initial_stop_for_entry(entry_price)
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
            entry_price=entry_price,
            sma9=round(float(ev.sma9), 2),
            prev_close=float(ev.prev_close),
            current_open=float(ev.current_open),
            condition_a=bool(ev.condition_a),
            condition_b=bool(ev.condition_b),
            ltp_at_entry=round(float(ev.ltp), 2),
            hwm=round(float(ev.ltp), 2),
            stop=None,
            be_locked=False,
            exit_policy=SL_TARGET_EXIT_POLICY,
            initial_stop=initial_stop,
            target_price=target_for_entry(entry_price, initial_stop),
        )
        self.position = pos
        self.entered_candles.add(ev.candle_start)
        return pos

    # -- exit ------------------------------------------------------------
    def update_trail(self, ltp: Optional[float]) -> Optional[float]:
        if self.position is None or self.position.exit_policy != LEGACY_EXIT_POLICY:
            return None
        return self.position.update_trail(ltp)

    def check_stop_loss(self, ltp: Optional[float]) -> Optional[float]:
        """Return the LEGACY 5% stop price when LTP has breached it."""
        pos = self.position
        if pos is None or ltp is None or pos.exit_policy != LEGACY_EXIT_POLICY:
            return None
        sl_price = round(pos.entry_price * (1.0 - STOP_LOSS_PCT), 2)
        if ltp <= sl_price:
            return sl_price
        return None

    def check_initial_stop(self, ltp: Optional[float]) -> Optional[float]:
        """Return the persisted initial stop when a new-policy LTP crosses it."""
        pos = self.position
        if (pos is None or ltp is None
                or pos.exit_policy != SL_TARGET_EXIT_POLICY
                or pos.initial_stop is None):
            return None
        stop = round(float(pos.initial_stop), 2)
        if float(ltp) <= stop:
            return stop
        return None

    def check_target(self, ltp: Optional[float]) -> Optional[float]:
        """Return the persisted 1:2 target when a new-policy LTP crosses it."""
        pos = self.position
        if (pos is None or ltp is None
                or pos.exit_policy != SL_TARGET_EXIT_POLICY
                or pos.target_price is None):
            return None
        target = round(float(pos.target_price), 2)
        if float(ltp) >= target:
            return target
        return None

    def needs_exit(self, now: datetime) -> bool:
        """Only LEGACY rows use entry-candle-close / restart recovery."""
        pos = self.position
        return (pos is not None and pos.exit_policy == LEGACY_EXIT_POLICY
                and now >= pos.entry_candle_end)

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
            "exit_policy": pos.exit_policy,
            "initial_stop": pos.initial_stop,
            "target_price": pos.target_price,
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
