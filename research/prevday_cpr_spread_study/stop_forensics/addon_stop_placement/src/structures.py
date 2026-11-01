"""Point-in-time structural stop derivation for B0 and S1-S5.

Every stop below is computed from candles with ``timestamp <= trigger candle`` only.
The entry is the open of the candle AFTER the trigger (production rule), so anything
observed up to and including the trigger candle is legitimately available at the
entry timestamp. Nothing later than the trigger candle may influence a stop, a
buffer, a swing, a retest or a rejection.

All parameters are frozen in ``spec_addon.md`` before this module was run.
"""
from __future__ import annotations

import statistics

EPS_PCT = 0.0002          # minimum clearance beyond a structural extreme (0.02%)
Z = 0.0010                # retest tolerance (0.10% of the level)
SWING_LOOKBACK = 20       # max distance (bars) between the swing bar and the trigger
SWING_M = 2               # fractal confirmation width (bars each side)
K_VOL = 0.5               # volatility buffer multiplier (S5)
VOL_MIN_BARS = 3          # minimum bars for a median-range buffer
MIN_STOP_PCT = 0.0025     # a stop closer than 0.25% is unusable
MAX_STOP_PCT = 0.0150     # a stop wider than 1.50% is excessive
PULLBACK_MULT = 1.0       # stop closer than 1x median bar range = noise-level

CPR_SETUPS = ('BELOW_CPR', 'ABOVE_CPR', 'BRK_BC', 'BRK_TC')
LEVEL_NAMES = {
    'pp': 'pivot', 'tc': 'CPR top', 'bc': 'CPR bottom',
    'r1': 'R1', 'r2': 'R2', 's1': 'S1', 's2': 'S2',
    'pdh': 'prior day high', 'pdl': 'prior day low',
}


def eps(entry: float) -> float:
    return EPS_PCT * entry


def pit_median_range(candles: list, trig_idx: int, min_bars: int = VOL_MIN_BARS):
    """Median intrabar range of candles 0..trig_idx inclusive (point-in-time)."""
    if trig_idx is None or trig_idx < 0:
        return None
    vals = [float(c['high']) - float(c['low']) for c in candles[:trig_idx + 1]]
    if len(vals) < min_bars:
        return None
    return float(statistics.median(vals))


def swings(candles: list, m: int = SWING_M) -> list:
    """Strict fractal swings, each with its confirmation bar index.

    Bar i is a swing high iff high[i] is strictly above the highs of the m bars on
    each side. It is only *confirmed* at the close of bar i+m.
    """
    out = []
    n = len(candles)
    for i in range(m, n - m):
        hi = float(candles[i]['high'])
        lo = float(candles[i]['low'])
        if (all(hi > float(candles[i - k]['high']) for k in range(1, m + 1))
                and all(hi > float(candles[i + k]['high']) for k in range(1, m + 1))):
            out.append({'idx': i, 'kind': 'HIGH', 'price': hi, 'confirm_idx': i + m})
        if (all(lo < float(candles[i - k]['low']) for k in range(1, m + 1))
                and all(lo < float(candles[i + k]['low']) for k in range(1, m + 1))):
            out.append({'idx': i, 'kind': 'LOW', 'price': lo, 'confirm_idx': i + m})
    return out


def usable_swing(candles: list, trig_idx: int, direction: str, entry: float):
    """Most recent usable swing extreme, or (None, reason)."""
    if trig_idx is None:
        return None, 'no_trigger_index'
    want = 'HIGH' if direction == 'BEAR' else 'LOW'
    cands = [s for s in swings(candles)
             if s['kind'] == want and s['confirm_idx'] <= trig_idx
             and s['idx'] >= trig_idx - SWING_LOOKBACK]
    if not cands:
        return None, 'no_confirmed_swing_within_lookback'
    s = max(cands, key=lambda x: x['idx'])
    if direction == 'BEAR' and s['price'] <= entry:
        return None, 'swing_on_wrong_side_of_entry'
    if direction == 'BULL' and s['price'] >= entry:
        return None, 'swing_on_wrong_side_of_entry'
    return s, None


