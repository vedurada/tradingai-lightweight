"""Drop-in KiteConnect facade.

Scanners keep doing ``from kiteconnect import KiteConnect``. This module routes
the five read-only calls they use through the broker gateway daemon, which owns
the broker credentials. No scanner code or broker order path is involved.
"""
from __future__ import annotations

import datetime as dt
import threading
from typing import Any

from broker_gateway.client import call
from broker_gateway.config import broker_for, scanner_name

_WRITE_PREFIXES = ("place_", "modify_", "cancel_", "order", "squareoff")
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


class KiteConnect:
    def __init__(self, api_key: str | None = None, **kwargs: Any):
        self.api_key = api_key
        self.access_token: str | None = None
        self.broker = broker_for(scanner_name())
        # Some brokers publish historical candles only after the session ends.
        # Keep today's quote samples so a 5m bar can still be derived from
        # fresh broker quotes while the market is open. Broker history always
        # wins; this is only a fallback, and every derived bar is labelled.
        self._quote_samples: dict[int, list[tuple[dt.datetime, float]]] = {}
        self._bar_lock = threading.Lock()
        self.bar_source = "broker_history"

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
        result = self._call("quote", symbols=list(symbols)) or {}
        now = dt.datetime.now(IST)
        with self._bar_lock:
            for item in result.values():
                if not isinstance(item, dict):
                    continue
                try:
                    token = int(item["instrument_token"])
                    price = float(item["last_price"])
                except (KeyError, TypeError, ValueError):
                    continue
                if not token or price <= 0:
                    continue
                samples = self._quote_samples.setdefault(token, [])
                samples.append((now, price))
                # Keep today only: older sessions come from broker history.
                self._quote_samples[token] = [
                    s for s in samples if s[0].date() == now.date()]
        return result

    @staticmethod
    def _parse_end(end) -> dt.datetime:
        value = end if isinstance(end, dt.datetime) else dt.datetime.fromisoformat(
            str(end))
        if value.tzinfo is None:
            value = value.replace(tzinfo=IST)
        return value.astimezone(IST)

    def _quote_derived_bars(self, token: int, end: dt.datetime) -> list[dict]:
        with self._bar_lock:
            samples = [
                s for s in self._quote_samples.get(int(token), [])
                if s[0].date() == end.date()
            ]
        buckets: dict[dt.datetime, list[float]] = {}
        for stamp, price in samples:
            start = stamp.replace(minute=(stamp.minute // 5) * 5,
                                  second=0, microsecond=0)
            buckets.setdefault(start, []).append(price)
        return [
            {
                "date": start.isoformat(),
                "open": prices[0],
                "high": max(prices),
                "low": min(prices),
                "close": prices[-1],
                "volume": 0,
                "source": "quote_derived",
            }
            for start, prices in sorted(buckets.items())
        ]

    def historical_data(self, token, start, end, interval: str) -> list[dict]:
        rows = self._call(
            "historical_data",
            token=int(token),
            start=start.isoformat() if hasattr(start, "isoformat") else start,
            end=end.isoformat() if hasattr(end, "isoformat") else end,
            interval=interval,
        ) or []
        self.bar_source = "broker_history"
        if interval != "5minute":
            return rows
        try:
            end_dt = self._parse_end(end)
        except (TypeError, ValueError):
            return rows
        derived = self._quote_derived_bars(int(token), end_dt)
        if not derived:
            return rows
        existing = {str(r.get("date"))[:16] for r in rows}
        added = [b for b in derived if b["date"][:16] not in existing]
        if not added:
            return rows
        self.bar_source = "quote_derived"
        return sorted(rows + added, key=lambda r: str(r.get("date")))

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
