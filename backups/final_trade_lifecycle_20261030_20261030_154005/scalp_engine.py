"""Scalp engine (connected HLC price-action): 3-bar alignment trigger.

Global (cross-session) 3-bar alignment: three consecutive 5m bars whose
high/low/close all move the same way. Entry at the next candle open.
Matches the research in ~/scalp/connected_hlc_price_action (~464 NIFTY trades).
"""
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.db import get_conn

_IST = ZoneInfo('Asia/Kolkata')

VALID = ('NIFTY', 'BANKNIFTY', 'INDIA_VIX')
VARIANTS = ('plain',)

COST_POINTS = 1.0  # 0.5 + 0.5


def _load_candles(instrument):
    conn = get_conn()
    rows = conn.execute(
        'SELECT timestamp,open,high,low,close FROM market_candles_5m '
        'WHERE instrument_id=? ORDER BY timestamp', (instrument,)).fetchall()
    conn.close()
    out = []
    for r in rows:
        out.append({'timestamp': r['timestamp'],
                    'open': float(r['open']), 'high': float(r['high']),
                    'low': float(r['low']), 'close': float(r['close']),
                    'date': str(r['timestamp'])[:10]})
    return out


def _features(candles):
    feats = []
    for i in range(1, len(candles)):
        p, c = candles[i - 1], candles[i]
        feats.append((c['high'] - p['high'], c['low'] - p['low'], c['close'] - p['close']))
    return feats


def _scan_signals(candles):
    feats = _features(candles)  # length len(candles)-1
    sigs = []
    for i in range(5, len(feats)):
        tri = feats[i-2:i+1]
        if any(f is None for f in tri):
            continue
        up = all(f[0] > 0 and f[1] > 0 and f[2] > 0 for f in tri)
        down = all(f[0] < 0 and f[1] < 0 and f[2] < 0 for f in tri)
        if not (up or down):
            continue
        sigs.append((i, 'BULL' if up else 'BEAR'))
    # Also detect a signal at the last candle using only the 3 most recent
    # candles (no entry candle needed for signal detection). This allows the
    # live engine to fire as soon as the signal candle is completed and
    # ingested, without waiting for the entry candle (~5 min ingestion delay).
    if len(candles) >= 3:
        i = len(candles) - 1
        c2, c1, c0 = candles[i-2], candles[i-1], candles[i]
        up = (c0['high'] > c1['high'] > c2['high'] and
              c0['low'] > c1['low'] > c2['low'] and
              c0['close'] > c1['close'] > c2['close'])
        down = (c0['high'] < c1['high'] < c2['high'] and
                c0['low'] < c1['low'] < c2['low'] and
                c0['close'] < c1['close'] < c2['close'])
        if up or down:
            sigs.append((i, 'BULL' if up else 'BEAR'))
    return sigs, feats


def _trade_for(candles, idx, direction):
    c = candles[idx]
    if idx + 1 >= len(candles):
        return None
    nc = candles[idx + 1]
    entry = nc['open']
    if direction == 'BULL':
        stop = float(c['low']) - 1.0
        risk = float(entry) - stop
        target = float(entry) + risk * 1.5
    else:
        stop = float(c['high']) + 1.0
        risk = stop - float(entry)
        target = float(entry) - risk * 1.5
    if risk <= 0:
        return None
    pnl_gross = None
    exit_px = None
    exit_reason = None
    exit_ts = None
    for k in range(idx + 1, len(candles)):
        bar = candles[k]
        if bar['date'] != nc['date']:
            break
        if direction == 'BULL':
            hit_stop = bar['low'] <= stop
            hit_target = bar['high'] >= target
        else:
            hit_stop = bar['high'] >= stop
            hit_target = bar['low'] <= target
        if hit_stop and hit_target:
            pnl_gross = (stop - entry) if direction == 'BULL' else (entry - stop)
            exit_px = stop
            exit_reason = 'STOP (both same candle)'
            exit_ts = bar['timestamp']
            break
        if hit_stop:
            pnl_gross = (stop - entry) if direction == 'BULL' else (entry - stop)
            exit_px = stop
            exit_reason = 'STOP'
            exit_ts = bar['timestamp']
            break
        if hit_target:
            pnl_gross = (target - entry) if direction == 'BULL' else (entry - target)
            exit_px = target
            exit_reason = 'TARGET'
            exit_ts = bar['timestamp']
            break
    if pnl_gross is None:
        last_close = nc['close']
        last_ts = nc['timestamp']
        for k in range(idx + 1, len(candles)):
            if candles[k]['date'] != nc['date']:
                break
            last_close = candles[k]['close']
            last_ts = candles[k]['timestamp']
        pnl_gross = (last_close - entry) if direction == 'BULL' else (entry - last_close)
        exit_px = last_close
        exit_reason = 'EOD'
        exit_ts = last_ts
    r_multiple = round(pnl_gross / risk, 3) if risk else 0.0
    points = round((exit_px - entry) if direction == 'BULL' else (entry - exit_px), 2)
    win_loss = 'WIN' if r_multiple > 0 else ('LOSS' if r_multiple < 0 else 'FLAT')
    level = 'H1_UP' if direction == 'BULL' else 'H1_DOWN'
    return {
        'trade_date': nc['date'],
        'direction': direction,
        'level': level,
        'entry': round(float(entry), 2),
        'stop': round(float(stop), 2),
        'target': round(float(target), 2),
        'entry_time': nc['timestamp'],
        'exit': round(float(exit_px), 2),
        'exit_time': exit_ts,
        'exit_reason': exit_reason,
        'r_multiple': r_multiple,
        'points': points,
        'win_loss': win_loss,
        'signal_time': c['timestamp'],
    }


