"""Broker adapter contract.

The scanner surface is read-only by design. Order methods are *optional* and
only implemented by adapters explicitly enabled for the isolated live service;
the Kite-compatible shim still blocks every write-prefix method.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from broker_gateway.errors import BrokerGatewayError


class BrokerAdapter(ABC):
    """Minimal read-only surface required by the scanners.

    Paper trading remains simulated inside each scanner's own database. The
    optional order methods below are reachable only through the daemon's
    gated order allowlist, never through the Kite compatibility shim.
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

    def credential_signature(self):
        """Identify the current on-disk credential state, or None."""
        return None

    def refresh_credentials_if_changed(self) -> None:
        """Adopt credentials written by a refresh tool. No-op by default."""
        return None

    def validate_credentials(self) -> None:
        """Raise if the current token is unusable. No-op by default."""
        return None

    def place_order(self, **params) -> dict:
        """Optional live order entry. Refused unless explicitly implemented."""
        raise BrokerGatewayError(f"{self.name}: order placement is not available")

    def order_status(self, **params) -> dict:
        """Optional live order status lookup."""
        raise BrokerGatewayError(f"{self.name}: order status is not available")

    def order_by_tag(self, **params) -> dict:
        """Optional read-only order-book lookup by our client tag."""
        raise BrokerGatewayError(f"{self.name}: order lookup by tag is not available")
