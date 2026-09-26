"""No-filter CPR trigger strategy (approved offline as vix_regime variant without VIX gate).

Bull triggers: candle low touches S2 / S1 / PDL (prev-day low), or close above TC.
Bear triggers: candle high touches R2 / R1 / PDH (prev-day high), or close below BC.
First trigger per session wins.

Two executions (run_opens_* = approved spec; legacy close/intrabar kept for
run_range/today_state/log_trigger history):
- opens: entry at next candle OPEN in [09:20, 15:10); stops/targets evaluated
  at subsequent opens (stop first); flat at 15:10 OPEN. Days <10 candles skipped.
- variant 'aligned': bull signal needs close above WEEKLY TC, bear needs close
  below WEEKLY BC (weekly CPR over prior 5 sessions).

Read-only vs the market DB (SELECT only). Shared by:
- POST /api/backtest/cpr-triggers (date-range backtest, variant param)
- GET /api/strategy/cpr-triggers (today's trigger state, read-only)
- scripts/paper_confluence.py log_trigger() [legacy] / log_align() [opens]
"""
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.db import get_conn
from app.research.cpr_strategy_engine import calculate_cpr, pivot_levels

_IST = ZoneInfo('Asia/Kolkata')

VALID = ('NIFTY', 'BANKNIFTY', 'INDIA_VIX')

STOP_PCT = 0.01
TARGET_PCT = 0.02


def day_levels(prev_high, prev_low, prev_close):
    """CPR + PDH/PDL bundle from previous-session OHLC. None-safe."""
    try:
        ph, pl, pc = float(prev_high), float(prev_low), float(prev_close)
    except (TypeError, ValueError):
        return None
    if not (ph > 0 and pl > 0 and pc > 0 and ph >= pl):
        return None
    cpr = calculate_cpr(ph, pl, pc)
    piv = pivot_levels(ph, pl, cpr['pp'])
    return {'pp': cpr['pp'], 'tc': cpr['tc'], 'bc': cpr['bc'],
            'r1': piv['r1'], 's1': piv['s1'], 'r2': piv['r2'], 's2': piv['s2'],
            'pdh': ph, 'pdl': pl, 'prev_close': pc}


def bull_trigger(candle, lv):
    """Return level name or None. Checks support touches first, then CPR break."""
    try:
        lo, cl = float(candle['low']), float(candle['close'])
    except (KeyError, TypeError, ValueError):
        return None
    if lo <= lv['s2']:
        return 'S2'
    if lo <= lv['s1']:
        return 'S1'
    if lo <= lv['pdl']:
        return 'PDL'
    if cl > lv['tc']:
        return 'ABOVE_CPR'
    return None


def bear_trigger(candle, lv):
    """Return level name or None. Checks resistance touches first, then CPR break."""
    try:
        hi, cl = float(candle['high']), float(candle['close'])
    except (KeyError, TypeError, ValueError):
        return None
    if hi >= lv['r2']:
        return 'R2'
    if hi >= lv['r1']:
        return 'R1'
    if hi >= lv['pdh']:
        return 'PDH'
    if cl < lv['bc']:
        return 'BELOW_CPR'
    return None


def first_trigger(day_candles, lv):
    """First (direction, level, index) trigger of the session, else None."""
    for i, c in enumerate(day_candles):
        t = bear_trigger(c, lv) or bull_trigger(c, lv)
        if t:
            dr = 'BEAR' if bear_trigger(c, lv) else 'BULL'
            return {'direction': dr, 'level': t, 'index': i,
                    'timestamp': c.get('timestamp')}
    return None


