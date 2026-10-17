"""Scheduled market-moving events calendar (explicit + rule-based, fail-safe).

COVERAGE
- Hand-encoded (non-recurring) events: RBI MPC, US FOMC, Union Budget,
  India/US CPI, India WPI, India GDP. Dates from primary sources (RBI press
  releases, the Federal Reserve FOMC calendar, the Union Budget cycle,
  MOSPI/BLS release cadence). Verified through HAND_ENCODED_END.
- Rule-generated recurring events, per NSE contract specifications
  (circular NSE/FAOP/68747): monthly F&O expiry is the LAST TUESDAY of the
  month for Nifty 50 / Bank Nifty / other NSE index and stock contracts;
  Nifty 50 also has a WEEKLY expiry EVERY TUESDAY. When the scheduled Tuesday
  is a trading holiday, expiry moves to the PREVIOUS trading day. US Non-Farm
  Payrolls is the month's first Friday (shifted a week when that Friday is New
  Year's Day). Generated across RECURRING_START..RECURRING_END with no
  per-month maintenance.

NOTE ON THE EXPIRY DAY: NSE switched its derivatives expiry from Thursday to
Tuesday effective 2025-09-01 (SEBI-approved swap with BSE, which moved to
Thursday). Do not reintroduce a Thursday assumption.

WHY THIS EXISTS
Every live trade the engine freezes is exposed to scheduled risk: an RBI or
Fed decision, a CPI print, a Union Budget, a monthly or weekly F&O expiry. The
decision view surfaces an EVENT RISK overlay (advisory) so a reader can see
that a high-impact event is imminent and requires an explicit confirmation.

DESIGN CONTRACT (mirrors app/market/nse_calendar.py):
- Pure data + pure functions. No network, no DB, no clock side effects.
- Every event carries an `approx` flag and `source`. Approximate dates
  (monthly data releases, rule-generated recurrences) are marked so nothing
  is presented as certain.
- Fail-safe: unknown/expired coverage yields an empty upcoming list and risk
  NONE, never a fabricated event. Downstream must treat a missing overlay as
  "no known scheduled risk", never as "safe".
- After-close events (FOMC, US CPI/NFP, India CPI/WPI/GDP: they land after
  the NSE 15:30 close) impact the NEXT trading session, not the same one.
  The model resolves each event to a landing session.

COVERAGE_END is driven by the rule-generated recurring window; HAND_ENCODED_END
is the boundary of the hand-verified non-recurring table. `scripts/
events_coverage_check.py` (monthly cron) warns before either expires.
CALENDAR_LAST_VERIFIED=2026-10-17.
"""
from calendar import monthrange
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.market.nse_calendar import is_session_day

_IST = ZoneInfo('Asia/Kolkata')

COVERAGE_START = '2026-10-17'
RECURRING_START = '2026-09-01'
RECURRING_END = '2028-06-30'
HAND_ENCODED_END = '2027-03-31'
COVERAGE_END = RECURRING_END
CALENDAR_LAST_VERIFIED = '2026-10-17'

# Impact vocabulary (advisory only):
#   HIGH   - central-bank decisions, Union Budget, US payrolls/CPI, RBI MPC
#   MEDIUM - monthly domestic CPI/WPI GDP, monthly F&O expiry
#   LOW    - minor scheduled releases, weekly index expiry
# Timing:
#   INTRADAY    - release lands during NSE hours, same-session impact
#   AFTER_CLOSE - release lands after the 15:30 IST close, NEXT-session impact
# bias (typical direction tendency, NOT a forecast):
#   VOLATILITY / BEARISH_RISK / BULLISH_RISK / NEUTRAL
_HIGH, _MEDIUM, _LOW = 'HIGH', 'MEDIUM', 'LOW'
_INTRADAY, _AFTER_CLOSE = 'INTRADAY', 'AFTER_CLOSE'

_ALL_NSE = ('NIFTY', 'BANKNIFTY')

