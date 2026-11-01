"""No-filter CPR trigger strategy (approved offline as vix_regime variant without VIX gate).

Bull triggers: candle low touches S2 / S1 / PDL (prev-day low), or close above TC.
Bear triggers: candle high touches R2 / R1 / PDH (prev-day high), or close below BC.
First trigger per session wins.

DIRECTION GATE (SHORT_ONLY, 2026-10-17): bull/continuation signals are
suppressed and only BEAR signals are emitted. bull_trigger() level math is
unchanged for diagnostics/tests. See the SHORT_ONLY comment for the basis.

WEEKDAY GATE (SKIP_FRIDAY, 2026-10-17): a BEAR signal whose session is a Friday
is dropped entirely (first trigger wins, so the whole session is skipped). BULL
is unaffected. Promoted from the SHADOW_SKIP_FRIDAY annotation. See the
SKIP_FRIDAY comment for the basis.

Two executions (run_opens_* = approved spec; legacy close/intrabar kept for
run_range/today_state/log_trigger history):
- opens: entry at next candle OPEN in [09:20, 15:20); stops/targets evaluated
  at subsequent opens (stop first); flat at 15:20 OPEN. Days <10 candles skipped.
- variant 'aligned': bull signal needs close above WEEKLY TC, bear needs close
  below WEEKLY BC (weekly CPR over prior 5 sessions).

Read-only vs the market DB (SELECT only). Shared by:
- POST /api/backtest/cpr-triggers (date-range backtest, variant param)
- GET /api/strategy/cpr-triggers (today's trigger state, read-only)
- scripts/paper_confluence.py log_trigger() [legacy] / log_align() [opens]
"""
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.db import get_conn
from app.research.cpr_strategy_engine import calculate_cpr, pivot_levels

_IST = ZoneInfo('Asia/Kolkata')

VALID = ('NIFTY', 'BANKNIFTY', 'INDIA_VIX')

STOP_PCT = 0.01
TARGET_PCT = 0.02

# ---------------------------------------------------------------------------
# Direction gate: SHORT_ONLY
# Read-only walk-forward analysis of trade_journal (246 trades,
# 2026-07-07..2026-10-12) found long/continuation setups (ABOVE_CPR, S1, S2,
# PDL) losing IN-SAMPLE and OUT-OF-SAMPLE, and on BOTH instruments:
#   BEAR  n=199  win 68.3%  avg +0.215R  total +42.8R
#   BULL  n=47   win 51.1%  avg -0.186R  total  -8.8R
# Dropping the long side raises the baseline from 65.0% / +0.138R (+34.0R) to
# 68.3% / +0.215R (+42.8R) while trading fewer signals. The short bias was
# independently confirmed on raw yfinance 5-minute candles (09:20->15:10).
# With SHORT_ONLY the engine emits BEAR signals only; bull_trigger() keeps its
# level math for tests and diagnostics but never produces a signal.
# Set to False to restore both sides.
# A trailing-trend gate was also tested and REJECTED (lookahead artifact):
# computed on a prev-close basis, up-trend shorts were the BETTER side.
# Do not reintroduce a trend gate without a fresh no-lookahead test.
# ---------------------------------------------------------------------------
SHORT_ONLY = True

# ---------------------------------------------------------------------------
# Scope 2 (SHADOW, non-blocking): skip-Friday
# The same walk-forward found BEAR-only + skip-Friday reached 73.6% / +0.359R
# (+57.1R) vs BEAR-only 68.3% / +0.215R (+42.8R). The effect is small-n
# (Fri n=45) and the loss-memory decay engine already flagged the learned
# dow:Fri rule, so it is NOT enforced. SHADOW_SKIP_FRIDAY only annotates BEAR
# signals that fall on a Friday (see shadow_flags) so the live/paper book can
# measure the counterfactual before any promotion to a hard gate.
# Set to False to silence. Promotion to enforcement is a separate decision.
# ---------------------------------------------------------------------------
SHADOW_SKIP_FRIDAY = True

# ---------------------------------------------------------------------------
# Scope 2 (ENFORCED): skip-Friday  (promoted 2026-10-17)
# SKIP_FRIDAY turns the shadow annotation above into a hard gate: a BEAR signal
# whose session is a Friday is dropped (first trigger wins, so the whole session
# is skipped). BULL is unaffected. Basis (trade_journal BEAR book, n=199):
#   Fridays     n=40  win 47.5%  avg -0.359R  total -14.3R
#   non-Friday  n=159 win 73.6%  avg +0.359R  total +57.1R
# and the drag was recent (last ~21 sessions: 28.6% / -0.592R). Monitored by
# scripts/shadow_friday.py (exit 2 = persistent+recent drag). Fail-open: an
# unknown/missing session date keeps the trade. Set both SHADOW_SKIP_FRIDAY and
# SKIP_FRIDAY to False to fully revert.
# ---------------------------------------------------------------------------
SKIP_FRIDAY = True