def exit_trade(direction, entry, fwd_candles):
    """Walk forward candles. Returns (R_multiple, exit_price, exit_reason)."""
    if direction == 'BULL':
        stop, tgt = entry * (1 - STOP_PCT), entry * (1 + TARGET_PCT)
    else:
        stop, tgt = entry * (1 + STOP_PCT), entry * (1 - TARGET_PCT)
    risk = abs(entry - stop)
    for c in fwd_candles:
        try:
            hi, lo, cl = float(c['high']), float(c['low']), float(c['close'])
        except (KeyError, TypeError, ValueError):
            continue
        if direction == 'BULL':
            s, t = lo <= stop, hi >= tgt
            if s and t:
                return -1.0, cl, 'STOP (both same candle)'
            if s:
                return -1.0, cl, 'STOP'
            if t:
                return 2.0, cl, 'TARGET'
        else:
            s, t = hi >= stop, lo <= tgt
            if s and t:
                return -1.0, cl, 'STOP (both same candle)'
            if s:
                return -1.0, cl, 'STOP'
            if t:
                return 2.0, cl, 'TARGET'
    last = None
    for c in reversed(fwd_candles):
        try:
            last = float(c['close'])
            break
        except (KeyError, TypeError, ValueError):
            continue
    if last is None or not risk:
        return 0.0, entry, 'NO_FORWARD_DATA'
    move = (last - entry) if direction == 'BULL' else (entry - last)
    return round(move / risk, 3), last, 'EOD'


def prev_session_ohlc(conn, instrument, day_iso):
    """Max high / min low / last close strictly before day_iso. None if absent."""
    row = conn.execute(
        'SELECT substr(timestamp,1,10) AS d, MAX(high) AS h, MIN(low) AS l '
        'FROM market_candles_5m WHERE instrument_id=? AND substr(timestamp,1,10)<? '
        'GROUP BY d ORDER BY d DESC LIMIT 1', (instrument, day_iso)).fetchone()
    if not row or row['h'] is None:
        return None
    last = conn.execute(
        'SELECT close FROM market_candles_5m WHERE instrument_id=? '
        'AND substr(timestamp,1,10)=? ORDER BY timestamp DESC LIMIT 1',
        (instrument, row['d'])).fetchone()
    if not last or last['close'] is None:
        return None
    return {'date': row['d'], 'high': float(row['h']),
            'low': float(row['l']), 'close': float(last['close'])}


def session_candles(conn, instrument, day_iso):
    rows = conn.execute(
        'SELECT timestamp,open,high,low,close FROM market_candles_5m '
        'WHERE instrument_id=? AND substr(timestamp,1,10)=? ORDER BY timestamp',
        (instrument, day_iso)).fetchall()
    return [dict(r) for r in rows]


def run_range(instrument, date_start, date_end):
    """Backtest over stored sessions in [start, end]. Returns summary dict."""
    inst = (instrument or '').upper()
    if inst not in VALID:
        return {'error': 'UNKNOWN_INSTRUMENT'}
    conn = get_conn()
    try:
        days = [r[0] for r in conn.execute(
            'SELECT DISTINCT substr(timestamp,1,10) FROM market_candles_5m '
            'WHERE instrument_id=? AND substr(timestamp,1,10) BETWEEN ? AND ? ORDER BY 1',
            (inst, date_start, date_end)).fetchall()]
        trades, no_signal = [], 0
        for d in days:
            prev = prev_session_ohlc(conn, inst, d)
            if not prev:
                continue
            lv = day_levels(prev['high'], prev['low'], prev['close'])
            if not lv:
                continue
            candles = session_candles(conn, inst, d)
            if not candles:
                continue
            sig = first_trigger(candles, lv)
            if not sig:
                no_signal += 1
                continue
            entry = float(candles[sig['index']]['close'])
            r, exit_px, how = exit_trade(sig['direction'], entry, candles[sig['index'] + 1:])
            trades.append({'trade_date': d, 'direction': sig['direction'],
                           'level': sig['level'], 'entry': round(entry, 2),
                           'exit': round(exit_px, 2), 'r_multiple': r,
                           'exit_reason': how,
                           'signal_time': sig.get('timestamp')})
    finally:
        conn.close()
    rs = [t['r_multiple'] for t in trades]
    w = sum(1 for r in rs if r > 0)
    n = len(rs)
    by_level = {}
    for t in trades:
        k = f"{t['direction']}/{t['level']}"
        e = by_level.setdefault(k, {'n': 0, 'wins': 0, 'R': 0.0})
        e['n'] += 1
        e['R'] = round(e['R'] + t['r_multiple'], 2)
        if t['r_multiple'] > 0:
            e['wins'] += 1
    return {'instrument': inst, 'date_start': date_start, 'date_end': date_end,
            'days': len(trades) + no_signal, 'signals': n,
            'no_signal_days': no_signal, 'wins': w,
            'losses': sum(1 for r in rs if r < 0),
            'win_rate': round(100 * w / n, 1) if n else 0,
            'total_R': round(sum(rs), 2) if n else 0,
            'avg_R': round(sum(rs) / n, 3) if n else 0,
            'by_level': by_level, 'trades': trades}


