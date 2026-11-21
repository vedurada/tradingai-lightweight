"""Drop-in KiteConnect facade.

Scanners keep doing ``from kiteconnect import KiteConnect``. This module routes
the five read-only calls they use through the broker gateway daemon, which owns
the broker credentials. No scanner code or broker order path is involved.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from broker_gateway.client import call
from broker_gateway.config import broker_for, scanner_name

_WRITE_PREFIXES = ("place_", "modify_", "cancel_", "order", "squareoff")


class KiteConnect:
    def __init__(self, api_key: str | None = None, **kwargs: Any):
        self.api_key = api_key
        self.access_token: str | None = None
        self.broker = broker_for(scanner_name())

    def set_access_token(self, access_token: str) -> None:
        """Accepted for API compatibility; the daemon owns real credentials."""
        self.access_token = access_token

    def _call(self, method: str, **params):
        return call(self.broker, method, **params)

    def instruments(self, exchange: str) -> list[dict]:
        rows = self._call("instruments", exchange=exchange) or []
        for row in rows:
            expiry = row.get("expiry")
            if isinstance(expiry, str):
                try:
                    row["expiry"] = dt.date.fromisoformat(expiry[:10])
                except ValueError:
                    row["expiry"] = None
            if row.get("instrument_token") is not None:
                row["instrument_token"] = int(row["instrument_token"])
            if row.get("strike") not in (None, ""):
                row["strike"] = float(row["strike"])
        return rows

    def quote(self, symbols) -> dict[str, dict]:
        if isinstance(symbols, str):
            symbols = [symbols]
        return self._call("quote", symbols=list(symbols)) or {}

    def historical_data(self, token, start, end, interval: str) -> list[dict]:
        return self._call(
            "historical_data",
            token=int(token),
            start=start.isoformat() if hasattr(start, "isoformat") else start,
            end=end.isoformat() if hasattr(end, "isoformat") else end,
            interval=interval,
        ) or []

    def profile(self) -> dict:
        return self._call("profile") or {}

    def __getattr__(self, name: str):
        if name.startswith(_WRITE_PREFIXES):
            def _blocked(*args, **kwargs):
                raise PermissionError(
                    f"broker gateway is read-only; {name} is not available"
                )
            return _blocked
        raise AttributeError(name)


class KiteException(Exception):
    """Compatibility exception type."""


def __dir__():
    return ["KiteConnect", "KiteException"]