# ---------------------------------------------------------------------------
# No-chase BEAR entry (2026-10-17)
# A BEAR trigger is never chased at the next open. Instead the entry RE-ANCHORS
# to whichever level price actually trades back near after the trigger:
#   - resistance levels (R2 / R1 / PDH / BC)  -> SHORT (BEAR)
#   - support levels (TC / S1 / S2 / PDL)      -> LONG  (BULL)
# "Near" = the candle's open is within NO_CHASE_BAND_PCT (0.15% of the level),
# or the candle's range covers the level (limit fill at the level). If price
# never returns to any level within the entry window, the session is skipped.
# The direction re-anchor deliberately OVERRIDES SHORT_ONLY: if price leaves
# the bear trigger and falls to a support level, the correct directional trade
# there is a LONG (the bounce). BC / TC are kept in the level set so a
# BELOW_CPR / ABOVE_CPR break still fills near its CPR boundary. BULL re-anchor
# is therefore allowed on any session, including under SHORT_ONLY. A BEAR
# trigger on a Friday is still dropped whole (skip_Friday) before re-anchoring.
# Reference and fill are shared by the paper/backtest book (run_opens_range) and
# the live path (app/live/engine.py _select_entry), so live == backtest == paper
# parity holds. Set NO_CHASE_BEAR=False to restore plain next-open entries.
# DISABLED 2026-10-17: the 8-block walk-forward over all 73 sessions showed the
# re-anchor degrades the strategy (NIFTY +21.54R -> +2.34R, BNK +19.64R ->
# +10.96R), driven by BULL flips fading breakdowns. Kept gated off for research.
# ---------------------------------------------------------------------------
NO_CHASE_BEAR = False
NO_CHASE_BAND_PCT = 0.0015   # 0.15% of the level price

# ---------------------------------------------------------------------------
# Breakout add-on (2026-10-17)
# A session that produces NO base CPR-book trigger falls back to the first
# fresh close-CROSS of a level: close crossing UP through a resistance level
# (R1/R2/PDH/TC) is a BULL continuation, close crossing DOWN through a support
# level (S1/S2/PDL/BC) is a BEAR continuation. This is an ADD-ON only — it can
# never override or delay a base trigger (the base always wins "first trigger
# per session"). Rationale: the base is SHORT_ONLY, so upside breakout days are
# otherwise left flat; on those base-flat days the long breakout adds a small
# positive (NIFTY +2.9R, BNK +3.7R over the full range, positive in 7/8 and 6/8
# walk-forward blocks). Broad standalone breakout entries were measured negative
# (long side), so this is deliberately NOT a primary signal. The BULL side is a
# sanctioned SHORT_ONLY exception for exactly this fallback. Set
# BREAKOUT_ADDON=False to disable.
# ---------------------------------------------------------------------------
BREAKOUT_ADDON = True

# (level_name, day_levels key) for up-breaks (BULL) and down-breaks (BEAR).
_BREAKOUT_UP = (('BRK_R1', 'r1'), ('BRK_R2', 'r2'),
                ('BRK_PDH', 'pdh'), ('BRK_TC', 'tc'))
_BREAKOUT_DN = (('BRK_S1', 's1'), ('BRK_S2', 's2'),
                ('BRK_PDL', 'pdl'), ('BRK_BC', 'bc'))

# (level_name, implied_direction, day_levels key). Resistance first (bear
# priority on a tie), then support.
_ENTRY_LEVELS = (
    ('R2', 'BEAR', 'r2'), ('R1', 'BEAR', 'r1'), ('PDH', 'BEAR', 'pdh'),
    ('BC', 'BEAR', 'bc'),
    ('TC', 'BULL', 'tc'), ('S1', 'BULL', 's1'), ('S2', 'BULL', 's2'),
    ('PDL', 'BULL', 'pdl'),
)