OPEN_STOP_PCT = 0.005
OPEN_TARGET_PCT = 0.02

# Display-only cost placeholder for net-R reporting (does NOT alter trades,
# R multiples, or history): 0.10R per round trip ≈ brokerage + STT + slippage
# on typical retail size. Replace with measured brokerage when available.
COST_R_PER_TRADE = 0.10


def today_state(instrument, now_ist=None, variant='aligned'):
    """Today's trigger state from stored candles so far (opens execution).

    Same math as run_opens_range: first trigger (bear priority), weekly gate
    when variant='aligned', entry at next candle OPEN when available (else
    entry stays None with note ENTRY_AT_NEXT_OPEN). Read-only."""
    inst = (instrument or '').upper()
    if inst not in VALID:
        return {'error': 'UNKNOWN_INSTRUMENT'}
    if variant not in VARIANTS:
        return {'error': 'UNKNOWN_VARIANT'}
    now = now_ist or datetime.now(_IST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=_IST)
    day_iso = now.date().isoformat()
    conn = get_conn()
    try:
        prev = prev_session_ohlc(conn, inst, day_iso)
        if not prev:
            return {'instrument': inst, 'variant': variant, 'date': day_iso,
                    'state': 'NO_DATA', 'reason': 'CPR_DATA_UNAVAILABLE'}
        lv = day_levels(prev['high'], prev['low'], prev['close'])
        wlv = weekly_levels(conn, inst, monday_of(day_iso)) if variant == 'aligned' else None
        if variant == 'aligned' and not wlv:
            return {'instrument': inst, 'variant': variant, 'date': day_iso,
                    'state': 'WATCH', 'levels': lv,
                    'reason': 'WEEKLY_GATE_MISSING'}
        candles = [c for c in session_candles(conn, inst, day_iso)
                   if c['timestamp'] <= now.isoformat()]
    finally:
        conn.close()
    if not candles:
        return {'instrument': inst, 'variant': variant, 'date': day_iso,
                'state': 'WATCH', 'levels': lv, 'reason': 'NO_CANDLES_YET'}
    sig = None
    for i, c in enumerate(candles):
        b = bear_trigger(c, lv)
        u = bull_trigger(c, lv)
        t = b or u
        if not t:
            continue
        dr = 'BEAR' if b else 'BULL'
        if variant == 'aligned' and not aligned_ok(dr, c['close'], wlv):
            continue
        sig = (dr, t, i)
        break
    if not sig:
        return {'instrument': inst, 'variant': variant, 'date': day_iso,
                'state': 'WATCH', 'levels': lv,
                'candles_so_far': len(candles),
                'last_candle': candles[-1]['timestamp']}
    dr, t, i = sig
    if i + 1 < len(candles):
        entry = float(candles[i + 1]['open'])
        note = None
    else:
        entry, note = None, 'ENTRY_AT_NEXT_OPEN'
    if entry is not None:
        if dr == 'BULL':
            stop, tgt = entry * (1 - OPEN_STOP_PCT), entry * (1 + OPEN_TARGET_PCT)
        else:
            stop, tgt = entry * (1 + OPEN_STOP_PCT), entry * (1 - OPEN_TARGET_PCT)
        entry, stop, tgt = round(entry, 2), round(stop, 2), round(tgt, 2)
    else:
        stop = tgt = None
    return {'instrument': inst, 'variant': variant, 'date': day_iso,
            'state': 'SIGNAL', 'direction': dr, 'level': t,
            'signal_time': candles[i]['timestamp'],
            'entry': entry, 'stop': stop, 'target': tgt, 'levels': lv,
            'note': note, 'candles_so_far': len(candles),
            'last_candle': candles[-1]['timestamp']}


