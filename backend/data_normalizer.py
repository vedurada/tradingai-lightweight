from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

IST = timezone(timedelta(hours=5, minutes=30))


def to_ist(ts: Optional[str]) -> Optional[str]:
    """Normalize any timestamp string to IST ISO-8601.

    Handles:
    - UTC ISO with Z or +00:00
    - Naive 'YYYY-MM-DD HH:MM:SS' (assumed UTC wall-clock per existing convention)
    - Already IST ISO strings
    Returns None for empty/invalid input.
    """
    if not ts or not isinstance(ts, str):
        return None
    s = ts.strip()
    if not s:
        return None
    try:
        if "T" in s:
            if s.endswith("Z"):
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            elif "+" in s[10:] or (s.count("-") > 2 and len(s) > 20):
                dt = datetime.fromisoformat(s)
            else:
                dt = datetime.fromisoformat(s)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            ist_dt = dt.astimezone(IST)
            return ist_dt.isoformat()
        parts = s.split(" ")
        if len(parts) >= 2:
            dt = datetime.strptime(" ".join(parts[:2]), "%Y-%m-%d %H:%M:%S")
            dt_ist = dt.replace(tzinfo=IST)
            return dt_ist.isoformat()
        return None
    except Exception:
        return None


def to_utc(ts: Optional[str]) -> Optional[str]:
    """Convert any timestamp string to UTC ISO-8601.

    Inverse of to_ist for storage in DB (all writers store UTC).
    """
    if not ts or not isinstance(ts, str):
        return None
    s = ts.strip()
    if not s:
        return None
    try:
        if "+" in s or "Z" in s:
            if s.endswith("Z"):
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            else:
                dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            utc_dt = dt.astimezone(timezone.utc)
            return utc_dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")
        if "T" in s:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        return dt.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    except Exception:
        return None


def candle_timestamp_to_ist(ts: str) -> str:
    """Convert a DB candle timestamp (naive UTC wall-clock) to IST display string."""
    if not ts:
        return ""
    try:
        dt = datetime.strptime(str(ts).strip(), "%Y-%m-%d %H:%M:%S")
        dt_ist = dt.replace(tzinfo=IST)
        return dt_ist.isoformat()
    except Exception:
        try:
            if "T" in str(ts):
                dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(IST).isoformat()
        except Exception:
            pass
        return str(ts)


def is_within_market_hours(ts: Optional[str] = None) -> bool:
    """Check if an IST timestamp falls within Indian market hours (9:15 - 15:30)."""
    if ts is None:
        now = datetime.now(IST)
    else:
        ist = to_ist(ts)
        if not ist:
            return False
        try:
            now = datetime.fromisoformat(ist)
        except Exception:
            return False
    if now.weekday() >= 5:
        return False
    hour = now.hour
    minute = now.minute
    seconds = now.second
    total_minutes = hour * 60 + minute + seconds / 60
    return 9 * 60 + 15 <= total_minutes <= 15 * 60 + 30


def get_ist_now() -> datetime:
    """Return current time in IST."""
    return datetime.now(IST)


def now_ist_str() -> str:
    """Return current IST time as ISO string."""
    return get_ist_now().isoformat()