# ---------------------------------------------------------------------------
# Hand-encoded non-recurring table. Keep sorted by date. `time` is IST.
# (Recurring expiry / payrolls are generated below, never listed here.)
# ---------------------------------------------------------------------------
EVENTS = (
    # --- 2026 ---
    {'date': '2026-10-28', 'time': '23:30', 'name': 'US Fed FOMC policy decision',
     'category': 'MONETARY_POLICY', 'region': 'US', 'impact': _HIGH,
     'timing': _AFTER_CLOSE, 'bias': 'VOLATILITY',
     'instruments': ('NIFTY', 'BANKNIFTY', 'INDIA_VIX'), 'approx': False,
     'source': 'Federal Reserve FOMC calendar',
     'note': 'Rate statement 2:00 PM ET; lands after NSE close, gaps the next session.'},
    {'date': '2026-11-12', 'time': '17:30', 'name': 'India CPI inflation',
     'category': 'INFLATION', 'region': 'IN', 'impact': _MEDIUM,
     'timing': _AFTER_CLOSE, 'bias': 'NEUTRAL',
     'instruments': ('NIFTY', 'BANKNIFTY'), 'approx': True,
     'source': 'MOSPI monthly CPI release (~12th)',
     'note': 'Released after NSE close; drives next-session rate-sensitive moves.'},
    {'date': '2026-11-12', 'time': '18:00', 'name': 'US CPI inflation',
     'category': 'INFLATION', 'region': 'US', 'impact': _MEDIUM,
     'timing': _AFTER_CLOSE, 'bias': 'VOLATILITY',
     'instruments': ('NIFTY', 'BANKNIFTY'), 'approx': True,
     'source': 'US BLS release cadence (~mid-month)',
     'note': '8:30 AM ET; next-session gap risk.'},
    {'date': '2026-11-14', 'time': '12:00', 'name': 'India WPI inflation',
     'category': 'INFLATION', 'region': 'IN', 'impact': _LOW,
     'timing': _AFTER_CLOSE, 'bias': 'NEUTRAL',
     'instruments': ('NIFTY',), 'approx': True,
     'source': 'Office of Economic Adviser (~14th)',
     'note': 'Secondary inflation print.'},
    {'date': '2026-11-27', 'time': '17:30', 'name': 'India GDP (Q2 FY27)',
     'category': 'GROWTH', 'region': 'IN', 'impact': _MEDIUM,
     'timing': _AFTER_CLOSE, 'bias': 'NEUTRAL',
     'instruments': ('NIFTY', 'BANKNIFTY'), 'approx': True,
     'source': 'MOSPI quarterly estimates',
     'note': 'Quarterly growth print; released after close.'},
    {'date': '2026-12-04', 'time': '10:00', 'name': 'RBI MPC policy decision',
     'category': 'MONETARY_POLICY', 'region': 'IN', 'impact': _HIGH,
     'timing': _INTRADAY, 'bias': 'VOLATILITY',
     'instruments': ('NIFTY', 'BANKNIFTY', 'INDIA_VIX'), 'approx': False,
     'source': 'RBI MPC schedule 2026-27 (meeting Dec 2-4, 2026)',
     'note': 'Repo rate / stance decision during NSE hours.'},
    {'date': '2026-12-09', 'time': '00:30', 'name': 'US Fed FOMC policy decision',
     'category': 'MONETARY_POLICY', 'region': 'US', 'impact': _HIGH,
     'timing': _AFTER_CLOSE, 'bias': 'VOLATILITY',
     'instruments': ('NIFTY', 'BANKNIFTY', 'INDIA_VIX'), 'approx': False,
     'source': 'Federal Reserve FOMC calendar',
     'note': '2:00 PM ET (Dec 9) = ~00:30 IST Dec 10; gaps the next session.'},
    {'date': '2026-12-10', 'time': '18:00', 'name': 'US CPI inflation',
     'category': 'INFLATION', 'region': 'US', 'impact': _MEDIUM,
     'timing': _AFTER_CLOSE, 'bias': 'VOLATILITY',
     'instruments': ('NIFTY', 'BANKNIFTY'), 'approx': True,
     'source': 'US BLS release cadence',
     'note': 'Next-session gap risk.'},
    {'date': '2026-12-14', 'time': '17:30', 'name': 'India CPI inflation',
     'category': 'INFLATION', 'region': 'IN', 'impact': _MEDIUM,
     'timing': _AFTER_CLOSE, 'bias': 'NEUTRAL',
     'instruments': ('NIFTY', 'BANKNIFTY'), 'approx': True,
     'source': 'MOSPI monthly CPI release',
     'note': 'Released after NSE close.'},
    # --- 2027 ---
    {'date': '2027-01-12', 'time': '17:30', 'name': 'India CPI inflation',
     'category': 'INFLATION', 'region': 'IN', 'impact': _MEDIUM,
     'timing': _AFTER_CLOSE, 'bias': 'NEUTRAL',
     'instruments': ('NIFTY', 'BANKNIFTY'), 'approx': True,
     'source': 'MOSPI monthly CPI release',
     'note': 'Released after NSE close.'},
    {'date': '2027-01-13', 'time': '18:00', 'name': 'US CPI inflation',
     'category': 'INFLATION', 'region': 'US', 'impact': _MEDIUM,
     'timing': _AFTER_CLOSE, 'bias': 'VOLATILITY',
     'instruments': ('NIFTY', 'BANKNIFTY'), 'approx': True,
     'source': 'US BLS release cadence',
     'note': 'Next-session gap risk.'},
    {'date': '2027-01-27', 'time': '00:30', 'name': 'US Fed FOMC policy decision',
     'category': 'MONETARY_POLICY', 'region': 'US', 'impact': _HIGH,
     'timing': _AFTER_CLOSE, 'bias': 'VOLATILITY',
     'instruments': ('NIFTY', 'BANKNIFTY', 'INDIA_VIX'), 'approx': False,
     'source': 'Federal Reserve FOMC calendar (meeting Jan 26-27, 2027)',
     'note': '2:00 PM ET = ~00:30 IST next day; gaps the next session.'},
    {'date': '2027-02-01', 'time': '11:00', 'name': 'Union Budget (India)',
     'category': 'FISCAL', 'region': 'IN', 'impact': _HIGH,
     'timing': _INTRADAY, 'bias': 'VOLATILITY',
     'instruments': ('NIFTY', 'BANKNIFTY', 'INDIA_VIX'), 'approx': False,
     'source': 'Union Budget presentation (Feb 1)',
     'note': 'Budget speech during NSE hours; the highest-volatility session of the year.'},
    {'date': '2027-02-05', 'time': '10:00', 'name': 'RBI MPC policy decision',
     'category': 'MONETARY_POLICY', 'region': 'IN', 'impact': _HIGH,
     'timing': _INTRADAY, 'bias': 'VOLATILITY',
     'instruments': ('NIFTY', 'BANKNIFTY', 'INDIA_VIX'), 'approx': False,
     'source': 'RBI MPC schedule 2026-27 (meeting Feb 3-5, 2027)',
     'note': 'Repo rate / stance decision during NSE hours.'},
    {'date': '2027-02-11', 'time': '18:00', 'name': 'US CPI inflation',
     'category': 'INFLATION', 'region': 'US', 'impact': _MEDIUM,
     'timing': _AFTER_CLOSE, 'bias': 'VOLATILITY',
     'instruments': ('NIFTY', 'BANKNIFTY'), 'approx': True,
     'source': 'US BLS release cadence',
     'note': 'Next-session gap risk.'},
    {'date': '2027-02-12', 'time': '17:30', 'name': 'India CPI inflation',
     'category': 'INFLATION', 'region': 'IN', 'impact': _MEDIUM,
     'timing': _AFTER_CLOSE, 'bias': 'NEUTRAL',
     'instruments': ('NIFTY', 'BANKNIFTY'), 'approx': True,
     'source': 'MOSPI monthly CPI release',
     'note': 'Released after NSE close.'},
    {'date': '2027-02-27', 'time': '17:30', 'name': 'India GDP (Q3 FY27)',
     'category': 'GROWTH', 'region': 'IN', 'impact': _MEDIUM,
     'timing': _AFTER_CLOSE, 'bias': 'NEUTRAL',
     'instruments': ('NIFTY', 'BANKNIFTY'), 'approx': True,
     'source': 'MOSPI quarterly estimates',
     'note': 'Quarterly growth print; released after close.'},
    {'date': '2027-03-12', 'time': '17:30', 'name': 'India CPI inflation',
     'category': 'INFLATION', 'region': 'IN', 'impact': _MEDIUM,
     'timing': _AFTER_CLOSE, 'bias': 'NEUTRAL',
     'instruments': ('NIFTY', 'BANKNIFTY'), 'approx': True,
     'source': 'MOSPI monthly CPI release',
     'note': 'Released after NSE close.'},
)

