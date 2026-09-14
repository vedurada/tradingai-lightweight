"""B.3 Failure Recovery — Data quality constants and helpers."""

DATA_QUALITY_LIVE = "LIVE"
DATA_QUALITY_STALE = "STALE"
DATA_QUALITY_UNAVAILABLE = "DATA UNAVAILABLE"
DATA_QUALITY_PARTIAL = "PARTIAL"

SOURCE_FRESHNESS_THRESHOLS = {
    "price_1m": 5,
    "price_1d": 60,
    "vix_data": 60,
    "live_quotes": 5,
    "option_chain": 60,
    "option_expiries": 60,
    "market_outlooks": 1440,
    "indicators": 60,
    "regimes": 1440,
    "strategies": 1440,
    "scenarios": 1440,
    "outlooks": 1440,
    "pcr": 60,
    "maxpain": 60,
    "oi_top": 60,
    "oi_concentration": 60,
    "expected_move": 60,
    "options_intelligence": 60,
    "snapshots": 60,
    "breadth": 60,
    "history": 60,
    "alerts": 60,
    "data_status": 60,
    "nifty_price": 5,
}

DATA_FRESHNESS_THRESHOLDS = {
    "price_1m": {"stale": 5, "unavailable": 30},
    "vix_data": {"stale": 60, "unavailable": 120},
    "option_chain": {"stale": 60, "unavailable": 240},
    "market_outlooks": {"stale": 1440, "unavailable": 4320},
    "indicators": {"stale": 60, "unavailable": 180},
    "live_quotes": {"stale": 5, "unavailable": 15},
}


def data_age_minutes(timestamp):
    if not timestamp:
        return None
    from datetime import datetime, timezone
    if isinstance(timestamp, str):
        ts = timestamp
    else:
        ts = str(timestamp)
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return (now - dt).total_seconds() / 60
    except Exception:
        try:
            dt = datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")
            return (datetime.now(timezone.utc) - dt.replace(tzinfo=timezone.utc)).total_seconds() / 60
        except Exception:
            return None