def entry_levels(lv):
    """Ordered (name, direction, ref) entry levels for the no-chase re-anchor.

    Skips any level whose price is missing or non-positive."""
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
    """First candle j>i within the band of ANY entry level -> re-anchored entry.

    Near = the candle's OPEN is within NO_CHASE_BAND_PCT of a level (fill at
    that open), or the candle's range covers a level (limit fill at the level).
    Returns (j, level_name, direction, fill_price) or None. Pure; no I/O."""
    levels = entry_levels(lv)
    if not levels:
        return None
    for j in range(i + 1, len(candles or [])):
        c = candles[j]
        try:
            op, hi, lo = float(c['open']), float(c['high']), float(c['low'])
        except (KeyError, TypeError, ValueError):
            continue
        for name, dr, ref in levels:                 # open near a level
            if abs(op - ref) <= NO_CHASE_BAND_PCT * ref:
                return j, name, dr, op
        for name, dr, ref in levels:                 # range covers a level
            if lo <= ref <= hi:
                return j, name, dr, ref
    return None


def breakout_trigger(candle, prev_close, lv):
    """Fresh close-cross breakout, or None -> (direction, level_name).

    Long (BULL) when the close crosses UP through a resistance level; short
    (BEAR) when it crosses DOWN through a support level. 'Crosses' means the
    previous close was on the other side, so a level merely touched but not
    broken does not fire. Pure; no I/O."""
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


def breakout_signal(candles, lv, wlv=None, variant='aligned'):
    """First breakout add-on signal for a session, or None -> (dr, name, i).

    Only fresh close-crosses (see BREAKOUT_ADDON); the aligned weekly gate is
    applied, but friday_skip is left to the caller. Pure; no I/O."""
    if not lv or not BREAKOUT_ADDON:
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
        if variant == 'aligned' and not aligned_ok(dr, close, wlv):
            continue
        return dr, name, i
    return None


def day_levels(prev_high, prev_low, prev_close):
    """CPR + PDH/PDL bundle from previous-session OHLC. None-safe."""
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


def bull_trigger(candle, lv):
    """Return level name or None. Checks support touches first, then CPR break."""
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


def bear_trigger(candle, lv):
    """Return level name or None. Checks resistance touches first, then CPR break."""
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


def shadow_flags(direction, day_iso):
    """Non-blocking shadow annotations for a signal (scope 2, 2026-10-17).

    Returns rule codes that WOULD fire but are NOT enforced. SKIP_FRIDAY marks
    a BEAR signal on a Friday. Pure/deterministic; a missing or malformed date
    yields no flags (fail-open to a normal, unannotated trade)."""
    if not SHADOW_SKIP_FRIDAY or direction != 'BEAR':
        return []
    try:
        wd = datetime.fromisoformat(str(day_iso)[:10]).weekday()
    except (TypeError, ValueError):
        return []
    return ['SKIP_FRIDAY'] if wd == 4 else []


def _day_of(candle):
    """Session date (YYYY-MM-DD) of a candle, or None."""
    ts = (candle or {}).get('timestamp')
    return str(ts)[:10] if ts else None


def is_friday(day_iso):
    """True iff day_iso is a Friday. Missing/malformed -> False (fail-open)."""
    if not day_iso:
        return False
    try:
        return datetime.fromisoformat(str(day_iso)[:10]).weekday() == 4
    except (TypeError, ValueError):
        return False


def friday_skip(direction, day_iso):
    """Enforced scope-2 gate: drop BEAR signals whose session is a Friday.

    Promoted from SHADOW_SKIP_FRIDAY on 2026-10-17 (see the SKIP_FRIDAY block).
    Only BEAR is affected; unknown/missing dates fail open (keep the trade)."""
    return bool(SKIP_FRIDAY and direction == 'BEAR' and is_friday(day_iso))


def first_trigger(day_candles, lv):
    """First (direction, level, index) trigger of the session, else None.

    If the first trigger is a BEAR on a Friday the whole session is skipped
    (SKIP_FRIDAY gate, 2026-10-17)."""
    for i, c in enumerate(day_candles):
        b = bear_trigger(c, lv)
        u = None if SHORT_ONLY else bull_trigger(c, lv)
        t = b or u
        if t:
            dr = 'BEAR' if b else 'BULL'
            if friday_skip(dr, _day_of(c)):
                return None
            return {'direction': dr, 'level': t, 'index': i,
                    'timestamp': c.get('timestamp')}
    return None


