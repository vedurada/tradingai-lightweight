"""Chronological price-path reconstruction from the recorded 5-minute candles.

Definitions mirror the parent study (stop_forensics/src/execution.py) so the
numbers are comparable with Phase 3:

  excursion window : bars from the entry bar up to and including the exit bar
  MAE / MFE        : adverse / favourable extreme of high-low, plus the
                     open-based variant that matches the execution model
  forward path     : signed return from the exit fill to the close of the first
                     candle at or after the horizon, with the worst / best
                     intrabar excursion inside the same window

Nothing here uses a candle that was not closed at or before the moment it is
used for.
"""
from . import config

TS = 16          # 'YYYY-MM-DD HH:MM' length


def _minute(ts):
    return int(ts[11:13]) * 60 + int(ts[14:16])


def _day(ts):
    return ts[:10]


def load_candles(conn):
    """{instrument: {date: [bar, ...]}} with bars sorted by timestamp."""
    from . import dbutil
    out = {}
    for row in dbutil.rows(conn, config.T_CANDLES, order='timestamp, instrument_id'):
        if not row.get('is_complete'):
            continue
        ts = str(row['timestamp'])[:10] + ' ' + str(row['timestamp'])[11:16]
        bar = {'timestamp': ts,
               'open': float(row['open']), 'high': float(row['high']),
               'low': float(row['low']), 'close': float(row['close'])}
        out.setdefault(row['instrument_id'], {}).setdefault(ts[:10], []).append(bar)
    for inst in out:
        for day in out[inst]:
            out[inst][day].sort(key=lambda b: b['timestamp'])
    return out


def session(candles, instrument, date):
    return candles.get(instrument, {}).get(date, [])


def find_index(bars, ts16, price, tolerance=config.PRICE_TOLERANCE):
    """Index of the bar whose open produced the recorded fill.

    The engine books entries and exits at candle OPENS, so the recorded price
    must match that bar's open. The timestamp is used to disambiguate; when the
    price does not match any open the bar containing the timestamp is used and
    the mismatch is reported.
    """
    if not bars or not ts16:
        return None, 'no_bars'
    price_match = None
    for i, bar in enumerate(bars):
        if abs(bar['open'] - price) <= tolerance:
            price_match = i
            break
    ts_match = None
    for i, bar in enumerate(bars):
        if bar['timestamp'][:TS] <= ts16:
            ts_match = i
        else:
            break
    if ts_match is None:
        ts_match = 0
    if price_match is not None:
        if price_match == ts_match:
            return ts_match, 'price_and_timestamp_match'
        if abs(price_match - ts_match) <= 1:
            return price_match, 'price_match_adjacent_bar'
        return price_match, 'price_match_other_bar'
    return ts_match, 'timestamp_only_price_mismatch'


def excursion(direction, entry, bars, entry_idx, exit_ts16):
    """Intrabar and open-based adverse/favourable excursion over the window."""
    adverse = favourable = o_adverse = o_favourable = None
    n = 0
    mae_ts = mfe_ts = None
    for bar in bars[entry_idx:]:
        if exit_ts16 and bar['timestamp'][:TS] > exit_ts16:
            break
        n += 1
        hi, lo, o = bar['high'], bar['low'], bar['open']
        if direction == 'BULL':
            a, f = lo, hi
            oa, of = min(o, lo), max(o, hi)
        else:
            a, f = hi, lo
            oa, of = max(o, hi), min(o, lo)
        if adverse is None or (a < adverse if direction == 'BULL' else a > adverse):
            adverse = a
            mae_ts = bar['timestamp']
        if favourable is None or (f > favourable if direction == 'BULL' else f < favourable):
            favourable = f
            mfe_ts = bar['timestamp']
        o_adverse = oa if o_adverse is None else (min(o_adverse, oa) if direction == 'BULL'
                                                  else max(o_adverse, oa))
        o_favourable = of if o_favourable is None else (max(o_favourable, of) if direction == 'BULL'
                                                        else min(o_favourable, of))
    if n == 0:
        return {'mae_hl_pts': 0.0, 'mfe_hl_pts': 0.0, 'mae_open_pts': 0.0,
                'mfe_open_pts': 0.0, 'bars_held': 0}
    mae_pts = (entry - adverse) if direction == 'BULL' else (adverse - entry)
    mfe_pts = (favourable - entry) if direction == 'BULL' else (entry - favourable)
    mae_open_pts = (entry - o_adverse) if direction == 'BULL' else (o_adverse - entry)
    mfe_open_pts = (o_favourable - entry) if direction == 'BULL' else (entry - o_favourable)
    out = {'mae_hl_pts': round(mae_pts, 4), 'mfe_hl_pts': round(mfe_pts, 4),
           'mae_open_pts': round(mae_open_pts, 4), 'mfe_open_pts': round(mfe_open_pts, 4),
           'bars_held': n, 'mae_ts': mae_ts, 'mfe_ts': mfe_ts}
    return out