VARIANTS = ('plain', 'aligned')

DECAY_TOL_POINTS = {'NIFTY': 30.0, 'BANKNIFTY': 60.0, 'INDIA_VIX': 0.02}
# Tolerances ≈ 0.11-0.17% of typical price (30/24000, 60/55000, 0.02/12):
# same relative band per instrument; VIX is indicative-only (non-tradable).


def decay_win(direction, entry, exit_px, r_multiple, instrument):
    """Short-premium decay reclassification (pure).

    A small adverse drift (under the per-instrument points tolerance) counts
    as WIN: overnight/day theta on a short spread outweighs it. Full stops
    and large drifts stay losses. Spot R is never rewritten — only the label."""
    try:
        if r_multiple is None:
            return None
        if r_multiple > 0:
            return 'WIN'
        if r_multiple < 0:
            tol = DECAY_TOL_POINTS.get((instrument or '').upper(), 30.0)
            pts = (float(exit_px) - float(entry)) if direction == 'BULL' else (float(entry) - float(exit_px))
            if abs(pts) < tol:
                return 'WIN'
            return 'LOSS'
        return 'FLAT'
    except (TypeError, ValueError):
        return None

OPEN_MIN = '09:20'
OPEN_MAX = '15:10'
OPEN_EOD = '15:10'
MIN_CANDLES = 10


def aligned_ok(direction, close, wlv):
    """Weekly-alignment gate (pure). Bull needs close above weekly TC,
    bear needs close below weekly BC. Missing wlv fails closed."""
    try:
        cl = float(close)
    except (TypeError, ValueError):
        return False
    if not wlv:
        return False
    if direction == 'BULL':
        return cl > wlv['tc']
    if direction == 'BEAR':
        return cl < wlv['bc']
    return False


def weekly_levels(conn, instrument, monday_iso, min_sessions=3):
    """Weekly CPR bundle over prior sessions before monday_iso.

    Returns None when fewer than min_sessions distinct prior sessions exist
    (fail-closed: first week of history gates nothing). Callers count such
    days as gate-missing, never as trades."""
    rows = conn.execute(
        'SELECT substr(timestamp,1,10) AS d, high, low, close FROM market_candles_5m '
        'WHERE instrument_id=? AND substr(timestamp,1,10)<? ORDER BY timestamp DESC LIMIT 375',
        (instrument, monday_iso)).fetchall()
    if not rows:
        return None
    if len({r['d'] for r in rows}) < min_sessions:
        return None
    try:
        return day_levels(max(r['high'] for r in rows), min(r['low'] for r in rows),
                          rows[0]['close'])
    except (TypeError, ValueError):
        return None


def monday_of(day_iso):
    from datetime import datetime as _dt, timedelta as _td
    dt = _dt.strptime(day_iso, '%Y-%m-%d').date()
    return (dt - _td(days=dt.weekday())).isoformat()


