#!/usr/bin/env python3
"""Monthly coverage guard for the scheduled-events calendar.

Installed as a monthly cron job (see DEPLOYMENT.md). It never mutates data;
it only reports whether the events calendar needs maintenance before it
silently runs out of coverage.

    cd /opt/tradingai && /usr/bin/python3 scripts/events_coverage_check.py

Exit codes:
    0  coverage healthy
    2  ACTION NEEDED — hand-encoded or recurring coverage is near expiry, or a
       required monthly F&O expiry is missing from the near-term window.
    3  unexpected error (cron safety net).

Set MAILTO in the crontab to be emailed on a non-zero exit, or read
logs/events_coverage.log.
"""
import os
import sys
from datetime import date, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from app.market import events_calendar as ec  # noqa: E402

HAND_LEAD_DAYS = 45
RECUR_LEAD_DAYS = 60


def _month_keys(start, count):
    keys = []
    d = start.replace(day=1)
    for _ in range(count):
        keys.append((d.year, d.month))
        d = (d + timedelta(days=32)).replace(day=1)
    return keys


def main():
    today = date.today()
    issues = []

    hand_end = date.fromisoformat(ec.HAND_ENCODED_END)
    recur_end = date.fromisoformat(ec.RECURRING_END)
    d_hand = (hand_end - today).days
    d_recur = (recur_end - today).days

    print(f"events calendar coverage check @ {today.isoformat()}")
    print(f"  hand-encoded end {ec.HAND_ENCODED_END} ({d_hand}d away), "
          f"last verified {ec.CALENDAR_LAST_VERIFIED}")
    print(f"  recurring   end {ec.RECURRING_END} ({d_recur}d away)")

    if d_hand <= HAND_LEAD_DAYS:
        issues.append(
            f"hand-encoded events expire in {d_hand}d (<= {HAND_LEAD_DAYS}d): "
            f"add the next RBI/FOMC/Budget/CPI-WPI-GDP dates, then bump "
            f"HAND_ENCODED_END and CALENDAR_LAST_VERIFIED")
    if d_recur <= RECUR_LEAD_DAYS:
        issues.append(
            f"recurring generation window ends in {d_recur}d "
            f"(<= {RECUR_LEAD_DAYS}d): extend RECURRING_END")

    up = ec.all_events()
    have = {(int(e['date'][:4]), int(e['date'][5:7]))
            for e in up if e['category'] == 'EXPIRY'}
    # Check the next three full months (skip the partial current month).
    first_next = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
    for year, month in _month_keys(first_next, 3):
        if (year, month) not in have:
            issues.append(
                f"no monthly F&O expiry generated for {year}-{month:02d}")

    if issues:
        print("ACTION NEEDED:")
        for issue in issues:
            print(f"  - {issue}")
        return 2
    print("OK: coverage healthy")
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:  # pragma: no cover - cron safety net
        print(f"ERROR: {exc!r}")
        sys.exit(3)
