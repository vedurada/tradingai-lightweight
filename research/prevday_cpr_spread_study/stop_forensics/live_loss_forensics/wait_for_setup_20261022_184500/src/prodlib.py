"""Faithful replica of the production signal/exit rules (pure functions).

Source of truth: /opt/tradingai/app/research/cpr_trigger_engine.py and
app/research/cpr_strategy_engine.py (read 2026-10-22). The functions below are
behavioural copies of the production code so the study never imports production
modules (no import side effects, no live DB handles). Every copy is annotated
with the production function it mirrors.
"""
import wconfig as C


# ------------------------------------------- cpr_strategy_engine.py ---------
def calculate_cpr(prev_high, prev_low, prev_close):
    """Copy of app/research/cpr_strategy_engine.py:calculate_cpr."""
    pp = (prev_high + prev_low + prev_close) / 3
    bc = (prev_high + prev_low) / 2
    tc = (pp * 2) - bc
    if tc < bc:
        tc, bc = bc, tc
    width_pct = ((tc - bc) / pp) * 100 if pp != 0 else 0
    return {'pp': round(pp, 4), 'tc': round(tc, 4), 'bc': round(bc, 4),
            'width_pct': round(width_pct, 6)}


def pivot_levels(prev_high, prev_low, pp):
    """Copy of app/research/cpr_strategy_engine.py:pivot_levels."""
    r1 = 2 * pp - prev_low
    s1 = 2 * pp - prev_high
    rng = prev_high - prev_low
    return {'r1': r1, 's1': s1, 'r2': pp + rng, 's2': pp - rng}


# ------------------------------------------- cpr_trigger_engine.py ----------
def day_levels(prev_high, prev_low, prev_close):
    """Copy of cpr_trigger_engine.py:day_levels."""
    try:
        ph, pl, pc = float(prev_high), float(prev_low), float(prev_close)
    except (TypeError, ValueError):
        return None
    if not (ph > 0 and pl > 0 and pc > 0 and ph >= pl):
        return None
    cpr = calculate_cpr(ph, pl, pc)
    piv = pivot_levels(ph, pl, cpr['pp'])
    return {'pp': cpr['pp'], 'tc': cpr['tc'], 'bc': cpr['bc'],
            'r1': piv['r1'], 's1': piv['s1'], 'r2': piv['r2'], 's2': piv['s2'],
            'pdh': ph, 'pdl': pl, 'prev_close': pc}


def bear_trigger(candle, lv):
    """Copy of cpr_trigger_engine.py:bear_trigger."""
    try:
        hi, cl = float(candle['high']), float(candle['close'])
    except (KeyError, TypeError, ValueError):
        return None
    if hi >= lv['r2']:
        return 'R2'
    if hi >= lv['r1']:
        return 'R1'
    if hi >= lv['pdh']:
        return 'PDH'
    if cl < lv['bc']:
        return 'BELOW_CPR'
    return None


def bull_trigger(candle, lv):
    """Copy of cpr_trigger_engine.py:bull_trigger (diagnostics only: SHORT_ONLY)."""
    try:
        lo, cl = float(candle['low']), float(candle['close'])
    except (KeyError, TypeError, ValueError):
        return None
    if lo <= lv['s2']:
        return 'S2'
    if lo <= lv['s1']:
        return 'S1'
    if lo <= lv['pdl']:
        return 'PDL'
    if cl > lv['tc']:
        return 'ABOVE_CPR'
    return None


_BREAKOUT_UP = (('BRK_R1', 'r1'), ('BRK_R2', 'r2'), ('BRK_PDH', 'pdh'), ('BRK_TC', 'tc'))
_BREAKOUT_DN = (('BRK_S1', 's1'), ('BRK_S2', 's2'), ('BRK_PDL', 'pdl'), ('BRK_BC', 'bc'))

