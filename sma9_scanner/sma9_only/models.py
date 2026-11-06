#!/usr/bin/env python3
"""Data models for the SMA9 scanner - BUY ONLY."""

from dataclasses import dataclass
from typing import Any, Dict
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


@dataclass
class TradeRecord:
    signal_id: str
    scanner_id: str
    scanner_version: str
    strategy_type: str
    instrument: str
    timeframe: str
    signal_timestamp: str
    signal_direction: str
    signal_type: str
    signal_status: str
    entry_reference_price: Any
    actual_entry_price: Any
    stop_loss: Any
    target: Any
    current_price: Any
    exit_price: Any
    exit_time: Any
    exit_reason: Any
    net_points: Any
    points_gained_lost: Any
    candle_data: dict
    scanner_metadata: dict
    session_date: str
    created_at: str
    updated_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "scanner_id": self.scanner_id,
            "scanner_version": self.scanner_version,
            "strategy_type": self.strategy_type,
            "instrument": self.instrument,
            "timeframe": self.timeframe,
            "signal_timestamp": self.signal_timestamp,
            "signal_direction": self.signal_direction,
            "signal_type": self.signal_type,
            "signal_status": self.signal_status,
            "entry_reference_price": self.entry_reference_price,
            "actual_entry_price": self.actual_entry_price,
            "stop_loss": self.stop_loss,
            "target": self.target,
            "current_price": self.current_price,
            "exit_price": self.exit_price,
            "exit_time": self.exit_time,
            "exit_reason": self.exit_reason,
            "net_points": self.net_points,
            "points_gained_lost": self.points_gained_lost,
            "candle_data": self.candle_data,
            "scanner_metadata": self.scanner_metadata,
            "session_date": self.session_date,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
