"""Entry rules E0-E6 and the forward outcome measurement.

Every rule is causal: the signal is fixed on a closed bar and the entry is
always the OPEN of a LATER bar. Rules that cannot fire produce a skipped
record with a reason; they are never silently dropped.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as C  # noqa: E402
import data as D  # noqa: E402
import events as E  # noqa: E402
import levels as L  # noqa: E402

WINDOW_BARS = {3: 15, 6: 30, 12: 60}


def next_opposing_level(lv, level, price, direction):
    """The next reference level in the direction of the trade (price order)."""
    order = sorted(L.LEVEL_NAMES, key=lambda k: lv[k])
    try:
        i = order.index(level)
    except ValueError:
        return None, None
    if direction == 'BULL':
        cands = [(k, lv[k]) for k in order[i + 1:]]
        if not cands:
            return None, None
        return min(cands, key=lambda kv: kv[1])
    cands = [(k, lv[k]) for k in order[:i]]
    if not cands:
        return None, None
    return max(cands, key=lambda kv: kv[1])


def _extreme(b, sign):
    return b['h'] if sign > 0 else b['l']


def forward(sess, entry_idx, direction, level, tol, window_bars):
    """Forward outcome of a candidate entry.

    Returns a dict with the signed forward move, MFE, MAE, the times to a
    favourable/adverse move, and the behavioural flags.
    """
    bars = sess['bars']
    n = len(bars)
    sign = 1 if direction == 'BULL' else -1
    entry_price = bars[entry_idx]['o']
    lv = sess['levels']
    p = lv.get(level)
    out = {'entry_price': entry_price, 'window_bars': window_bars,
           'window_minutes': window_bars * 5, 'window_complete': False,
           'forward_move': None, 'mfe': None, 'mae': None,
           'time_to_favourable': None, 'time_to_adverse': None,
           'reversal': None, 'breakout_failure': None,
           'reached_next_level': None, 'next_level': None,
           'room_to_next_level': None, 'bars_available': n - entry_idx}
    if entry_idx >= n:
        return out

    end = min(n, entry_idx + window_bars)
    if entry_idx + window_bars <= n:
        out['window_complete'] = True
    hi = None
    lo = None
    for i in range(entry_idx, end):
        e = sign * (_extreme(bars[i], sign) - entry_price)
        if hi is None or e > hi:
            hi = e
        if lo is None or e < lo:
            lo = e
    out['mfe'] = round(hi, 4) if hi is not None else None
    out['mae'] = round(lo, 4) if lo is not None else None
    if out['window_complete']:
        exit_px = bars[entry_idx + window_bars - 1]['c']
        out['forward_move'] = round(sign * (exit_px - entry_price), 4)
    else:
        exit_px = bars[end - 1]['c']
        out['forward_move'] = round(sign * (exit_px - entry_price), 4)
        out['forward_move_censored'] = True

    thr = C.MOVE_POINTS[sess['instrument']] if 'instrument' in sess \
        else 20.0
    for i in range(entry_idx, end):
        e = sign * (_extreme(bars[i], sign) - entry_price)
        if e >= thr:
            out['time_to_favourable'] = (i - entry_idx + 1) * 5
            break
    for i in range(entry_idx, end):
        e = sign * (_extreme(bars[i], sign) - entry_price)
        if e <= -thr:
            out['time_to_adverse'] = (i - entry_idx + 1) * 5
            break

    # next opposing level
    nl, np_ = next_opposing_level(lv, level, entry_price, direction)
    out['next_level'] = nl
    if np_ is not None:
        room = abs(np_ - entry_price)
        out['room_to_next_level'] = round(room, 4)
        hit = False
        for i in range(entry_idx, end):
            e = sign * (_extreme(bars[i], sign) - entry_price)
            if e >= room - tol:
                hit = True
                break
        out['reached_next_level'] = hit

    # reversal: the price closed beyond the level against the trade
    if p is not None:
        rev = False
        fail = False
        for i in range(entry_idx, end):
            c = bars[i]['c']
            if sign > 0 and c < p - tol:
                rev = True
                fail = True
                break
            if sign < 0 and c > p + tol:
                rev = True
                fail = True
                break
        out['reversal'] = rev
        out['breakout_failure'] = fail
    return out


def room_to_opposing(sess, entry_idx, direction, level, tol):
    lv = sess['levels']
    bars = sess['bars']
    price = bars[entry_idx]['o']
    nl, np_ = next_opposing_level(lv, level, price, direction)
    if np_ is None:
        return None, None
    return nl, abs(np_ - price)


def apply_rules(sess, pat, instrument, tol, variant):
    """Apply E0..E6 to one pattern instance.

    Returns a list of entry records (each with a 'status' of 'ENTERED' or
    'SKIPPED').
    """
    bars = sess['bars']
    n = len(bars)
    lv = sess['levels']
    recs = []

    def mk_entry(rule, entry_idx, extra=None):
        b = bars[entry_idx]
        rec = {'rule': rule, 'status': 'ENTERED', 'entry_idx': entry_idx,
               'entry_ts': b['ts'], 'entry_t': b['t'],
               'entry_price': b['o'], 'direction': pat['direction'],
               'level': pat['level'], 'level_price': pat.get('level_price'),
               'pattern_id': pat['pattern_id'], 'pattern_name': pat['name'],
               'family': pat['family'], 'instrument': instrument,
               'date': sess['date'], 'tol_variant': variant,
               'anchor_idx': pat['anchor_idx'],
               'anchor_t': pat['anchor_t'], 'skip_reason': ''}
        if extra:
            rec.update(extra)
        return rec

    def mk_skip(rule, reason):
        return {'rule': rule, 'status': 'SKIPPED', 'entry_idx': None,
                'entry_ts': '', 'entry_t': '', 'entry_price': None,
                'direction': pat['direction'], 'level': pat['level'],
                'level_price': pat.get('level_price'),
                'pattern_id': pat['pattern_id'], 'pattern_name': pat['name'],
                'family': pat['family'], 'instrument': instrument,
                'date': sess['date'], 'tol_variant': variant,
                'anchor_idx': pat['anchor_idx'], 'anchor_t': pat['anchor_t'],
                'skip_reason': reason}

    def basic_checks(rule, idx):
        if idx is None:
            return None, 'no qualifying bar for the rule'
        if idx >= n:
            return None, 'no bar after the signal inside the session'
        t = bars[idx]['t']
        if not D.entry_eligible(t):
            return None, 'entry bar %s outside the entry window [%s, %s)' % (
                t, C.ENTRY_WINDOW_OPEN, C.ENTRY_WINDOW_CLOSE)
        return idx, ''

    # E0: the next open after the signal bar
    idx, why = basic_checks('E0', pat['anchor_idx'] + 1)
    recs.append(mk_entry('E0', idx) if idx is not None else mk_skip('E0', why))

    # E1: after a completed rejection candle
    rj = pat.get('rejection_idx')
    idx, why = basic_checks('E1', None if rj is None else rj + 1)
    if rj is None:
        recs.append(mk_skip('E1', 'pattern has no rejection candle'))
    else:
        recs.append(mk_entry('E1', idx) if idx is not None
                    else mk_skip('E1', why))

    # E2: after a completed break confirmation and retest
    rt = pat.get('retest_idx')
    idx, why = basic_checks('E2', None if rt is None else rt + 1)
    if rt is None:
        recs.append(mk_skip('E2', 'pattern has no retest'))
    else:
        recs.append(mk_entry('E2', idx) if idx is not None
                    else mk_skip('E2', why))

    # E3: after a failed break and a confirmed reclaim
    rc = pat.get('reclaim_idx')
    idx, why = basic_checks('E3', None if rc is None else rc + 1)
    if rc is None:
        recs.append(mk_skip('E3', 'pattern has no reclaim'))
    else:
        recs.append(mk_entry('E3', idx) if idx is not None
                    else mk_skip('E3', why))

    # E4: wait for a return to the original level within 3 / 6 / 12 bars
    lp = pat.get('level_price')
    for w in (3, 6, 12):
        rule = 'E4_%d' % w
        ridx = None
        if lp is not None:
            for k in range(pat['anchor_idx'] + 1,
                           min(n, pat['anchor_idx'] + 1 + w)):
                if bars[k]['l'] <= lp + tol and bars[k]['h'] >= lp - tol:
                    ridx = k
                    break
        if ridx is None:
            recs.append(mk_skip(rule, 'no return to the level within %d bars'
                                % w))
            continue
        idx, why = basic_checks(rule, ridx + 1)
        recs.append(mk_entry(rule, idx, {'return_idx': ridx})
                    if idx is not None else mk_skip(rule, why))

    # E5: E0 with a minimum room to the next opposing level
    idx, why = basic_checks('E5', pat['anchor_idx'] + 1)
    if idx is None:
        recs.append(mk_skip('E5', why))
    else:
        nl, room = room_to_opposing(sess, idx, pat['direction'],
                                    pat['level'], tol)
        need = C.MIN_ROOM_POINTS[instrument]
        if room is None or room < need:
            recs.append(mk_skip(
                'E5', 'room to the next opposing level %.1f < %.1f points'
                % (room if room is not None else -1, need)))
        else:
            recs.append(mk_entry('E5', idx, {'next_level': nl,
                                             'room_to_next_level': room}))

    # E6: E0 but skip a choppy CPR crossing regime (causal lookback)
    idx, why = basic_checks('E6', pat['anchor_idx'] + 1)
    if idx is None:
        recs.append(mk_skip('E6', why))
    else:
        chops = E.chop_count_in_window(sess, pat['anchor_idx'],
                                        C.CHOP_LOOKBACK)
        if chops >= C.CHOP_CROSSINGS:
            recs.append(mk_skip(
                'E6', 'choppy CPR regime (%d crossings in the previous %d bars)'
                % (chops, C.CHOP_LOOKBACK)))
        else:
            recs.append(mk_entry('E6', idx, {'chop_crossings': chops}))
    return recs
