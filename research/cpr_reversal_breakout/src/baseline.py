"""Baseline reproduction: run the PRODUCTION backtest unmodified, read-only.

The production baseline for this research is
`app.research.cpr_trigger_engine.run_opens_range(instrument, start, end,
variant='plain')` — the exact function behind POST /api/backtest/cpr-triggers
and the same trigger math the live engine uses (_cpr_book_signal -> book_scan).

Nothing here re-implements the baseline rules. The function is imported and
called as-is; the only added code normalises its output into the shared trade
schema so baseline and candidate rows can be concatenated, and converts R to
₹ with the same lot/cost model used for the candidate.

Cross-checks (written into baseline_results.json):
  * journal  : trade_journal rows with variant='plain' on shared dates
  * paper    : paper_align rows with variant='plain' on shared dates
Any disagreement is reported as counts, never silently reconciled.
"""
from __future__ import annotations

from datetime import datetime

from app.research.cpr_trigger_engine import run_opens_range

from common import LOT_SIZES, STOP_PCT, period_of

# production level token -> research family id (comparability only)
_BASELINE_FAMILY = {
    'R2': 'A2', 'R1': 'A1', 'PDH': 'A4', 'PDH_REJECT': 'A4',
    'BELOW_CPR': 'C_DN_BC', 'S2': 'B2', 'S1': 'B1', 'PDL': 'B4',
    'ABOVE_CPR': 'C_UP_TC',
    'BRK_R1': 'C_UP_R1', 'BRK_R2': 'C_UP_R2', 'BRK_PDH': 'C_UP_PDH',
    'BRK_TC': 'C_UP_TC', 'BRK_S1': 'C_DN_S1', 'BRK_S2': 'C_DN_S2',
    'BRK_PDL': 'C_DN_PDL', 'BRK_BC': 'C_DN_BC',
}


def family_of(level: str) -> str:
    return _BASELINE_FAMILY.get(level, level)


def run_baseline(instrument, date_start, date_end, cfg, variant='plain'):
    """Call the production backtest verbatim and normalise its trades."""
    res = run_opens_range(instrument, date_start, date_end, variant)
    if isinstance(res, dict) and res.get('error'):
        raise RuntimeError(f'baseline error: {res["error"]}')
    trades = []
    for t in res['trades']:
        trades.append(normalise(t, instrument, cfg))
    return {'variant': f'baseline_{variant}', 'instrument': instrument,
            'date_start': res['date_start'], 'date_end': res['date_end'],
            'raw_summary': {k: v for k, v in res.items() if k != 'trades'},
            'trades': trades}


def normalise(t, instrument, cfg):
    entry = float(t['entry'])
    exit_px = float(t['exit'])
    r = float(t.get('r_multiple') or 0.0)
    direction = t['direction']
    points = t.get('points')
    if points is None:
        points = (exit_px - entry) if direction == 'BULL' else (entry - exit_px)
    risk_pts = entry * STOP_PCT
    l = LOT_SIZES.get(instrument, 65)
    gross = float(points) * l
    cost = float(cfg['costs'].get('brokerage_rs', 40.0)) + \
        float(cfg['costs'].get('slippage_pts', 0.5)) * l
    day = t['trade_date']
    level = t.get('level') or ''
    direction_norm = 'BULL' if direction == 'BULL' else 'BEAR'
    out = {
        'variant': f'baseline_{cfg.get("_baseline_variant", "plain")}',
        'instrument': instrument,
        'session_date': day,
        'period': period_of(day, cfg),
        'direction': direction_norm,
        'signal_kind': 'BREAKOUT' if level.startswith('BRK_') else 'REVERSAL',
        'family': family_of(level),
        'level': level,
        'level_price': None,
        'signal_time': t.get('signal_time') or '',
        'trigger_time': t.get('signal_time') or '',
        'entry_time': _iso(t.get('entry_time'), day),
        'entry': entry,
        'stop': round(entry * (1 - STOP_PCT) if direction == 'BULL'
                      else entry * (1 + STOP_PCT), 2),
        'target': round(entry * (1 + 0.02) if direction == 'BULL'
                        else entry * (1 - 0.02), 2),
        'exit_time': _iso(t.get('exit_time'), day),
        'exit': exit_px,
        'exit_reason': t.get('exit_reason'),
        'r_multiple': round(r, 3),
        'points': round(float(points), 4),
        'risk_pts': round(risk_pts, 2),
        'lot_size': l,
        'pnl_gross_rs': round(gross, 2),
        'cost_rs': round(cost, 2),
        'pnl_net_rs': round(gross - cost, 2),
        'risk_rs': round(risk_pts * l, 2),
        'r_net': round(r - (cost / (risk_pts * l)), 4),
        'win_loss': t.get('win_loss') or _wl(r),
        'structure_stop': None, 'structure_target': None,
        'next_level': None, 'next_level_name': None,
        'friday': _is_friday(day),
    }
    try:
        a = datetime.fromisoformat(out['entry_time'])
        b = datetime.fromisoformat(out['exit_time'])
        out['holding_minutes'] = round((b - a).total_seconds() / 60.0, 1)
    except (TypeError, ValueError):
        out['holding_minutes'] = None
    return out


