"""Structure that was knowable at the moment of entry.

Only information that existed at or before the entry timestamp is used:
the previous session's levels, pivot levels derived from them, the running
session extremes up to the entry bar (a partial CPR), and swings that were
already confirmed at the entry bar.

No future candle, no future session high/low and no future-confirmed swing is
used anywhere in this module.
"""
from . import config

TS = 16


def _session_dates(candles, instrument):
    return sorted(candles.get(instrument, {}).keys())


def previous_session(candles, instrument, date):
    dates = [d for d in _session_dates(candles, instrument) if d < date]
    return dates[-1] if dates else None


def session_stats(bars):
    if not bars:
        return None
    return {'high': max(b['high'] for b in bars),
            'low': min(b['low'] for b in bars),
            'close': bars[-1]['close'],
            'first_ts': bars[0]['timestamp'],
            'last_ts': bars[-1]['timestamp']}


def pivots(prev):
    if not prev:
        return {}
    p = (prev['high'] + prev['low'] + prev['close']) / 3.0
    rng = prev['high'] - prev['low']
    return {'P': p, 'R1': 2 * p - prev['low'], 'R2': p + rng, 'S1': 2 * p - prev['high'],
            'S2': p - rng, 'PDH': prev['high'], 'PDL': prev['low']}


def confirmed_swings(bars_before_entry, lookback=config.LEVEL_LOOKBACK_BARS):
    """Swing highs / lows confirmed with data available at the entry bar.

    A swing high at bar i is confirmed at the entry if bar i's high is the
    highest of the bars after it up to (and including) the entry bar. No bar
    after the entry is used.
    """
    window = bars_before_entry[-lookback:] if bars_before_entry else []
    highs, lows = [], []
    for i, bar in enumerate(window):
        after = window[i + 1:]
        if not after:
            continue
        if bar['high'] > max(b['high'] for b in after):
            highs.append({'ts': bar['timestamp'], 'price': bar['high']})
        if bar['low'] < min(b['low'] for b in after):
            lows.append({'ts': bar['timestamp'], 'price': bar['low']})
    return {'swing_highs': highs, 'swing_lows': lows}


