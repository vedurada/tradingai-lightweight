#!/usr/bin/env python3
"""SMA9 Scanner - ATM Option Strike (CE/PE) - 5 Minute Timeframe - BUY ONLY.

Both ATM CE and ATM PE use the same long-only rule set:

Qualification at a 5-minute candle boundary (per option, from its own candles):
  A) previous completed candle CLOSE > SMA9 of the 9 completed candles
     ending at that previous candle
  OR
  B) current forming candle OPEN > the same SMA9

Execution confirmation:
  live option LTP > the same SMA9

Entry: paper BUY immediately when qualified and confirmed.
Exit:  at the CLOSE of the entry 5-minute candle (no carry forward).

SMA9 is always computed from completed candles only; the current candle's
close is never used, so no future data can leak into a decision.  There is
no CE-bullish / PE-bearish split and no short option leg.

This module is a signal-only / shadow implementation.  It never sends broker
orders.  The production paper trader is sma9_scanner/app/live_sma9_scanner.py.
"""

import hashlib
from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

try:  # package import
    from .config import (
        STRATEGY_ID, STRATEGY_NAME, STRATEGY_VERSION, STRATEGY_TYPE,
        INSTRUMENT, TIMEFRAME, MARKET_SESSION, SMA_PERIOD, ATM_STRIKE,
        MAX_POSITIONS,
    )
except ImportError:  # direct/standalone import
    from config import (  # type: ignore
        STRATEGY_ID, STRATEGY_NAME, STRATEGY_VERSION, STRATEGY_TYPE,
        INSTRUMENT, TIMEFRAME, MARKET_SESSION, SMA_PERIOD, ATM_STRIKE,
        MAX_POSITIONS,
    )

_IST = ZoneInfo("Asia/Kolkata")


# ---------------------------------------------------------------------------
# Helper data containers
# ---------------------------------------------------------------------------
class ScannerInfo:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class Signal:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
        self.timestamp = datetime.now(_IST).isoformat()


class MarketData:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class ScanResult:
    """Result of one scan pass."""

    def __init__(self, scanner_id: str = STRATEGY_ID,
                 scanner_version: str = STRATEGY_VERSION,
                 timestamp: Optional[str] = None,
                 market_state: str = "UNKNOWN",
                 data_fresh: bool = True):
        self.scanner_id = scanner_id
        self.scanner_version = scanner_version
        self.timestamp = timestamp or datetime.now(_IST).isoformat()
        self.market_state = market_state
        self.data_fresh = data_fresh
        self.signals: List[Dict[str, Any]] = []
        self.errors: List[str] = []


# ---------------------------------------------------------------------------
# SMA helpers
# ---------------------------------------------------------------------------
def make_sma9_signal_id(instrument: str, strike: int, option_type: str,
                        candle_ts: str) -> str:
    raw = f"SMA9|{STRATEGY_ID}|{instrument}|{strike}|{option_type}|{candle_ts}"
    return "S9-" + hashlib.sha1(raw.encode()).hexdigest()[:12].upper()


def compute_sma9(prices: List[float], idx: int,
                 period: int = SMA_PERIOD) -> Optional[float]:
    """SMA through ``idx`` (inclusive).

    Kept for backward compatibility.  Do NOT use this for an entry decision:
    at index ``idx`` it includes the entry candle's own close, which is
    look-ahead.  Use :func:`compute_previous_sma9` instead.
    """
    if idx < period - 1:
        return None
    window = prices[idx - period + 1:idx + 1]
    if len(window) < period:
        return None
    return sum(window) / len(window)


def compute_previous_sma9(closes: List[float], idx: int,
                          period: int = SMA_PERIOD) -> Optional[float]:
    """SMA of the ``period`` completed candles ending at ``idx - 1``.

    This is the only SMA that is actually available at the open of candle
    ``idx``.  It excludes the entry candle entirely.
    """
    if idx < period:
        return None
    window = closes[idx - period:idx]
    if len(window) < period:
        return None
    return sum(window) / len(window)