def _nearest_level(levels: dict, entry: float, side: str):
    if not levels:
        return None, None
    keys = ('r1', 'r2', 'pdh', 'tc', 'pp') if side == 'above' else ('s1', 's2', 'pdl', 'bc', 'pp')
    vals = [(k, float(levels[k])) for k in keys if levels.get(k) is not None]
    if side == 'above':
        vals = [(k, v) for k, v in vals if v > entry]
        return (min(vals, key=lambda kv: kv[1]) if vals else (None, None))
    vals = [(k, v) for k, v in vals if v < entry]
    return (max(vals, key=lambda kv: kv[1]) if vals else (None, None))


def failed_break(candles: list, trig_idx: int, levels: dict, entry: float,
                 direction: str):
    """Most recent failed opposite-side break attempt before the trigger.

    BEAR: nearest level above the entry; a bar crosses it (high >= level) and at
    least one close returns below it before the trigger. Extreme = max high of the
    attempt. BULL: mirror below the entry.
    """
    side = 'above' if direction == 'BEAR' else 'below'
    name, level = _nearest_level(levels, entry, side)
    if level is None:
        return None
    if direction == 'BEAR':
        crossed = lambda c: float(c['high']) >= level
        inside = lambda c: float(c['close']) < level
        extreme = lambda cs: max(float(c['high']) for c in cs)
    else:
        crossed = lambda c: float(c['low']) <= level
        inside = lambda c: float(c['close']) > level
        extreme = lambda cs: min(float(c['low']) for c in cs)
    j = next((i for i in range(0, trig_idx) if crossed(candles[i])), None)
    if j is None:
        return None
    f = next((k for k in range(j, trig_idx) if inside(candles[k])), None)
    if f is None:
        return None  # price crossed and never closed back inside -> not a failure
    window = candles[j:trig_idx]
    return {'level_key': name, 'level_name': LEVEL_NAMES.get(name, name),
            'level': round(level, 4), 'cross_idx': j, 'fail_idx': f,
            'extreme': round(extreme(window), 4)}


def retest(candles: list, trig_idx: int, entry_idx: int, level, direction: str,
           break_side):
    """Completed retest of the trigger level before the entry bar, or None.

    ``break_side`` is the side price travelled to reach the level ('above' for
    R1/R2/PDH/ABOVE_CPR/BRK_R*/BRK_TC, 'below' for support/breakdown levels).
    Retest = extreme returns to within Z of the level and the bar closes back on the
    trade-favourable side.
    """
    if level is None or break_side is None or trig_idx is None or entry_idx is None:
        return None
    for i in range(trig_idx, entry_idx):
        c = candles[i]
        if break_side == 'above':
            near = float(c['low']) <= level * (1 + Z)
        else:
            near = float(c['high']) >= level * (1 - Z)
        favourable = (float(c['close']) < level) if direction == 'BEAR' else (float(c['close']) > level)
        if near and favourable:
            window = candles[trig_idx:i + 1]
            ext = (max(float(c['high']) for c in window) if direction == 'BEAR'
                   else min(float(c['low']) for c in window))
            return {'idx': i, 'extreme': round(ext, 4), 'level': round(level, 4),
                    'break_side': break_side}
    return None


def validate(direction: str, entry: float, stop: float):
    """Return a rejection reason string, or None when the stop is usable."""
    if stop is None:
        return 'no_structural_level'
    dist = (stop - entry) if direction == 'BEAR' else (entry - stop)
    if dist <= 0:
        return 'stop_on_wrong_side_of_entry'
    pct = dist / entry
    if pct < MIN_STOP_PCT:
        return 'stop_too_tight_below_minimum'
    if pct > MAX_STOP_PCT:
        return 'stop_too_wide_risk_excessive'
    return None