_VALID_INSTRUMENTS = ('NIFTY', 'BANKNIFTY', 'INDIA_VIX')
_MAX_UPCOMING = 40


# ---------------------------------------------------------------------------
# Rule-generated recurring events (no per-month maintenance).
# ---------------------------------------------------------------------------
def _last_weekday(year, month, weekday):
    """Last date in the month with the given weekday (0=Mon..6=Sun)."""
    d = date(year, month, monthrange(year, month)[1])
    while d.weekday() != weekday:
        d -= timedelta(days=1)
    return d


def _first_weekday(year, month, weekday):
    d = date(year, month, 1)
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d


def _months_between(start, end):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        m += 1
        if m > 12:
            m, y = 1, y + 1


def _prev_session(d):
    """The scheduled expiry day, or, if it is a trading holiday, the previous
    trading day (NSE rule). Fail-safe: outside the NSE-holiday coverage years
    the weekday rule applies and the event stays flagged `approx`."""
    for _ in range(10):
        if is_session_day(d):
            return d
        d -= timedelta(days=1)
    return d


def _monthly_expiry_day(year, month):
    """NSE monthly F&O expiry: the month's last Tuesday (previous trading day
    if that Tuesday is a holiday)."""
    return _prev_session(_last_weekday(year, month, 1))  # Tuesday