def run_range(instrument, date_start, date_end):
    inst = (instrument or '').upper()
    if inst not in VALID:
        return {'error': 'UNKNOWN_INSTRUMENT'}
    candles = _load_candles(inst)
    # filter by date range on trade_date (entry day)
    sigs, _ = _scan_signals(candles)
    trades = []
    for idx, direction in sigs:
        t = _trade_for(candles, idx, direction)
        if t is None:
            continue
        if not (date_start <= t['trade_date'] <= date_end):
            continue
        trades.append(t)
    rs = [t['r_multiple'] for t in trades]
    n = len(rs)
    w = sum(1 for t in trades if (t['r_multiple'] or 0) > 0)
    in_range = [c for c in candles if date_start <= c['date'] <= date_end]
    sessions = len({c['date'] for c in in_range})
    trade_days = len({t['trade_date'] for t in trades})
    by_level = {}
    for t in trades:
        k = f"{t['direction']}/{t['level']}"
        e = by_level.setdefault(k, {'n': 0, 'wins': 0, 'R': 0.0})
        e['n'] += 1
        e['R'] = round(e['R'] + t['r_multiple'], 2)
        if (t['r_multiple'] or 0) > 0:
            e['wins'] += 1
    return {'instrument': inst, 'date_start': date_start, 'date_end': date_end,
            'days': sessions,
            'signals': n, 'no_signal_days': max(0, sessions - trade_days), 'wins': w,
            'losses': sum(1 for t in trades if (t['r_multiple'] or 0) < 0),
            'win_rate': round(100 * w / n, 1) if n else 0,
            'total_R': round(sum(rs), 2) if n else 0,
            'avg_R': round(sum(rs) / n, 3) if n else 0,
            'by_level': by_level, 'trades': trades}


def _valid_range(date_start, date_end):
    try:
        from datetime import datetime as _dt
        s = _dt.strptime(date_start, '%Y-%m-%d').date().isoformat()
        e = _dt.strptime(date_end, '%Y-%m-%d').date().isoformat()
        return (s, e) if s <= e else None
    except (TypeError, ValueError):
        return None


def run_opens_range(instrument, date_start, date_end, variant='plain',
                    stop_pct=0.005, target_pct=0.02):
    inst = (instrument or '').upper()
    if inst not in VALID:
        return {'error': 'UNKNOWN_INSTRUMENT'}
    if variant not in VARIANTS:
        return {'error': 'UNKNOWN_VARIANT'}
    rng = _valid_range(date_start, date_end)
    if not rng:
        return {'error': 'INVALID_DATE_RANGE'}
    date_start, date_end = rng
    r = run_range(inst, date_start, date_end)
    # normalize keys expected by paper/backtest callers
    r['variant'] = variant
    r['date_start'] = date_start
    r['date_end'] = date_end
    return r


