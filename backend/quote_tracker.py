"""Quote Telemetry - tracks price data cadence and freshness.

Records every quote received with:
- quote_received_at: when we received it
- source_timestamp: what the source says the timestamp is
- previous_price: last received price
- current_price: current price
- price_change: difference from previous
- update_interval_ms: time since last quote
- quote_age_ms: age of source data
- source: where the data came from
"""
import time
from typing import Any, Dict, List, Optional


class QuoteTracker:
    """Tracks price quotes and produces telemetry.

    Records every quote. Computes per-quote metadata.
    Produces aggregate statistics on quote cadence.
    """

    def __init__(self, symbol: str):
        self.symbol = symbol
        self.quotes: List[Dict[str, Any]] = []
        self._last_price: Optional[float] = None
        self._last_received_at: Optional[float] = None

    def receive(self, price: float, source_timestamp: Optional[str] = None,
                source: str = "unknown") -> Dict[str, Any]:
        """Record a new quote and return telemetry for this quote."""
        now = time.time()
        previous_price = self._last_price
        price_change = None
        if previous_price is not None:
            price_change = round(price - previous_price, 2)

        update_interval = None
        if self._last_received_at is not None:
            update_interval = round((now - self._last_received_at) * 1000, 1)

        quote_age = None
        if source_timestamp:
            try:
                from datetime import datetime, timezone as _tz
                source_dt = datetime.fromisoformat(str(source_timestamp).replace("Z", "+00:00"))
                quote_age = round((now - source_dt.timestamp()) * 1000, 1)
            except Exception:
                pass

        quote: Dict[str, Any] = {
            "symbol": self.symbol,
            "quote_received_at": now,
            "source_timestamp": source_timestamp,
            "previous_price": previous_price,
            "current_price": price,
            "price_change": price_change,
            "update_interval_ms": update_interval,
            "quote_age_ms": quote_age,
            "source": source,
        }
        self.quotes.append(quote)
        self._last_price = price
        self._last_received_at = now
        return quote

    def get_telemetry(self) -> Dict[str, Any]:
        """Return aggregate telemetry about quote cadence."""
        if not self.quotes:
            return {"symbol": self.symbol, "status": "NO_QUOTES"}

        intervals = [q["update_interval_ms"] for q in self.quotes if q["update_interval_ms"] is not None]
        ages = [q["quote_age_ms"] for q in self.quotes if q["quote_age_ms"] is not None]

        return {
            "symbol": self.symbol,
            "status": "LIVE",
            "total_quotes": len(self.quotes),
            "current_price": self._last_price,
            "last_quote_received": self.quotes[-1]["quote_received_at"],
            "quote_intervals": {
                "avg_ms": round(sum(intervals) / len(intervals), 1) if intervals else None,
                "median_ms": sorted(intervals)[len(intervals) // 2] if intervals else None,
                "min_ms": min(intervals) if intervals else None,
                "max_ms": max(intervals) if intervals else None,
            },
            "quote_ages": {
                "avg_ms": round(sum(ages) / len(ages), 1) if ages else None,
                "max_ms": max(ages) if ages else None,
            },
            "last_update_interval_ms": self.quotes[-1].get("update_interval_ms"),
            "last_quote_age_ms": self.quotes[-1].get("quote_age_ms"),
            "source": self.quotes[-1].get("source", "unknown"),
        }
