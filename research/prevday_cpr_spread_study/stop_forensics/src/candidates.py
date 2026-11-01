"""Pre-registered candidate entry conditions (E1..E6).

Every arm acts on the **unchanged production trigger set**: same sessions, same
levels, same triggers, same execution model and the same corrected accounting.
Only the entry condition differs. No new signal family is introduced.

Level semantics (pre-registered):

Each production trigger is one of four groups. The group fixes the *excursion
direction* (the side price travelled to reach the level), the *retest rule* and the
*cancel rule* used by E2/E3.

    group 1  BEAR fade at resistance  (R1, R2, PDH)          excursion: up
    group 2  BULL fade at support      (S1, S2, PDL)          excursion: down
    group 3  BULL breakout             (ABOVE_CPR, BRK_R1/R2/PDH/TC)  excursion: up
    group 4  BEAR breakout             (BELOW_CPR, BRK_S1/S2/PDL/BC)  excursion: down

`dir` is +1 for an upward excursion and -1 for a downward one, so the signed
extension of an entry is always `(entry - level) * dir` (positive = the entry was
made after price had already travelled that far beyond the level).
"""
from __future__ import annotations

from . import accounting, data, forensics

STOP_PCT = accounting.STOP_PCT
TARGET_PCT = accounting.TARGET_PCT

E1_GRID = (1.00, 1.25, 1.50)
E2_GRID = (0.0010, 0.0025)
E3_Y = 0.0025
E3_Z = 0.0010
E4_GRID = ('11:00', '13:00')
E5_TAIL = ('q10', 'q90')
E6_MAX_REENTRIES = 1

# level token -> (excursion dir, group)
LEVEL_GROUP = {
    'R1': (+1, 1), 'R2': (+1, 1), 'PDH': (+1, 1),
    'S1': (-1, 2), 'S2': (-1, 2), 'PDL': (-1, 2),
    'ABOVE_CPR': (+1, 3),
    'BRK_R1': (+1, 3), 'BRK_R2': (+1, 3), 'BRK_PDH': (+1, 3), 'BRK_TC': (+1, 3),
    'BELOW_CPR': (-1, 4),
    'BRK_S1': (-1, 4), 'BRK_S2': (-1, 4), 'BRK_PDL': (-1, 4), 'BRK_BC': (-1, 4),
}


def level_group(level: str):
    return LEVEL_GROUP.get(level)


def signed_extension(entry: float, level: float, dir_: int) -> float:
    """Positive when the entry happened after price had travelled beyond the level."""
    return (entry - level) * dir_


def _signal_record(signal: dict, arm: str, entry=None, entry_idx=None,
                    entry_source='baseline_open'):
    return accounting.account(signal, arm, entry=entry, entry_idx=entry_idx,
                              entry_source=entry_source)


def arm_baseline(universe: dict) -> list:
    out = []
    for s in universe['signals']:
        r = _signal_record(s, 'BASELINE')
        if r:
            out.append(r)
    return out


def arm_e1(universe: dict, k: float) -> tuple:
    """Risk-distance filter.

    Skip the signal when the 0.5 % stop distance is wider than k times the median
    intrabar range of the candles available up to and including the trigger candle
    (point-in-time). Such a stop is structurally larger than the session's own
    bar noise.
    """
    kept, removed = [], []
    for s in universe['signals']:
        r = _signal_record(s, f'E1_k{k:.2f}')
        if not r:
            continue
        med = forensics.median_range_to_trigger(s['ctx'], s['trigger_idx'])
        if med is None:
            r['e1_evaluable'] = False
            kept.append(r)
            continue
        r['e1_evaluable'] = True
        r['e1_median_range_pts'] = round(med, 3)
        r['e1_stop_distance_pts'] = round(abs(r['entry'] * STOP_PCT), 2)
        if r['e1_stop_distance_pts'] > k * med:
            r['filter_reason'] = ('stop distance wider than k x median bar range '
                                  '(structurally over-sized risk)')
            removed.append(r)
        else:
            kept.append(r)
    return kept, removed