def exit_trade(direction, entry, fwd_candles):
    """Walk forward candles. Returns (R_multiple, exit_price, exit_reason)."""
    if direction == 'BULL':
        stop, tgt = entry * (1 - STOP_PCT), entry * (1 + TARGET_PCT)
    else:
        stop, tgt = entry * (1 + STOP_PCT), entry * (1 - TARGET_PCT)
    risk = abs(entry - stop)
    for c in fwd_candles:
        try:
            hi, lo, cl = float(c['high']), float(c['low']), float(c['close'])
        except (KeyError, TypeError, ValueError):
            continue
        if direction == 'BULL':
            s, t = lo <= stop, hi >= tgt
            if s and t:
                return -1.0, cl, 'STOP (both same candle)'
            if s:
                return -1.0, cl, 'STOP'
            if t:
                return 2.0, cl, 'TARGET'
        else:
            s, t = hi >= stop, lo <= tgt
            if s and t:
                return -1.0, cl, 'STOP (both same candle)'
            if s:
                return -1.0, cl, 'STOP'
            if t:
                return 2.0, cl, 'TARGET'
    last = None
    for c in reversed(fwd_candles):
        try:
            last = float(c['close'])
            break
        except (KeyError, TypeError, ValueError):
            continue
    if last is None or not risk:
        return 0.0, entry, 'NO_FORWARD_DATA'
    move = (last - entry) if direction == 'BULL' else (entry - last)
    return round(move / risk, 3), last, 'EOD'


def prev_session_ohlc(conn, instrument, day_iso):
    """Max high / min low / last close strictly before day_iso. None if absent."""
    row = conn.execute(
        'SELECT substr(timestamp,1,10) AS d, MAX(high) AS h, MIN(low) AS l '
        'FROM market_candles_5m WHERE instrument_id=? AND substr(timestamp,1,10)<? '
        'GROUP BY d ORDER BY d DESC LIMIT 1', (instrument, day_iso)).fetchone()
    if not row or row['h'] is None:
        return None
    last = conn.execute(
        'SELECT close FROM market_candles_5m WHERE instrument_id=? '
        'AND substr(timestamp,1,10)=? ORDER BY timestamp DESC LIMIT 1',
        (instrument, row['d'])).fetchone()
    if not last or last['close'] is None:
        return None
    return {'date': row['d'], 'high': float(row['h']),
            'low': float(row['l']), 'close': float(last['close'])}


def session_candles(conn, instrument, day_iso):
    rows = conn.execute(
        'SELECT timestamp,open,high,low,close FROM market_candles_5m '
        'WHERE instrument_id=? AND substr(timestamp,1,10)=? ORDER BY timestamp',
        (instrument, day_iso)).fetchall()
    return [dict(r) for r in rows]


def run_range(instrument, date_start, date_end):
    """Backtest over stored sessions in [start, end]. Returns summary dict."""
    inst = (instrument or '').upper()
    if inst not in VALID:
        return {'error': 'UNKNOWN_INSTRUMENT'}
    conn = get_conn()
    try:
        days = [r[0] for r in conn.execute(
            'SELECT DISTINCT substr(timestamp,1,10) FROM market_candles_5m '
            'WHERE instrument_id=? AND substr(timestamp,1,10) BETWEEN ? AND ? ORDER BY 1',
            (inst, date_start, date_end)).fetchall()]
        trades, no_signal = [], 0
        for d in days:
            prev = prev_session_ohlc(conn, inst, d)
            if not prev:
                continue
            lv = day_levels(prev['high'], prev['low'], prev['close'])
            if not lv:
                continue
            candles = session_candles(conn, inst, d)
            if not candles:
                continue
            sig = first_trigger(candles, lv)
            if not sig:
                no_signal += 1
                continue
            entry = float(candles[sig['index']]['close'])
            r, exit_px, how = exit_trade(sig['direction'], entry, candles[sig['index'] + 1:])
            trades.append({'trade_date': d, 'direction': sig['direction'],
                           'level': sig['level'], 'entry': round(entry, 2),
                           'exit': round(exit_px, 2), 'r_multiple': r,
                           'exit_reason': how,
                           'signal_time': sig.get('timestamp')})
    finally:
        conn.close()
    # FIXALL R3: legacy path had no win_loss col; derive single-label wins/losses
    # from decay label when present else raw sign (matches opens-path semantics).
    def _w(tr):
        wl = tr.get('win_loss')
        if wl in ('WIN', 'LOSS'): return wl
        return 'WIN' if tr.get('r_multiple', 0) > 0 else ('LOSS' if tr.get('r_multiple', 0) < 0 else 'BREAKEVEN')
    rs = [t['r_multiple'] for t in trades]
    w = sum(1 for tr in trades if _w(tr) == 'WIN')
    n = len(rs)
    by_level = {}
    for t in trades:
        k = f"{t['direction']}/{t['level']}"
        e = by_level.setdefault(k, {'n': 0, 'wins': 0, 'R': 0.0})
        e['n'] += 1
        e['R'] = round(e['R'] + t['r_multiple'], 2)
        if _w(t) == 'WIN':
            e['wins'] += 1
    return {'instrument': inst, 'date_start': date_start, 'date_end': date_end,
            'days': len(trades) + no_signal, 'signals': n,
            'no_signal_days': no_signal, 'wins': w,
            'losses': sum(1 for tr in trades if _w(tr) == 'LOSS'),
            'win_rate': round(100 * w / n, 1) if n else 0,
            'total_R': round(sum(rs), 2) if n else 0,
            'avg_R': round(sum(rs) / n, 3) if n else 0,
            'by_level': by_level, 'trades': trades}


