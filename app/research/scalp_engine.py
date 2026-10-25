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
        if i + 1 >= len(candles):
            continue
        sigs.append((i, 'BULL' if up else 'BEAR'))
    return sigs, feats


def _trade_for(candles, idx, direction):
    c = candles[idx]
    nc = candles[idx + 1]
    if direction == 'BULL':
        entry = nc['open']
        stop = c['low'] - 1.0
        risk = entry - stop
        target = entry + risk * 1.5
    else:
        entry = nc['open']
        stop = c['high'] + 1.0
        risk = stop - entry
        target = entry - risk * 1.5
    if risk <= 0 or risk > 40:
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
    by_level = {}
    for t in trades:
        k = f"{t['direction']}/{t['level']}"
        e = by_level.setdefault(k, {'n': 0, 'wins': 0, 'R': 0.0})
        e['n'] += 1
        e['R'] = round(e['R'] + t['r_multiple'], 2)
        if (t['r_multiple'] or 0) > 0:
            e['wins'] += 1
    return {'instrument': inst, 'date_start': date_start, 'date_end': date_end,
            'days': len({c['date'] for c in candles}),
            'signals': n, 'no_signal_days': 0, 'wins': w,
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
    # first signal whose entry day == today
    today_sig = None
    for idx, direction in sigs:
        if candles[idx + 1]['date'] == day_iso:
            today_sig = (idx, direction)
            break
    if today_sig is None:
        # maybe signal candle today but entry next day
        for idx, direction in sigs:
            if candles[idx]['date'] == day_iso:
                today_sig = (idx, direction)
                break
    if today_sig is None:
        return {'instrument': inst, 'variant': variant, 'date': day_iso,
                'state': 'WATCH', 'reason': 'NO_SIGNAL_YET',
                'candles_so_far': len(candles)}
    idx, direction = today_sig
    c = candles[idx]
    nc = candles[idx + 1] if idx + 1 < len(candles) else None
    entry = entry_time = note = None
    if nc is not None and nc['date'] == day_iso:
        entry = round(float(nc['open']), 2)
        entry_time = nc['timestamp']
    elif nc is not None:
        note = 'ENTRY_AT_NEXT_OPEN'
    else:
        note = 'ENTRY_AT_NEXT_OPEN'
    if entry is not None:
        stop = entry * (0.995 if direction == 'BULL' else 1.005)
        tgt = entry * (1.02 if direction == 'BULL' else 0.98)
        stop, tgt = round(stop, 2), round(tgt, 2)
    else:
        stop = tgt = None
    return {'instrument': inst, 'variant': variant, 'date': day_iso,
            'state': 'SIGNAL', 'direction': direction,
            'level': 'H1_UP' if direction == 'BULL' else 'H1_DOWN',
            'signal_time': c['timestamp'],
            'entry': entry, 'entry_time': entry_time, 'stop': stop, 'target': tgt,
            'levels': None, 'note': note, 'candles_so_far': len(candles),
            'last_candle': candles[-1]['timestamp'] if candles else None}


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
