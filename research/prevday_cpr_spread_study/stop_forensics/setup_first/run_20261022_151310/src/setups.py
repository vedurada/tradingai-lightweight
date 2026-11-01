"""Setup identification: six causal, point-in-time setup families (short side).

The families are fixed before any result is computed and are never re-selected
by outcome. Every setup is identified from information that was available at the
identification bar: previous-session levels, closed candles of the current
session and point-in-time confirmed swings.

Scope decision (pre-registered): only BEAR (short) setups are traded. The frozen
baseline is 129/129 BEAR because the deployment runs `SHORT_ONLY=True`, so a
long mirror would be a different signal family with no comparable baseline.
Mirrored long setups are therefore not identified at all.
"""
from __future__ import annotations

from . import config, structures


def level_bundle(engine_mod, prev):
    """Production CPR / pivot / PDH / PDL bundle of the previous session.

    The parent's `data.level_bundle` cannot be used: it calls the sibling
    *module* `prod` as a function and therefore raises
    `TypeError: 'module' object is not callable`. The bundle is rebuilt here
    from the unmodified production engine (`cpr_trigger_engine.day_levels`),
    which is exactly the call the parent's `accounting.build_session` uses, so
    the levels are identical to the ones the production engine sees.
    """
    if not prev:
        return None
    levels = engine_mod.day_levels(prev['high'], prev['low'], prev['close'])
    if not levels:
        return None
    bundle = dict(levels)
    try:
        bundle['cpr_width_pct'] = round(
            ((levels['tc'] - levels['bc']) / levels['pp']) * 100, 6)
    except (KeyError, TypeError, ZeroDivisionError):
        bundle['cpr_width_pct'] = None
    bundle['prev_date'] = prev.get('date')
    return bundle


def _level_value(bundle, name):
    if name == 'PDH':
        return bundle.get('pdh')
    if name == 'PDL':
        return bundle.get('pdl')
    if name == 'PIVOT':
        return bundle.get('pp')
    if name == 'TC':
        return bundle.get('tc')
    if name == 'BC':
        return bundle.get('bc')
    return bundle.get(name.lower())


def _nearest_above(bundle, names, session_open):
    """The nearest level above the session open; the priority order breaks ties."""
    cands = []
    for i, name in enumerate(names):
        lv = _level_value(bundle, name)
        if lv is None or lv <= session_open:
            continue
        cands.append((float(lv), i, name))
    if not cands:
        return None
    cands.sort(key=lambda t: (t[0], t[1]))
    return cands[0]


def _nearest_below(bundle, names, session_open):
    """The nearest level below the session open; the priority order breaks ties."""
    cands = []
    for i, name in enumerate(names):
        lv = _level_value(bundle, name)
        if lv is None or lv >= session_open:
            continue
        cands.append((-float(lv), i, name))
    if not cands:
        return None
    cands.sort(key=lambda t: (t[0], t[1]))
    return cands[0]


def _base_setup(family, inst, day, level_price, id_idx, candles, direction='BEAR',
                **extra):
    w = level_price * config.ZONE_PCT
    setup = {
        'setup_id': f"{inst}_{day}_{family}_{level_price:.2f}_{id_idx}",
        'instrument': inst,
        'session_date': day,
        'direction': direction,
        'direction_label': 'SHORT',
        'setup_family': family,
        'level_price': float(level_price),
        'zone_low': round(level_price - w, 4),
        'zone_high': round(level_price + w, 4),
        'zone_width_pct': config.ZONE_PCT,
        'identification_idx': id_idx,
        'identification_ts': (str(candles[id_idx]['timestamp'])
                              if 0 <= id_idx < len(candles) else None),
        'expiry_bars': config.EXPIRY_BARS,
        'state': config.STATE_WATCHING,
        'arrival_idx': None,
        'arrival_ts': None,
        'confirm_idx': None,
        'confirm_ts': None,
        'rejection_reason': None,
        'transitions': [],
    }
    setup.update(extra)
    return setup