# ---------------------------------------------------------------------------
# Signal construction
# ---------------------------------------------------------------------------
def build_sma9_signal(signal_id: str, instrument: str, strike: int,
                      option_type: str, candle_ts: str,
                      open_px: float, high: float, low: float,
                      close: float, sma9: float,
                      prev_close: Optional[float] = None
                      ) -> Optional[Dict[str, Any]]:
    """Build one BUY-only trade from a candle.

    ``sma9`` must be computed from completed candles only (see
    :func:`compute_previous_sma9`).

    Qualification is ``prev_close > sma9`` OR ``open_px > sma9``.  The
    historical confirmation proxy is ``open_px > sma9`` because OHLC data
    has no intra-candle ticks; the live scanner uses the real LTP instead.
    Entry is the candle open and exit is the same candle's close, so P&L is
    always ``close - open`` for both CE and PE.
    """
    if option_type not in ("CE", "PE"):
        return None

    entry = float(open_px)
    exit_px = float(close)

    condition_a = bool(prev_close is not None and float(prev_close) > sma9)
    condition_b = bool(entry > sma9)
    qualified = condition_a or condition_b
    confirmation = entry > sma9  # OHLC proxy for LTP > SMA9
    if not (qualified and confirmation):
        return None

    # BUY-only: identical direction and arithmetic for CE and PE.
    signal_direction = "BUY"
    signal_type = "SMA9_BUY"
    pnl = round(exit_px - entry, 2)

    return {
        "signal_id": signal_id,
        "scanner_id": STRATEGY_ID,
        "scanner_version": STRATEGY_VERSION,
        "strategy_type": STRATEGY_TYPE,
        "instrument": instrument,
        "timeframe": TIMEFRAME,
        "signal_timestamp": candle_ts,
        "signal_direction": signal_direction,
        "signal_type": signal_type,
        "signal_status": "CLOSED",
        "entry_reference_price": round(entry, 2),
        "actual_entry_price": round(entry, 2),
        # Long option: stop is below entry, target is above entry.
        "stop_loss": round(low, 2),
        "target": round(high, 2),
        "current_price": round(exit_px, 2),
        "exit_price": round(exit_px, 2),
        "exit_time": candle_ts,
        "exit_reason": "SAME_CANDLE_EXIT",
        "net_points": pnl,
        "points_gained_lost": pnl,
        "candle_data": {
            "open": open_px, "high": high, "low": low, "close": close,
            "sma9": round(sma9, 2)
        },
        "scanner_metadata": {
            "strike": strike,
            "option_type": option_type,
            "sma9": round(sma9, 2),
            "prev_close": prev_close,
            "condition_a": condition_a,
            "condition_b": condition_b,
            "qualified": qualified,
            "confirmation": confirmation,
            "sma_period": SMA_PERIOD,
            "same_candle_exit": True,
            "buy_only": True,
        },
        "session_date": candle_ts[:10],
        "created_at": datetime.now(_IST).isoformat(),
        "updated_at": datetime.now(_IST).isoformat(),
    }