# (level_name, implied_direction, day_levels key). Resistance first (bear
# priority on a tie), then support. Copy of cpr_trigger_engine.py:_ENTRY_LEVELS.
_ENTRY_LEVELS = (
    ('R2', 'BEAR', 'r2'), ('R1', 'BEAR', 'r1'), ('PDH', 'BEAR', 'pdh'),
    ('BC', 'BEAR', 'bc'),
    ('TC', 'BULL', 'tc'), ('S1', 'BULL', 's1'), ('S2', 'BULL', 's2'),
    ('PDL', 'BULL', 'pdl'),
)


def is_friday(day_iso):
    """Copy of cpr_trigger_engine.py:is_friday."""
    try:
        from datetime import datetime as _dt
        return _dt.fromisoformat(str(day_iso)[:10]).weekday() == 4
    except (TypeError, ValueError):
        return False


def friday_skip(direction, day_iso):
    """Copy of cpr_trigger_engine.py:friday_skip."""
    return bool(C.SKIP_FRIDAY and direction == 'BEAR' and is_friday(day_iso))


def breakout_trigger(candle, prev_close, lv):
    """Copy of cpr_trigger_engine.py:breakout_trigger."""
    if not lv or prev_close is None:
        return None
    try:
        cl = float(candle['close'])
        pc = float(prev_close)
    except (KeyError, TypeError, ValueError):
        return None
    for name, key in _BREAKOUT_UP:
        lvl = lv.get(key)
        if lvl and pc <= lvl < cl:
            return 'BULL', name
    for name, key in _BREAKOUT_DN:
        lvl = lv.get(key)
        if lvl and pc >= lvl > cl:
            return 'BEAR', name
    return None


def breakout_signal(candles, lv, wlv=None, variant='plain'):
    """Copy of cpr_trigger_engine.py:breakout_signal (aligned gate off for 'plain')."""
    if not lv or not C.BREAKOUT_ADDON:
        return None
    prev = None
    for i, c in enumerate(candles or []):
        try:
            close = float(c['close'])
        except (KeyError, TypeError, ValueError):
            prev = None
            continue
        r = breakout_trigger(c, prev, lv)
        prev = close
        if not r:
            continue
        dr, name = r
        if variant == 'aligned' and wlv is None:
            return None
        return dr, name, i
    return None


def entry_levels(lv):
    """Copy of cpr_trigger_engine.py:entry_levels."""
    if not lv:
        return []
    out = []
    for name, dr, key in _ENTRY_LEVELS:
        try:
            ref = float(lv.get(key))
        except (TypeError, ValueError):
            continue
        if ref and ref > 0:
            out.append((name, dr, ref))
    return out


def no_chase_fill(lv, candles, i):
    """Copy of cpr_trigger_engine.py:no_chase_fill (the rule disabled 2026-10-17)."""
    levels = entry_levels(lv)
    if not levels:
        return None
    for j in range(i + 1, len(candles or [])):
        c = candles[j]
        try:
            op, hi, lo = float(c['open']), float(c['high']), float(c['low'])
        except (KeyError, TypeError, ValueError):
            continue
        for name, dr, ref in levels:
            if abs(op - ref) <= C.NO_CHASE_BAND_PCT * ref:
                return j, name, dr, op
        for name, dr, ref in levels:
            if lo <= ref <= hi:
                return j, name, dr, ref
    return None


def exits_opens(direction, entry, stop_pct, target_pct, opens):
    """Copy of cpr_trigger_engine.py:exits_opens (opens-only execution)."""
    risk = abs(entry * stop_pct)
    if not risk:
        return 0.0, entry, 'NO_RISK', None
    if direction == 'BULL':
        stop, tgt = entry * (1 - stop_pct), entry * (1 + target_pct)
    else:
        stop, tgt = entry * (1 + stop_pct), entry * (1 - target_pct)
    for ts, o in opens:
        try:
            o = float(o)
        except (TypeError, ValueError):
            continue
        if direction == 'BULL':
            s, t = o <= stop, o >= tgt
        else:
            s, t = o >= stop, o <= tgt
        if s:
            return -1.0, round(o, 2), 'STOP', ts
        if t:
            return round(target_pct / stop_pct, 3), round(o, 2), 'TARGET', ts
    return None


