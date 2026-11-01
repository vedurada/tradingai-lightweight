"""Read-only data access for the prev-day/CPR spread study.

Rules (see spec.md):
  * The production database is NEVER opened for writing. The study works on a
    snapshot copy created with sqlite3's backup API from a `mode=ro` source.
  * No side-effectful production entry point is imported. The only production
    module imported is `app.market.nse_calendar`, which is stdlib-only and
    free of import-time side effects (verified by reading the file).
"""
import os
import sqlite3
from datetime import date, datetime, timedelta

from app.market.nse_calendar import holiday_name, is_session_day  # noqa: F401

PROD_DB = "/opt/tradingai/database/tradingai.db"
STUDY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUTS = os.path.join(STUDY_DIR, "outputs")

BAR_MINUTES = 5
SESSION_OPEN = "09:15"
SESSION_CLOSE = "15:30"
EXPECTED_BARS = 75          # 09:15 .. 15:25 inclusive
MIN_VALID_BARS = 70         # a session below this is not used
EOD_BAR = "15:20"           # production flat time (exit at this bar's open)
MIN_ENTRY_BAR = "09:30"     # no entry before the first OR is complete
LAST_SIGNAL_BAR = "14:45"   # max signal time (Model E entry-delay rule)

INSTRUMENTS = ("NIFTY", "BANKNIFTY")


def snapshot(prod_db=PROD_DB, out_path=None):
    """Copy the production DB to a study-local snapshot. Read-only source."""
    out_path = out_path or os.path.join(OUTPUTS, "snapshot.db")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    src = sqlite3.connect("file:%s?mode=ro" % prod_db, uri=True)
    try:
        dst = sqlite3.connect(out_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return out_path


def connect(db_path):
    """Read-only connection to a snapshot."""
    con = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
    con.row_factory = sqlite3.Row
    return con


def load_candles(con, instrument):
    """All 5-minute bars of one instrument, ordered, as a list of dicts."""
    rows = con.execute(
        "SELECT timestamp, open, high, low, close, volume, is_complete "
        "FROM market_candles_5m WHERE instrument_id = ? ORDER BY timestamp",
        (instrument,)).fetchall()
    out = []
    for r in rows:
        ts = datetime.fromisoformat(r["timestamp"])
        out.append({
            "ts": ts,
            "date": ts.date().isoformat(),
            "hhmm": ts.strftime("%H:%M"),
            "o": float(r["open"]), "h": float(r["high"]),
            "l": float(r["low"]), "c": float(r["close"]),
            "v": float(r["volume"] or 0),
            "complete": int(r["is_complete"] or 0),
        })
    return out


def group_sessions(candles):
    """dict: session_date -> list of bars (ordered)."""
    by = {}
    for c in candles:
        by.setdefault(c["date"], []).append(c)
    return by


def session_quality(bars):
    """Quality flags for one session (never silently repairs anything)."""
    hhmm = [b["hhmm"] for b in bars]
    expected = []
    t = datetime(2026, 1, 1, 9, 15)
    for _ in range(EXPECTED_BARS):
        expected.append(t.strftime("%H:%M"))
        t += timedelta(minutes=BAR_MINUTES)
    missing = [x for x in expected if x not in set(hhmm)]
    return {
        "n_bars": len(bars),
        "missing_bars": missing,
        "has_open_bar": SESSION_OPEN in hhmm,
        "has_eod_bar": EOD_BAR in hhmm,
        "complete": len(bars) >= MIN_VALID_BARS and SESSION_OPEN in hhmm,
        "short": 0 < len(missing) <= 5,
    }


def is_session(date_iso):
    d = date.fromisoformat(date_iso)
    if d.weekday() >= 5:
        return False
    return is_session_day(d)


def prior_sessions(session_dates):
    """date -> previous session date present in the data (holiday aware)."""
    out = {}
    for i, d in enumerate(session_dates):
        out[d] = session_dates[i - 1] if i > 0 else None
    return out


def calendar_gap_days(d0, d1):
    a = date.fromisoformat(d0)
    b = date.fromisoformat(d1)
    return (b - a).days