def compute_sma9_signals(candles: List[Dict[str, Any]],
                         strike: int, option_type: str
                         ) -> List[Dict[str, Any]]:
    """Generate BUY-only signals for one option contract.

    Requires 9 completed candles before the entry candle, so the first
    possible entry is at index ``SMA_PERIOD`` (the 10th candle).  SMA9 for
    candle ``i`` uses closes ``i-9 .. i-1`` only.
    """
    if option_type not in ("CE", "PE"):
        return []
    if len(candles) < SMA_PERIOD + 1:
        return []

    signals: List[Dict[str, Any]] = []
    closes = [float(r["close"]) for r in candles]

    for i in range(SMA_PERIOD, len(candles)):
        row = candles[i]
        sma9 = compute_previous_sma9(closes, i)
        if sma9 is None:
            continue

        signal = build_sma9_signal(
            signal_id=make_sma9_signal_id(
                row.get("instrument_id", INSTRUMENT), strike, option_type,
                row["timestamp"]
            ),
            instrument=row.get("instrument_id", INSTRUMENT),
            strike=strike,
            option_type=option_type,
            candle_ts=row["timestamp"],
            open_px=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            sma9=sma9,
            prev_close=closes[i - 1],
        )
        if signal is not None:
            signals.append(signal)

    return signals


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------
class Sma9Scanner:
    """SMA9 Only Scanner - ATM Option Strike - BUY ONLY.

    CE and PE are evaluated with the same long-only rule.  Each is an
    independent option contract with its own candles and SMA9.
    """

    def __init__(self):
        self._initialized = False
        self._trades: List[Dict[str, Any]] = []
        self._signal_count = 0

    @property
    def info(self) -> ScannerInfo:
        return ScannerInfo(
            scanner_id=STRATEGY_ID,
            scanner_name=STRATEGY_NAME,
            scanner_version=STRATEGY_VERSION,
            strategy_type=STRATEGY_TYPE,
            instrument=INSTRUMENT,
            timeframe=TIMEFRAME,
            market_session=MARKET_SESSION,
            description=(
                "SMA9 Only - ATM Option Strike - BUY ONLY. Entry for CE and PE "
                "when previous completed close > SMA9 OR current open > SMA9, "
                "confirmed by LTP > SMA9. Same-candle exit at CLOSE."
            ),
        )

    def initialize(self) -> bool:
        self._trades = []
        self._signal_count = 0
        self._initialized = True
        return True

    def validate_configuration(self) -> Dict[str, Any]:
        errors = []
        if SMA_PERIOD <= 0:
            errors.append("SMA_PERIOD must be positive")
        if MAX_POSITIONS <= 0:
            errors.append("MAX_POSITIONS must be positive")
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "scanner_id": STRATEGY_ID,
            "scanner_version": STRATEGY_VERSION,
        }

    def scan_market(self, market_data: List[MarketData]) -> ScanResult:
        result = ScanResult()

        if len(market_data) < SMA_PERIOD + 1:
            result.errors.append(
                "Insufficient candles for SMA9 entry (need 9 completed + 1)"
            )
            return result

        candle_dicts = []
        for c in market_data:
            candle_dicts.append({
                "timestamp": c.timestamp,
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
            })

        ce_signals = compute_sma9_signals(candle_dicts, ATM_STRIKE, "CE")
        pe_signals = compute_sma9_signals(candle_dicts, ATM_STRIKE, "PE")

        all_signals = ce_signals + pe_signals
        all_signals.sort(key=lambda s: s["signal_timestamp"])

        for sig in all_signals:
            result.signals.append(sig)
            self._trades.append(sig)
            self._signal_count += 1

        # BUY-only: there is no bullish/bearish regime call.
        result.market_state = "SIGNALS" if all_signals else "NEUTRAL"
        return result

    def generate_signal(self, candle_data: Dict[str, Any]) -> Optional[Signal]:
        return None

    def validate_signal(self, signal: Signal) -> bool:
        return True

    def get_status(self) -> Dict[str, Any]:
        return {
            "strategy_id": STRATEGY_ID,
            "scanner_name": STRATEGY_NAME,
            "scanner_version": STRATEGY_VERSION,
            "strategy_type": STRATEGY_TYPE,
            "instrument": INSTRUMENT,
            "timeframe": TIMEFRAME,
            "initialized": self._initialized,
            "active_signals": len(self._trades),
            "total_signals": self._signal_count,
        }

    def shutdown(self) -> bool:
        self._trades = []
        self._initialized = False
        return True

    def monitor_exits(self, active_signals: List[Signal],
                      market_data: List[MarketData]) -> List[Signal]:
        return active_signals


# Backward-compatible alias: older code imported this name.
ReverseShortScanner = Sma9Scanner