def decay_win(direction, entry, exit_px, r_multiple, instrument):
    """Copy of cpr_trigger_engine.py:decay_win."""
    try:
        if r_multiple is None:
            return None
        if r_multiple > 0:
            return 'WIN'
        if r_multiple < 0:
            tol = C.DECAY_TOL_POINTS.get((instrument or '').upper(), 30.0)
            pts = ((float(exit_px) - float(entry)) if direction == 'BULL'
                   else (float(entry) - float(exit_px)))
            if abs(pts) < tol:
                return 'WIN'
            return 'LOSS'
        return 'FLAT'
    except (TypeError, ValueError):
        return None


def evaluate_outcome(direction, entry, entry_idx, candles, instrument):
    """Production exit + label for an entry at candles[entry_idx].

    Mirrors run_opens_range: exits walk the OPENS after the entry candle,
    stop before target, a gap is honoured at the breaching open; with no
    exit the trade is flat at the 15:20 open.
    """
    opens = [(c['timestamp'], c['open']) for c in candles[entry_idx + 1:]]
    eod = [c for c in candles if c['timestamp'][11:16] == C.OPEN_EOD]
    if not eod:
        return None
    hit = exits_opens(direction, entry, C.OPEN_STOP_PCT, C.OPEN_TARGET_PCT, opens)
    risk = abs(entry * C.OPEN_STOP_PCT)
    if hit is None:
        try:
            last = float(eod[0]['open'])
        except (KeyError, TypeError, ValueError):
            return None
        move = (last - entry) if direction == 'BULL' else (entry - last)
        r = round(move / risk, 3) if risk else 0.0
        xp, how, xt = round(last, 2), 'EOD-1520', eod[0]['timestamp']
    else:
        r, xp, how, xt = hit
    pts = round((xp - entry) if direction == 'BULL' else (entry - xp), 1)
    label = decay_win(direction, entry, xp, r, instrument)
    mae_pts = _mae_points(direction, entry, candles[entry_idx + 1:])
    return {
        'entry': round(float(entry), 2),
        'entry_time': candles[entry_idx]['timestamp'][:16].replace('T', ' '),
        'exit': xp,
        'exit_time': (xt or '')[:16].replace('T', ' '),
        'exit_reason': how,
        'r_multiple': r,
        'points': pts,
        'win_loss': label,
        'mae_pts': mae_pts,
        'mae_r': round(mae_pts / risk, 3) if risk else None,
    }


def _mae_points(direction, entry, fwd):
    """Max adverse excursion in points from the entry (highs/lows after entry)."""
    best = 0.0
    for c in fwd:
        try:
            hi, lo = float(c['high']), float(c['low'])
        except (KeyError, TypeError, ValueError):
            continue
        if direction == 'BEAR':
            adv = hi - entry
        else:
            adv = entry - lo
        if adv > best:
            best = adv
    return round(best, 1)


def level_price(level_name, lv):
    """Price of the trigger level inside the day's level bundle."""
    m = {
        'R2': 'r2', 'R1': 'r1', 'PDH': 'pdh', 'BELOW_CPR': 'bc',
        'S2': 's2', 'S1': 's1', 'PDL': 'pdl', 'ABOVE_CPR': 'tc',
        'BRK_R1': 'r1', 'BRK_R2': 'r2', 'BRK_PDH': 'pdh', 'BRK_TC': 'tc',
        'BRK_S1': 's1', 'BRK_S2': 's2', 'BRK_PDL': 'pdl', 'BRK_BC': 'bc',
    }
    key = m.get(level_name)
    if not key or not lv:
        return None
    try:
        v = float(lv.get(key))
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None
