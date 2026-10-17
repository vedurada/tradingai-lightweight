"""Live production decision layer (index-price based, no broker, no AI trading).

Pipeline enforced here (Phase 9 contract):

    completed 5m candle -> timestamp validation -> freshness validation
      -> session gate -> candle-integrity validation
      -> scenario as-of completed_ts -> qualify as-of completed_ts
      -> first-qualifying-signal/day -> NO_TRADE... / QUALIFIED
      -> JSON state for the static frontend

Rules:
- Decisions use ONLY completed candles. Candle timestamps follow the project
  convention: timestamp == candle OPEN (09:15, 09:20, ..., 15:25 IST).
  At wall time T the latest completed candle is
      completed(T) = floor_5m(T - 5min).
- All time handling in Asia/Kolkata. No server-local assumptions.
- Stale/missing/invalid data -> explicit non-trading states (DATA_STALE,
  NO_DATA, ...). Never 0/neutral/bearish fabrications.
- Session: PREMARKET (< 09:15), LIVE (09:15..15:30 on a day with data),
  MARKET_CLOSED (after 15:30, holiday, or no-data day), WEEKEND (Sat/Sun),
  with STALE/NO_DATA feed states.
- Firing uses the unified CPR book (_cpr_book_signal: first trigger,
  bear priority, variant gate, next-open entry) — same math as
  backtest/paper. Live default variant is 'plain' (no weekly gate).
  A trigger on the latest completed candle waits for
  that open (ENTRY pending, no lookahead).
  Live mode persists the one-trade-day lock in daily_trade_locks so it is
  shared across gunicorn workers; dry-run mode uses in-memory locks only.
- Structured logging: one line per evaluation state CHANGE per instrument
  (plus every error state), so 30s browser polls do not spam logs.
- Book math: next-open entry in [09:20, 15:20), 0.5% stop / 2% target, flat 15:20 open.
"""
import logging
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.market.nse_calendar import holiday_name, is_weekend

_IST = ZoneInfo('Asia/Kolkata')
log = logging.getLogger('tradingai.live')

MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)
CANDLE_MINUTES = 5
FIRST_CANDLE = time(9, 15)
LAST_CANDLE = time(15, 25)

# A completed 5m candle older than this during session hours is STALE:
# decisions must not be made on it.
STALE_AFTER_MIN = 15

# Distinct API-visible states (frontend distinguishes all of these).
ST_NO_DATA = 'NO_DATA'
ST_PREMARKET = 'PREMARKET'
ST_STALE = 'STALE'
ST_CLOSED = 'MARKET_CLOSED'
ST_WEEKEND = 'WEEKEND'
ST_NO_TRADE = 'NO_TRADE'
ST_QUALIFIED = 'QUALIFIED'

# States that may pass through the session gate unchanged.
_SESSION_PASSTHROUGH = (ST_PREMARKET, ST_CLOSED, ST_WEEKEND, ST_NO_DATA)

# Live CPR-book variant: 'plain' (no filter) or 'aligned' (weekly gate).
# Owner decision 2026-10-12: default engine for live signals, paper book,
# backtest UI and Telegram alerts is plain.
LIVE_VARIANT = 'plain'

# Remembers last logged state per instrument: log on change only.
_last_logged = {}


