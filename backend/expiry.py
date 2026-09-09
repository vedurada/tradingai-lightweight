from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional


def get_current_expiry() -> dict[str, any]:
    now = datetime.now(timezone.utc)
    ist = now.astimezone(timezone(timedelta(hours=5, minutes=30)))
    today = ist.date()
    # Find next Thursday
    days_ahead = 3 - ist.weekday()
    if days_ahead < 0:
        days_ahead += 7
    if days_ahead == 0 and ist.hour >= 15:
        days_ahead = 7
    expiry_date = today + timedelta(days=days_ahead)
    days_to_expiry = (expiry_date - today).days
    return {
        "expiry_date": expiry_date.isoformat(),
        "expiry_label": expiry_date.strftime("%d %b %Y"),
        "days_to_expiry": days_to_expiry,
        "expiry_day": "Thursday",
        "timestamp": now.isoformat(),
    }