def ambiguity(direction, stop_px, target_px, bars, entry_idx, exit_ts16):
    """Bars in which both the stop and the target could have been touched."""
    ambiguous = 0
    for bar in bars[entry_idx + 1:]:
        if exit_ts16 and bar['timestamp'][:TS] > exit_ts16:
            break
        hi, lo = bar['high'], bar['low']
        if direction == 'BULL':
            both = hi >= target_px and lo <= stop_px
        else:
            both = hi >= stop_px and lo <= target_px
        if both:
            ambiguous += 1
    return ambiguous


def first_touch(direction, stop_px, target_px, bars, entry_idx, exit_idx):
    """Which level was reached first, using highs/lows and using opens."""
    hl_stop = hl_target = None
    op_stop = op_target = None
    for i in range(entry_idx, len(bars)):
        bar = bars[i]
        if exit_idx is not None and i > exit_idx:
            break
        hi, lo, o = bar['high'], bar['low'], bar['open']
        if hl_stop is None or hl_target is None:
            if direction == 'BULL':
                if hl_stop is None and lo <= stop_px:
                    hl_stop = i
                if hl_target is None and hi >= target_px:
                    hl_target = i
            else:
                if hl_stop is None and hi >= stop_px:
                    hl_stop = i
                if hl_target is None and lo <= target_px:
                    hl_target = i
        if op_stop is None and ((direction == 'BULL' and o <= stop_px) or
                                (direction != 'BULL' and o >= stop_px)):
            op_stop = i
        if op_target is None and ((direction == 'BULL' and o >= target_px) or
                                  (direction != 'BULL' and o <= target_px)):
            op_target = i
    def _first(a, b):
        if a is None and b is None:
            return 'NEITHER'
        if a is None:
            return 'TARGET'
        if b is None:
            return 'STOP'
        return 'STOP' if a <= b else 'TARGET'
    return {'first_touch_hl': _first(hl_stop, hl_target),
            'first_touch_open': _first(op_stop, op_target),
            'stop_bar_hl': hl_stop, 'target_bar_hl': hl_target,
            'stop_bar_open': op_stop, 'target_bar_open': op_target,
            'both_levels_same_bar_hl': bool(hl_stop is not None and hl_target is not None
                                            and hl_stop == hl_target)}