def _nfp_day(year, month):
    """US Non-Farm Payrolls: the month's first Friday.

    BLS publishes on the first Friday, except when that Friday is New Year's
    Day (Jan 1), when the print moves to the following Friday."""
    d = _first_weekday(year, month, 4)  # Friday
    if d.month == 1 and d.day == 1:
        d += timedelta(days=7)
    return d


def _monthly_event(d):
    return {
        'date': d.isoformat(), 'time': '15:30',
        'name': 'Monthly F&O expiry (NSE)', 'category': 'EXPIRY',
        'series': 'MONTHLY', 'region': 'IN', 'impact': _MEDIUM,
        'timing': _INTRADAY, 'bias': 'VOLATILITY', 'instruments': _ALL_NSE,
        'approx': True, 'recurring': True,
        'source': 'NSE monthly expiry = last Tuesday (circular NSE/FAOP/68747)',
        'note': 'Nifty 50 / Bank Nifty / other index and stock F&O settle; expiry-day pinning / unwind volatility.'}


def _weekly_event(d):
    return {
        'date': d.isoformat(), 'time': '15:30',
        'name': 'Weekly Nifty options expiry (NSE)', 'category': 'EXPIRY',
        'series': 'WEEKLY', 'region': 'IN', 'impact': _LOW,
        'timing': _INTRADAY, 'bias': 'VOLATILITY', 'instruments': ('NIFTY',),
        'approx': True, 'recurring': True,
        'source': 'NSE weekly Nifty 50 expiry = every Tuesday (circular NSE/FAOP/68747)',
        'note': 'Weekly Nifty 50 options settle; intraday volatility. Bank Nifty / other indices are monthly only.'}


def _nfp_event(d):
    return {
        'date': d.isoformat(), 'time': '18:00',
        'name': 'US Non-Farm Payrolls', 'category': 'EMPLOYMENT',
        'region': 'US', 'impact': _HIGH, 'timing': _AFTER_CLOSE,
        'bias': 'VOLATILITY', 'instruments': ('NIFTY', 'BANKNIFTY'),
        'approx': True, 'recurring': True,
        'source': 'US BLS release cadence (first Friday, auto-generated)',
        'note': '8:30 AM ET; lands after NSE close, next-session gap risk.'}