def build_session_setups(inst, day, candles, bundle, period):
    """All setups identified in one session (point-in-time, causal)."""
    out = []
    if not candles or not bundle:
        return out
    session_open = float(candles[0]['open'])
    close_v = [float(c['close']) for c in candles]
    high_v = [float(c['high']) for c in candles]

    res = _nearest_above(bundle, config.RESISTANCE_PRIORITY, session_open)
    sup = _nearest_below(bundle, config.SUPPORT_PRIORITY, session_open)

    # ---- F1: rejection at a pre-existing resistance (level known at the open)
    if res:
        lv, _, name = res
        out.append(_base_setup('F1_PREV_DAY_LEVEL_REJECTION', inst, day, lv, 0,
                                candles, level_name=name,
                                why_monitor=('price rallying into a pre-existing '
                                             f'resistance ({name}) from below'),
                                data_used='previous-session levels + session open'))

    # ---- F2: rejection at the top of the previous CPR (known at the open) ----
    tc = bundle.get('tc')
    if tc is not None and tc > session_open:
        out.append(_base_setup('F2_CPR_BOUNDARY_REJECTION', inst, day, tc, 0,
                                candles, level_name='TC',
                                why_monitor=('price rallying into the previous CPR '
                                             'top from below'),
                                data_used='frozen previous-session CPR + session open'))

    # ---- F5: failed breakout above a pre-existing resistance -----------------
    # Identified at the open (the level is known); the arrival is the breakout
    # attempt itself and the confirmation is the close back below the level.
    if res:
        lv, _, name = res
        out.append(_base_setup('F5_FAILED_BREAK_REJECTION', inst, day, lv, 0,
                                candles, level_name=name,
                                why_monitor=('a breakout above the level must fail; '
                                             'the rejection is the confirmation'),
                                data_used='previous-session levels + session open'))

    # ---- F3: breakdown of a pre-existing support, then the failed retest -----
    if sup:
        lv, _, name = sup
        for i in range(1, len(candles)):
            if close_v[i] < lv:
                out.append(_base_setup('F3_BREAKDOWN_RETEST', inst, day, lv, i,
                                        candles, level_name=name,
                                        why_monitor=('support level broken on a '
                                                     'close; wait for the failed '
                                                     'retest'),
                                        data_used=('previous-session levels + '
                                                   'closed candles'),
                                        breakdown_ts=str(candles[i]['timestamp'])))
                break

    # ---- F4: pullback into a confirmed swing high of a confirmed downtrend ----
    for i in range(1, len(candles)):
        dt = structures.confirmed_downtrend(candles, i)
        if not dt:
            continue
        sh = dt['last_swing_high']
        if sh['price'] <= close_v[i]:
            continue
        out.append(_base_setup('F4_PULLBACK_TO_SWING_HIGH', inst, day, sh['price'], i,
                                candles, level_name='SWING_HIGH',
                                why_monitor=('confirmed lower-high structure; wait '
                                             'for the rally into the last confirmed '
                                             'swing high'),
                                data_used='point-in-time confirmed m=2 fractals',
                                swing_confirm_idx=sh['confirm_idx'],
                                swing_high_ts=sh['ts']))
        break

    # ---- F6: break of a confirmed swing low in a confirmed downtrend ---------
    for i in range(1, len(candles)):
        dt = structures.confirmed_downtrend(candles, i)
        if not dt:
            continue
        sl = dt['last_swing_low']
        if close_v[i] >= sl['price']:
            continue
        out.append(_base_setup('F6_SWING_BREAK_RETEST', inst, day, sl['price'], i,
                                candles, level_name='SWING_LOW',
                                why_monitor=('confirmed swing low broken in a '
                                             'downtrend; wait for the failed retest'),
                                data_used='point-in-time confirmed m=2 fractals',
                                swing_confirm_idx=sl['confirm_idx'],
                                swing_low_ts=sl['ts'],
                                breakdown_ts=str(candles[i]['timestamp'])))
        break

    for s in out:
        s['period'] = period
    return out