def exits_opens(direction, entry, stop_pct, target_pct, opens):
    """Walk subsequent candle OPENS. Returns (R, exit_px, reason, exit_ts).

    opens: list of (timestamp, open) AFTER the entry candle. Stop first."""
    risk = abs(entry * stop_pct)
    if not risk:
        return 0.0, entry, 'NO_RISK', None
    if direction == 'BULL':
        stop, tgt = entry * (1 - stop_pct), entry * (1 + target_pct)
    else:
        stop, tgt = entry * (1 + stop_pct), entry * (1 - target_pct)
    for ts, o in opens:
        try:
            o = float(o)
        except (TypeError, ValueError):
            continue
        if direction == 'BULL':
            s, t = o <= stop, o >= tgt
        else:
            s, t = o >= stop, o <= tgt
        if s:
            return -1.0, round(o, 2), 'STOP', ts
        if t:
            return round(target_pct / stop_pct, 3), round(o, 2), 'TARGET', ts
    return None


def _valid_range(date_start, date_end):
    """YYYY-MM-DD + start<=end. Returns (start, end) or None."""
    try:
        from datetime import datetime as _dt
        s = _dt.strptime(date_start, '%Y-%m-%d').date().isoformat()
        e = _dt.strptime(date_end, '%Y-%m-%d').date().isoformat()
        return (s, e) if s <= e else None
    except (TypeError, ValueError):
        return None