def arm_e2(universe: dict, x: float) -> tuple:
    """Extension filter.

    Skip the signal when the signed extension of the entry beyond the trigger
    level exceeds x: `(entry - level) * dir / level > x`.
    """
    kept, removed = [], []
    for s in universe['signals']:
        r = _signal_record(s, f'E2_x{x * 100:.2f}pct')
        if not r:
            continue
        lvl = r.get('level_price')
        grp = level_group(r['setup'])
        if not lvl or grp is None:
            r['e2_evaluable'] = False
            kept.append(r)
            continue
        dir_ = grp[0]
        ext = signed_extension(r['entry'], lvl, dir_) / lvl
        r['e2_evaluable'] = True
        r['e2_signed_extension_pct'] = round(ext * 100, 4)
        if ext > x:
            r['filter_reason'] = 'entry extended beyond the trigger level'
            removed.append(r)
        else:
            kept.append(r)
    return kept, removed


def arm_e3(universe: dict, y: float = E3_Y, z: float = E3_Z) -> tuple:
    """Retest re-entry.

    If the excursion that produced the trigger travelled more than y beyond the
    level before the baseline entry, the baseline entry is abandoned. The arm
    waits for a **retest**: a candle whose extreme returns to within z of the
    level and which closes back on the trade-favourable side. The trade is then
    entered at that candle's close.

    Cancel rule (group dependent):
      group 1 (BEAR fade at resistance): a close above the level kills the fade.
      group 2 (BULL fade at support):    a close below the level kills the fade.
      group 3 (BULL breakout):           a close below the level kills the breakout.
      group 4 (BEAR breakout):           a close above the level kills the breakout.

    If the excursion never exceeded y, the baseline entry is kept unchanged.
    If no retest occurs before the 15:20 flat, no trade is taken.
    """
    kept, removed = [], []
    for s in universe['signals']:
        base = _signal_record(s, 'E3_retest')
        if not base:
            continue
        ctx = s['ctx']
        scan = ctx['scan']
        lvl = base.get('level_price')
        grp = level_group(base['setup'])
        if not lvl or grp is None:
            base['e3_mode'] = 'not_applicable_level_group'
            kept.append(base)
            continue
        dir_, group = grp
        trig = s['trigger_idx']
        entry_idx = s['entry_idx']
        if trig is None:
            base['e3_mode'] = 'not_evaluable'
            kept.append(base)
            continue
        window = scan[trig:entry_idx + 1]
        if dir_ > 0:
            beyond = max(float(c['high']) for c in window)
            ext = (beyond - lvl) / lvl
        else:
            beyond = min(float(c['low']) for c in window)
            ext = (lvl - beyond) / lvl
        base['e3_extension_pct'] = round(ext * 100, 4)
        if ext <= y:
            base['e3_mode'] = 'baseline_entry_kept'
            kept.append(base)
            continue
        retest_idx = None
        cancelled = False
        for i in range(entry_idx, len(scan)):
            c = scan[i]
            ts = str(c['timestamp'])
            if ts[11:16] >= '15:20':
                break
            close = float(c['close'])
            if group in (1, 4):
                # BEAR side: a close above the level invalidates
                if close > lvl:
                    cancelled = True
                    break
            else:
                # BULL side: a close below the level invalidates
                if close < lvl:
                    cancelled = True
                    break
            if group in (1, 3):
                # upward excursion group: price must come back to within z above L
                near = float(c['low']) <= lvl * (1 + z)
                favourable = close < lvl if group == 1 else close > lvl
            else:
                near = float(c['high']) >= lvl * (1 - z)
                favourable = close > lvl if group == 2 else close < lvl
            if near and favourable:
                retest_idx = i
                break
        if cancelled:
            base['e3_mode'] = 'cancelled_level_closed_through'
            base['filter_reason'] = 'level closed through before a retest'
            removed.append(base)
            continue
        if retest_idx is None:
            base['e3_mode'] = 'no_retest_before_flat'
            base['filter_reason'] = 'no retest of the level before the 15:20 flat'
            removed.append(base)
            continue
        r = _signal_record(s, 'E3_retest', entry=float(scan[retest_idx]['close']),
                           entry_idx=retest_idx, entry_source='retest_close')
        if r:
            r['e3_mode'] = 'retest_entry'
            r['e3_retest_time'] = str(scan[retest_idx]['timestamp'])[:16].replace('T', ' ')
            kept.append(r)
        else:
            base['e3_mode'] = 'retest_entry_missing_eod'
            removed.append(base)
    return kept, removed


