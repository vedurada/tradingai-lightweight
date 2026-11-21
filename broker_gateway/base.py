"""Broker adapter contract. Read-only by design."""
from __future__ import annotations

from abc import ABC, abstractmethod


class BrokerAdapter(ABC):
    """Minimal read-only surface required by the scanners.

    Deliberately excludes place_order/modify_order/cancel_order. Paper trading
    remains simulated inside each scanner's own database.
    """

    name = "base"

    @abstractmethod
    def instruments(self, exchange: str) -> list[dict]:
        """Return Kite-shaped instrument rows for an exchange."""

    @abstractmethod
    def quote(self, symbols: list[str]) -> dict[str, dict]:
        """Return Kite-shaped quote map keyed by exchange:symbol."""

    @abstractmethod
    def historical_data(self, token: int, start, end, interval: str) -> list[dict]:
        """Return OHLC rows with a ``date`` field."""

    def profile(self) -> dict:
        """Optional connectivity check."""
        return {"broker": self.name}
