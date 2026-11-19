#!/usr/bin/env python3
"""SMA9 strategy engine, polled once per minute, with an ATR-scaled stop
and an ATR-scaled trailing stop.

BUY-ONLY rules (identical to the SMA9 scanner):
  Entry at a 5-minute candle boundary:
    A) previous completed candle CLOSE > SMA9
    AND
    B) current (forming) candle OPEN > SMA9
  Entry: paper BUY at the live LTP on the first 1-minute poll that sees A and B

Exit (identical for CE and PE):
  1) INITIAL STOP: live LTP <= entry - stop_distance
     stop_distance = clamp(k * ATR(14) of the option premium,
                           floor% of entry, cap% of entry)
     -> exit at the ACTUAL live LTP (never at the theoretical stop price)
  2) TRAIL: +5 activates breakeven, then the stop ratchets at
     peak - trail_distance, where trail_distance is the same ATR-scaled
     distance computed at entry; +6 locks entry + 2.
     Only a stop strictly above entry can trigger a trail exit.
  3) otherwise hold (no time-based exit)

The ATR distance is computed once at entry from completed candles only, so the
trail width cannot drift with intraday volatility and no future data can leak
into a decision.  No broker / database / network dependencies.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence

SMA_PERIOD = 9
CANDLE_MINUTES = 5
STRATEGY_ID = "sma9_1min_atr"
STRATEGY_VERSION = "1.0.0"
STRATEGY_TYPE = "SMA9_1MIN_ATR_STOP_BUY_ONLY"

# Initial-stop model.
ATR_PERIOD = 14
STOP_K = 0.70          # stop distance = 0.70 * premium ATR(14)
STOP_FLOOR_PCT = 0.05  # never tighter than 5% of premium (old behaviour)
STOP_CAP_PCT = 0.30    # never wider than 30% of premium (risk guard)
STOP_FALLBACK_PCT = 0.10  # used only when ATR cannot be computed

# Trailing stop: same +5 / +6 shape as the other scanners, but the ratchet
# distance is the ATR-scaled distance computed at entry.
TRAIL = 5.0            # fallback distance when the ATR distance is missing
ACTIVATE = 5.0
BE_LOCK_PROFIT = 6.0
BE_LOCK_STOP = 2.0


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
                  entry_candle_start, prefix: str = "S1A-") -> str:
    ts = _as_dt(entry_candle_start).isoformat()
    raw = f"SMA9ATR|{STRATEGY_ID}|{instrument}|{strike}|{option_type}|{ts}"
    return prefix + hashlib.sha1(raw.encode()).hexdigest()[:12].upper()


# ---------------------------------------------------------------------------
# Volatility (premium ATR)
# ---------------------------------------------------------------------------
def premium_atr(candles: Sequence[dict], period: int = ATR_PERIOD) -> Optional[float]:
    """Simple-mean True Range of the option premium over completed candles.

    The last row (the forming candle) is excluded so the value is known at
    entry time.  Returns None when there is not enough history.
    """
    rows = normalize_candles(candles)
    completed = rows[:-1]
    if len(completed) < period + 1:
        return None
    window = completed[-(period + 1):]
    trs: List[float] = []
    for prev, cur in zip(window[:-1], window[1:]):
        tr = max(cur["high"] - cur["low"],
                 abs(cur["high"] - prev["close"]),
                 abs(cur["low"] - prev["close"]))
        trs.append(tr)
    if not trs:
        return None
    return sum(trs) / len(trs)


def compute_stop(entry_price: float, atr: Optional[float]) -> tuple:
    """Return (stop_price, distance, distance_pct, source)."""
    entry = float(entry_price)
    if atr is not None and atr > 0:
        distance = STOP_K * float(atr)
        distance = max(distance, entry * STOP_FLOOR_PCT)
        distance = min(distance, entry * STOP_CAP_PCT)
        source = "atr"
    else:
        distance = entry * STOP_FALLBACK_PCT
        source = "fallback_pct"
    stop_price = round(entry - distance, 2)
    distance_pct = round(distance / entry, 4) if entry else 0.0
    return stop_price, round(distance, 4), distance_pct, source


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
    atr_at_entry: Optional[float] = None
    stop_price: Optional[float] = None
    stop_k: Optional[float] = None
    stop_distance_pct: Optional[float] = None
    stop_source: Optional[str] = None
    trail_distance: Optional[float] = None
    hwm: float = 0.0
    stop: Optional[float] = None
    be_locked: bool = False

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

    def update_trail(self, ltp: Optional[float]) -> Optional[float]:
        """Update high-water mark and return a trail-stop exit price.

        Trail activates once the peak is `ACTIVATE` above entry (stop ->
        breakeven), then ratchets at peak - trail_distance.  trail_distance is
        the ATR-scaled distance fixed at entry (TRAIL only if it is missing).
        One-time breakeven lock at +BE_LOCK_PROFIT moves the stop to
        entry + BE_LOCK_STOP.  Only a strictly profitable stop (stop > entry)
        may trigger an exit; otherwise hold.
        """
        if ltp is None:
            return None
        if ltp > self.hwm:
            self.hwm = ltp
        distance = self.trail_distance if self.trail_distance else TRAIL
        if self.hwm - self.entry_price >= ACTIVATE:
            # Apply activation and the ratchet in the same poll: with a
            # 60-second sample a single tick can jump straight past +ACTIVATE,
            # and holding at breakeven until the next minute would widen the
            # trail far beyond the ATR distance.
            candidate = self.hwm - distance
            if self.stop is None:
                self.stop = max(self.entry_price, candidate)
            else:
                self.stop = max(self.stop, candidate)
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
      * ATR-scaled initial stop checked on every poll, filled at live LTP
      * trailing stop after +ACTIVATE, breakeven lock after +BE_LOCK_PROFIT
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
                  market_close: datetime,
                  atr: Optional[float] = None) -> Optional[Position]:
        if self.position is not None:
            return None
        if not ev.signal or ev.ltp is None or ev.candle_start is None:
            return None
        if ev.candle_start in self.entered_candles:
            return None
        if candle_end(ev.candle_start) > market_close:
            return None

        entry_price = round(float(ev.ltp), 2)
        stop_price, dist, dist_pct, source = compute_stop(entry_price, atr)

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
            ltp_at_entry=entry_price,
            atr_at_entry=round(float(atr), 4) if atr is not None else None,
            stop_price=stop_price,
            stop_k=STOP_K if source == "atr" else 0.0,
            stop_distance_pct=dist_pct,
            stop_source=source,
            trail_distance=round(float(dist), 4),
            hwm=entry_price,
            stop=None,
            be_locked=False,
        )
        self.position = pos
        self.entered_candles.add(ev.candle_start)
        return pos

    # -- exit ------------------------------------------------------------
    def update_trail(self, ltp: Optional[float]) -> Optional[float]:
        if self.position is None:
            return None
        return self.position.update_trail(ltp)

    def check_stop_loss(self, ltp: Optional[float]) -> Optional[float]:
        """Return the ACTUAL exit price when LTP has breached the ATR stop.

        The fill is the live LTP, not the theoretical stop price: a fast move
        can trade through the stop, and paper fills must reflect that.
        """
        pos = self.position
        if pos is None or ltp is None:
            return None
        stop_price = pos.stop_price
        if stop_price is None:
            stop_price = compute_stop(pos.entry_price, pos.atr_at_entry)[0]
            pos.stop_price = stop_price
        if ltp <= stop_price:
            return round(float(ltp), 2)
        return None

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
            "atr_at_entry": pos.atr_at_entry,
            "stop_price": pos.stop_price,
            "stop_k": pos.stop_k,
            "stop_distance_pct": pos.stop_distance_pct,
            "stop_source": pos.stop_source,
        }
        self.position = None
        return trade

    def restore(self, position: Position) -> None:
        self.position = position
        self.entered_candles.add(position.entry_candle_start)