def arm_e4(universe: dict, window_end: str) -> tuple:
    """Time-of-day filter: keep entries strictly before `window_end`."""
    kept, removed = [], []
    for s in universe['signals']:
        r = _signal_record(s, f'E4_until_{window_end.replace(":", "")}')
        if not r:
            continue
        if r['entry_time'][11:16] < window_end:
            kept.append(r)
        else:
            r['filter_reason'] = f'entry at or after {window_end}'
            removed.append(r)
    return kept, removed


def arm_e5(universe: dict, tail: str, cpr_stats: dict) -> tuple:
    """CPR-width regime filter (previous-session width, IS-frozen quantiles)."""
    bound = cpr_stats.get(tail)
    kept, removed = [], []
    for s in universe['signals']:
        r = _signal_record(s, f'E5_skip_{tail}')
        if not r:
            continue
        w = s['ctx'].get('cpr_width_pct')
        if w is None or bound is None:
            kept.append(r)
            continue
        skip = (w < bound) if tail == 'q10' else (w > bound)
        if skip:
            r['filter_reason'] = f'previous-session CPR width outside the {tail} band'
            removed.append(r)
        else:
            kept.append(r)
    return kept, removed


def arm_e6(universe: dict, engine) -> tuple:
    """Re-entry after a stop.

    After a baseline STOP on level L the (instrument, L) pair is armed for
    **later sessions only** (one full session of cooldown). A fresh close-cross in
    the ORIGINAL direction through the SAME level (production breakout trigger
    semantics) arms the re-entry, taken at the next eligible open inside
    [09:20, 15:20) with the identical exit model. At most one re-entry per stop
    event; the re-entry is an ADDITIONAL trade.
    """
    kept = []
    extra = []
    sessions = universe['sessions']
    all_days = sorted(sessions)
    for s in universe['signals']:
        base = _signal_record(s, 'E6_reentry')
        if not base:
            continue
        kept.append(base)
        if base['exit_reason'] != 'STOP':
            base['e6_applicable'] = False
            continue
        key = data.LEVEL_KEY.get(s['level'])
        if key is None:
            base['e6_applicable'] = False
            continue
        base['e6_applicable'] = True
        start = all_days.index(s['session_date']) + 2  # one-session cooldown
        found = False
        for day in all_days[start:]:
            ctx = sessions[day]
            prev = None
            for i, c in enumerate(ctx['scan']):
                close = float(c['close'])
                if prev is not None:
                    r = engine.breakout_trigger(c, prev, ctx['levels'])
                    if r and r[0] == s['direction'] and data.LEVEL_KEY.get(r[1]) == key:
                        nxt = i + 1
                        if nxt < len(ctx['scan']) and '09:20' <= str(ctx['scan'][nxt]['timestamp'])[11:16] < '15:20':
                            sig = dict(s)
                            sig['ctx'] = ctx
                            sig['entry_idx'] = nxt
                            sig['session_date'] = day
                            sig['period'] = ctx['period']
                            sig['level_price'] = base.get('level_price')
                            rec = accounting.account(sig, 'E6_reentry', entry=None,
                                                     entry_idx=nxt,
                                                     entry_source='reentry_open')
                            if rec:
                                rec['e6_origin_session'] = s['session_date']
                                rec['e6_origin_level'] = s['level']
                                extra.append(rec)
                                found = True
                        break
                prev = close
            if found:
                break
    return kept + extra, []


def detect_conflicts(universe: dict, engine) -> list:
    """Sessions whose FIRST trigger candle qualifies for BOTH directions.

    The production engine resolves a same-candle conflict deterministically (BEAR is
    checked before BULL). This detector finds the sessions where such a conflict
    actually exists; the number of bars on which both trigger functions fire is
    reported separately as session-level co-occurrence.
    """
    out = []
    for day, ctx in universe['sessions'].items():
        if not ctx['levels']:
            continue
        both_bars = 0
        for i, c in enumerate(ctx['scan']):
            b = engine.bear_trigger(c, ctx['levels'])
            u = engine.bull_trigger(c, ctx['levels'])
            if b and u:
                both_bars += 1
        first = None
        for i, c in enumerate(ctx['scan']):
            b = engine.bear_trigger(c, ctx['levels'])
            u = engine.bull_trigger(c, ctx['levels'])
            if b or u:
                first = {'idx': i, 'bear_level': b, 'bull_level': u,
                         'same_candle': bool(b and u)}
                break
        if first and first['same_candle']:
            out.append({'session_date': day, 'trigger_idx': first['idx'],
                        'bear_level': first['bear_level'],
                        'bull_level': first['bull_level'],
                        'both_trigger_bars_in_session': both_bars})
    return out