def run_opens_range(instrument, date_start, date_end, variant='plain',
                    stop_pct=0.005, target_pct=0.02):
    """Approved-spec backtest: opens execution + optional weekly alignment.

    Rules (all deliberate, see boundaries below):
    - signal: first trigger/session over candles < 15:15; BEAR checked before
      BULL, so a same-candle double-touch counts BEAR. Within a side the
      first listed level wins (S2>S1>PDL>ABOVE_CPR; R2>R1>PDH>BELOW_CPR),
      so PDL/PDH only fire when S1/R1 did not.
    - entry: next candle OPEN in [09:20, 15:10); later signals that day ignored.
    - exits: subsequent OPENS only; an open exactly on stop counts STOP;
      an open exactly on target counts TARGET; stop checked before target;
      a stop exactly at the 15:10 open labels STOP (not EOD).
    - flat: 15:10 OPEN. Missing 15:10 candle -> missing_eod (not a signal).
    - decay: |adverse points| < tolerance (NIFTY 30 / BANKNIFTY 60 /
      INDIA_VIX 0.02, ~0.11-0.17% of price) labels WIN; exactly at tolerance
      stays LOSS. Spot R is never rewritten.
    - wins AND losses both derive from win_loss (single label definition).

    Read-only. `days` = signals + every skipped bucket (no silent drops)."""
    inst = (instrument or '').upper()
    if inst not in VALID:
        return {'error': 'UNKNOWN_INSTRUMENT'}
    if variant not in VARIANTS:
        return {'error': 'UNKNOWN_VARIANT'}
    rng = _valid_range(date_start, date_end)
    if not rng:
        return {'error': 'INVALID_DATE_RANGE'}
    date_start, date_end = rng
    conn = get_conn()
    try:
        days = [r[0] for r in conn.execute(
            'SELECT DISTINCT substr(timestamp,1,10) FROM market_candles_5m '
            'WHERE instrument_id=? AND substr(timestamp,1,10) BETWEEN ? AND ? ORDER BY 1',
            (inst, date_start, date_end)).fetchall()]
        trades = []
        skipped = {'no_signal': 0, 'short_day': 0, 'missing_eod': 0,
                   'gate_missing': 0, 'bad_data': 0}
        for d in days:
            prev = prev_session_ohlc(conn, inst, d)
            if not prev:
                skipped['bad_data'] += 1
                continue
            lv = day_levels(prev['high'], prev['low'], prev['close'])
            if not lv:
                skipped['bad_data'] += 1
                continue
            wlv = weekly_levels(conn, inst, monday_of(d)) if variant == 'aligned' else None
            if variant == 'aligned' and not wlv:
                skipped['gate_missing'] += 1
                continue
            candles = [c for c in session_candles(conn, inst, d)
                       if c['timestamp'][11:16] < '15:15']
            if len(candles) < MIN_CANDLES:
                skipped['short_day'] += 1
                continue
            sig = None
            for i, c in enumerate(candles):
                b = bear_trigger(c, lv)
                u = bull_trigger(c, lv)
                t = b or u
                if not t:
                    continue
                dr = 'BEAR' if b else 'BULL'
                if variant == 'aligned' and not aligned_ok(dr, c['close'], wlv):
                    continue
                if i + 1 >= len(candles):
                    continue
                nt = candles[i + 1]['timestamp']
                if not (OPEN_MIN <= nt[11:16] < OPEN_EOD):
                    continue
                sig = (dr, t, i)
                break
            if not sig:
                skipped['no_signal'] += 1
                continue
            dr, t, i = sig
            try:
                entry = float(candles[i + 1]['open'])
            except (KeyError, TypeError, ValueError):
                skipped['bad_data'] += 1
                continue
            nt = candles[i + 1]['timestamp']
            opens = [(c['timestamp'], c['open']) for c in candles[i + 2:]]
            eod = [c for c in candles if c['timestamp'][11:16] == OPEN_EOD]
            if not eod:
                skipped['missing_eod'] += 1
                continue
            hit = exits_opens(dr, entry, stop_pct, target_pct, opens)
            if hit is None:
                try:
                    last = float(eod[0]['open'])
                except (KeyError, TypeError, ValueError):
                    skipped['bad_data'] += 1
                    continue
                risk = abs(entry * stop_pct)
                move = (last - entry) if dr == 'BULL' else (entry - last)
                r = round(move / risk, 3) if risk else 0.0
                xp, how, xt = round(last, 2), 'EOD-1510', eod[0]['timestamp']
            else:
                r, xp, how, xt = hit
            pts = round((xp - entry) if dr == 'BULL' else (entry - xp), 1)
            trades.append({'trade_date': d, 'direction': dr, 'level': t,
                           'entry_time': nt[:16].replace('T', ' '),
                           'entry': round(entry, 2),
                           'exit_time': (xt or '')[:16].replace('T', ' '),
                           'exit': xp, 'r_multiple': r, 'exit_reason': how,
                           'points': pts, 'signal_time': candles[i]['timestamp'],
                           'win_loss': decay_win(dr, entry, xp, r, inst)})
    finally:
        conn.close()
    rs = [t['r_multiple'] for t in trades]
    w = sum(1 for t in trades if t.get('win_loss') == 'WIN')
    n = len(rs)
    losses = sum(1 for t in trades if t.get('win_loss') == 'LOSS')
    by_level = {}
    for t in trades:
        k = f"{t['direction']}/{t['level']}"
        e = by_level.setdefault(k, {'n': 0, 'wins': 0, 'R': 0.0})
        e['n'] += 1
        e['R'] = round(e['R'] + t['r_multiple'], 2)
        if t.get('win_loss') == 'WIN':
            e['wins'] += 1
    losses = sum(1 for t in trades if t.get('win_loss') == 'LOSS')
    by_level = {}
    for t in trades:
        k = f"{t['direction']}/{t['level']}"
        e = by_level.setdefault(k, {'n': 0, 'wins': 0, 'R': 0.0})
        e['n'] += 1
        e['R'] = round(e['R'] + t['r_multiple'], 2)
        if t.get('win_loss') == 'WIN':
            e['wins'] += 1
    return {'instrument': inst, 'variant': variant,
            'date_start': date_start, 'date_end': date_end,
            'days': n + sum(skipped.values()), 'signals': n,
            'no_signal_days': skipped['no_signal'], 'skipped': skipped,
            'wins': w,
            'losses': losses,
            'win_rate': round(100 * w / n, 1) if n else 0,
            'total_R': round(sum(rs), 2) if n else 0,
            'avg_R': round(sum(rs) / n, 3) if n else 0,
            'net_R': round(sum(rs) - COST_R_PER_TRADE * n, 2) if n else 0,
            'cost_note': 'net_R deducts %.2fR/trade estimated costs; gross total_R unchanged' % COST_R_PER_TRADE,
            'by_level': by_level, 'trades': trades}