def _build_recurring():
    start = date.fromisoformat(RECURRING_START)
    end = date.fromisoformat(RECURRING_END)
    out = []
    monthly_dates = set()
    # Monthly expiry: last Tuesday of each month.
    for y, m in _months_between(start, end):
        d = _monthly_expiry_day(y, m)
        if start <= d <= end:
            out.append(_monthly_event(d))
            monthly_dates.add(d)
    # Weekly Nifty expiry: every Tuesday (skip dates already used by the
    # monthly expiry — the last Tuesday is the monthly for that week).
    tue = start + timedelta(days=(1 - start.weekday()) % 7)
    while tue <= end:
        d = _prev_session(tue)
        if d not in monthly_dates and start <= d <= end:
            out.append(_weekly_event(d))
        tue += timedelta(days=7)
    # US payrolls: first Friday of each month.
    for y, m in _months_between(start, end):
        d = _nfp_day(y, m)
        if start <= d <= end:
            out.append(_nfp_event(d))
    return tuple(out)


_RECURRING = _build_recurring()


def _parse(ev):
    return date.fromisoformat(ev['date'])


def _lands_on(ev):
    """Session date on which `ev`'s impact is felt.

    INTRADAY -> the event's own date. AFTER_CLOSE -> the next NSE session
    after it (weekends/holidays skipped via the NSE calendar). A non-session
    event date for either timing rolls forward to the next session."""
    d = date.fromisoformat(ev['date'])
    step = ev.get('timing') == _AFTER_CLOSE
    cur = d + timedelta(days=1) if step else d
    for _ in range(15):
        if is_session_day(cur):
            return cur
        cur += timedelta(days=1)
    return cur


def _display(ev, today):
    d = _parse(ev)
    lands = _lands_on(ev)
    return {
        'date': ev['date'],
        'time_ist': ev.get('time'),
        'name': ev['name'],
        'category': ev['category'],
        'series': ev.get('series'),
        'region': ev['region'],
        'impact': ev['impact'],
        'timing': ev['timing'],
        'bias': ev['bias'],
        'instruments': list(ev['instruments']),
        'approx': bool(ev.get('approx')),
        'recurring': bool(ev.get('recurring')),
        'source': ev.get('source'),
        'note': ev.get('note'),
        'lands_on_session': lands.isoformat(),
        'days_away': (d - today).days,
    }


def _relevant(ev, instrument):
    if instrument is None:
        return True
    if instrument not in _VALID_INSTRUMENTS:
        return False
    return instrument in ev['instruments']


def all_events(instrument=None):
    """Hand-encoded + rule-generated events (optional instrument filter), sorted.

    Hand-encoded entries win over generated ones on a (date, name) collision."""
    merged = {}
    if instrument is None or instrument in _VALID_INSTRUMENTS:
        for e in _RECURRING:
            if _relevant(e, instrument):
                merged[(e['date'], e['name'])] = e
        for e in EVENTS:
            if _relevant(e, instrument):
                merged[(e['date'], e['name'])] = e  # hand-encoded overrides
    rows = list(merged.values())
    return sorted(rows, key=lambda e: (e['date'], e.get('time') or ''))


def upcoming_events(now=None, days=90, instrument=None):
    """Events whose date is on/after `now` within `days`, as display dicts.

    Pure. Unknown instrument -> []. Missing coverage -> whatever remains in
    the table on/after now (never fabricated)."""
    if instrument is not None and instrument not in _VALID_INSTRUMENTS:
        return []
    today = (now or datetime.now(_IST)).astimezone(_IST).date()
    horizon = today + timedelta(days=days)
    out = []
    for ev in all_events(instrument):
        d = _parse(ev)
        if today <= d <= horizon:
            out.append(_display(ev, today))
    return out[:_MAX_UPCOMING]