OPEN_STOP_PCT = 0.005
OPEN_TARGET_PCT = 0.02

# Display-only cost placeholder for net-R reporting (does NOT alter trades,
# R multiples, or history): 0.10R per round trip ≈ brokerage + STT + slippage
# on typical retail size. Replace with measured brokerage when available.
COST_R_PER_TRADE = 0.10


def book_scan(candles, lv, wlv, variant='aligned'):
    """First CPR trigger over a candle list. Pure shared core.

    Same rules as run_opens_range/today_state: bear checked before bull
    (same-candle tie -> BEAR), weekly gate when variant='aligned'.
    Returns (direction, level, index) or None. No I/O. A BEAR first trigger on
    a Friday is skipped (SKIP_FRIDAY gate, 2026-10-17)."""
    if not lv:
        return None
    for i, c in enumerate(candles or []):
        try:
            b = bear_trigger(c, lv)
            u = None if SHORT_ONLY else bull_trigger(c, lv)
        except (KeyError, TypeError, ValueError):
            continue
        t = b or u
        if not t:
            continue
        dr = 'BEAR' if b else 'BULL'
        if friday_skip(dr, _day_of(c)):
            # Friday BEAR: no base trade. Fall through to the breakout add-on
            # (a Friday BULL up-break may still fire; a Friday BEAR one will
            # not). Never resumes the base scan.
            break
        try:
            cl = c.get('close')
        except AttributeError:
            cl = None
        if variant == 'aligned' and not aligned_ok(dr, cl, wlv):
            continue
        return dr, t, i
    # No base trigger this session: optional breakout add-on fallback.
    bs = breakout_signal(candles, lv, wlv, variant)
    if bs is not None and not friday_skip(bs[0], _day_of(candles[bs[2]])):
        return bs
    return None


def today_state(instrument, now_ist=None, variant='aligned'):
    """Today's trigger state from stored candles so far (opens execution).

    Same math as run_opens_range: first trigger (bear priority), weekly gate
    when variant='aligned', entry at next candle OPEN when available (else
    entry stays None with note ENTRY_AT_NEXT_OPEN). Read-only."""
    inst = (instrument or '').upper()
    if inst not in VALID:
        return {'error': 'UNKNOWN_INSTRUMENT'}
    if variant not in VARIANTS:
        return {'error': 'UNKNOWN_VARIANT'}
    now = now_ist or datetime.now(_IST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=_IST)
    day_iso = now.date().isoformat()
    conn = get_conn()
    try:
        prev = prev_session_ohlc(conn, inst, day_iso)
        if not prev:
            return {'instrument': inst, 'variant': variant, 'date': day_iso,
                    'state': 'NO_DATA', 'reason': 'CPR_DATA_UNAVAILABLE'}
        lv = day_levels(prev['high'], prev['low'], prev['close'])
        wlv = weekly_levels(conn, inst, monday_of(day_iso)) if variant == 'aligned' else None
        if variant == 'aligned' and not wlv:
            return {'instrument': inst, 'variant': variant, 'date': day_iso,
                    'state': 'WATCH', 'levels': lv,
                    'reason': 'WEEKLY_GATE_MISSING'}
        candles = [c for c in session_candles(conn, inst, day_iso)
                   if c['timestamp'] <= now.isoformat()]
    finally:
        conn.close()
    if not candles:
        return {'instrument': inst, 'variant': variant, 'date': day_iso,
                'state': 'WATCH', 'levels': lv, 'reason': 'NO_CANDLES_YET'}
    sig = book_scan(candles, lv, wlv, variant)
    if not sig:
        return {'instrument': inst, 'variant': variant, 'date': day_iso,
                'state': 'WATCH', 'levels': lv,
                'candles_so_far': len(candles),
                'last_candle': candles[-1]['timestamp']}
    dr, t, i = sig
    entry = entry_time = note = None
    if NO_CHASE_BEAR and dr == 'BEAR':
        # No-chase re-anchor: wait for price back within the band of an entry
        # level (direction may flip to BULL at a support level). Until then the
        # signal stands but the entry is pending (NO_CHASE_WAIT).
        nc = no_chase_fill(lv, candles, i)
        if nc is None:
            note = 'NO_CHASE_WAIT'
        else:
            j, name, dr2, fill = nc
            if OPEN_MIN <= candles[j]['timestamp'][11:16] < OPEN_EOD:
                entry = round(float(fill), 2)
                entry_time = candles[j]['timestamp']
                dr, t = dr2, name
            else:
                note = 'NO_CHASE_WAIT'
    elif i + 1 < len(candles):
        entry = round(float(candles[i + 1]['open']), 2)
        entry_time = candles[i + 1]['timestamp']
    else:
        note = 'ENTRY_AT_NEXT_OPEN'
    if entry is not None:
        if dr == 'BULL':
            stop, tgt = entry * (1 - OPEN_STOP_PCT), entry * (1 + OPEN_TARGET_PCT)
        else:
            stop, tgt = entry * (1 + OPEN_STOP_PCT), entry * (1 - OPEN_TARGET_PCT)
        entry, stop, tgt = round(entry, 2), round(stop, 2), round(tgt, 2)
    else:
        stop = tgt = None
    return {'instrument': inst, 'variant': variant, 'date': day_iso,
            'state': 'SIGNAL', 'direction': dr, 'level': t,
            'signal_time': candles[i]['timestamp'],
            'entry': entry, 'entry_time': entry_time, 'stop': stop, 'target': tgt, 'levels': lv,
            'shadow': shadow_flags(dr, day_iso),
            'note': note, 'candles_so_far': len(candles),
            'last_candle': candles[-1]['timestamp']}


