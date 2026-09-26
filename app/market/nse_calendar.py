"""NSE trading calendar (explicit, no heavy dependency).

Source: NSE circular CMTR71775 (2025-12-12) + nseindia.com holiday list for
calendar year 2026, Equity/Equity-Derivatives segments. Only weekday holidays
are encoded (weekend entries need no rule — Saturday/Sunday are never
sessions). Special sessions (e.g. Budget Sunday 2026-02-01, Diwali Muhurat)
are NOT modeled: the engine treats weekends as non-sessions, documented as a
limitation. Unknown future years: no holidays known -> weekday rule applies;
absence of feed data still yields NO_DATA/MARKET_CLOSED, never a trade.
"""
from datetime import date

# 2026 weekday trading holidays (ISO dates). Verified against NSE circular.
NSE_HOLIDAYS_2026 = frozenset({
    '2026-01-26',  # Republic Day (Mon)
    '2026-03-03',  # Holi (Tue)
    '2026-03-26',  # Shri Ram Navami (Thu)
    '2026-03-31',  # Shri Mahavir Jayanti (Tue)
    '2026-04-03',  # Good Friday (Fri)
    '2026-04-14',  # Ambedkar Jayanti (Tue)
    '2026-05-01',  # Maharashtra Day (Fri)
    '2026-05-28',  # Bakri Id (Thu)
    '2026-06-26',  # Muharram (Fri)
    '2026-09-14',  # Ganesh Chaturthi (Mon)
    '2026-10-02',  # Mahatma Gandhi Jayanti (Fri)
    '2026-10-20',  # Dussehra (Tue)
    '2026-11-10',  # Diwali-Balipratipada (Tue)
    '2026-11-24',  # Guru Nanak Jayanti (Tue)
    '2026-12-25',  # Christmas (Fri)
})

_HOLIDAY_NAMES_2026 = {
    '2026-01-26': 'Republic Day', '2026-03-03': 'Holi',
    '2026-03-26': 'Shri Ram Navami', '2026-03-31': 'Shri Mahavir Jayanti',
    '2026-04-03': 'Good Friday', '2026-04-14': 'Ambedkar Jayanti',
    '2026-05-01': 'Maharashtra Day', '2026-05-28': 'Bakri Id',
    '2026-06-26': 'Muharram', '2026-09-14': 'Ganesh Chaturthi',
    '2026-10-02': 'Mahatma Gandhi Jayanti', '2026-10-20': 'Dussehra',
    '2026-11-10': 'Diwali-Balipratipada',
    '2026-11-24': 'Guru Nanak Jayanti', '2026-12-25': 'Christmas',
}

_HOLIDAYS_BY_YEAR = {2026: (NSE_HOLIDAYS_2026, _HOLIDAY_NAMES_2026)}


def is_weekend(day):
    """day: datetime.date. Saturday/Sunday are never NSE sessions."""
    return day.weekday() >= 5


def holiday_name(day):
    """Holiday name if `day` is an explicitly listed NSE holiday, else None."""
    table = _HOLIDAYS_BY_YEAR.get(day.year)
    if not table:
        return None
    dates, names = table
    key = day.isoformat()
    return names.get(key) if key in dates else None


def is_session_day(day):
    """A market session can occur on a non-weekend, non-holiday date."""
    return not is_weekend(day) and holiday_name(day) is None