def derive(signal: dict, entry: float, variant: str) -> dict:
    """Derive one stop variant for one signal.

    Returns a dict with ``stop_price`` (None on NO TRADE), ``stop_rule``, the
    point-in-time evidence, ``inputs_max_idx`` (the largest candle index used, for
    the lookahead audit) and ``rejection_reason``.
    """
    ctx = signal['ctx']
    candles = ctx['scan']
    trig = signal['trigger_idx']
    direction = signal['direction']
    levels = ctx['levels'] or {}
    base = {'variant': variant, 'rejection_reason': None, 'stop_price': None,
            'stop_rule': None, 'evidence': {}, 'inputs_max_idx': trig}

    if variant == 'B0':
        stop = entry * (1 + 0.005) if direction == 'BEAR' else entry * (1 - 0.005)
        return {**base, 'stop_price': round(stop, 4),
                'stop_rule': 'production 0.5% of entry',
                'evidence': {'kind': 'production_pct'}}

    if variant in ('S1', 'S5'):
        sw, why = usable_swing(candles, trig, direction, entry)
        if sw is None:
            return {**base, 'rejection_reason': why}
        stop = sw['price'] + eps(entry) if direction == 'BEAR' else sw['price'] - eps(entry)
        ev = {'kind': 'confirmed_swing', 'swing_idx': sw['idx'],
              'swing_confirm_idx': sw['confirm_idx'], 'swing_price': round(sw['price'], 4)}
        rule = ('S1 confirmed swing high + EPS' if direction == 'BEAR'
                else 'S1 confirmed swing low - EPS')
        if variant == 'S5':
            med = pit_median_range(candles, trig)
            if med is None:
                return {**base, 'rejection_reason': 'insufficient_bars_for_vol_buffer'}
            buf = K_VOL * med
            stop = (stop + buf) if direction == 'BEAR' else (stop - buf)
            ev.update({'median_range_pts': round(med, 4), 'vol_buffer_pts': round(buf, 4),
                       'k_vol': K_VOL})
            rule = ('S5 confirmed swing high + EPS + k*median range' if direction == 'BEAR'
                    else 'S5 confirmed swing low - EPS - k*median range')
        reason = validate(direction, entry, stop)
        return {**base, 'stop_price': None if reason else round(stop, 4),
                'stop_rule': rule, 'evidence': ev, 'rejection_reason': reason}

    if variant == 'S2':
        fb = failed_break(candles, trig, levels, entry, direction)
        if fb is None:
            return {**base, 'rejection_reason': 'no_failed_opposite_break_attempt'}
        stop = fb['extreme'] + eps(entry) if direction == 'BEAR' else fb['extreme'] - eps(entry)
        reason = validate(direction, entry, stop)
        return {**base, 'stop_price': None if reason else round(stop, 4),
                'stop_rule': ('S2 failed upside-break high + EPS' if direction == 'BEAR'
                              else 'S2 failed downside-break low - EPS'),
                'evidence': fb, 'inputs_max_idx': max(trig, fb['fail_idx']),
                'rejection_reason': reason}

    if variant == 'S3':
        rt = retest(candles, trig, signal['entry_idx'], signal.get('level_price'),
                    direction, signal.get('break_side'))
        if rt is None:
            return {**base, 'rejection_reason': 'no_completed_retest_before_entry'}
        stop = rt['extreme'] + eps(entry) if direction == 'BEAR' else rt['extreme'] - eps(entry)
        reason = validate(direction, entry, stop)
        return {**base, 'stop_price': None if reason else round(stop, 4),
                'stop_rule': ('S3 retested resistance high + EPS' if direction == 'BEAR'
                              else 'S3 retested support low - EPS'),
                'evidence': rt, 'inputs_max_idx': max(trig, rt['idx']),
                'rejection_reason': reason}

    if variant == 'S4':
        if signal['level'] not in CPR_SETUPS:
            return {**base, 'rejection_reason': 'setup_does_not_support_cpr_invalidation'}
        if levels.get('tc') is None or levels.get('bc') is None:
            return {**base, 'rejection_reason': 'missing_cpr_boundary'}
        if direction == 'BEAR':
            stop = float(levels['tc']) + eps(entry)
            rule = 'S4 CPR-top invalidation (close back above CPR top) + EPS'
        else:
            stop = float(levels['bc']) - eps(entry)
            rule = 'S4 CPR-bottom invalidation (close back below CPR bottom) - EPS'
        reason = validate(direction, entry, stop)
        return {**base, 'stop_price': None if reason else round(stop, 4),
                'stop_rule': rule,
                'evidence': {'cpr_top': float(levels['tc']), 'cpr_bottom': float(levels['bc'])},
                'rejection_reason': reason}

    raise ValueError(f'unknown variant {variant}')