def forward_path(direction, exit_price, bars, exit_idx, risk_pts,
                 horizons=config.FWD_HORIZONS):
    """Parent-compatible forward path from the exit fill."""
    out = {}
    if exit_idx is None or exit_idx >= len(bars):
        for h in horizons:
            out[f'fwd{h}_r'] = None
            out[f'fwd{h}_pts'] = None
            out[f'fwd{h}_worst_r'] = None
            out[f'fwd{h}_best_r'] = None
        return out
    base_ts = bars[exit_idx]['timestamp']
    day = _day(base_ts)
    for h in horizons:
        target_min = _minute(base_ts) + h
        horizon_idx = None
        for j in range(exit_idx + 1, len(bars)):
            if _day(bars[j]['timestamp']) != day:
                break
            if _minute(bars[j]['timestamp']) >= target_min:
                horizon_idx = j
                break
        if horizon_idx is None:
            out[f'fwd{h}_r'] = None
            out[f'fwd{h}_pts'] = None
            out[f'fwd{h}_worst_r'] = None
            out[f'fwd{h}_best_r'] = None
            continue
        close = bars[horizon_idx]['close']
        pts = (close - exit_price) if direction == 'BULL' else (exit_price - close)
        worst = 0.0
        best = 0.0
        for j in range(exit_idx + 1, horizon_idx + 1):
            hi, lo = bars[j]['high'], bars[j]['low']
            if direction == 'BULL':
                adverse = lo - exit_price
                favourable = hi - exit_price
            else:
                adverse = exit_price - hi
                favourable = exit_price - lo
            worst = min(worst, adverse)
            best = max(best, favourable)
        out[f'fwd{h}_r'] = round(pts / risk_pts, 4) if risk_pts else None
        out[f'fwd{h}_pts'] = round(pts, 3)
        out[f'fwd{h}_worst_r'] = round(worst / risk_pts, 4) if risk_pts else None
        out[f'fwd{h}_best_r'] = round(best / risk_pts, 4) if risk_pts else None
    return out


def post_exit_category(forward, risk_pts):
    """Mutually exclusive post-exit category using the primary 60-minute window.

    CONTINUATION_AGAINST  the underlying moved further against the position
    REVERSAL_TOWARD_TARGET the underlying moved back in the trade's direction
    CHOP                   the underlying stayed inside a narrow band
    """
    worst = forward.get('fwd60_worst_r')
    best = forward.get('fwd60_best_r')
    if worst is None and best is None:
        return 'NOT_ASSESSABLE'
    worst = worst or 0.0
    best = best or 0.0
    if worst <= -config.CONTINUATION_R:
        return 'CONTINUATION_AGAINST'
    if best >= config.REVERSAL_R:
        return 'REVERSAL_TOWARD_TARGET'
    if abs(best - worst) < config.CHOP_R:
        return 'CHOP'
    return 'MIXED'


def features(record, path, candles, level_price=None):
    """Entry-time features that need both the candle path and the level price.

    `pre_entry_move_pct`  net move of the 12 closed bars before the entry,
                          signed in the trade direction.
    `level_crossed_after_entry`  price traded through the level by more than
                          the trigger band after the entry (a failed breakout).
    `is_choppy`  the 12 bars before the entry had a range below 0.25 %.
    """
    inst = record['instrument']
    date = record['session_date']
    bars = candles.get(inst, {}).get(date, [])
    entry_ts = (record.get('entry_time') or '')[:TS]
    before = [b for b in bars if b['timestamp'][:TS] < entry_ts]
    window = before[-config.CHOP_BARS:] if before else []
    out = {'pre_entry_bars': len(window)}
    if window:
        hi = max(b['high'] for b in window)
        lo = min(b['low'] for b in window)
        out['pre_entry_range_pct'] = round((hi - lo) / window[-1]['close'] * 100, 4)
        out['is_choppy'] = bool(out['pre_entry_range_pct'] < config.CHOP_RANGE_PCT * 100)
        net = window[-1]['close'] - window[0]['open']
        sign = config.direction_sign(record.get('direction'))
        out['pre_entry_move_pct'] = round(net / window[0]['open'] * 100 * sign, 4)
    else:
        out['pre_entry_range_pct'] = None
        out['is_choppy'] = None
        out['pre_entry_move_pct'] = None
    crossings = 0
    crossed_back = 0
    failed_breakout = False
    if level_price:
        entry_idx = path.get('entry_index')
        exit_idx = path.get('exit_index')
        if entry_idx is not None:
            end_idx = len(bars) - 1 if exit_idx is None else min(exit_idx, len(bars) - 1)
            prev_side = None
            traded_favourable = False
            for i in range(entry_idx, end_idx + 1):
                bar = bars[i]
                # a crossing is a change of side of the level between two bars
                side = 'above' if bar['close'] > level_price else 'below'
                if prev_side is not None and side != prev_side:
                    crossings += 1
                prev_side = side
                # a failed breakout: the price traded through the level in the
                # direction of the trade and then closed back beyond it
                if record.get('direction') == 'BULL':
                    if bar['high'] > level_price * (1 + config.CONTINUATION_TRIGGER_PCT):
                        traded_favourable = True
                    elif traded_favourable and bar['close'] < level_price:
                        crossed_back += 1
                        failed_breakout = True
                        traded_favourable = False
                else:
                    if bar['low'] < level_price * (1 - config.CONTINUATION_TRIGGER_PCT):
                        traded_favourable = True
                    elif traded_favourable and bar['close'] > level_price:
                        crossed_back += 1
                        failed_breakout = True
                        traded_favourable = False
    out['level_crossings_after_entry'] = crossings
    out['level_crossed_after_entry'] = crossings > 0
    out['level_crossed_back_after_entry'] = crossed_back
    out['failed_breakout_after_entry'] = failed_breakout
    return out


