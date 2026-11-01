"""Research-only candidate signal engine: reversal (A/B) + breakout (C).

Everything here is a PURE function over completed candle lists plus the
point-in-time level bundle for the session. No database access, no I/O and no
future candles: every decision made at index k uses only candles[0..k], and
the entry is always the open of candle k+1 (asserted by
tests/test_research.py::test_no_lookahead).

Strategy A (bearish reversal, short-credit direction) at R1 / R2 / CPR-top /
PDH.  Strategy B (bullish reversal, bull-credit direction) at S1 / S2 /
CPR-bottom / PDL.  Strategy C (breakout) above R1/R2/PDH/TC or below
S1/S2/PDL/BC.

Entry is ALWAYS the open of the candle AFTER the trigger candle, inside the
production entry window [09:20, 15:20) — identical to the baseline's
next-open execution, so the only difference between baseline and candidate is
WHICH signals are taken, never how they are executed or exited.

No-look-ahead rules embedded here:
- reversal: confirmation at candle i (completed), entry trigger = first later
  candle j that breaks the confirmation extreme, entry at open(j+1). Nothing
  after j is consulted.
- breakout (no-retest): `follow_through` later candles must all close beyond
  the level before entry at open(i+1+follow_through); a close back through the
  level is observed BEFORE entry, so failed breaks are a legal filter.
- breakout (retest): failure and retest are checked in one forward walk; the
  entry is placed at open(j+1) after the retest candle j completes.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

from common import (MIN_SESSION_CANDLES, OPEN_EOD, OPEN_MIN, STOP_PCT,
                    scan_candles)

# Ordered level families (production order: strongest outer level first for
# bear, then inner; the order also decides a same-candle multi-level tie).
BEAR_LEVELS = (('A2', 'r2', 'R2'), ('A1', 'r1', 'R1'),
               ('A4', 'pdh', 'PDH'), ('A3', 'tc', 'TC'))
BULL_LEVELS = (('B2', 's2', 'S2'), ('B1', 's1', 'S1'),
               ('B4', 'pdl', 'PDL'), ('B3', 'bc', 'BC'))
BREAKOUT_UP = (('C_UP_R1', 'r1', 'R1'), ('C_UP_R2', 'r2', 'R2'),
               ('C_UP_PDH', 'pdh', 'PDH'), ('C_UP_TC', 'tc', 'TC'))
BREAKOUT_DN = (('C_DN_S1', 's1', 'S1'), ('C_DN_S2', 's2', 'S2'),
               ('C_DN_PDL', 'pdl', 'PDL'), ('C_DN_BC', 'bc', 'BC'))

# Levels below/above entry used as the structure target ("next relevant level").
_TARGETS_DOWN = (('pp', 'PP'), ('bc', 'BC'), ('tc', 'TC'), ('s1', 'S1'),
                 ('s2', 'S2'), ('pdl', 'PDL'))
_TARGETS_UP = (('pp', 'PP'), ('tc', 'TC'), ('bc', 'BC'), ('r1', 'R1'),
               ('r2', 'R2'), ('pdh', 'PDH'))


@dataclass
class Candidate:
    kind: str                 # 'REVERSAL' | 'BREAKOUT'
    family: str               # 'A1'..'A4','B1'..'B4','C_UP_R1',...
    direction: str            # 'BULL' | 'BEAR'
    level_name: str
    level: float
    confirm_idx: int
    trigger_idx: int
    confirm_time: str = ''
    trigger_time: str = ''
    entry_idx: int = -1
    entry_time: str = ''
    entry: float = 0.0
    structure_stop: float = 0.0
    structure_target: float | None = None
    next_level_name: str | None = None
    next_level: float | None = None
    evidence: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


def new_counters() -> dict:
    return {'no_confirmation': 0, 'rejected_conflict': 0,
            'rejected_no_trigger': 0, 'rejected_entry_window': 0,
            'rejected_reward_filter': 0, 'rejected_failed_break': 0,
            'rejected_short_day': 0, 'duplicate_suppressed': 0}


# --------------------------------------------------------------------------
# rejection / hold helpers
# --------------------------------------------------------------------------
def _rng(c):
    try:
        return float(c['high']) - float(c['low'])
    except (KeyError, TypeError, ValueError):
        return 0.0


def upper_shadow_frac(c) -> float:
    r = _rng(c)
    if r <= 0:
        return 0.0
    return (float(c['high']) - max(float(c['open']), float(c['close']))) / r


def lower_shadow_frac(c) -> float:
    r = _rng(c)
    if r <= 0:
        return 0.0
    return (min(float(c['open']), float(c['close'])) - float(c['low'])) / r


def bear_rejects(c, level: float, cfg: dict):
    """A completed 5m candle REJECTING resistance `level` (not merely touching).

    Requires: the level was tested (high >= level), price closed back below it
    (a wick-only pierce that closes beyond the level is a break, not a
    rejection), a bearish body, and a minimum upper shadow.
    Returns (ok: bool, evidence: dict)."""
    try:
        h, o, cl = float(c['high']), float(c['open']), float(c['close'])
    except (KeyError, TypeError, ValueError):
        return False, {}
    if h < level:
        return False, {'tested': False}
    if cl >= level:
        return False, {'closed_above_level': True}
    if cfg.get('require_bearish_body', True) and cl >= o:
        return False, {'not_bearish_body': True}
    usf = upper_shadow_frac(c)
    if usf < float(cfg.get('min_shadow_frac', 0.25)):
        return False, {'upper_shadow_too_small': round(usf, 3)}
    return True, {'high': h, 'close': cl, 'overshoot_pts': round(h - level, 2),
                  'upper_shadow_frac': round(usf, 3)}


def bull_holds(c, level: float, cfg: dict):
    """A completed 5m candle SHOWING A BULLISH RESPONSE at support `level`.

    Requires: the level was tested (low <= level), price closed back above it
    (a close through the level is a breakdown/reclaim miss, not a hold), a
    bullish body and a minimum lower shadow."""
    try:
        l, o, cl = float(c['low']), float(c['open']), float(c['close'])
    except (KeyError, TypeError, ValueError):
        return False, {}
    if l > level:
        return False, {'tested': False}
    if cl <= level:
        return False, {'closed_below_level': True}
    if cfg.get('require_bullish_body', True) and cl <= o:
        return False, {'not_bullish_body': True}
    lsf = lower_shadow_frac(c)
    if lsf < float(cfg.get('min_shadow_frac', 0.25)):
        return False, {'lower_shadow_too_small': round(lsf, 3)}
    return True, {'low': l, 'close': cl, 'undershoot_pts': round(level - l, 2),
                  'lower_shadow_frac': round(lsf, 3)}


def fresh_cross(c, prev_close, level: float, direction: str):
    """True when the candle CLOSE freshly crosses `level` (never a wick-only).

    'BULL' -> previous close at/below level and this close above it.
    'BEAR' -> previous close at/above level and this close below it.
    """
    if prev_close is None:
        return False
    try:
        cl, pc = float(c['close']), float(prev_close)
    except (KeyError, TypeError, ValueError):
        return False
    if direction == 'BULL':
        return pc <= level < cl
    return pc >= level > cl


# --------------------------------------------------------------------------
# session scan
# --------------------------------------------------------------------------
def scan_session(candles, levels, cfg):
    """Return (candidates, counters) for ONE session. Pure, no I/O.

    Candidates are ordered by confirmation index (breakout before reversal on
    an identical index) so downstream selection is deterministic.
    """
    counters = new_counters()
    candles = scan_candles(candles)
    if len(candles) < MIN_SESSION_CANDLES:
        counters['rejected_short_day'] += 1
        return [], counters

    mode = cfg.get('mode', 'combined')
    out = []

    if mode in ('combined', 'reversal'):
        out.extend(_scan_reversals(candles, levels, cfg, counters))
    if mode in ('combined', 'breakout'):
        sides = cfg.get('breakout_sides', ['UP', 'DN'])
        if 'UP' in sides:
            out.extend(_scan_breakouts(candles, levels, cfg, BREAKOUT_UP,
                                       'BULL', counters))
        if 'DN' in sides:
            out.extend(_scan_breakouts(candles, levels, cfg, BREAKOUT_DN,
                                       'BEAR', counters))

    out.sort(key=lambda k: (k.confirm_idx, 0 if k.kind == 'BREAKOUT' else 1))
    return out, counters


def _scan_reversals(candles, levels, cfg, counters):
    """Earliest confirmed reversal, scanning candle-major then level order.

    Candle-major ordering mirrors the production book (earliest trigger wins,
    level priority only decides a same-candle tie)."""
    out = []
    fams = cfg.get('reversal_families')
    for direction, families, checker in (
            ('BEAR', BEAR_LEVELS, bear_rejects),
            ('BULL', BULL_LEVELS, bull_holds)):
        ordered = [(f, k, n) for f, k, n in families
                   if fams is None or f in fams]
        if not ordered:
            continue
        found = None
        window_dead = False
        for i, c in enumerate(candles):
            if window_dead:
                break
            for fam, key, name in ordered:
                level = levels.get(key)
                if not level or level <= 0:
                    continue
                ok, ev = checker(c, level, cfg)
                if not ok:
                    continue
                trig = _reversal_trigger(candles, i, direction, cfg)
                if trig is None:
                    counters['rejected_no_trigger'] += 1
                    continue           # try other levels, then later candles
                j, jreason = trig
                if not _entry_window_ok(candles, j):
                    counters['rejected_entry_window'] += 1
                    window_dead = True    # every later entry is later too
                    break
                found = Candidate(
                    kind='REVERSAL', family=fam, direction=direction,
                    level_name=name, level=float(level), confirm_idx=i,
                    trigger_idx=j, confirm_time=c['timestamp'],
                    trigger_time=candles[j]['timestamp'],
                    evidence={'confirmation': ev, 'trigger': jreason})
                break
            if found:
                break
        if found:
            _attach_reversal_geometry(found, candles, levels)
            out.append(found)
    return out


def _reversal_trigger(candles, i, direction, cfg):
    """First candle j>i breaking the confirmation candle's extreme.

    BEAR: break below the rejection candle's low. BULL: break above the
    confirmation candle's high. Optional `trigger_require_close` additionally
    demands the break candle CLOSE beyond the extreme (a wick-only break then
    does not trigger). Returns (j, reason) or None. Pure."""
    try:
        c_low = float(candles[i]['low'])
        c_high = float(candles[i]['high'])
    except (KeyError, TypeError, ValueError):
        return None
    need_close = bool(cfg.get('trigger_require_close', False))
    for j in range(i + 1, len(candles)):
        c = candles[j]
        try:
            lo, hi, cl = float(c['low']), float(c['high']), float(c['close'])
        except (KeyError, TypeError, ValueError):
            continue
        if direction == 'BEAR':
            if lo <= c_low and (not need_close or cl <= c_low):
                return j, {'kind': 'break_below_confirm_low',
                           'confirm_low': c_low, 'trigger_low': lo, 'close': cl}
        else:
            if hi >= c_high and (not need_close or cl >= c_high):
                return j, {'kind': 'break_above_confirm_high',
                           'confirm_high': c_high, 'trigger_high': hi,
                           'close': cl}
    return None


def _entry_window_ok(candles, trigger_idx):
    """Entry = open of candle trigger_idx+1, inside [09:20, 15:20) (baseline)."""
    k = trigger_idx + 1
    if k >= len(candles):
        return False
    t = str(candles[k]['timestamp'])[11:16]
    return OPEN_MIN <= t < OPEN_EOD


def _entry_of(candles, trigger_idx):
    k = trigger_idx + 1
    c = candles[k]
    return round(float(c['open']), 2), str(c['timestamp']), k


def _attach_reversal_geometry(cand, candles, levels):
    entry, entry_time, eidx = _entry_of(candles, cand.trigger_idx)
    cand.entry, cand.entry_time, cand.entry_idx = entry, entry_time, eidx
    confirm = candles[cand.confirm_idx]
    if cand.direction == 'BEAR':
        stop = float(confirm['high'])          # invalidation: rejection high
        target, tname, tlevel = _next_below(levels, entry)
    else:
        stop = float(confirm['low'])           # invalidation: rejection low
        target, tname, tlevel = _next_above(levels, entry)
    cand.structure_stop = round(stop, 2)
    cand.structure_target = (round(target, 2) if target is not None else None)
    cand.next_level_name, cand.next_level = tname, tlevel


def _next_below(levels, entry):
    best = None
    for key, name in _TARGETS_DOWN:
        v = levels.get(key)
        if v and 0 < v < entry and (best is None or v > best[0]):
            best = (v, name)
    if best:
        return best[0], best[1], best[0]
    return None, None, None


def _next_above(levels, entry):
    best = None
    for key, name in _TARGETS_UP:
        v = levels.get(key)
        if v and v > entry and (best is None or v < best[0]):
            best = (v, name)
    if best:
        return best[0], best[1], best[0]
    return None, None, None


# --------------------------------------------------------------------------
# breakouts
# --------------------------------------------------------------------------
def _scan_breakouts(candles, levels, cfg, table, direction, counters):
    """Confirmed fresh close-cross breakouts with follow-through / retest.

    One candidate per level per session (the FIRST cross). A cross that fails
    immediately disqualifies that level for the session; the failure is always
    observed on a candle that COMPLETES BEFORE the entry candle, so this is a
    legal filter and not look-ahead.
    """
    out = []
    for fam, key, name in table:
        if cfg.get('breakout_families') is not None and \
                fam not in cfg['breakout_families']:
            continue
        level = levels.get(key)
        if not level or level <= 0:
            continue
        require_retest = bool(cfg.get('require_retest', False))
        ft = int(cfg.get('follow_through', 1))
        retest_band = float(cfg.get('retest_band', 0.0010))
        min_rr = float(cfg.get('min_level_rr', 0.0))
        cand = None
        for i in range(1, len(candles)):
            c, prev = candles[i], candles[i - 1]
            if not fresh_cross(c, prev.get('close'), level, direction):
                continue
            if require_retest:
                cand = _retest_entry(candles, i, level, direction, retest_band,
                                     fam, name, counters)
            else:
                cand = _followthrough_entry(candles, i, level, direction, ft,
                                             fam, name, counters)
            break                      # only the first cross of the level counts
        if cand is None:
            continue
        _attach_breakout_geometry(cand, candles, levels)
        if min_rr > 0 and _reward_ok(cand, min_rr) is False:
            counters['rejected_reward_filter'] += 1
            continue
        out.append(cand)
    return out


def _followthrough_entry(candles, i, level, direction, ft, fam, name, counters):
    """Cross at i, entry after `ft` candles all CLOSE beyond the level."""
    trig = i
    ev = {'kind': 'close_cross', 'prev_close': candles[i - 1].get('close'),
          'close': candles[i].get('close'), 'level': level}
    for w in range(1, ft + 1):
        k = i + w
        if k >= len(candles):
            return None
        cl = candles[k].get('close')
        if cl is None:
            return None
        cl = float(cl)
        if (direction == 'BULL' and cl < level) or \
           (direction == 'BEAR' and cl > level):
            counters['rejected_failed_break'] += 1
            return None
        trig = k
    if not _entry_window_ok(candles, trig):
        counters['rejected_entry_window'] += 1
        return None
    ev['follow_through'] = ft
    return Candidate(kind='BREAKOUT', family=fam, direction=direction,
                     level_name=name, level=float(level), confirm_idx=i,
                     trigger_idx=trig, confirm_time=candles[i]['timestamp'],
                     trigger_time=candles[trig]['timestamp'], evidence=ev)


def _retest_entry(candles, i, level, direction, band, fam, name, counters):
    """Cross at i; walk forward rejecting failures and waiting for a holding retest."""
    for j in range(i + 1, len(candles)):
        c = candles[j]
        try:
            h, l, cl = float(c['high']), float(c['low']), float(c['close'])
        except (KeyError, TypeError, ValueError):
            continue
        if (direction == 'BULL' and cl < level) or \
           (direction == 'BEAR' and cl > level):
            counters['rejected_failed_break'] += 1
            return None
        retested = (l <= level * (1 + band)) if direction == 'BULL' else \
                   (h >= level * (1 - band))
        if retested and ((direction == 'BULL' and cl > level) or
                         (direction == 'BEAR' and cl < level)):
            if not _entry_window_ok(candles, j):
                counters['rejected_entry_window'] += 1
                return None
            return Candidate(
                kind='BREAKOUT', family=fam, direction=direction,
                level_name=name, level=float(level), confirm_idx=i,
                trigger_idx=j, confirm_time=candles[i]['timestamp'],
                trigger_time=c['timestamp'],
                evidence={'kind': 'close_cross',
                          'prev_close': candles[i - 1].get('close'),
                          'close': candles[i].get('close'), 'level': level,
                          'retest': {'kind': 'retest_hold', 'low': l,
                                     'high': h, 'close': cl}})
    return None


def _attach_breakout_geometry(cand, candles, levels):
    entry, entry_time, eidx = _entry_of(candles, cand.trigger_idx)
    cand.entry, cand.entry_time, cand.entry_idx = entry, entry_time, eidx
    cand.structure_stop = round(cand.level, 2)     # invalidation = the level
    if cand.direction == 'BULL':
        t = _next_above(levels, entry)
    else:
        t = _next_below(levels, entry)
    cand.structure_target = (round(t[0], 2) if t[0] is not None else None)
    cand.next_level_name, cand.next_level = t[1], t[2]


def _reward_ok(cand, min_rr):
    """Reward-to-risk to the next relevant level vs the structural stop."""
    if cand.next_level is None:
        return None                      # no next level -> not filterable
    risk_pts = abs(cand.entry - cand.structure_stop)
    if risk_pts <= 0:
        risk_pts = max(cand.entry * STOP_PCT, 1e-9)
    reward_pts = abs(cand.next_level - cand.entry)
    cand.evidence['level_rr'] = round(reward_pts / risk_pts, 3)
    return (reward_pts / risk_pts) >= min_rr


# --------------------------------------------------------------------------
# selection (decision hierarchy)
# --------------------------------------------------------------------------
def select_candidate(cands, cfg, counters):
    """Hierarchy: confirmed breakout -> confirmed reversal -> NO TRADE.

    Conflict rule (pre-configured, never tuned): if a BEAR and a BULL
    reversal are both confirmed in the same session and no breakout exists,
    the EARLIEST confirmation wins (tie -> BEAR, matching the production
    bear-priority rule); with conflict_rule='reject' both are dropped.
    Unselected candidates are counted as duplicates (one trade per session).
    """
    if not cands:
        counters['no_confirmation'] += 1
        return None
    breakouts = [c for c in cands if c.kind == 'BREAKOUT']
    chosen = breakouts[0] if breakouts else None
    if chosen is None:
        reversals = [c for c in cands if c.kind == 'REVERSAL']
        bulls = [c for c in reversals if c.direction == 'BULL']
        bears = [c for c in reversals if c.direction == 'BEAR']
        if bulls and bears:
            if cfg.get('conflict_rule', 'earliest_wins') == 'reject':
                counters['rejected_conflict'] += 1
                return None
            b0, r0 = bulls[0], bears[0]
            chosen = r0 if r0.confirm_idx <= b0.confirm_idx else b0
        else:
            chosen = reversals[0] if reversals else None
    if chosen is None:
        counters['no_confirmation'] += 1
        return None
    dup = len(cands) - 1
    if dup:
        counters['duplicate_suppressed'] += dup
    return chosen