def _live_signal(candles, idx, direction, inst, day_iso, variant):
    """One completed signal for display/live execution (no future fills).

    If the entry candle (idx+1) is not yet in the data (not ingested into
    market_candles_5m), entry/entry_time/target/risk are returned as None.
    The caller (paper_scalp_live.py) resolves the entry price from the live
    provider at trade creation time.
    """
    from datetime import timedelta as _td
    c = candles[idx]
    entry = None
    entry_time = None
    trade_date = str(c['timestamp'])[:10]
    stop = float(c['low']) - 1.0 if direction == 'BULL' else float(c['high']) + 1.0
    if idx + 1 < len(candles):
        nc = candles[idx + 1]
        entry = float(nc['open'])
        entry_time = nc['timestamp']
        trade_date = nc['timestamp'][:10]
    else:
        # Entry candle not yet ingested: compute its timestamp as 5 minutes
        # after the signal candle (5-minute bar boundaries).
        signal_dt = datetime.fromisoformat(str(c['timestamp']).replace('Z', '+00:00'))
        entry_dt = signal_dt + _td(minutes=5)
        entry_time = entry_dt.isoformat()
        trade_date = str(entry_dt)[:10]
    target = None
    risk = None
    if entry is not None:
        if direction == 'BULL':
            risk = entry - stop
        else:
            risk = stop - entry
        if risk > 0:
            if direction == 'BULL':
                target = entry + risk * 1.5
            else:
                target = entry - risk * 1.5
    return {'instrument': inst, 'variant': variant, 'date': day_iso,
            'state': 'SIGNAL', 'direction': direction,
            'level': 'H1_UP' if direction == 'BULL' else 'H1_DOWN',
            'signal_time': c['timestamp'], 'trade_date': trade_date,
            'entry': round(entry, 2) if entry is not None else None,
            'entry_time': entry_time,
            'stop': round(stop, 2),
            'target': round(target, 2) if target is not None else None,
            'risk': round(risk, 2) if risk is not None else None,
            'levels': None, 'note': None}


def today_signals(instrument, now_ist=None, variant='plain'):
    """Every completed qualifying signal whose entry day is today."""
    st = today_state(instrument, now_ist=now_ist, variant=variant)
    if isinstance(st, dict) and isinstance(st.get('signals'), list):
        return st['signals']
    return []


def today_state(instrument, now_ist=None, variant='plain'):
    inst = (instrument or '').upper()
    if inst not in VALID:
        return {'error': 'UNKNOWN_INSTRUMENT'}
    if variant not in VARIANTS:
        return {'error': 'UNKNOWN_VARIANT'}
    now = now_ist or datetime.now(_IST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=_IST)
    day_iso = now.date().isoformat()
    all_candles = _load_candles(inst)
    candles = [c for c in all_candles if c['timestamp'] <= now.isoformat()]
    sigs, _ = _scan_signals(candles)
    # ALL completed signals whose entry day is today (canonical research).
    completed = []
    for idx, direction in sigs:
        # Entry candle may not yet be ingested into market_candles_5m (yfinance
        # provides completed candles with ~5 min delay). If idx+1 is out of
        # range, the entry candle is not yet available; _live_signal will
        # return a signal with entry=None, and the caller resolves the entry
        # price from the live provider at trade creation time.
        if idx + 1 < len(candles) and candles[idx + 1]['date'] != day_iso:
            continue
        s = _live_signal(candles, idx, direction, inst, day_iso, variant)
        if s is not None:
            completed.append(s)
    base = {'instrument': inst, 'variant': variant, 'date': day_iso,
            'signals': completed, 'signal_count': len(completed),
            'candles_so_far': len(candles),
            'last_candle': candles[-1]['timestamp'] if candles else None}
    if not completed:
        base.update({'state': 'WATCH', 'reason': 'NO_SIGNAL_YET'})
        return base
    latest = dict(completed[-1])
    base.update(latest)
    base['signals'] = completed
    base['signal_count'] = len(completed)
    return base


def scalp_signal(*a, **k):
    return today_state(*a, **k)


DECAY_TOL_POINTS = {'NIFTY': 30.0, 'BANKNIFTY': 60.0, 'INDIA_VIX': 0.02}

def decay_win(direction, entry, exit_px, r_multiple, instrument):
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
