"""Level interaction events.

Every event is anchored to a bar that has already closed, except the
"touch" events which are anchored to the bar in which the level was reached
(the trade is always taken on a LATER bar, never on the signal bar).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import levels as L  # noqa: E402

RETEST_LOOKBACK = 12
REPEAT_COOLDOWN = 5
ACCEPT_BARS = 3
CROSS_LOOK = 2
CHOP_LOOKBACK = 12


def _mk(event, sess, level, idx, **kw):
    bars = sess['bars']
    b = bars[idx]
    ev = {'event': event, 'date': sess['date'], 'level': level,
          'bar_idx': idx, 'ts': b['ts'], 't': b['t'], 'close': b['c']}
    ev.update(kw)
    return ev


def zone_of(close, lv):
    if close < lv['bc']:
        return 'BELOW'
    if close > lv['tc']:
        return 'ABOVE'
    return 'INSIDE'


def cpr_zone_series(sess):
    lv = sess.get('levels')
    if not lv:
        return []
    return [zone_of(b['c'], lv) for b in sess['bars']]


def chop_count_in_window(sess, end_idx, lookback=CHOP_LOOKBACK):
    zs = cpr_zone_series(sess)
    if not zs:
        return 0
    lo = max(0, end_idx - lookback + 1)
    changes = 0
    for i in range(lo + 1, end_idx + 1):
        if zs[i] != zs[i - 1]:
            changes += 1
    return changes


def detect_level_events(sess, tol):
    if not sess.get('levels'):
        return []
    lv = sess['levels']
    bars = sess['bars']
    n = len(bars)
    out = []

    for level in L.LEVEL_NAMES:
        p = lv[level]
        roles = []
        pc = bars[0]['o']
        for b in bars:
            roles.append('support' if pc > p else 'resistance')
            pc = b['c']

        touches = []
        for i, b in enumerate(bars):
            r = roles[i]
            if r == 'resistance':
                touched = b['h'] >= p - tol
            else:
                touched = b['l'] <= p + tol
            if touched:
                touches.append(i)

        for i, b in enumerate(bars):
            if i in touches:
                break
            r = roles[i]
            d = (p - b['l']) if r == 'resistance' else (b['h'] - p)
            if 0 < d <= 2 * tol:
                out.append(_mk('APPROACH', sess, level, i, role=r,
                               level_price=p, distance=round(d, 4),
                               direction='BULL' if r == 'support' else 'BEAR',
                               note='approach without a touch'))
                break

        prev_touch = None
        touch_count = 0
        for idx in touches:
            b = bars[idx]
            r = roles[idx]
            if prev_touch is None:
                out.append(_mk('TOUCH', sess, level, idx, role=r,
                               level_price=p, direction=None,
                               note='first touch of the session'))
            elif idx - prev_touch >= REPEAT_COOLDOWN:
                out.append(_mk('REPEAT_TEST', sess, level, idx, role=r,
                               level_price=p, touch_number=touch_count + 1,
                               direction=None, note='repeat test'))
            prev_touch = idx
            touch_count += 1

        for idx in touches:
            b = bars[idx]
            r = roles[idx]
            if r == 'resistance':
                wick = b['h'] > p + tol and b['c'] < p - tol
            else:
                wick = b['l'] < p - tol and b['c'] > p + tol
            if not wick:
                continue
            out.append(_mk('REJECTION_WICK', sess, level, idx, role=r,
                           level_price=p,
                           direction='BEAR' if r == 'resistance' else 'BULL',
                           note='wick beyond the level, close back inside'))
            if idx + 1 < n:
                nb = bars[idx + 1]
                if r == 'resistance':
                    conf = nb['c'] < p - tol
                else:
                    conf = nb['c'] > p + tol
                if conf:
                    out.append(_mk('REJECTION_CONFIRM', sess, level, idx + 1,
                                   role=r, level_price=p,
                                   direction='BEAR' if r == 'resistance'
                                   else 'BULL',
                                   note='next bar confirms the rejection'))

        break_idx = None
        for i, b in enumerate(bars):
            r = roles[i]
            if r == 'resistance':
                broke = b['h'] > p + tol
                closed_beyond = b['c'] > p + tol
            else:
                broke = b['l'] < p - tol
                closed_beyond = b['c'] < p - tol
            if broke and break_idx is None:
                break_idx = i
                dirn = 'BULL' if r == 'resistance' else 'BEAR'
                out.append(_mk('BREAK', sess, level, i, role=r, level_price=p,
                               direction=dirn, note='wick beyond the level'))
            if closed_beyond:
                dirn = 'BULL' if r == 'resistance' else 'BEAR'
                out.append(_mk('CLOSE_BEYOND', sess, level, i, role=r,
                               level_price=p, direction=dirn,
                               note='close beyond the level'))
                break

        if break_idx is not None:
            br = roles[break_idx]
            dirn = 'BULL' if br == 'resistance' else 'BEAR'
            for j in range(break_idx + 1, min(n, break_idx + 1 + RETEST_LOOKBACK)):
                b = bars[j]
                r = roles[j]
                if r == 'resistance':
                    returned = b['l'] <= p + tol
                    beyond = b['c'] > p + tol
                else:
                    returned = b['h'] >= p - tol
                    beyond = b['c'] < p - tol
                if not returned:
                    continue
                if beyond:
                    out.append(_mk('RETEST_HOLD', sess, level, j, role=r,
                                   level_price=p, direction=dirn, break_bar=break_idx,
                                   note='break retested and held'))
                else:
                    out.append(_mk('BREAK_FAIL', sess, level, j, role=r,
                                   level_price=p,
                                   direction='BEAR' if br == 'resistance' else 'BULL',
                                   break_bar=break_idx,
                                   note='break failed, close back inside'))
                    for k in range(j + 1, min(n, j + 1 + RETEST_LOOKBACK)):
                        bk = bars[k]
                        rk = roles[k]
                        if rk == 'resistance':
                            cb = bk['c'] > p + tol
                        else:
                            cb = bk['c'] < p - tol
                        if cb:
                            out.append(_mk('RECLAIM', sess, level, k, role=rk,
                                           level_price=p, direction=dirn,
                                           note='price reclaimed the level'))
                            break
                break

        run = 0
        side = None
        for i, b in enumerate(bars):
            r = roles[i]
            if r == 'resistance':
                cb = b['c'] > p + tol
            else:
                cb = b['c'] < p - tol
            if cb:
                if side == r:
                    run += 1
                else:
                    side = r
                    run = 1
                if run == ACCEPT_BARS:
                    out.append(_mk('ACCEPTANCE', sess, level, i, role=r,
                                   level_price=p, direction='BULL' if r == 'resistance' else 'BEAR',
                                   note='3 closes beyond the level'))
            else:
                run = 0
                side = None

        for i, b in enumerate(bars):
            r = roles[i]
            crossed = (b['l'] <= p + tol and b['h'] >= p - tol)
            if not crossed:
                continue
            near = abs(b['c'] - p) <= tol
            if not near:
                continue
            ok = True
            for k in range(i + 1, min(n, i + 1 + CROSS_LOOK)):
                if abs(bars[k]['c'] - p) > tol:
                    ok = False
                    break
            if ok:
                out.append(_mk('CROSS_NO_REACTION', sess, level, i, role=r,
                               level_price=p, direction=None,
                               note='level crossed but no reaction'))

    zs = cpr_zone_series(sess)
    inside = None
    for i in range(n):
        z = zs[i]
        if z == 'INSIDE':
            if inside is None:
                out.append(_mk('CPR_ENTER', sess, 'cpr', i, role='zone',
                               level_price=lv['bc'], direction=None,
                               note='first close inside the CPR'))
            inside = i
        elif inside is not None and zs[i - 1] == 'INSIDE':
            out.append(_mk('CPR_EXIT', sess, 'cpr', i, role='zone',
                           level_price=lv['bc'] if zs[i] == 'BELOW' else lv['tc'],
                           direction='BEAR' if zs[i] == 'BELOW' else 'BULL',
                           note='closed back outside the CPR'))
            inside = None
    for i in range(2, n):
        if zs[i] == 'INSIDE' and zs[i - 1] == 'INSIDE' and zs[i - 2] != 'INSIDE':
            out.append(_mk('CPR_TRAVERSE', sess, 'cpr', i, role='zone',
                           level_price=lv['bc'], direction='BEAR' if zs[i - 1] == 'BELOW' else 'BULL',
                           note='traversed the CPR'))

    o0 = bars[0]['o']
    for name, cond, dirn in (
            ('GAP_ABOVE_PDH', o0 > lv['pdh'], 'BULL'),
            ('GAP_BELOW_PDL', o0 < lv['pdl'], 'BEAR'),
            ('GAP_ABOVE_PDC', o0 > lv['pdc'], 'BULL'),
            ('GAP_BELOW_PDC', o0 < lv['pdc'], 'BEAR')):
        if cond:
            out.append(_mk(name, sess, name.split('_')[-1].lower(), 0,
                           role='gap', level_price=lv['pdc'], direction=dirn,
                           note='session open beyond a prior day level'))

    order = sorted(L.LEVEL_NAMES, key=lambda k: lv[k])
    touch_idx = {}
    for level in L.LEVEL_NAMES:
        p = lv[level]
        idxs = [i for i, b in enumerate(bars)
                if b['l'] <= p + tol and b['h'] >= p - tol]
        touch_idx[level] = idxs
    for a_i in range(len(order)):
        for b_i in range(a_i + 1, len(order)):
            lo, hi = order[a_i], order[b_i]
            found = None
            for j in touch_idx[hi]:
                hit = [i for i in touch_idx[lo] if i > j]
                if hit:
                    found = (j, min(hit))
                    break
            if found:
                out.append(_mk('LEVEL_TO_LEVEL', sess, '%s>%s' % (hi, lo), found[0],
                               role='transition', level_price=lv[hi],
                               target_level=lo, target_price=lv[lo], direction='BEAR',
                               to_bar=found[1], bars_to_target=found[1] - found[0],
                               minutes_to_target=(found[1] - found[0]) * 5,
                               note='price moved from %s to %s' % (hi, lo)))
            found = None
            for i in touch_idx[lo]:
                hit = [j for j in touch_idx[hi] if j > i]
                if hit:
                    found = (i, min(hit))
                    break
            if found:
                out.append(_mk('LEVEL_TO_LEVEL', sess, '%s>%s' % (lo, hi), found[0],
                               role='transition', level_price=lv[lo],
                               target_level=hi, target_price=lv[hi], direction='BULL',
                               to_bar=found[1], bars_to_target=found[1] - found[0],
                               minutes_to_target=(found[1] - found[0]) * 5,
                               note='price moved from %s to %s' % (lo, hi)))

    for a_i in range(len(order)):
        for b_i in range(a_i + 1, len(order)):
            loL, hiL = order[a_i], order[b_i]
            for j in touch_idx[hiL]:
                hit = [i for i in touch_idx[loL] if i < j]
                if not hit:
                    continue
                i0 = max(hit)
                found = None
                for k in range(i0 + 1, min(n, i0 + 1 + RETEST_LOOKBACK)):
                    if bars[k]['h'] >= lv[hiL] - 2 * tol and bars[k]['h'] < lv[hiL]:
                        found = k
                        break
                if found is None:
                    continue
                rev = None
                for k in range(found, min(n, found + 3)):
                    if bars[k]['c'] < lv[hiL] - tol:
                        rev = k
                        break
                if rev is not None:
                    out.append(_mk('REVERSAL_BEFORE_NEXT', sess, hiL, j,
                                   role='transition', level_price=lv[hiL],
                                   target_level=loL, target_price=lv[loL],
                                   direction='BEAR', reverse_bar=rev,
                                   bars_to_target=found - i0,
                                   note='price turned before reaching %s' % loL))

    return out


def session_chop(sess):
    zs = cpr_zone_series(sess)
    changes = sum(1 for i in range(1, len(zs)) if zs[i] != zs[i - 1])
    return {'zone_changes': changes, 'zone_path': ''.join(z[0] for z in zs)}
