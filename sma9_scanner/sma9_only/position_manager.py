#!/usr/bin/env python3
"""Position management for the SMA9 scanner - BUY ONLY.

All positions are closed within the entry candle, so there are no multi-bar
positions to manage.  CE and PE are independent long option positions; at
most one of each may be open, for a maximum of two.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

_IST = ZoneInfo("Asia/Kolkata")


class PositionManager:
    """Manages same-candle BUY positions for the SMA9 scanner."""

    def __init__(self, max_positions: int = 2):
        self.max_positions = max_positions
        self.positions: Dict[str, Any] = {}

    def can_open_position(self) -> bool:
        """True while fewer than ``max_positions`` long positions are open."""
        active_count = sum(
            1 for p in self.positions.values()
            if getattr(p, "signal_status", None) in ("PENDING_ENTRY", "ACTIVE")
        )
        return active_count < self.max_positions

    def add_position(self, signal: Any) -> bool:
        if not self.can_open_position():
            return False
        self.positions[signal.signal_id] = signal
        return True

    def get_position(self, signal_id: str) -> Optional[Any]:
        return self.positions.get(signal_id)

    def get_active_positions(self) -> List[Any]:
        return [
            p for p in self.positions.values()
            if getattr(p, "signal_status", None) in ("PENDING_ENTRY", "ACTIVE")
        ]

    def close_position(self, signal_id: str, exit_price: float,
                       exit_time: str, exit_reason: str,
                       net_points: float) -> bool:
        position = self.positions.get(signal_id)
        if position is None:
            return False

        position.exit_price = exit_price
        position.exit_time = exit_time
        position.signal_status = "CLOSED"
        position.net_points = net_points
        position.points_gained_lost = net_points
        position.updated_at = datetime.now(_IST).isoformat()
        return True
