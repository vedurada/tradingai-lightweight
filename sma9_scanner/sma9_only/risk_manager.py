#!/usr/bin/env python3
"""Risk management for the SMA9 scanner - BUY ONLY.

All trades are long option BUYs.  For a long position the protective level
is the entry candle's low (below entry) and the reference target is the
entry candle's high (above entry).  There is no short-side branch.
"""

from typing import Any, Dict


class RiskManager:
    """Risk management for same-candle BUY option trades."""

    def __init__(self):
        pass

    def calculate_stop_loss(self, entry_price: float,
                            direction: str = "BUY",
                            candle_high: float = None,
                            candle_low: float = None) -> float:
        """Return the candle low for a long option BUY."""
        if candle_low is not None:
            return round(candle_low, 2)
        return entry_price

    def calculate_risk_points(self, entry_price: float,
                              stop_loss: float,
                              direction: str = "BUY") -> float:
        """Risk for a long position: entry - stop (never negative)."""
        return round(max(0.0, entry_price - stop_loss), 2)

    def calculate_reward_points(self, entry_price: float,
                                target: float,
                                direction: str = "BUY") -> float:
        """Reward for a long position: target - entry (never negative)."""
        return round(max(0.0, target - entry_price), 2)

    def calculate_risk_reward(self, risk_points: float,
                              reward_points: float) -> float:
        if risk_points <= 0:
            return 0.0
        return round(reward_points / risk_points, 3)

    def validate_signal(self, signal: Dict[str, Any]) -> bool:
        """Validate that the signal has valid long-side risk parameters."""
        if signal.get("signal_status") == "INVALID_TARGET":
            return False
        if signal.get("entry_reference_price") is None:
            return False
        if signal.get("stop_loss") is None:
            return False
        if signal.get("target") is None:
            return False
        return True

    def is_stop_loss_fixed(self, signal: Dict[str, Any]) -> bool:
        """The stop is the candle low, not a fixed offset."""
        return True
