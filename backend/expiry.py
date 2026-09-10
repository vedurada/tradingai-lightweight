from __future__ import annotations

"""Index expiry calendar for TradingAI.in.

Rules (SEBI rationalisation, effective 1 Sep 2025; verified Sep 2026):
- NSE derivatives expire on TUESDAY, BSE derivatives on THURSDAY.
- Weekly options exist only for NIFTY 50 (NSE, Tuesday) and SENSEX (BSE, Thursday).
- BANKNIFTY / FINNIFTY are monthly-only: last Tuesday of the month.
- Monthly NIFTY: last Tuesday; monthly SENSEX: last Thursday.
- If an expiry day is a trading holiday, expiry moves to the previous trading day
  (approximated here by weekday roll-forward; known NSE/BSE holidays can be
  added to HOLIDAYS_IST below).

Reference: NSE circular NSE/FAOP/68747, SEBI circular 26 May 2025.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Optional

IST = timezone(timedelta(hours=5, minutes=30))

# NSE/BSE trading holidays (YYYY-MM-DD). Extend each January from the
# official NSE/BSE circulars. Expiry shifts to the previous trading day.
HOLIDAYS_IST = frozenset({
    # 2026 weekday holidays affecting Tue/Thu expiries (Mon-Fri only matter here).
    "2026-03-03",  # Holi (Tue)
    "2026-03-26",  # Mahavir Jayanti (Thu)
    "2026-05-26",  # Bakri Id (Tue)
    "2026-11-24",  # Guru Nanak Jayanti (Tue)
    "2026-12-24",  # Christmas Eve observed (Thu)
})

# symbol -> (exchange, weekday, has_weekly). weekday: Mon=0..Sun=6.
INDEX_EXPIRY_RULES: dict[str, dict] = {
    "NIFTY": {"exchange": "NSE", "weekday": 1, "weekly": True, "label": "Tuesday"},
    "BANKNIFTY": {"exchange": "NSE", "weekday": 1, "weekly": False, "label": "Tuesday"},
    "FINNIFTY": {"exchange": "NSE", "weekday": 1, "weekly": False, "label": "Tuesday"},
    "SENSEX": {"exchange": "BSE", "weekday": 3, "weekly": True, "label": "Thursday"},
}

# Settlement cut-off: expiries settle ~15:30 IST; after that, roll to next.
EXPIRY_CUTOFF_MINUTES = 15 * 60 + 30


def _now_ist() -> datetime:
    return datetime.now(timezone.utc).astimezone(IST)


def _is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d.isoformat() not in HOLIDAYS_IST


def _prev_trading_day(d: date) -> date:
    d -= timedelta(days=1)
    while not _is_trading_day(d):
        d -= timedelta(days=1)
    return d


def _adjust_for_holiday(d: date) -> date:
    while not _is_trading_day(d):
        d = _prev_trading_day(d)
    return d


def _next_weekday(from_date: date, weekday: int, include_today: bool = True) -> date:
    days_ahead = (weekday - from_date.weekday()) % 7
    if days_ahead == 0 and not include_today:
        days_ahead = 7
    return _adjust_for_holiday(from_date + timedelta(days=days_ahead))


def _last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    if month == 12:
        nxt = date(year + 1, 1, 1)
    else:
        nxt = date(year, month + 1, 1)
    d = nxt - timedelta(days=1)
    while d.weekday() != weekday:
        d -= timedelta(days=1)
    return _adjust_for_holiday(d)


def _payload(expiry_date: date, today: date, tenor: str, weekday_label: str, now: datetime) -> dict:
    return {
        "expiry_date": expiry_date.isoformat(),
        "expiry_label": expiry_date.strftime("%d %b %Y"),
        "expiry_weekday": expiry_date.strftime("%A"),
        "days_to_expiry": (expiry_date - today).days,
        "tenor": tenor,
        "expiry_day": weekday_label,
        "timestamp": now.isoformat(),
    }


def get_weekly_expiry(symbol: str = "NIFTY", today: Optional[date] = None, now: Optional[datetime] = None) -> Optional[dict]:
    """Next weekly expiry for symbols that have weeklies, else None."""
    symbol = (symbol or "NIFTY").upper()
    rule = INDEX_EXPIRY_RULES.get(symbol)
    if not rule or not rule["weekly"]:
        return None
    now = now or _now_ist()
    today = today or now.date()
    ist_mins = now.hour * 60 + now.minute
    include_today = not (today.weekday() == rule["weekday"] and ist_mins >= EXPIRY_CUTOFF_MINUTES)
    expiry = _next_weekday(today, rule["weekday"], include_today=include_today)
    # If this week's expiry IS the monthly expiry, weekly tenor still lists it.
    return _payload(expiry, today, "WEEKLY", rule["label"], now)


def get_monthly_expiry(symbol: str = "NIFTY", today: Optional[date] = None, now: Optional[datetime] = None) -> Optional[dict]:
    """Next monthly expiry (last exchange-weekday of the month)."""
    symbol = (symbol or "NIFTY").upper()
    rule = INDEX_EXPIRY_RULES.get(symbol)
    if not rule:
        return None
    now = now or _now_ist()
    today = today or now.date()
    ist_mins = now.hour * 60 + now.minute
    candidate = _last_weekday_of_month(today.year, today.month, rule["weekday"])
    if candidate < today or (candidate == today and ist_mins >= EXPIRY_CUTOFF_MINUTES):
        m = today.month + 1
        y = today.year + (1 if m > 12 else 0)
        m = 1 if m > 12 else m
        candidate = _last_weekday_of_month(y, m, rule["weekday"])
    return _payload(candidate, today, "MONTHLY", rule["label"], now)


def get_current_expiry(symbol: str = "NIFTY", today: Optional[date] = None, now: Optional[datetime] = None) -> dict:
    """Nearest upcoming expiry for an index (weekly when available, else monthly).

    Keeps the legacy flat shape ({expiry_date, expiry_label, days_to_expiry, ...})
    and adds weekly/monthly detail blocks for the website.
    """
    symbol = (symbol or "NIFTY").upper()
    now = now or _now_ist()
    today = today or now.date()
    weekly = get_weekly_expiry(symbol, today=today, now=now)
    monthly = get_monthly_expiry(symbol, today=today, now=now)
    candidates = [e for e in (weekly, monthly) if e]
    if not candidates:
        return {"symbol": symbol, "timestamp": now.isoformat()}
    nearest = min(candidates, key=lambda e: e["days_to_expiry"])
    return {
        "symbol": symbol,
        "exchange": INDEX_EXPIRY_RULES.get(symbol, {}).get("exchange", ""),
        "expiry_date": nearest["expiry_date"],
        "expiry_label": nearest["expiry_label"],
        "expiry_weekday": nearest["expiry_weekday"],
        "days_to_expiry": nearest["days_to_expiry"],
        "tenor": nearest["tenor"],
        "expiry_day": nearest["expiry_day"],
        "weekly": weekly,
        "monthly": monthly,
        "timestamp": now.isoformat(),
    }


if __name__ == "__main__":
    for sym in ("NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"):
        cur = get_current_expiry(sym)
        w = (cur.get("weekly") or {})
        m = (cur.get("monthly") or {})
        print(f"{sym}: weekly={w.get('expiry_label')} ({w.get('days_to_expiry')}d) | monthly={m.get('expiry_label')} ({m.get('days_to_expiry')}d)")