def arm_e7(universe: dict, engine) -> tuple:
    """E7 conflict ranking (registered, filter-only implementation).

    On sessions whose first trigger candle qualifies for BOTH directions, the two
    directions are ranked by their point-in-time reward-to-risk to the next relevant
    level. The production direction must be the better (or equal) one; if the
    opposite direction ranks better the session is skipped. If no defensible
    comparison exists (one side has no relevant next level) the session is skipped
    as pre-registered.

    A direction *flip* is not traded: the deployed configuration suppresses BULL
    base triggers, so flipping would introduce a signal family that the production
    trigger set does not act on. The count of sessions where the opposite direction
    would have ranked better is reported descriptively.
    """
    kept, removed = [], []
    flip_better = 0
    for s in universe['signals']:
        r = _signal_record(s, 'E7_conflict')
        if not r:
            continue
        ctx = s['ctx']
        trig = s['trigger_idx']
        if trig is None:
            r['e7_mode'] = 'not_evaluable'
            kept.append(r)
            continue
        candle = ctx['scan'][trig]
        other_level = (engine.bull_trigger(candle, ctx['levels'])
                       if s['direction'] == 'BEAR'
                       else engine.bear_trigger(candle, ctx['levels']))
        if not other_level:
            r['e7_mode'] = 'no_conflict'
            kept.append(r)
            continue
        r['e7_mode'] = 'conflict'
        r['e7_other_level'] = other_level
        rank = conflict_rank(engine, ctx, trig, trig)
        bear, bull = rank.get('BEAR'), rank.get('BULL')
        r['e7_rank_bear'] = bear
        r['e7_rank_bull'] = bull
        if not bear or not bull or bear.get('rr') is None or bull.get('rr') is None:
            r['filter_reason'] = 'no defensible reward-to-risk comparison'
            removed.append(r)
            continue
        prod_rr = bear['rr'] if s['direction'] == 'BEAR' else bull['rr']
        other_rr = bull['rr'] if s['direction'] == 'BEAR' else bear['rr']
        if other_rr > prod_rr:
            flip_better += 1
            r['filter_reason'] = ('opposite direction ranked better on '
                                   'reward-to-risk (not traded: SHORT_ONLY)')
            removed.append(r)
        else:
            kept.append(r)
    for r in removed:
        r['e7_flip_would_have_ranked_better'] = True
    return kept, removed


def conflict_rank(engine, ctx: dict, bear_idx: int, bull_idx: int) -> dict:
    """Point-in-time reward-to-risk ranking of two conflicting directions."""
    out = {}
    for direction, idx in (('BEAR', bear_idx), ('BULL', bull_idx)):
        nxt = idx + 1
        if nxt >= len(ctx['scan']):
            out[direction] = None
            continue
        entry = float(ctx['scan'][nxt]['open'])
        stop = entry * (1 + 0.005) if direction == 'BEAR' else entry * (1 - 0.005)
        risk = abs(entry - stop)
        if direction == 'BEAR':
            targets = [ctx['levels'][k] for k in ('s1', 's2', 'pdl', 'bc')
                       if ctx['levels'][k] is not None and ctx['levels'][k] < entry]
            reward = (entry - max(targets)) if targets else 0.0
        else:
            targets = [ctx['levels'][k] for k in ('r1', 'r2', 'pdh', 'tc')
                       if ctx['levels'][k] is not None and ctx['levels'][k] > entry]
            reward = (min(targets) - entry) if targets else 0.0
        out[direction] = {'entry': entry, 'reward_pts': round(reward, 2),
                          'risk_pts': round(risk, 2),
                          'rr': round(reward / risk, 3) if risk else None}
    return out