def build(record, candles):
    """Reconstruct the entry-time structure for one trade."""
    inst = record['instrument']
    date = record['session_date']
    if not inst or not date:
        return {'prev_session_date': None, 'prev_high': None, 'prev_low': None,
                'prev_close': None, 'bars_before_entry': 0,
                'running_high_at_entry': None, 'running_low_at_entry': None,
                'level_price': None, 'level_price_source': 'UNKNOWN',
                'pivots': {}, 'swings': {'swing_highs': [], 'swing_lows': []},
                'known_levels_at_entry': [], 'touches_before_entry': None,
                'entry_is_first_touch': None, 'touch_condition': None,
                'nearest_invalidation': None, 'stop_beyond_invalidation': None,
                'stop_inside_ordinary_move': None, 'invalidation_name': None,
                'invalidation_price': None, 'entry_extension_pct': None,
                'distance_to_level_pts': None}
    bars = candles.get(inst, {}).get(date, [])
    entry_ts = (record.get('entry_time') or '')[:TS]
    before = [b for b in bars if b['timestamp'][:TS] < entry_ts]
    upto = [b for b in bars if b['timestamp'][:TS] <= entry_ts]
    prev_date = previous_session(candles, inst, date)
    prev_bars = candles.get(inst, {}).get(prev_date, []) if prev_date else []
    prev = session_stats(prev_bars)
    out = {
        'prev_session_date': prev_date,
        'prev_high': prev['high'] if prev else None,
        'prev_low': prev['low'] if prev else None,
        'prev_close': prev['close'] if prev else None,
        'bars_before_entry': len(before),
        'running_high_at_entry': max((b['high'] for b in upto), default=None),
        'running_low_at_entry': min((b['low'] for b in upto), default=None),
        'level_price': None,
        'level_price_source': 'UNKNOWN',
    }
    out['pivots'] = pivots(prev)
    out['swings'] = confirmed_swings(before)
    level = (record.get('level') or '').upper()
    entry = record.get('entry_price')
    pv = out['pivots']
    if level == 'PDH' and pv.get('PDH'):
        out['level_price'], out['level_price_source'] = pv['PDH'], 'PREV_DAY_HIGH'
    elif level == 'PDL' and pv.get('PDL'):
        out['level_price'], out['level_price_source'] = pv['PDL'], 'PREV_DAY_LOW'
    elif level == 'R1' and pv.get('R1'):
        out['level_price'], out['level_price_source'] = pv['R1'], 'PIVOT_R1'
    elif level == 'R2' and pv.get('R2'):
        out['level_price'], out['level_price_source'] = pv['R2'], 'PIVOT_R2'
    elif level == 'S1' and pv.get('S1'):
        out['level_price'], out['level_price_source'] = pv['S1'], 'PIVOT_S1'
    elif level == 'BELOW_CPR':
        # The CPR lower boundary is intraday: only the running low of the
        # session up to the entry bar is knowable at the entry.
        if out['running_low_at_entry']:
            out['level_price'] = out['running_low_at_entry']
            out['level_price_source'] = 'RUNNING_SESSION_LOW (partial CPR at entry)'
    elif level == 'ABOVE_CPR':
        if out['running_high_at_entry']:
            out['level_price'] = out['running_high_at_entry']
            out['level_price_source'] = 'RUNNING_SESSION_HIGH (partial CPR at entry)'
    if out['level_price'] and entry:
        out['entry_extension_pct'] = round(
            (entry - out['level_price']) / out['level_price'] * 100.0, 4)
    else:
        out['entry_extension_pct'] = None
    out['distance_to_level_pts'] = (round(entry - out['level_price'], 3)
                                     if out['level_price'] and entry else None)
    # Pre-existing levels that were known at the entry.
    known = []
    if pv.get('PDH'):
        known.append({'name': 'PREV_DAY_HIGH', 'price': pv['PDH']})
    if pv.get('PDL'):
        known.append({'name': 'PREV_DAY_LOW', 'price': pv['PDL']})
    for name in ('R1', 'R2', 'S1'):
        if pv.get(name):
            known.append({'name': 'PIVOT_' + name, 'price': pv[name]})
    for sh in out['swings']['swing_highs']:
        known.append({'name': 'SWING_HIGH', 'price': sh['price'], 'ts': sh['ts']})
    for sl in out['swings']['swing_lows']:
        known.append({'name': 'SWING_LOW', 'price': sl['price'], 'ts': sl['ts']})
    out['known_levels_at_entry'] = known
    # Was the entry the FIRST touch of the level in this session?
    # The production engine enters on the first qualifying touch, so this
    # measures whether the level had already been visited before the entry
    # (a retest) or not (no retest, no wait).
    touches_before = 0
    entry_is_first_touch = None
    if out['level_price'] and entry:
        # The price reaches the level from above when the level is below the
        # entry (support / breakdown) and from below when the level is above
        # the entry (resistance / breakout).
        from_above = out['level_price'] <= entry
        for bar in before:
            hit = (bar['low'] <= out['level_price']) if from_above \
                else (bar['high'] >= out['level_price'])
            if hit:
                touches_before += 1
        out['touches_before_entry'] = touches_before
        out['entry_is_first_touch'] = touches_before == 0
        out['touch_condition'] = ('low <= level (level below the entry)'
                                  if from_above else
                                  'high >= level (level above the entry)')
    else:
        out['touches_before_entry'] = None
        out['entry_is_first_touch'] = None
        out['touch_condition'] = None
    # Nearest structural invalidation for the position (opposite side).
    sign = config.direction_sign(record.get('direction'))
    stop = record.get('stop_price')
    entry = record.get('entry_price')
    if entry and sign < 0:
        above = [k for k in known if k['price'] > entry]
        invalidation = min(above, key=lambda k: k['price']) if above else None
    elif entry:
        below = [k for k in known if k['price'] < entry]
        invalidation = max(below, key=lambda k: k['price']) if below else None
    else:
        invalidation = None
    # the ordinary noise band of the session before the entry (12 bars)
    recent = before[-config.PHASE3_EXPIRY_BARS:] if before else []
    if recent:
        out['pre_entry_range_pts'] = round(
            max(b['high'] for b in recent) - min(b['low'] for b in recent), 3)
    else:
        out['pre_entry_range_pts'] = None
    out['nearest_invalidation'] = invalidation
    out['stop_beyond_invalidation'] = None
    out['stop_inside_ordinary_move'] = None
    if stop and entry and invalidation:
        stop_dist = abs(stop - entry)
        invalid_dist = abs(invalidation['price'] - entry)
        out['stop_beyond_invalidation'] = stop_dist > invalid_dist
        out['invalidation_name'] = invalidation['name']
        out['invalidation_price'] = invalidation['price']
    elif stop and entry:
        out['invalidation_name'] = None
        out['stop_beyond_invalidation'] = None
    if stop and entry:
        stop_dist = abs(stop - entry)
        # the stop sat inside the ordinary noise band of the session
        out['stop_inside_ordinary_move'] = (
            out['pre_entry_range_pts'] is not None
            and stop_dist <= out['pre_entry_range_pts'])
    return out