def event_risk(instrument, now=None, lookahead_sessions=2):
    """Advisory event-risk overlay for one instrument at `now`.

    Returns a deterministic dict. Pure (no I/O). This is an ADVISORY layer:
    callers must not use it to override risk/lock/freshness gates, only to
    annotate a decision and require explicit confirmation.

    risk_level:
      HIGH   - a HIGH-impact event lands today, or a HIGH after-close event
               from the prior session lands today, or one is pending within
               `lookahead_sessions` sessions (overnight-gap anticipation).
      MEDIUM - a MEDIUM-impact event lands today / next session, or a HIGH
               event is 3-5 sessions out.
      LOW    - a MEDIUM- or HIGH-impact event is within the next 10 days
               (weekly index expiry alone does not raise this).
      NONE   - nothing known in range.
    """
    now_ist = (now or datetime.now(_IST))
    if now_ist.tzinfo is None:
        now_ist = now_ist.replace(tzinfo=_IST)
    else:
        now_ist = now_ist.astimezone(_IST)
    today = now_ist.date()

    base = {
        'instrument': instrument,
        'as_of': now_ist.isoformat(),
        'risk_level': 'NONE',
        'risk_label': 'No scheduled event risk in range',
        'confirmation_required': False,
        'bias_overlay': 'NEUTRAL',
        'today_impact': [],
        'pending': [],
        'next_event': None,
        'upcoming': [],
        'reasons': [],
        'coverage': {'start': COVERAGE_START, 'end': COVERAGE_END,
                     'hand_encoded_end': HAND_ENCODED_END,
                     'last_verified': CALENDAR_LAST_VERIFIED},
    }
    if instrument not in _VALID_INSTRUMENTS:
        return base

    events = [e for e in all_events(instrument)]
    horizon = today + timedelta(days=90)
    upcoming = [_display(e, today) for e in events
                if today <= _parse(e) <= horizon]
    base['upcoming'] = upcoming[:_MAX_UPCOMING]

    sess_seq = []
    cur = today
    for _ in range(30):
        if is_session_day(cur):
            sess_seq.append(cur)
        cur += timedelta(days=1)
    idx_of = {d: i for i, d in enumerate(sess_seq)}
    today_idx = idx_of.get(today, 0)

    today_impact = []
    pending = []
    for ev in events:
        lands = _lands_on(ev)
        disp = _display(ev, today)
        if lands == today:
            today_impact.append((ev['impact'], disp))
        li = idx_of.get(lands)
        if li is not None and 1 <= (li - today_idx) <= lookahead_sessions:
            pending.append((ev['impact'], disp))

    base['today_impact'] = [d for _, d in today_impact]
    base['pending'] = [d for _, d in pending]

    future = [d for d in upcoming if d['lands_on_session'] >= today.isoformat()]
    base['next_event'] = future[0] if future else None

    today_high = any(i == _HIGH for i, _ in today_impact)
    today_med = any(i == _MEDIUM for i, _ in today_impact)
    pending_high = any(i == _HIGH for i, _ in pending)
    pending_med = any(i == _MEDIUM for i, _ in pending)

    reasons = []
    if today_high:
        base['risk_level'] = 'HIGH'
        base['risk_label'] = 'High-impact event lands this session'
        reasons.append('EVENT_IMPACT_TODAY_HIGH')
    elif pending_high:
        base['risk_level'] = 'HIGH'
        base['risk_label'] = 'High-impact event pending within the next sessions'
        reasons.append('EVENT_PENDING_HIGH')
    elif today_med:
        base['risk_level'] = 'MEDIUM'
        base['risk_label'] = 'Medium-impact event lands this session'
        reasons.append('EVENT_IMPACT_TODAY_MEDIUM')
    elif pending_med:
        base['risk_level'] = 'MEDIUM'
        base['risk_label'] = 'Medium-impact event pending within the next sessions'
        reasons.append('EVENT_PENDING_MEDIUM')
    else:
        # LOW only for a notable (MEDIUM+/HIGH) event within 10 days; a routine
        # weekly index expiry must not keep the level pinned at LOW.
        notable = [d for d in future if d['impact'] in (_HIGH, _MEDIUM)]
        if notable and notable[0]['days_away'] <= 10:
            base['risk_level'] = 'LOW'
            base['risk_label'] = 'Scheduled notable event within the next 10 days'
            reasons.append('EVENT_NEARBY')

    if base['risk_level'] in ('HIGH', 'MEDIUM'):
        base['confirmation_required'] = True
        base['bias_overlay'] = 'CAUTION'
        reasons.append('EVENT_CONFIRM_REQUIRED')
    base['reasons'] = reasons
    return base
