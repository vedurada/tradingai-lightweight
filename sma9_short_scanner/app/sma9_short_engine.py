#!/usr/bin/env python3
"""Pure SMA9 SHORT engine for NIFTY CE/PE option premiums.

This is a paper/shadow strategy only. It never places broker orders.

Per-option rules (CE and PE are independent):
  Contract:
    CE = nearest ATM strike + 200; PE = nearest ATM strike - 200.
  Entry:
    Paper SHORT at the sampled live premium LTP when LTP < SMA9, where SMA9 is
    the mean of the last 9 completed 5-minute premium closes. The forming bar
    is never used to calculate SMA9.
  Exit:
    ATR-only risk: ATR(14) of completed 5-minute option-premium candles.
    Distance = 0.70 x ATR, fixed at entry; no percentage floor, cap or fallback.
    Initial SHORT stop = round(entry + distance, 2).
    Track the lowest LTP seen since entry. Ratchet the stop down to
    round(lowest_ltp + distance, 2), never upward and never above the previous
    stop. A stop breach closes the short at the stop level.
    Any position still open at 15:20 IST is closed flat at the sampled LTP
    (or the 15:20 candle open on a late scan), reason EOD_15_20_FLAT.
    Entries are skipped when ATR(14) is unavailable.
  P&L:
    entry_price - exit_price (in premium points).

At most one open position per option; CE and PE may both be open.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, time as dtime, timedelta
from typing import Dict, List, Optional, Sequence

SMA_PERIOD = 9
CANDLE_MINUTES = 5
STRATEGY_ID = "sma9_short"
STRATEGY_VERSION = "2.0.0"
STRATEGY_TYPE = "SMA9_SHORT_ONLY"
ATR_PERIOD = 14
ATR_MULTIPLIER = 0.70
STOP_LOSS_REASON = "STOP_LOSS_ATR"
EOD_EXIT_TIME = dtime(15, 20)
EOD_EXIT_REASON = "EOD_15_20_FLAT"
STRIKE_OFFSETS = {"CE": 200.0, "PE": -200.0}


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


def premium_atr(candles: Sequence[dict],
                period: int = ATR_PERIOD) -> Optional[float]:
    """Mean true range over completed candles; the forming bar is excluded."""
    rows = normalize_candles(candles)
    completed = rows[:-1]
    if len(completed) < period + 1:
        return None
    window = completed[-(period + 1):]
    trs: List[float] = []
    for prev, cur in zip(window[:-1], window[1:]):
        trs.append(max(
            cur["high"] - cur["low"],
            abs(cur["high"] - prev["close"]),
            abs(cur["low"] - prev["close"]),
        ))
    return sum(trs) / len(trs) if trs else None


def eod_bar_open(candles: Sequence[dict], eod_start: datetime) -> Optional[float]:
    """Return the opening premium of the first candle at/after the EOD cutoff.

    Used when a scan runs after 15:20 and the exact cutoff quote was missed.
    The live sampled LTP remains the preferred fill when the scan is on time.
    """
    for row in normalize_candles(candles):
        if row["start"] >= eod_start:
            return round(float(row["open"]), 2)
    return None


def make_trade_id(instrument: str, strike: float, option_type: str,
                  entry_candle_start, prefix: str = "S9S-") -> str:
    ts = _as_dt(entry_candle_start).isoformat()
    raw = (f"SMA9_SHORT|{STRATEGY_ID}|{instrument}|{strike}|"
           f"{option_type}|{ts}")
    return prefix + hashlib.sha1(raw.encode()).hexdigest()[:12].upper()


@dataclass
class Evaluation:
    option_type: str
    candle_start: Optional[datetime] = None
    candle_end: Optional[datetime] = None
    sma9: Optional[float] = None
    atr: Optional[float] = None
    atr_distance: Optional[float] = None
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
            "atr": round(self.atr, 4) if self.atr is not None else None,
            "atr_distance": self.atr_distance,
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

    # Candle context only. The actual entry trigger is LTP < SMA9, exactly as
    # requested; the previous close / forming open are not entry gates.
    ev.condition_a = prev["close"] < sma
    ev.condition_b = forming["open"] < sma
    ev.confirmation = ltp is not None and ltp < sma
    ev.signal = bool(ev.confirmation)
    ev.qualified = bool(ev.signal)

    atr = premium_atr(rows)
    if atr is not None and atr > 0:
        ev.atr = round(atr, 4)
        ev.atr_distance = round(ATR_MULTIPLIER * atr, 2)

    if ltp is None:
        ev.reason = "no LTP: SHORT signal unavailable"
    elif ev.signal:
        ev.reason = f"SHORT signal: LTP {ltp:.2f} < SMA9 {sma:.2f}"
    else:
        ev.reason = f"no SHORT signal: LTP {ltp:.2f} >= SMA9 {sma:.2f}"

    if ev.signal and (ev.atr_distance is None or ev.atr_distance <= 0):
        ev.signal = False
        ev.qualified = False
        ev.reason = "no ATR(14): SHORT entry skipped until ATR is available"

    return ev


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
    lowest_ltp: float
    initial_stop: float
    stop: float
    atr_distance: Optional[float] = None

    def as_dict(self) -> dict:
        d = self.__dict__.copy()
        for k in ("entry_timestamp", "entry_candle_start", "entry_candle_end"):
            d[k] = d[k].isoformat()
        d["side"] = "SHORT"
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Position":
        data = dict(d)
        data.pop("side", None)
        for k in ("entry_timestamp", "entry_candle_start", "entry_candle_end"):
            data[k] = _as_dt(data[k])
        return cls(**data)

    def update_trail(self, ltp: Optional[float]) -> None:
        """Ratchet the stop down by the ATR distance frozen at entry."""
        if ltp is None:
            return
        price = float(ltp)
        if self.lowest_ltp is None or price < self.lowest_ltp:
            self.lowest_ltp = price
        distance = self.atr_distance
        if distance is None:
            # Back-compat for rows written before ATR distance was persisted.
            distance = round(self.initial_stop - self.entry_price, 2)
        candidate = round(float(self.lowest_ltp) + distance, 2)
        # Never loosen: initial stop is the ceiling and each new low can only
        # pull the stop lower.
        if candidate < self.stop:
            self.stop = candidate

    def trailing_active(self) -> bool:
        return self.stop < self.initial_stop

    def stop_is_hit(self, ltp: Optional[float]) -> bool:
        return ltp is not None and float(ltp) >= self.stop


class OptionStateMachine:
    """Independent CE or PE SHORT state machine."""

    def __init__(self, option_type: str):
        if option_type not in ("CE", "PE"):
            raise ValueError("option_type must be CE or PE")
        self.option_type = option_type
        self.position: Optional[Position] = None
        self.entered_candles: set = set()

    def try_entry(self, ev: Evaluation, now: datetime, strike: float,
                  expiry: str, token: Optional[int], tradingsymbol: str,
                  market_close: datetime) -> Optional[Position]:
        if self.position is not None:
            return None
        if not ev.signal or ev.ltp is None or ev.candle_start is None:
            return None
        if ev.atr_distance is None or ev.atr_distance <= 0:
            return None
        if ev.candle_start in self.entered_candles:
            return None
        if candle_end(ev.candle_start) > market_close:
            return None

        entry = round(float(ev.ltp), 2)
        distance = round(float(ev.atr_distance), 2)
        initial_stop = round(entry + distance, 2)
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
            entry_price=entry,
            sma9=round(float(ev.sma9), 2),
            prev_close=float(ev.prev_close),
            current_open=float(ev.current_open),
            condition_a=bool(ev.condition_a),
            condition_b=bool(ev.condition_b),
            ltp_at_entry=entry,
            lowest_ltp=entry,
            initial_stop=initial_stop,
            stop=initial_stop,
            atr_distance=distance,
        )
        self.position = pos
        self.entered_candles.add(ev.candle_start)
        return pos

    def update_trail(self, ltp: Optional[float]) -> None:
        if self.position is not None:
            self.position.update_trail(ltp)

    def check_stop_loss(self, ltp: Optional[float]) -> Optional[float]:
        pos = self.position
        if pos is None or not pos.stop_is_hit(ltp):
            return None
        return round(pos.stop, 2)

    def needs_exit(self, now: datetime,
                   eod_time: dtime = EOD_EXIT_TIME) -> bool:
        """True once the daily flat cutoff has passed."""
        return now.time() >= eod_time

    def close(self, exit_timestamp: datetime, exit_price: float,
              exit_reason: str = STOP_LOSS_REASON,
              candle_high: Optional[float] = None,
              candle_low: Optional[float] = None) -> Optional[dict]:
        pos = self.position
        if pos is None:
            return None
        exit_px = round(float(exit_price), 2)
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
            "entry_price": pos.entry_price,
            "exit_timestamp": exit_timestamp.isoformat(),
            "exit_price": exit_px,
            "exit_reason": exit_reason,
            "pnl_points": round(pos.entry_price - exit_px, 2),  # SHORT
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
            "lowest_ltp": pos.lowest_ltp,
            "initial_stop": pos.initial_stop,
            "atr_distance": pos.atr_distance,
            "final_stop": pos.stop,
            "entry_candle_start": pos.entry_candle_start.isoformat(),
            "entry_candle_end": pos.entry_candle_end.isoformat(),
        }
        self.position = None
        return trade

    def restore(self, position: Position) -> None:
        self.position = position
        self.entered_candles.add(position.entry_candle_start)