def confirmation_state(record, candles, level_info=None):
    """Was a rejection close available at the level before the entry?

    Uses only bars that closed at or before the entry bar. A rejection close is
    a candle that closed back beyond the level in the direction of the trade
    (Phase 3 rule C1_CLOSE_BACK):

      BULL trade (support)  touch  = bar low  <= level
                            confirm= bar close > level
      BEAR trade (resistance) touch = bar high >= level
                            confirm= bar close < level

    For the CPR boundary levels the boundary is intraday, so the running
    session extreme that existed BEFORE each bar is used as that bar's level.
    """
    inst = record['instrument']
    date = record['session_date']
    bars = candles.get(inst, {}).get(date, [])
    entry_ts = (record.get('entry_time') or '')[:TS]
    before = [b for b in bars if b['timestamp'][:TS] < entry_ts]
    window = before[-config.PHASE3_EXPIRY_BARS:] if before else []
    level = (record.get('level') or '').upper()
    result = {'bars_in_confirmation_window': len(window),
              'rejection_close_before_entry': None,
              'touch_before_entry': None,
              'note': None}
    if not window:
        result['note'] = 'no bars before the entry'
        return result
    if level_info is None:
        level_info = build(record, candles)
    level_price = level_info.get('level_price')
    sign = config.direction_sign(record.get('direction'))
    if level in ('BELOW_CPR', 'ABOVE_CPR'):
        running = None
        touches = 0
        rejection = False
        for bar in window:
            if running is not None:
                if level == 'BELOW_CPR':
                    touched = bar['low'] <= running
                else:
                    touched = bar['high'] >= running
                if touched:
                    touches += 1
                    # the close back beyond the boundary in the direction of
                    # the trade is the Phase 3 C1 confirmation
                    closed_back = (bar['close'] > running) if sign > 0 \
                        else (bar['close'] < running)
                    if closed_back:
                        rejection = True
            if level == 'BELOW_CPR':
                running = bar['low'] if running is None else min(running, bar['low'])
            else:
                running = bar['high'] if running is None else max(running, bar['high'])
        result['touch_before_entry'] = touches
        result['rejection_close_before_entry'] = rejection
        result['note'] = ('partial CPR boundary: the running session extreme that '
                          'existed before each bar is used as that bar level')
        return result
    if not level_price:
        result['note'] = 'the level price could not be reconstructed'
        result['touch_before_entry'] = None
        result['rejection_close_before_entry'] = None
        return result
    entry = record.get('entry_price')
    # the price reaches a level that lies below the entry from above, and a
    # level that lies above the entry from below
    from_above = entry is None or level_price <= entry
    touches = 0
    rejection = False
    for bar in window:
        touched = (bar['low'] <= level_price) if from_above \
            else (bar['high'] >= level_price)
        if touched:
            touches += 1
            closed_back = (bar['close'] > level_price) if sign > 0 \
                else (bar['close'] < level_price)
            if closed_back:
                rejection = True
    result['touch_before_entry'] = touches
    result['rejection_close_before_entry'] = rejection
    result['note'] = ('pre-existing level: the Phase 3 C1 rejection close is '
                      'used as the confirmation test')
    return result
