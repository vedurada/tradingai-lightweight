#!/usr/bin/env python3
"""Exit rules for the SMA9 scanner - BUY ONLY.

Exit conditions:
- Same candle exit at CLOSE (5-minute candle)
- No overnight positions

Because entry and exit are both within the same candle, P&L is always
``CLOSE - OPEN`` for both CE and PE.  There is no short-side arithmetic.
"""

from typing import Any, Dict, Tuple


def check_same_candle_exit(candle_timestamp: str,
                           session_exit_time: str = "15:30") -> bool:
    """Return True when the candle is at/after the session exit time.

    The last tradable candle starts at 15:25 and closes at 15:30.  Since the
    strategy always exits at the entry candle's close, this helper only
    guards the end of the session.
    """
    if not candle_timestamp:
        return False
    try:
        time_part = candle_timestamp[11:16]  # HH:MM
        return time_part >= session_exit_time
    except (IndexError, TypeError):
        return False


def evaluate_exit(signal: Dict[str, Any], candle: Dict[str, Any]) -> Tuple[Any, Any]:
    """Evaluate the same-candle exit.

    Returns:
        (exit_price, exit_reason) or (None, None)
    """
    entry_px = signal.get("entry_reference_price")
    if entry_px is None:
        return None, None

    close_px = float(candle.get("close", 0))
    return close_px, "SAME_CANDLE_EXIT"


def compute_pnl(entry_px: float, exit_px: float,
                option_type: str = "CE") -> float:
    """Compute BUY-only P&L: ``exit - entry`` for both CE and PE."""
    return round(float(exit_px) - float(entry_px), 2)