def reconstruct(record, candles):
    """Full price path for one ledger record."""
    bars = session(candles, record['instrument'], record['session_date'])
    out = {'bars_in_session': len(bars)}
    if not bars:
        out['path_status'] = 'NO_CANDLES'
        return out
    entry_ts = (record.get('entry_time') or '')[:TS]
    exit_ts = (record.get('exit_time') or '')[:TS]
    entry_idx, entry_match = find_index(bars, entry_ts, record['entry_price'] or 0)
    exit_idx, exit_match = find_index(bars, exit_ts, record['exit_price'] or 0)
    out['entry_index'] = entry_idx
    out['entry_index_match'] = entry_match
    out['exit_index'] = exit_idx
    out['exit_index_match'] = exit_match
    out['path_status'] = 'OK'
    if entry_idx is None:
        out['path_status'] = 'NO_ENTRY_BAR'
        return out
    if record.get('entry_price') is None:
        out['path_status'] = 'NO_ENTRY_PRICE'
        return out
    direction = record['direction']
    entry = record['entry_price']
    risk_pts = record['risk_pts']
    exc = excursion(direction, entry, bars, entry_idx, exit_ts)
    out.update(exc)
    if risk_pts:
        out['mae_hl_r'] = round(exc['mae_hl_pts'] / risk_pts, 4)
        out['mfe_hl_r'] = round(exc['mfe_hl_pts'] / risk_pts, 4)
        out['mae_open_r'] = round(exc['mae_open_pts'] / risk_pts, 4)
        out['mfe_open_r'] = round(exc['mfe_open_pts'] / risk_pts, 4)
    if record.get('stop_price') and record.get('target_price'):
        out['intrabar_ambiguous_bars'] = ambiguity(
            direction, record['stop_price'], record['target_price'], bars, entry_idx, exit_ts)
        out.update(first_touch(direction, record['stop_price'],
                               record['target_price'], bars, entry_idx, exit_idx))
    if exit_idx is not None and record.get('exit_price') is not None and risk_pts:
        fwd = forward_path(direction, record['exit_price'], bars, exit_idx, risk_pts)
        out.update(fwd)
        out['post_exit_category'] = post_exit_category(fwd, risk_pts)
        out['stop_then_continued_loose'] = bool(
            fwd.get('fwd60_worst_r') is not None and fwd['fwd60_worst_r'] < 0)
        out['stop_then_reversed_loose'] = bool(
            fwd.get('fwd60_best_r') is not None and fwd['fwd60_best_r'] > 0)
    else:
        out['post_exit_category'] = 'NOT_ASSESSABLE'
    if record.get('exit_price') is not None and record.get('stop_price') is not None:
        sign = config.direction_sign(direction)
        # positive when the exit is worse than the stop (an adverse overshoot)
        overshoot = (record['stop_price'] - record['exit_price']) * sign
        out['stop_overshoot_pts'] = round(overshoot, 3)
        out['stop_overshoot_r'] = round(overshoot / risk_pts, 4) if risk_pts else None
    return out