VARIANTS = ('plain', 'aligned')

DECAY_TOL_POINTS = {'NIFTY': 30.0, 'BANKNIFTY': 60.0, 'INDIA_VIX': 0.02}
# Tolerances ≈ 0.11-0.17% of typical price (30/24000, 60/55000, 0.02/12):
# same relative band per instrument; VIX is indicative-only (non-tradable).


def decay_win(direction, entry, exit_px, r_multiple, instrument):
    """Short-premium decay reclassification (pure).

    A small adverse drift (under the per-instrument points tolerance) counts
    as WIN: overnight/day theta on a short spread outweighs it. Full stops
    and large drifts stay losses. Spot R is never rewritten — only the label."""
    try:
        if r_multiple is None:
            return None
        if r_multiple > 0:
            return 'WIN'
        if r_multiple < 0:
            tol = DECAY_TOL_POINTS.get((instrument or '').upper(), 30.0)
            pts = (float(exit_px) - float(entry)) if direction == 'BULL' else (float(entry) - float(exit_px))
            if abs(pts) < tol:
                return 'WIN'
            return 'LOSS'
        return 'FLAT'
    except (TypeError, ValueError):
        return None

OPEN_MIN = '09:20'
OPEN_MAX = '15:20'
OPEN_EOD = '15:20'
MIN_CANDLES = 10


def aligned_ok(direction, close, wlv):
    """Weekly-alignment gate (pure). Bull needs close above weekly TC,
    bear needs close below weekly BC. Missing wlv fails closed."""
    try:
        cl = float(close)
    except (TypeError, ValueError):
        return False
    if not wlv:
        return False
    if direction == 'BULL':
        return cl > wlv['tc']
    if direction == 'BEAR':
        return cl < wlv['bc']
    return False


def weekly_levels(conn, instrument, monday_iso, min_sessions=3):
    """Weekly CPR bundle over prior sessions before monday_iso.

    Returns None when fewer than min_sessions distinct prior sessions exist
    (fail-closed: first week of history gates nothing). Callers count such
    days as gate-missing, never as trades."""
    rows = conn.execute(
        'SELECT substr(timestamp,1,10) AS d, high, low, close FROM market_candles_5m '
        'WHERE instrument_id=? AND substr(timestamp,1,10)<? ORDER BY timestamp DESC LIMIT 375',
        (instrument, monday_iso)).fetchall()
    if not rows:
        return None
    if len({r['d'] for r in rows}) < min_sessions:
        return None
    try:
        return day_levels(max(r['high'] for r in rows), min(r['low'] for r in rows),
                          rows[0]['close'])
    except (TypeError, ValueError):
        return None


def monday_of(day_iso):
    from datetime import datetime as _dt, timedelta as _td
    dt = _dt.strptime(day_iso, '%Y-%m-%d').date()
    return (dt - _td(days=dt.weekday())).isoformat()


def exits_opens(direction, entry, stop_pct, target_pct, opens):
    """Walk subsequent candle OPENS. Returns (R, exit_px, reason, exit_ts).

    opens: list of (timestamp, open) AFTER the entry candle. Stop first."""
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


