#!/usr/bin/env python3
"""Entry rules for the SMA9 scanner - BUY ONLY.

Rules (identical for CE and PE):
  A) previous completed candle CLOSE > SMA9
     OR
  B) current forming candle OPEN > SMA9
  Confirmation: live LTP > SMA9

SMA9 is computed from the 9 completed candles ending at the previous candle,
never from the current candle's close.  Entry is at the signal candle's own
open.  There is no PE-short / bearish branch.
"""

from typing import Any, Dict, List, Optional, Tuple


def detect_sma9_signal(candles: List[Dict[str, Any]], idx: int,
                       sma_period: int = 9) -> Optional[float]:
    """Return the SMA9 available at the open of candle ``idx``.

    Uses the ``sma_period`` completed candles ending at ``idx - 1``.  The
    entry candle at ``idx`` is excluded, so there is no look-ahead.
    """
    if idx < sma_period:
        return None
    window = [float(c["close"]) for c in candles[idx - sma_period:idx]]
    if len(window) < sma_period:
        return None
    return sum(window) / len(window)


def check_entry_eligibility(open_px: float, sma9: float,
                            option_type: str,
                            prev_close: Optional[float] = None) -> Tuple[bool, str]:
    """Check BUY-only entry eligibility for CE or PE.

    Qualification: ``prev_close > sma9`` OR ``open_px > sma9``.
    Confirmation (historical proxy): ``open_px > sma9``.

    Returns:
        (eligible: bool, reason: str)
    """
    if option_type not in ("CE", "PE"):
        return False, "INVALID_OPTION_TYPE"

    condition_a = prev_close is not None and float(prev_close) > sma9
    condition_b = float(open_px) > sma9
    qualified = condition_a or condition_b
    confirmation = condition_b  # LTP proxy for OHLC-only history

    if not qualified:
        return False, "NOT_QUALIFIED"
    if not confirmation:
        return False, "CONFIRMATION_BELOW_SMA9"
    return True, "OK"


def compute_entry_price(candle: Dict[str, Any]) -> Optional[float]:
    """Entry is at the signal candle's own open."""
    try:
        return float(candle["open"])
    except (TypeError, ValueError, KeyError):
        return None
