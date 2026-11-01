"""Pattern families A-D.

A pattern instance is a (session, level, direction, anchor bar) record. The
entry rules in entries.py turn the anchors into tradeable candidates. Every
pattern is emitted for BOTH plausible directions where the pattern statement
itself does not fix one, so the study never silently assumes the credit
spread hypothesis.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import events as E  # noqa: E402
import levels as L  # noqa: E402

PIVOT_UPPER = ('r1', 'r2')
PIVOT_LOWER = ('s1', 's2')
PD_UPPER = ('pdh',)
PD_LOWER = ('pdl',)

PATTERN_NAMES = {
    'A1': 'Open above the CPR, session ends above the CPR',
    'A2': 'Open below the CPR, session ends below the CPR',
    'A3': 'Price enters the CPR and exits on the side it came from',
    'A4': 'Price traverses the whole CPR',
    'A5': 'Repeated CPR crossings (chop)',
    'A6': 'CPR boundary break, retest and hold',
    'A7': 'CPR boundary break that fails',
    'B1': 'First touch of R1/R2/S1/S2 with a rejection or bounce',
    'B2': 'R1/R2/S1/S2 break, retest and hold',
    'B3': 'R1/R2/S1/S2 break that fails',
    'B4': 'Price arrives at R1/R2/S1/S2 and consolidates there',
    'B5': 'Repeated test of R1/R2/S1/S2 that weakens',
    'B6': 'Repeated test of R1/R2/S1/S2 that breaks through',
    'C1': 'PDH rejection / PDL bounce',
    'C2': 'PDH/PDL break, retest and hold',
    'C3': 'PDH/PDL break that fails',
    'C4': 'Reclaim of the previous close',
    'C5': 'Rejection at the previous close',
    'C6': 'Gap beyond PDH / PDL',
    'C7': 'Session opens away from the previous close and returns to it',
    'D1': 'Multi level confluence (cluster) touch',
}

FAMILY = {'A1': 'A', 'A2': 'A', 'A3': 'A', 'A4': 'A', 'A5': 'A', 'A6': 'A',
          'A7': 'A', 'B1': 'B', 'B2': 'B', 'B3': 'B', 'B4': 'B', 'B5': 'B',
          'B6': 'B', 'C1': 'C', 'C2': 'C', 'C3': 'C', 'C4': 'C', 'C5': 'C',
          'C6': 'C', 'C7': 'C', 'D1': 'D'}


def _inst(pid, sess, level, direction, anchor_idx, inst_name=None,
          **kw):
    bars = sess['bars']
    b = bars[anchor_idx]
    d = {'pattern_id': pid, 'name': PATTERN_NAMES[pid],
         'family': FAMILY[pid], 'instrument': inst_name,
         'date': sess['date'], 'level': level,
         'level_price': kw.pop('level_price',
                               sess['levels'][level] if level in
                               sess['levels'] else None),
         'direction': direction, 'anchor_idx': anchor_idx,
         'anchor_ts': b['ts'], 'anchor_t': b['t'],
         'rejection_idx': None, 'retest_idx': None, 'reclaim_idx': None,
         'return_level': level}
    d.update(kw)
    return d


def build(sess, evs, instrument, tol):
    """Build the pattern instances for one session."""
    out = []
    lv = sess['levels']
    bars = sess['bars']
    n = len(bars)
    if not lv:
        return out

    by_type = {}
    for e in evs:
        by_type.setdefault(e['event'], []).append(e)

    def find(etype, level=None, after=None, before=None):
        res = []
        for e in by_type.get(etype, []):
            if level is not None and e['level'] != level:
                continue
            if after is not None and e['bar_idx'] <= after:
                continue
            if before is not None and e['bar_idx'] >= before:
                continue
            res.append(e)
        return res

    o0 = bars[0]['o']
    c_last = bars[-1]['c']

    # ---------------- family A: CPR ---------------------------------
    if o0 > lv['tc'] and c_last > lv['tc']:
        out.append(_inst('A1', sess, 'tc', 'BEAR', 0, instrument))
        out.append(_inst('A1', sess, 'tc', 'BULL', 0, instrument))
    if o0 < lv['bc'] and c_last < lv['bc']:
        out.append(_inst('A2', sess, 'bc', 'BULL', 0, instrument))
        out.append(_inst('A2', sess, 'bc', 'BEAR', 0, instrument))

    # A3: enter the CPR and exit on the same side it came from
    zones = E.cpr_zone_series(sess)
    entered_from = None
    for i in range(n):
        if zones[i] == 'INSIDE':
            entered_from = zones[i - 1] if i > 0 else None
            for j in range(i + 1, n):
                if zones[j] != 'INSIDE':
                    if entered_from and zones[j] == entered_from:
                        out.append(_inst(
                            'A3', sess, 'tc' if entered_from == 'ABOVE'
                            else 'bc',
                            'BULL' if entered_from == 'ABOVE' else 'BEAR', i,
                            instrument, exit_bar=j,
                            rejection_idx=i,
                            note='entered the CPR from %s and exited %s'
                                 % (entered_from, zones[j])))
                    break
            break

    # A4: full traversal of the CPR
    for i in range(1, n):
        if zones[i] == 'INSIDE' and zones[i - 1] != 'INSIDE':
            start = zones[i - 1]
            for j in range(i + 1, n):
                if zones[j] != 'INSIDE' and zones[j] != start:
                    out.append(_inst('A4', sess, 'tc' if start == 'ABOVE'
                                     else 'bc',
                                     'BEAR' if start == 'ABOVE' else 'BULL',
                                     i, instrument, exit_bar=j,
                                     note='traversed the CPR from %s to %s'
                                          % (start, zones[j])))
                    break
            break

    # A5: chop (session descriptor, no trade instance)
    chop = E.session_chop(sess)
    if chop['zone_changes'] >= 4:
        out.append(_inst('A5', sess, 'cpr', 'NONE', 0, instrument,
                         zone_changes=chop['zone_changes'],
                         note='repeated CPR crossings'))

    # A6 / A7: CPR boundary breaks
    for e in find('BREAK', level='tc') + find('BREAK', level='bc'):
        level = e['level']
        for h in find('RETEST_HOLD', level=level, after=e['bar_idx']):
            if h.get('break_bar') != e['bar_idx']:
                continue
            out.append(_inst('A6', sess, level, e['direction'], h['bar_idx'],
                             instrument, retest_idx=h['bar_idx'],
                             break_idx=e['bar_idx'],
                             note='CPR break and hold'))
        for f in find('BREAK_FAIL', level=level, after=e['bar_idx']):
            if f.get('break_bar') != e['bar_idx']:
                continue
            fail_dir = 'BEAR' if e['direction'] == 'BULL' else 'BULL'
            out.append(_inst('A7', sess, level, fail_dir, f['bar_idx'],
                             instrument, break_idx=e['bar_idx'],
                             note='CPR break failed'))

    # ---------------- family B: pivots -------------------------------
    for level in PIVOT_UPPER + PIVOT_LOWER:
        dirn = 'BEAR' if level in PIVOT_UPPER else 'BULL'
        t = find('TOUCH', level=level)
        if t:
            e = t[0]
            conf = [c for c in find('REJECTION_CONFIRM', level=level,
                                    after=e['bar_idx'])
                    if c['bar_idx'] == e['bar_idx'] + 1]
            if conf:
                out.append(_inst('B1', sess, level, dirn, e['bar_idx'],
                                 instrument, rejection_idx=e['bar_idx'],
                                 note='first touch with a rejection'))
            else:
                out.append(_inst('B1', sess, level, dirn, e['bar_idx'],
                                 instrument, rejection_idx=e['bar_idx'],
                                 note='first touch'))
        for h in find('RETEST_HOLD', level=level):
            out.append(_inst('B2', sess, level, h['direction'], h['bar_idx'],
                             instrument, retest_idx=h['bar_idx'],
                             break_idx=h.get('break_bar'),
                             note='pivot break and hold'))
        for f in find('BREAK_FAIL', level=level):
            fail_dir = 'BEAR' if level in PIVOT_UPPER else 'BULL'
            out.append(_inst('B3', sess, level, fail_dir, f['bar_idx'],
                             instrument, break_idx=f.get('break_bar'),
                             note='pivot break failed'))
        # B4: arrival followed by consolidation within 1x tolerance
        for e in find('TOUCH', level=level):
            i = e['bar_idx']
            ok = True
            for k in range(i + 1, min(n, i + 4)):
                if abs(bars[k]['c'] - lv[level]) > tol:
                    ok = False
                    break
            if ok and i + 3 < n:
                out.append(_inst('B4', sess, level, dirn, i, instrument,
                                 note='arrival then consolidation'))
        # B5 / B6: repeated tests
        rt = find('REPEAT_TEST', level=level)
        if rt:
            second = rt[0]
            if second.get('touch_number', 0) == 2:
                fails = find('BREAK_FAIL', level=level,
                             after=second['bar_idx'] - 1)
                broke = find('BREAK', level=level,
                             after=second['bar_idx'] - 1)
                if fails:
                    out.append(_inst('B5', sess, level, dirn,
                                     second['bar_idx'], instrument,
                                     note='repeated test weakened'))
                elif broke:
                    out.append(_inst('B6', sess, level, broke[0]['direction'],
                                     second['bar_idx'], instrument,
                                     note='repeated test broke through'))

    # ---------------- family C: previous day ------------------------
    for level, dirn in (('pdh', 'BEAR'), ('pdl', 'BULL')):
        t = find('TOUCH', level=level)
        if t:
            e = t[0]
            conf = [c for c in find('REJECTION_CONFIRM', level=level,
                                    after=e['bar_idx'])
                    if c['bar_idx'] == e['bar_idx'] + 1]
            out.append(_inst('C1', sess, level, dirn, e['bar_idx'],
                             instrument,
                             rejection_idx=e['bar_idx'],
                             note='PD rejection/bounce' +
                                  (' confirmed' if conf else '')))
        for h in find('RETEST_HOLD', level=level):
            out.append(_inst('C2', sess, level, h['direction'], h['bar_idx'],
                             instrument, retest_idx=h['bar_idx'],
                             break_idx=h.get('break_bar'),
                             note='PD break and hold'))
        for f in find('BREAK_FAIL', level=level):
            out.append(_inst('C3', sess, level, dirn, f['bar_idx'],
                             instrument, break_idx=f.get('break_bar'),
                             note='PD break failed'))

    # C4: reclaim of the previous close
    prev_c = sess['prev']['close'] if sess['prev'] else None
    if prev_c is not None:
        side = None
        for i, b in enumerate(bars):
            if b['c'] < prev_c:
                side = 'BELOW'
            elif b['c'] > prev_c:
                side = 'ABOVE'
            if side == 'BELOW' and b['c'] > prev_c:
                out.append(_inst('C4', sess, 'pdc', 'BULL', i, instrument,
                                 note='reclaimed above the previous close'))
            elif side == 'ABOVE' and b['c'] < prev_c:
                out.append(_inst('C4', sess, 'pdc', 'BEAR', i, instrument,
                                 note='reclaimed below the previous close'))
            if side is None:
                side = 'below' if b['c'] < prev_c else 'above'
                side = side.upper()

    # C5: rejection at the previous close
    for e in find('REJECTION_WICK', level='pdc'):
        out.append(_inst('C5', sess, 'pdc', e['direction'], e['bar_idx'],
                         instrument, rejection_idx=e['bar_idx'],
                         note='rejection at the previous close'))

    # C6: gap beyond PDH / PDL
    if o0 > lv['pdh']:
        out.append(_inst('C6', sess, 'pdh', 'BULL', 0, instrument))
        out.append(_inst('C6', sess, 'pdh', 'BEAR', 0, instrument))
    if o0 < lv['pdl']:
        out.append(_inst('C6', sess, 'pdl', 'BEAR', 0, instrument))
        out.append(_inst('C6', sess, 'pdl', 'BULL', 0, instrument))

    # C7: open away from the previous close, return to it
    if prev_c is not None:
        if o0 > prev_c:
            for i, b in enumerate(bars):
                if b['c'] <= prev_c:
                    out.append(_inst('C7', sess, 'pdc', 'BEAR', i, instrument,
                                     note='returned to the previous close'))
                    break
        elif o0 < prev_c:
            for i, b in enumerate(bars):
                if b['c'] >= prev_c:
                    out.append(_inst('C7', sess, 'pdc', 'BULL', i, instrument,
                                     note='returned to the previous close'))
                    break

    # ---------------- family D: confluence ---------------------------
    order = sorted(L.LEVEL_NAMES, key=lambda k: lv[k])
    cluster_tol = 2 * tol
    for i in range(n):
        window = range(i, min(n, i + 3))
        hit = []
        for level in L.LEVEL_NAMES:
            p = lv[level]
            for j in window:
                if bars[j]['l'] <= p + tol and bars[j]['h'] >= p - tol:
                    hit.append((level, j, p))
                    break
        if len(hit) < 2:
            continue
        prices = sorted(set(round(h[2], 4) for h in hit))
        clustered = False
        for a in range(len(prices) - 1):
            if prices[a + 1] - prices[a] <= cluster_tol:
                clustered = True
                break
        if not clustered:
            continue
        second = sorted(hit, key=lambda h: h[1])[1]
        level = second[0]
        side_up = lv[level] > bars[i]['c']
        out.append(_inst('D1', sess, level, 'BULL' if side_up else 'BEAR', i,
                         instrument,
                         cluster=sorted(set(h[0] for h in hit)),
                         note='confluence of %s' %
                              ','.join(sorted(set(h[0] for h in hit)))))

    # de-duplicate identical (pattern, date, level, direction, anchor)
    seen = set()
    uniq = []
    for p in out:
        key = (p['pattern_id'], p['date'], p['level'], p['direction'],
               p['anchor_idx'])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)
    return uniq