def _wl(r):
    return 'WIN' if r > 0 else ('LOSS' if r < 0 else 'FLAT')


def _is_friday(day_iso):
    try:
        return datetime.fromisoformat(str(day_iso)).weekday() == 4
    except (TypeError, ValueError):
        return False


def _iso(ts, day):
    """entry/exit times from run_opens_range are 'YYYY-MM-DD HH:MM'."""
    if not ts:
        return ''
    s = str(ts)
    if 'T' in s:
        return s
    if len(s) == 16 and s[4] == '-' and s[10] == ' ':
        return s[:10] + 'T' + s[11:] + ':00+05:30'
    return s


def crosscheck_journal(conn, instrument, variant, trades):
    """Compare reproduced trades with trade_journal rows (variant match).

    Read-only. Reports counts only; differences are never reconciled here.
    """
    mine = {t['session_date']: t for t in trades}
    rows = conn.execute(
        'SELECT session_date, direction, level, entry_price, exit_price, '
        'r_multiple, win_loss FROM trade_journal WHERE instrument_id=? AND '
        'variant=? ORDER BY session_date', (instrument, variant)).fetchall()
    shared, matched, entry_mismatch, missing = 0, 0, 0, 0
    details = []
    for r in rows:
        d = r['session_date']
        if d not in mine:
            missing += 1
            continue
        shared += 1
        t = mine[d]
        de = abs(float(r['entry_price']) - t['entry'])
        dr = abs(float(r['r_multiple']) - t['r_multiple'])
        if de < 0.011 and dr < 0.011:
            matched += 1
        else:
            entry_mismatch += 1
            if len(details) < 12:
                details.append({'date': d, 'journal_entry': r['entry_price'],
                                'reproduced_entry': t['entry'],
                                'journal_r': r['r_multiple'],
                                'reproduced_r': t['r_multiple'],
                                'journal_level': r['level'],
                                'reproduced_level': t['level']})
    extra = len(set(mine) - {r['session_date'] for r in rows})
    return {'journal_rows': len(rows), 'shared_dates': shared,
            'exact_matches': matched, 'value_mismatches': entry_mismatch,
            'journal_dates_not_reproduced': missing,
            'reproduced_dates_not_in_journal': extra,
            'match_rate_on_shared': round(matched / shared, 4) if shared else None,
            'examples': details}


def crosscheck_paper(conn, instrument, variant, trades):
    """Compare reproduced trades with paper_align rows (live paper book)."""
    mine = {t['session_date']: t for t in trades}
    try:
        rows = conn.execute(
            'SELECT session_date, direction, level, entry_price, exit_price, '
            'r_multiple FROM paper_align WHERE instrument_id=? AND variant=? '
            'ORDER BY session_date', (instrument, variant)).fetchall()
    except Exception as e:                                   # pragma: no cover
        return {'error': str(e)}
    shared = matched = 0
    examples = []
    for r in rows:
        d = r['session_date']
        if d not in mine:
            continue
        shared += 1
        t = mine[d]
        if abs(float(r['entry_price']) - t['entry']) < 0.011 and \
           abs(float(r['r_multiple']) - t['r_multiple']) < 0.011:
            matched += 1
        elif len(examples) < 8:
            examples.append({'date': d, 'paper_entry': r['entry_price'],
                             'reproduced_entry': t['entry'],
                             'paper_r': r['r_multiple'],
                             'reproduced_r': t['r_multiple']})
    return {'paper_rows': len(rows), 'shared_dates': shared,
            'exact_matches': matched,
            'match_rate_on_shared': round(matched / shared, 4) if shared else None,
            'examples': examples}