def _valid_range(date_start, date_end):
    """YYYY-MM-DD + start<=end. Returns (start, end) or None."""
    try:
        from datetime import datetime as _dt
        s = _dt.strptime(date_start, '%Y-%m-%d').date().isoformat()
        e = _dt.strptime(date_end, '%Y-%m-%d').date().isoformat()
        return (s, e) if s <= e else None
    except (TypeError, ValueError):
        return None


def run_opens_range(instrument, date_start, date_end, variant='plain',
                    stop_pct=0.005, target_pct=0.02):
    """Approved-spec backtest: opens execution + optional weekly alignment.

    Rules (all deliberate, see boundaries below):
    - signal: first trigger/session over candles < 15:25; BEAR checked before
      BULL, so a same-candle double-touch counts BEAR. Within a side the
      first listed level wins (S2>S1>PDL>ABOVE_CPR; R2>R1>PDH>BELOW_CPR),
      so PDL/PDH only fire when S1/R1 did not.
    - entry: next candle OPEN in [09:20, 15:20); later signals that day ignored.
    - exits: subsequent OPENS only; an open exactly on stop counts STOP;
      an open exactly on target counts TARGET; stop checked before target;
      a stop exactly at the 15:20 open labels STOP (not EOD).
    - flat: 15:20 OPEN. Missing 15:20 candle -> missing_eod (not a signal).
    - decay: |adverse points| < tolerance (NIFTY 30 / BANKNIFTY 60 /
      INDIA_VIX 0.02, ~0.11-0.17% of price) labels WIN; exactly at tolerance
      stays LOSS. Spot R is never rewritten.
    - wins AND losses both derive from win_loss (single label definition).
    - skip-Friday (2026-10-17): a session whose first trigger is a BEAR on a
      Friday takes no base trade (bucket skip_friday). With BREAKOUT_ADDON the
      session is still treated as flat, so a Friday upside-breakout BULL may be
      taken instead; a Friday BEAR breakout stays skipped.

    Read-only. `days` = signals + every skipped bucket (no silent drops)."""
    inst = (instrument or '').upper()
    if inst not in VALID:
        return {'error': 'UNKNOWN_INSTRUMENT'}
    if variant not in VARIANTS:
        return {'error': 'UNKNOWN_VARIANT'}
    rng = _valid_range(date_start, date_end)
    if not rng:
        return {'error': 'INVALID_DATE_RANGE'}
    date_start, date_end = rng
    conn = get_conn()
    try:
        days = [r[0] for r in conn.execute(
            'SELECT DISTINCT substr(timestamp,1,10) FROM market_candles_5m '
            'WHERE instrument_id=? AND substr(timestamp,1,10) BETWEEN ? AND ? ORDER BY 1',
            (inst, date_start, date_end)).fetchall()]
        trades = []
        skipped = {'no_signal': 0, 'short_day': 0, 'missing_eod': 0,
                   'gate_missing': 0, 'bad_data': 0, 'skip_friday': 0,
                   'no_chase': 0}
        for d in days:
            prev = prev_session_ohlc(conn, inst, d)
            if not prev:
                skipped['bad_data'] += 1
                continue
            lv = day_levels(prev['high'], prev['low'], prev['close'])
            if not lv:
                skipped['bad_data'] += 1
                continue
            wlv = weekly_levels(conn, inst, monday_of(d)) if variant == 'aligned' else None
            if variant == 'aligned' and not wlv:
                skipped['gate_missing'] += 1
                continue
            candles = [c for c in session_candles(conn, inst, d)
                       if c['timestamp'][11:16] < '15:25']
            if len(candles) < MIN_CANDLES:
                skipped['short_day'] += 1
                continue
            sig = None
            fri_skip = False
            for i, c in enumerate(candles):
                b = bear_trigger(c, lv)
                u = None if SHORT_ONLY else bull_trigger(c, lv)
                t = b or u
                if not t:
                    continue
                dr = 'BEAR' if b else 'BULL'
                if friday_skip(dr, d):
                    fri_skip = True
                    break
                if variant == 'aligned' and not aligned_ok(dr, c['close'], wlv):
                    continue
                if i + 1 >= len(candles):
                    continue
                nt = candles[i + 1]['timestamp']
                if not (OPEN_MIN <= nt[11:16] < OPEN_EOD):
                    continue
                sig = (dr, t, i)
                break
            if not sig and BREAKOUT_ADDON:
                # No base TRADE this session: either there was no base trigger
                # at all, or the only base trigger was a Friday BEAR that is
                # skipped (fri_skip). Either way the session is flat, so fall
                # back to the first fresh close-cross breakout (BULL above
                # resistance / BEAR below support). A Friday BEAR breakout is
                # itself skipped. Never overrides a base trigger.
                bs = breakout_signal(candles, lv, wlv, variant)
                if bs is not None and not friday_skip(bs[0], d):
                    sig = bs
            if not sig:
                if fri_skip:
                    skipped['skip_friday'] += 1
                else:
                    skipped['no_signal'] += 1
                continue
            dr, t, i = sig
            entry_idx = i + 1
            if NO_CHASE_BEAR and dr == 'BEAR':
                # No-chase re-anchor: never take the next open. Wait for price
                # to trade back within the band of ANY entry level and take the
                # direction that level implies (resistance -> short, support ->
                # long). Direction may flip (BULL is allowed here even under
                # SHORT_ONLY). Skip the session if price never returns.
                nc = no_chase_fill(lv, candles, i)
                if nc is None:
                    skipped['no_chase'] += 1
                    continue
                j, name, dr, fill = nc
                if not (OPEN_MIN <= candles[j]['timestamp'][11:16] < OPEN_EOD):
                    skipped['no_chase'] += 1
                    continue
                if friday_skip(dr, d):       # re-anchored BEAR on a Friday
                    skipped['skip_friday'] += 1
                    continue
                entry_idx, t = j, name
                try:
                    entry = float(fill)
                except (TypeError, ValueError):
                    skipped['bad_data'] += 1
                    continue
            else:
                try:
                    entry = float(candles[entry_idx]['open'])
                except (KeyError, TypeError, ValueError):
                    skipped['bad_data'] += 1
                    continue
            nt = candles[entry_idx]['timestamp']
            opens = [(c['timestamp'], c['open']) for c in candles[entry_idx + 1:]]
            eod = [c for c in candles if c['timestamp'][11:16] == OPEN_EOD]
            if not eod:
                skipped['missing_eod'] += 1
                continue
            hit = exits_opens(dr, entry, stop_pct, target_pct, opens)
            if hit is None:
                try:
                    last = float(eod[0]['open'])
                except (KeyError, TypeError, ValueError):
                    skipped['bad_data'] += 1
                    continue
                risk = abs(entry * stop_pct)
                move = (last - entry) if dr == 'BULL' else (entry - last)
                r = round(move / risk, 3) if risk else 0.0
                xp, how, xt = round(last, 2), 'EOD-1520', eod[0]['timestamp']
            else:
                r, xp, how, xt = hit
            pts = round((xp - entry) if dr == 'BULL' else (entry - xp), 1)
            trades.append({'trade_date': d, 'direction': dr, 'level': t,
                           'entry_time': nt[:16].replace('T', ' '),
                           'entry': round(entry, 2),
                           'exit_time': (xt or '')[:16].replace('T', ' '),
                           'exit': xp, 'r_multiple': r, 'exit_reason': how,
                           'points': pts, 'signal_time': candles[i]['timestamp'],
                           'win_loss': decay_win(dr, entry, xp, r, inst)})
    finally:
        conn.close()
    rs = [t['r_multiple'] for t in trades]
    w = sum(1 for t in trades if t.get('win_loss') == 'WIN')
    n = len(rs)
    losses = sum(1 for t in trades if t.get('win_loss') == 'LOSS')
    by_level = {}
    for t in trades:
        k = f"{t['direction']}/{t['level']}"
        e = by_level.setdefault(k, {'n': 0, 'wins': 0, 'R': 0.0})
        e['n'] += 1
        e['R'] = round(e['R'] + t['r_multiple'], 2)
        if t.get('win_loss') == 'WIN':
            e['wins'] += 1
    losses = sum(1 for t in trades if t.get('win_loss') == 'LOSS')
    by_level = {}
    for t in trades:
        k = f"{t['direction']}/{t['level']}"
        e = by_level.setdefault(k, {'n': 0, 'wins': 0, 'R': 0.0})
        e['n'] += 1
        e['R'] = round(e['R'] + t['r_multiple'], 2)
        if t.get('win_loss') == 'WIN':
            e['wins'] += 1
    return {'instrument': inst, 'variant': variant,
            'date_start': date_start, 'date_end': date_end,
            'days': n + sum(skipped.values()), 'signals': n,
            'no_signal_days': skipped['no_signal'], 'skipped': skipped,
            'wins': w,
            'losses': losses,
            'win_rate': round(100 * w / n, 1) if n else 0,
            'total_R': round(sum(rs), 2) if n else 0,
            'avg_R': round(sum(rs) / n, 3) if n else 0,
            'net_R': round(sum(rs) - COST_R_PER_TRADE * n, 2) if n else 0,
            'cost_note': 'net_R deducts %.2fR/trade estimated costs; gross total_R unchanged' % COST_R_PER_TRADE,
            'by_level': by_level, 'trades': trades}
