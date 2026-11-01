"""The 'wait for the setup' entry rules (counterfactual variants).

Every variant is a pure function of the session candles and the trigger index.
No lookahead: a variant may only use candles at or after the trigger bar, and
every decision is taken on a bar close (the fill is either a limit fill inside
that bar's range at the level, or the open of the next bar).
"""
import prodlib as P
import wconfig as C


def _entry_window_ok(ts):
    return C.OPEN_MIN <= ts[11:16] < C.OPEN_EOD


def _skipped(status, **kw):
    out = {'status': status, 'entry_idx': None, 'entry': None,
           'direction': None, 'level': None, 'wait_bars': None}
    out.update(kw)
    return out


def _entered(entry_idx, entry, direction, level, wait_bars):
    return {'status': 'ENTERED', 'entry_idx': entry_idx, 'entry': entry,
            'direction': direction, 'level': level, 'wait_bars': wait_bars}


def _bar(c):
    try:
        return float(c['low']), float(c['high']), float(c['close']), float(c['open'])
    except (KeyError, TypeError, ValueError):
        return None


def _covers_level(c, L):
    """True when the bar's range trades through the level price."""
    b = _bar(c)
    if not b:
        return False
    lo, hi = b[0], b[1]
    return lo <= L <= hi


def v1_wait_setup(candles, i, lv, direction, level, expiry=C.WAIT_EXPIRY_BARS):
    """V1: wait until the price trades back to the setup level and fill there.

    The direction is NOT changed (no flip). The fill is a limit fill at the
    level price when the bar's range covers it. A session in which the price
    never revisits the level is skipped (that is the trade we would not take).
    """
    L = P.level_price(level, lv)
    if L is None:
        return _skipped('NO_LEVEL')
    last = len(candles) if expiry is None else min(len(candles), i + 1 + expiry)
    for j in range(i + 1, last):
        c = candles[j]
        if c['timestamp'][11:16] >= C.OPEN_EOD:
            break
        if not _entry_window_ok(c['timestamp']):
            continue
        if _covers_level(c, L):
            return _entered(j, L, direction, level, j - i)
    return _skipped('EXPIRED' if expiry is not None else 'NO_SETUP')


def v1x_wait_setup_no_expiry(candles, i, lv, direction, level):
    """V1x: as V1 but the wait has no expiry (only the 15:20 entry cut-off)."""
    return v1_wait_setup(candles, i, lv, direction, level, expiry=None)


def _confirmation(c, L, direction, level):
    """Rejection close at the level (decision taken at this bar's close)."""
    b = _bar(c)
    if not b:
        return False
    lo, hi, cl, _ = b
    if direction == 'BULL':
        # the level held as support: the price came back to it and closed above
        return lo <= L and cl > L
    if level == 'BELOW_CPR':
        # the breakdown failed: the price traded below the band and closed back above
        return lo < L and cl > L
    # a resistance rejection: the price tagged the level and closed back below
    return hi >= L and cl < L


def v2_wait_confirm(candles, i, lv, direction, level, expiry=C.WAIT_EXPIRY_BARS):
    """V2: wait for a rejection close at the level, then enter at the next open."""
    L = P.level_price(level, lv)
    if L is None:
        return _skipped('NO_LEVEL')
    last = min(len(candles), i + 1 + expiry)
    for j in range(i + 1, last):
        c = candles[j]
        if c['timestamp'][11:16] >= C.OPEN_EOD:
            break
        if not _confirmation(c, L, direction, level):
            continue
        k = j + 1
        if k >= len(candles):
            return _skipped('NO_NEXT_BAR')
        if not _entry_window_ok(candles[k]['timestamp']):
            return _skipped('CUTOFF')
        b = _bar(candles[k])
        if not b:
            return _skipped('NO_BAR')
        return _entered(k, b[3], direction, level, k - i)
    return _skipped('EXPIRED')


def v3_wait_confirm_retest(candles, i, lv, direction, level, expiry=C.WAIT_EXPIRY_BARS):
    """V3: rejection close at the level, then the retest of the level (fill there)."""
    L = P.level_price(level, lv)
    if L is None:
        return _skipped('NO_LEVEL')
    conf = v2_wait_confirm(candles, i, lv, direction, level, expiry=expiry)
    if conf['status'] != 'ENTERED':
        return _skipped(conf['status'], wait_bars=conf.get('wait_bars'))
    k = conf['entry_idx']          # the bar the confirmation was entered on
    start = k                       # the confirmation bar itself may be the retest
    last = min(len(candles), start + 1 + expiry)
    for j in range(start, last):
        c = candles[j]
        if c['timestamp'][11:16] >= C.OPEN_EOD:
            break
        if not _entry_window_ok(c['timestamp']):
            continue
        if _covers_level(c, L):
            return _entered(j, L, direction, level, j - i)
    return _skipped('NO_RETEST', wait_bars=conf.get('wait_bars'))


def v4_no_chase_flip(candles, i, lv, direction, level):
    """V4: the production no-chase re-anchor (any entry level, direction may flip).

    Reference variant only: this is the rule the production disabled on
    2026-10-17 (it measured -19.2R on NIFTY and -8.7R on BANKNIFTY over the
    8-block walk-forward). Kept here so the historical decision can be
    re-measured on this book.
    """
    nc = P.no_chase_fill(lv, candles, i)
    if nc is None:
        return _skipped('NO_SETUP')
    j, name, dr2, fill = nc
    if not _entry_window_ok(candles[j]['timestamp']):
        return _skipped('CUTOFF')
    if P.friday_skip(dr2, candles[j]['timestamp'][:10]):
        return _skipped('SKIP_FRIDAY')
    try:
        entry = float(fill)
    except (TypeError, ValueError):
        return _skipped('NO_BAR')
    return _entered(j, entry, dr2, name, j - i)


VARIANT_FUNCS = {
    'V1_WAIT_SETUP': v1_wait_setup,
    'V1X_WAIT_SETUP_NO_EXPIRY': v1x_wait_setup_no_expiry,
    'V2_WAIT_CONFIRM': v2_wait_confirm,
    'V3_WAIT_CONFIRM_RETEST': v3_wait_confirm_retest,
    'V4_NO_CHASE_FLIP': v4_no_chase_flip,
}