def floor_5m(dt):
    return dt.replace(minute=(dt.minute // 5) * 5, second=0, microsecond=0)


def completed_candle_ts(now_ist):
    """Latest completed 5m candle OPEN timestamp at wall time `now_ist`.

    A candle [open, open+5m) is complete once wall time >= open+5m.
    Returns an aware IST datetime, or None if no candle has completed yet
    today (before 09:20).
    """
    if now_ist.tzinfo is None:
        now_ist = now_ist.replace(tzinfo=_IST)
    else:
        now_ist = now_ist.astimezone(_IST)
    fc = floor_5m(now_ist) - timedelta(minutes=CANDLE_MINUTES)
    day = now_ist.date()
    earliest = datetime.combine(day, FIRST_CANDLE).replace(tzinfo=_IST)
    if fc < earliest:
        return None
    return fc


def session_state(now_ist, has_data_today=True):
    """PREMARKET / LIVE / MARKET_CLOSED / WEEKEND / NO_DATA.

    Weekends are WEEKEND (never a session, regardless of data). NSE holidays
    are NOT decided here (no date table lookup in the hot path); the caller
    maps a data-less holiday to MARKET_CLOSED+HOLIDAY via holiday_name().
    """
    if now_ist.tzinfo is None:
        now_ist = now_ist.replace(tzinfo=_IST)
    else:
        now_ist = now_ist.astimezone(_IST)
    if is_weekend(now_ist.date()):
        return ST_WEEKEND
    t = now_ist.time()
    if t < MARKET_OPEN:
        return ST_PREMARKET
    if t > MARKET_CLOSE:
        return ST_CLOSED
    if not has_data_today:
        return ST_NO_DATA  # weekday in hours but no candles: holiday/feed gap
    return 'LIVE'


def _log_state(base):
    """One log line per state change per instrument (spam-safe polling)."""
    key = base.get('instrument')
    sig = (base.get('state'), base.get('completed_candle'),
           tuple(base.get('reasons', [])[:1]))
    if _last_logged.get(key) == sig:
        return
    _last_logged[key] = sig
    log.info('live instrument=%s state=%s session=%s completed=%s age_min=%s '
             'scenario=%s qual=%s reasons=%s',
             base.get('instrument'), base.get('state'), base.get('session'),
             base.get('completed_candle'), base.get('completed_age_minutes'),
             (base.get('trade') or {}).get('scenario'),
             base.get('qualification'), ';'.join(base.get('reasons', [])))


def validate_candles(candles, completed_ts):
    """Integrity gate over today's candles up to `completed_ts`.

    Returns (ok, issues, usable). `usable` is the completed candle dict or
    None. Never repairs data: any structural problem -> not ok.
    Checks: empty set, missing completed candle, duplicates, out-of-order,
    future timestamps, invalid OHLC (non-positive, high<low, open/close
    outside [low, high]).
    """
    issues = []
    if not candles:
        return False, ['NO_CANDLES'], None
    seen = set()
    prev = None
    for c in candles:
        ts = c.get('timestamp')
        if ts in seen:
            issues.append(f'DUPLICATE_CANDLE:{ts}')
        seen.add(ts)
        if prev is not None and ts < prev:
            issues.append(f'OUT_OF_ORDER:{ts}')
        prev = ts
        if ts is not None and completed_ts is not None and ts > completed_ts.isoformat():
            issues.append(f'FUTURE_CANDLE:{ts}')
        try:
            o, h, l, cl = (float(c['open']), float(c['high']),
                           float(c['low']), float(c['close']))
        except (KeyError, TypeError, ValueError):
            issues.append(f'NON_NUMERIC_OHLC:{ts}')
            continue
        if not (o > 0 and h > 0 and l > 0 and cl > 0):
            issues.append(f'NON_POSITIVE_PRICE:{ts}')
        if h < l:
            issues.append(f'HIGH_BELOW_LOW:{ts}')
        if not (l - 1e-9 <= o <= h + 1e-9 and l - 1e-9 <= cl <= h + 1e-9):
            issues.append(f'OHLC_RANGE_VIOLATION:{ts}')
    key = completed_ts.isoformat() if completed_ts else None
    usable = next((c for c in candles if c.get('timestamp') == key), None)
    if completed_ts is not None and usable is None:
        issues.append(f'MISSING_COMPLETED_CANDLE:{key}')
    if issues:
        return False, issues, None
    return True, [], usable


def build_market_state(price, candles=None):
    """Market state derived from PIT CLOSED candles only (never fabricated).

    FAIL-CLOSED: price<=0 or no usable candles -> all-None (downstream NO_DATA,
    never default BULLISH/ABOVE/POSITIVE/NORMAL). Research templates untouched. (v1 heuristic, 2026-09-26).

    - trend: last close vs mean of closes (session drift).
    - vwap_relation: last close vs cumulative typical-price VWAP (equal-weight
      when volume is 0, as index feeds report); ABOVE if >= else BELOW.
    - momentum: last close vs close 3 bars back (or first bar if fewer).
    - volatility: mean 5m range/close; HIGH above 0.8%, else NORMAL.
    Never invents: empty input returns None-valued keys and downstream
    defaults apply (no fabricated direction). Research templates untouched."""
    try:
        px = float(price)
    except (TypeError, ValueError):
        px = None
    out = {'trend': None, 'vwap_relation': None, 'momentum': None,
           'volatility': None, 'price': px}
    # Fail-closed: non-positive/missing price or empty candles -> None signals.
    if px is None or not (px > 0) or not candles:
        return out
    try:
        closes = [float(c['close']) for c in (candles or [])]
        if not closes or px is None:
            return out
        mean_c = sum(closes) / len(closes)
        out['trend'] = 'BULLISH' if closes[-1] >= mean_c else 'BEARISH'
        num = den = 0.0
        rngs = []
        for c in (candles or []):
            try:
                o, h, l, cl = (float(c['open']), float(c['high']),
                               float(c['low']), float(c['close']))
                v = float(c.get('volume') or 0)
            except (KeyError, TypeError, ValueError):
                continue
            tp = (h + l + cl) / 3.0
            num += tp * v
            den += v
            if cl > 0:
                rngs.append((h - l) / cl)
        vwap = (num / den) if den > 0 else (sum(
            ((float(c['high']) + float(c['low']) + float(c['close'])) / 3.0)
            for c in (candles or [])) / max(len(candles or []), 1))
        out['vwap_relation'] = 'ABOVE' if closes[-1] >= vwap else 'BELOW'
        ref = closes[-3] if len(closes) >= 3 else closes[0]
        out['momentum'] = 'POSITIVE' if closes[-1] >= ref else 'NEGATIVE'
        out['volatility'] = 'HIGH' if (sum(rngs) / len(rngs) > 0.008) else 'NORMAL' if rngs else None
    except (TypeError, ValueError, ZeroDivisionError):
        pass
    return out


def _select_entry(feed, forming, sig_index, live_price, now):
    """Pick (entry, entry_time, signal_time) for a CPR trigger. Pure (no I/O).

    Backtest parity (Oct-12 divergence fix): the entry is ALWAYS a next-open,
    never the live price.
    - A later COMPLETED entry candle exists (i+1 < len(feed)) -> historical
      next-open entry (unchanged; keeps live == backtest/replay on late reads).
    - Otherwise the trigger is on the latest completed candle: fire as soon as
      the next candle's OPEN is known (forming.open is a past, real price, not
      a forecast), with entry_time = the entry candle's timestamp. This keeps
      alerts within ~a minute of the candle open while matching backtest
      entries tick-for-tick.
    - If the next candle is not in cache yet, return None (caller -> WAIT
      entry_at_next_open) and keep polling; never fabricate from live price.
    live_price is accepted for signature compatibility and ignored.
    """
    i = sig_index
    if i + 1 < len(feed):
        ec = feed[i + 1]
        try:
            entry = round(float(ec['open']), 2)
        except (KeyError, TypeError, ValueError):
            return None
        return entry, str(ec.get('timestamp', '')), str(feed[i].get('timestamp', ''))
    if forming is None:
        return None
    # Next-open entry: the forming candle's OPEN is already history (its
    # interval started), so taking it is parity with backtest, not lookahead.
    try:
        entry = round(float(forming['open']), 2)
        if entry <= 0:
            return None
    except (KeyError, TypeError, ValueError):
        return None
    sig_ts = str(feed[i].get('timestamp', '')) if i < len(feed) else ''
    nt = str(forming.get('timestamp', ''))
    if not nt:
        return None
    return entry, nt, sig_ts


def _select_entry_no_chase(feed, forming, sig_index, lv):
    """No-chase re-anchor entry for a BEAR trigger: (entry, entry_time,
    direction, level) or None. Pure (no I/O).

    Mirrors app.research.cpr_trigger_engine.no_chase_fill so live == backtest
    == paper: the trigger's next open is NEVER taken. Instead we wait for price
    to trade back within NO_CHASE_BAND_PCT (0.15%) of ANY entry level and enter
    with the direction that level implies — resistance (R2/R1/PDH/BC) shorts,
    support (TC/S1/S2/PDL) longs. The direction may therefore flip to BULL even
    under SHORT_ONLY (that re-anchor is the intended exception).

    Fills from COMPLETED candles beyond the trigger first (historical parity).
    If price has not returned yet, the FORMING candle is checked: its open is a
    fixed past price and its high/low are the extremes already traded, so a
    near-level touch there is a past fact, not a lookahead forecast. Returns
    None -> the caller WAITs (no_chase_wait) until price returns or the entry
    window closes. Fills strictly inside [OPEN_MIN, OPEN_EOD)."""
    from app.research.cpr_trigger_engine import (
        no_chase_fill, entry_levels, NO_CHASE_BAND_PCT)
    nc = no_chase_fill(lv, feed, sig_index)
    if nc is not None:
        j, name, dr, fill = nc
        return round(float(fill), 2), str(feed[j].get('timestamp', '')), dr, name
    if forming is None:
        return None
    try:
        op = float(forming['open'])
        hi = float(forming['high'])
        lo = float(forming['low'])
    except (KeyError, TypeError, ValueError):
        return None
    levels = entry_levels(lv)
    for name, dr, ref in levels:                 # open near a level
        if abs(op - ref) <= NO_CHASE_BAND_PCT * ref:
            nt = str(forming.get('timestamp', ''))
            return (round(op, 2) if nt else None), nt, dr, name
    for name, dr, ref in levels:                 # range already covers a level
        if lo <= ref <= hi:
            nt = str(forming.get('timestamp', ''))
            return (round(ref, 2) if nt else None), nt, dr, name
    return None


def _cpr_book_signal(instrument, candles, completed, live_price=None, now=None):
    """CPR-book signal over live candles (unified rulebook; next-open entry).

    Trigger math is identical to backtest/paper (book_scan first trigger, bear
    priority, variant gate) run over COMPLETED candles only — the forming
    candle is never scanned (Oct-12 divergence fix: intrabar touches that fade
    by close permanently disagreed with the EOD paper book). Entry TIMING:
    - A trigger on a completed candle with a later completed candle uses that
      candle's open (historical next-open, unchanged).
    - A trigger on the latest completed candle fires as soon as the next
      candle's OPEN is known (forming.open is past fact, not a forecast),
      with entry_time = the entry candle's timestamp: same price the backtest
      would record, alerted within ~a minute of the candle open.
    - If the next candle is not in cache yet, WAIT (entry_at_next_open).
    Reads only real data, never future data. Returns {'trade': dict|None,
    'reasons': [...]}. Read-only."""
    from app.core.db import get_conn
    from app.research.cpr_trigger_engine import (
        book_scan, day_levels, prev_session_ohlc, weekly_levels, monday_of,
        OPEN_MIN, OPEN_EOD, OPEN_STOP_PCT, OPEN_TARGET_PCT, shadow_flags,
        NO_CHASE_BEAR, friday_skip)
    day_iso = completed.date().isoformat()
    conn = get_conn()
    try:
        prev = prev_session_ohlc(conn, instrument, day_iso)
        if not prev:
            return {'trade': None, 'reasons': ['CPR_DATA_UNAVAILABLE']}
        lv = day_levels(prev['high'], prev['low'], prev['close'])
        wlv = weekly_levels(conn, instrument, monday_of(day_iso)) \
            if LIVE_VARIANT == 'aligned' else None
    finally:
        try:
            conn.close()
        except Exception:
            pass
    if not lv:
        return {'trade': None, 'reasons': ['CPR_DATA_UNAVAILABLE']}
    if LIVE_VARIANT == 'aligned' and not wlv:
        return {'trade': None, 'reasons': ['weekly_gate_missing']}
    feed = [c for c in (candles or [])
            if str(c.get('timestamp', ''))[:10] == day_iso
            and str(c.get('timestamp', '')) <= completed.isoformat()]
    # Warm-up gate (Oct-12 divergence fix): the session's first completed
    # candle (09:15) must be present in the feed before any trigger can fire.
    # A cache that starts at 09:20 silently shifts first-trigger-wins onto a
    # truncated candle set and permanently disagrees with the EOD paper book.
    if feed and not any(str(c.get('timestamp', '')).startswith(day_iso + 'T09:15')
                        for c in feed):
        return {'trade': None, 'reasons': ['warmup_wait_first_candle']}
    nxt_ts = (completed + timedelta(minutes=CANDLE_MINUTES)).isoformat()
    forming = next((c for c in (candles or [])
                    if str(c.get('timestamp', '')) == nxt_ts), None)
    # Completed candles only: the forming candle is never scanned for triggers
    # (Oct-12 divergence fix). It is used solely as the next-open entry source
    # once a completed candle triggers (see _select_entry).
    sig = book_scan(feed, lv, wlv, LIVE_VARIANT)
    if not sig:
        return {'trade': None, 'reasons': ['no_cpr_trigger']}
    dr, t, i = sig
    no_chase = False
    if NO_CHASE_BEAR and dr == 'BEAR':
        # No-chase re-anchor: never take the next open. Wait for price to come
        # back near an entry level and enter with that level's direction (which
        # may flip to BULL). Until then WAIT (no_chase_wait); skip once the
        # window closes or a re-anchored BEAR lands on a Friday.
        picked = _select_entry_no_chase(feed, forming, i, lv)
        if picked is None:
            return {'trade': None, 'reasons': ['no_chase_wait']}
        entry, nt, dr, t = picked
        no_chase = True
    else:
        picked = _select_entry(feed, forming, i, live_price, now)
        if picked is None:
            return {'trade': None, 'reasons': ['entry_at_next_open']}
        entry, nt, _sig = picked
    sig_ts = str(feed[i].get('timestamp', ''))
    if not nt or not (OPEN_MIN <= nt[11:16] < OPEN_EOD):
        return {'trade': None, 'reasons': ['entry_window_closed']}
    if no_chase and friday_skip(dr, day_iso):
        return {'trade': None, 'reasons': ['skip_friday']}
    if dr == 'BEAR':
        stop = round(entry * (1 + OPEN_STOP_PCT), 2)
        tgt = round(entry * (1 - OPEN_TARGET_PCT), 2)
    else:
        stop = round(entry * (1 - OPEN_STOP_PCT), 2)
        tgt = round(entry * (1 + OPEN_TARGET_PCT), 2)
    trade = {'entry': entry, 'entry_time': nt,
             'signal_time': sig_ts,
             'stop': stop, 'target': tgt,
             'max_risk': round(OPEN_STOP_PCT * 100, 4),
             'expected_reward': round(OPEN_TARGET_PCT * 100, 4),
             'strategy': 'Bear Call Spread' if dr == 'BEAR' else 'Bull Put Spread',
             'objective': 'DIRECTIONAL', 'direction': dr, 'scenario': t,
             'shadow': shadow_flags(dr, day_iso),
             # Feed diagnostics (D): snapshot of what the trigger scan saw,
             # so any future live/paper disagreement is diagnosable from the
             # frozen record instead of log archaeology.
             'feed_n': len(feed),
             'feed_first_ts': str(feed[0].get('timestamp', '')) if feed else None,
             'forming_ts': str(forming.get('timestamp', '')) if forming is not None else None,
             # Markers so the frozen-trade gate + attribution know WHY a BULL
             # is here (the sanctioned SHORT_ONLY overrides): a no-chase
             # re-anchor, or the breakout add-on ('BRK_*' level).
             'no_chase_reanchor': no_chase,
             'breakout': str(t).startswith('BRK_')}
    return {'trade': trade, 'reasons': [f'CPR_TRIGGER_{t}', 'WEEKLY_GATE_PASS']}


def _frozen_trade(instrument, day_iso):
    """Today's persisted (frozen) live trade for an instrument, or None.

    Once a live trigger fires we persist the trade so the decision API serves
    a STABLE entry/stop/target for the rest of the session. The engine is
    stateless and recomputed on every poll; an unfrozen entry would otherwise
    drift poll-to-poll and break the alert exit-sweep (which compares
    each poll's entry to the one it recorded). Read-only (SELECT only)."""
    import json as _json
    from app.core.db import get_conn
    conn = get_conn()
    try:
        r = conn.execute(
            "SELECT timestamp, scenario, strategy, objective, direction, entry,"
            " stop, target, max_risk, expected_reward, qualification_evidence"
            " FROM qualified_trades WHERE instrument_id=? AND date=?"
            " AND status IN ('ACTIVE','QUALIFIED')"
            " ORDER BY created_at DESC LIMIT 1", (instrument, day_iso)).fetchone()
    except Exception:
        r = None
    finally:
        try:
            conn.close()
        except Exception:
            pass
    if not r:
        return None
    sig = None
    ncr = False
    brk = False
    try:
        ev = _json.loads(r['qualification_evidence'] or '{}') or {}
        sig = ev.get('signal_time')
        ncr = bool(ev.get('no_chase_reanchor'))
        brk = bool(ev.get('breakout'))
    except Exception:
        sig = None
        ncr = False
        brk = False
    return {'entry': r['entry'], 'entry_time': r['timestamp'],
            'signal_time': sig or r['timestamp'],
            'stop': r['stop'], 'target': r['target'],
            'max_risk': r['max_risk'], 'expected_reward': r['expected_reward'],
            'strategy': r['strategy'], 'objective': r['objective'],
            'direction': r['direction'], 'scenario': r['scenario'],
            'no_chase_reanchor': ncr, 'breakout': brk, 'frozen': True}


def _frozen_trade_passes_gate(frozen, day_iso):
    """Re-validate a persisted frozen trade against the CURRENT gates.

    A frozen row must never bypass the direction/weekday gates: a row frozen
    before a gate change (or by a non-gated writer) would otherwise keep
    serving TRADE for the rest of the session. Uses the same predicates as the
    trigger engine (SHORT_ONLY, friday_skip) and fails open on an unknown or
    missing date, exactly like friday_skip. Read-only."""
    from app.research.cpr_trigger_engine import (
        SHORT_ONLY, NO_CHASE_BEAR, BREAKOUT_ADDON, friday_skip)
    dr = (frozen or {}).get('direction')
    scen = (frozen or {}).get('scenario') or ''
    if SHORT_ONLY and dr != 'BEAR':
        # Sanctioned SHORT_ONLY overrides. (a) A no-chase re-anchor whose
        # direction came from the SUPPORT level price reached back to. (b) The
        # breakout add-on fallback ('BRK_*' levels) which is BULL above
        # resistance. Every other BULL row is still rejected exactly as before.
        reanchor_ok = NO_CHASE_BEAR and (frozen or {}).get('no_chase_reanchor')
        breakout_ok = BREAKOUT_ADDON and scen.startswith('BRK_')
        if not (reanchor_ok or breakout_ok):
            return False
    if friday_skip(dr, day_iso):
        return False
    return True


def _live_source(trade):
    """qualification.source label for a freshly frozen live trade.

    Attribution only: 'live_breakout' (breakout add-on, BRK_* level),
    'live_no_chase' (no-chase re-anchor), else 'live_next_open'."""
    t = trade or {}
    if t.get('breakout'):
        return 'live_breakout'
    if t.get('no_chase_reanchor'):
        return 'live_no_chase'
    return 'live_next_open'


def _freeze_trade(instrument, day_iso, trade):
    """Persist the one-trade-a-day lock + frozen trade (live mode only).

    Idempotent per (instrument, date): the UNIQUE daily lock makes a second
    attempt a no-op. Returns True when THIS call created the freeze."""
    import json as _json
    import sqlite3
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo as _ZI
    from app.core.db import get_conn
    now = _dt.now(_ZI('Asia/Kolkata')).isoformat()
    tid = f'QT-{instrument}-{day_iso}'
    conn = get_conn()
    try:
        conn.execute(
            'INSERT INTO daily_trade_locks (lock_id, instrument_id, date, status,'
            ' trade_id, locked_at, consumed_at, created_at)'
            ' VALUES (?,?,?,?,?,?,?,?)',
            (f'LCK-{instrument}-{day_iso}', instrument, day_iso, 'CONSUMED', tid,
             now, now, now))
        conn.execute(
            'INSERT INTO qualified_trades (trade_id, instrument_id, date, timestamp,'
            ' scenario, strategy, objective, direction, entry, stop, target,'
            ' max_risk, expected_reward, risk_reward, qualification_evidence,'
            ' status, daily_lock_consumed, created_at)'
            ' VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (tid, instrument, day_iso, trade.get('entry_time') or now,
             trade.get('scenario') or '', trade.get('strategy') or '',
             trade.get('objective') or '', trade.get('direction') or '',
             trade.get('entry'), trade.get('stop'), trade.get('target'),
             trade.get('max_risk'), trade.get('expected_reward'),
             round((trade.get('expected_reward') or 0.0) / (trade.get('max_risk') or 1.0), 3),
              _json.dumps({'signal_time': trade.get('signal_time'),
                           'source': _live_source(trade),
                           'no_chase_reanchor': bool(trade.get('no_chase_reanchor')),
                           'breakout': bool(trade.get('breakout')),
                           'feed_n': trade.get('feed_n'),
                           'feed_first_ts': trade.get('feed_first_ts'),
                           'forming_ts': trade.get('forming_ts')}),
             'ACTIVE', 1, now))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        try:
            conn.rollback()
        except Exception:
            pass
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


class LiveEngine:
    """Production decision path. Inject fns for tests/dry-run."""

    def __init__(self, quote_fn=None, candles_fn=None, settings=None):
        from app.market.provider import MarketDataProvider
        from app.core.qualification import QualificationEngine
        self.provider = MarketDataProvider()
        self.qualification = QualificationEngine(settings) if settings else QualificationEngine()
        self.quote_fn = quote_fn or self._default_quote
        self.candles_fn = candles_fn or self._default_candles

    def _default_quote(self, instrument):
        symbol = {'NIFTY': '^NSEI', 'BANKNIFTY': '^NSEBANK', 'INDIA_VIX': '^INDIAVIX'}.get(instrument, instrument)
        return self.provider.get_quote(symbol)

    def _default_candles(self, instrument, completed_ts):
        symbol = {'NIFTY': '^NSEI', 'BANKNIFTY': '^NSEBANK', 'INDIA_VIX': '^INDIAVIX'}.get(instrument, instrument)
        res = self.provider.get_5m_candles(symbol)
        if res.get('state') not in ('LIVE',):
            return []
        day = completed_ts.date().isoformat()
        # Include the candle that opens at completed_ts+5m (the currently
        # forming one) so _cpr_book_signal can use its OPEN as the next-open
        # entry price. It is never scanned for triggers (Oct-12 divergence
        # fix). Completed-candle gates still filter this out (see evaluate).
        nxt = (completed_ts + timedelta(minutes=CANDLE_MINUTES)).isoformat()
        return [c for c in res.get('candles', [])
                if c.get('timestamp', '')[:10] == day and c.get('timestamp', '') <= nxt]

    def evaluate(self, instrument, now=None, dry_run=False):
        """Full gated evaluation. dry_run=True performs zero DB writes."""
        now_ist = (now or datetime.now(_IST))
        if now_ist.tzinfo is None:
            now_ist = now_ist.replace(tzinfo=_IST)
        completed = completed_candle_ts(now_ist)
        quote = self.quote_fn(instrument) or {}
        quote_age_s = quote.get('age_seconds')

        base = {'instrument': instrument, 'now_ist': now_ist.isoformat(),
                'completed_candle': completed.isoformat() if completed else None,
                'live_price': quote.get('price'),
                'quote_timestamp': quote.get('timestamp'),
                'quote_age_seconds': quote_age_s,
                'change': quote.get('change'),
                'change_pct': quote.get('change_pct'),
                'quote_state': quote.get('state'),
                'decision_source': 'live_dry_run' if dry_run else 'live'}

        if completed is None:
            sess = session_state(now_ist, has_data_today=True)
            state = sess if sess in (ST_PREMARKET, ST_CLOSED, ST_WEEKEND) else ST_NO_DATA
            base.update(state=state, session=sess,
                        reasons=['NO_COMPLETED_CANDLE_YET'])
            _log_state(base)
            return base

        age_min = (now_ist - completed).total_seconds() / 60.0
        base['completed_age_minutes'] = round(age_min, 2)

        all_candles = self.candles_fn(instrument, completed) or []
        # Completed-candle gates (session, integrity, market state) see only
        # candles up to `completed`; the forming candle is used solely as the
        # same-instant entry open inside _cpr_book_signal (never validated,
        # never priced).
        candles = [c for c in all_candles
                   if str(c.get('timestamp', '')) <= completed.isoformat()]
        sess = session_state(now_ist, has_data_today=bool(candles))
        base['session'] = sess
        if sess != 'LIVE':
            hn = holiday_name(now_ist.date())
            if hn and sess == ST_NO_DATA:
                # Explicit NSE holiday: closed, with the reason named.
                base.update(state=ST_CLOSED, reasons=[f'HOLIDAY_{hn}'])
            else:
                base.update(state=sess if sess in _SESSION_PASSTHROUGH else ST_NO_DATA,
                            reasons=[f'SESSION_{sess}'])
            _log_state(base)
            return base

        if age_min > STALE_AFTER_MIN:
            base.update(state=ST_STALE,
                        reasons=[f'DATA_STALE:completed_candle_age_min={age_min:.1f}'])
            _log_state(base)
            return base

        ok, issues, usable = validate_candles(candles, completed)
        # The forming candle (completed+5m) is the only timestamp past the last
        # completed candle that a same-instant entry legitimately needs. Anything
        # beyond it is future data: reject (no lookahead), same as before.
        nxt_iso = (completed + timedelta(minutes=CANDLE_MINUTES)).isoformat()
        future = [c for c in all_candles
                  if str(c.get('timestamp', '')) > nxt_iso]
        if future:
            ok = False
            issues = issues + [f'FUTURE_CANDLE:{c.get("timestamp")}' for c in future]
        if not ok:
            # Dead feed (data existed today but newest row is older than the
            # stale threshold) is STALE, not NO_DATA: it must never silently
            # become a tradable state, and the frontend must say so.
            newest = max((c.get('timestamp', '') for c in candles), default='')
            try:
                gap_min = (now_ist - datetime.fromisoformat(newest)).total_seconds() / 60.0
            except ValueError:
                gap_min = None
            base['feed_newest'] = newest or None
            base['feed_gap_minutes'] = round(gap_min, 2) if gap_min is not None else None
            if gap_min is not None and gap_min > STALE_AFTER_MIN:
                base.update(state=ST_STALE,
                            reasons=[f'FEED_STALE:gap_min={gap_min:.1f}'] + issues)
            else:
                base.update(state=ST_NO_DATA, reasons=issues)
            _log_state(base)
            return base

        price = float(usable['close'])
        base.update(decision_price=price, decision_timestamp=completed.isoformat())
        ms = build_market_state(price, candles)
        # Unified rulebook: CPR-trigger book (same trigger math as backtest/
        # paper) over completed candles only. A trigger on the latest completed
        # candle fires as soon as the next candle's open is known (that open
        # is past fact, so the entry matches backtest tick-for-tick).
        book = _cpr_book_signal(instrument, all_candles, completed,
                                live_price=quote.get('price'), now=now_ist)
        trade = book.get('trade')
        day_iso = completed.date().isoformat()
        # Serve the frozen trade once one exists (stability for the alert
        # exit-sweep); otherwise freeze a freshly-fired live trade (write path
        # only). dry_run never writes and never freezes.
        frozen = _frozen_trade(instrument, day_iso)
        if frozen is not None and not _frozen_trade_passes_gate(frozen, day_iso):
            frozen = None
        if frozen is not None:
            trade = frozen
        elif trade is not None and not dry_run:
            if not _freeze_trade(instrument, day_iso, trade):
                base.update(state=ST_NO_TRADE, qualification='NO_TRADE',
                            reasons=['DAILY_TRADE_LIMIT_REACHED'], market_state=ms)
                _log_state(base)
                return base
        if trade is not None:
            base.update(state=ST_QUALIFIED, qualification='QUALIFIED_TRADE',
                        reasons=(['FROZEN_TRADE_ACTIVE'] if frozen is not None
                                 else book.get('reasons', [])),
                        trade=trade, market_state=ms)
        else:
            base.update(state=ST_NO_TRADE, qualification='NO_TRADE',
                        reasons=book.get('reasons', []), market_state=ms)
        _log_state(base)
        return base
