"""Baseline execution, corrected accounting and the trade ledger.

`build_universe` runs the **unmodified production** engine (`run_opens_range`) and
re-derives every signal's candle context from the snapshot. `account` re-simulates
the same exit model and reports the realized R of the modelled fill, the excursions
and the counterfactual stop widths.
"""
from __future__ import annotations

from . import data, execution

STOP_PCT = 0.005
TARGET_PCT = 0.02
COUNTERFACTUAL_WIDTHS = (0.0100, 0.0075, 0.0050, 0.00375, 0.0025)
SPLITS = {
    'in_sample': ('2026-07-06', '2026-08-31'),
    'validation': ('2026-09-01', '2026-09-30'),
    'out_of_sample': ('2026-10-01', '2026-10-21'),
}

# Which side of the level price travelled to reach the trigger.
# 'above' = price reached above the level, 'below' = price reached below it.
BREAK_SIDE = {
    'R1': 'above', 'R2': 'above', 'PDH': 'above',
    'BRK_R1': 'above', 'BRK_R2': 'above', 'BRK_PDH': 'above', 'BRK_TC': 'above',
    'S1': 'below', 'S2': 'below', 'PDL': 'below',
    'BRK_S1': 'below', 'BRK_S2': 'below', 'BRK_PDL': 'below', 'BRK_BC': 'below',
    'BELOW_CPR': 'below', 'ABOVE_CPR': 'above',
}


def _ts_to_minutes(ts: str) -> int:
    return int(ts[11:13]) * 60 + int(ts[14:16])


def build_session(conn, engine, inst: str, day: str) -> dict:
    """Point-in-time session context (levels come from the previous session only)."""
    candles = data.candles(conn, inst, day)
    scan = data.scan_candles(candles)
    prev = data.prev_session(conn, inst, day)
    levels = None
    cpr_width = None
    if prev:
        levels = engine.day_levels(prev['high'], prev['low'], prev['close'])
        if levels:
            cpr_width = round(((levels['tc'] - levels['bc']) / levels['pp']) * 100, 6)
    day_open = float(candles[0]['open']) if candles else None
    gap_pct = None
    if day_open and prev and prev['close']:
        gap_pct = round((day_open - prev['close']) / prev['close'] * 100, 4)
    return {
        'instrument': inst, 'date': day, 'candles': candles, 'scan': scan,
        'prev': prev, 'levels': levels, 'cpr_width_pct': cpr_width,
        'day_open': day_open, 'gap_pct': gap_pct,
        'period': data.period_of(day, SPLITS),
    }


def build_universe(conn, engine, inst: str, date_start: str, date_end: str) -> dict:
    """Production signals plus their candle context (read-only)."""
    res = engine.run_opens_range(inst, date_start, date_end, 'plain')
    if 'error' in res:
        raise RuntimeError(f'production run failed: {res}')
    sessions = {}
    for day in data.sessions(conn, inst, date_start, date_end):
        sessions[day] = build_session(conn, engine, inst, day)
    signals = []
    for t in res['trades']:
        ctx = sessions.get(t['trade_date'])
        if not ctx:
            continue
        scan = ctx['scan']
        entry_key = t['entry_time'].replace(' ', 'T')
        entry_idx = next((i for i, c in enumerate(scan)
                          if str(c['timestamp'])[:16] == entry_key), None)
        if entry_idx is None:
            continue
        trig_key = str(t['signal_time'])[:16]
        trig_idx = next((i for i, c in enumerate(scan)
                         if str(c['timestamp'])[:16] == trig_key), None)
        lvl_price = None
        if ctx['levels']:
            lvl_price = data.level_price(ctx['levels'], t['level'])
        signals.append({
            'instrument': inst, 'session_date': t['trade_date'],
            'direction': t['direction'], 'level': t['level'],
            'trigger_idx': trig_idx, 'entry_idx': entry_idx,
            'entry': float(t['entry']), 'entry_time': t['entry_time'],
            'signal_time': str(t['signal_time']),
            'level_price': lvl_price, 'break_side': BREAK_SIDE.get(t['level']),
            'ctx': ctx, 'period': ctx['period'],
            'prod_trade': t,
        })
    return {'run': res, 'signals': signals, 'sessions': sessions}


def account(signal: dict, arm: str, entry: float | None = None,
            entry_idx: int | None = None, entry_source: str = 'baseline_open',
            stop_pct: float = STOP_PCT, target_pct: float = TARGET_PCT) -> dict | None:
    """Re-simulate one signal and produce the corrected trade record."""
    ctx = signal['ctx']
    scan = ctx['scan']
    if entry_idx is None:
        entry_idx = signal['entry_idx']
    if entry is None:
        entry = float(scan[entry_idx]['open'])
    direction = signal['direction']
    sim = execution.simulate_exit(direction, entry, scan, entry_idx, stop_pct, target_pct)
    if sim is None:
        return None
    risk = sim['risk_pts']
    exc = execution.excursion(direction, entry, scan, entry_idx, sim['exit_ts'])
    exit_idx = next((i for i, c in enumerate(scan)
                     if str(c['timestamp'])[:16] == str(sim['exit_ts'])[:16]), None)
    fwd = execution.forward_path(direction, sim['exit_price'], scan, exit_idx, risk)
    bounds = execution.intrabar_bounds(direction, entry, scan, entry_idx, sim['exit_ts'],
                                        stop_pct, target_pct)
    entry_ts = str(scan[entry_idx]['timestamp'])
    exit_ts = str(sim['exit_ts'])
    held = _ts_to_minutes(exit_ts[:16]) - _ts_to_minutes(entry_ts[:16])
    if exit_ts[:10] != entry_ts[:10]:
        held += 24 * 60
    counter = {}
    for w in COUNTERFACTUAL_WIDTHS:
        c = execution.simulate_exit(direction, entry, scan, entry_idx, w, target_pct)
        key = f'{w * 100:.3f}'.rstrip('0').rstrip('.') + '_pct'
        counter[key] = None if not c else {
            'exit_reason': c['exit_reason'], 'exit_price': c['exit_price'],
            'realized_r': c['realized_r'], 'booked_r': c['booked_r'],
            'stop_overshoot_pts': c['stop_overshoot_pts'],
        }
    realized_pts = ((sim['exit_price'] - entry) if direction == 'BULL'
                    else (entry - sim['exit_price']))
    rec = {
        'arm': arm,
        'instrument': signal['instrument'],
        'session_date': signal['session_date'],
        'period': signal['period'],
        'direction': direction,
        'setup': signal['level'],
        'level_price': signal['level_price'],
        'entry_source': entry_source,
        'signal_time': signal['signal_time'],
        'entry_time': entry_ts[:16].replace('T', ' '),
        'entry': round(entry, 2),
        'exit_time': exit_ts[:16].replace('T', ' '),
        'exit_price': sim['exit_price'],
        'exit_reason': sim['exit_reason'],
        'stop_price': sim['stop_price'],
        'target_price': sim['target_price'],
        'risk_pts': round(risk, 4),
        'booked_r': sim['booked_r'],
        'realized_r': sim['realized_r'],
        'realized_pts': round(realized_pts, 2),
        'stop_overshoot_pts': sim['stop_overshoot_pts'],
        'stop_overshoot_r': sim['stop_overshoot_r'],
        'target_truncation_pts': sim['target_truncation_pts'],
        'target_truncation_r': sim['target_truncation_r'],
        'mae_hl_pts': exc['mae_hl_pts'], 'mae_hl_r': round(exc['mae_hl_pts'] / risk, 4),
        'mfe_hl_pts': exc['mfe_hl_pts'], 'mfe_hl_r': round(exc['mfe_hl_pts'] / risk, 4),
        'mae_open_pts': exc['mae_open_pts'], 'mae_open_r': round(exc['mae_open_pts'] / risk, 4),
        'mfe_open_pts': exc['mfe_open_pts'], 'mfe_open_r': round(exc['mfe_open_pts'] / risk, 4),
        'bars_held': exc['bars_held'],
        'time_to_exit_minutes': held,
        'win_sign': 'WIN' if sim['realized_r'] > 0 else ('LOSS' if sim['realized_r'] < 0 else 'FLAT'),
        'win_decay_label': _decay_label(signal, sim, entry, realized_pts),
        'gap_pct': ctx['gap_pct'],
        'cpr_width_pct': ctx['cpr_width_pct'],
        'intrabar_ambiguous_bars': bounds['intrabar_ambiguous_bars'],
        'r_lower_bound': bounds['lower_bound_r'],
        'r_upper_bound': bounds['upper_bound_r'],
        'counterfactual_stop_widths': counter,
    }
    rec.update(fwd)
    return rec


def _decay_label(signal, sim, entry, realized_pts) -> str:
    """Production decay label applied to the realized fill (label only, never P&L)."""
    try:
        from . import prod
        return prod.engine().decay_win(signal['direction'], entry, sim['exit_price'],
                                        sim['realized_r'], signal['instrument'])
    except Exception:
        return None


def reconcile(prod_run: dict, records: list) -> dict:
    """Compare the re-simulation against the production run (integrity check)."""
    prod_trades = prod_run.get('trades', [])
    issues = []
    if len(prod_trades) != len(records):
        issues.append(f'trade count mismatch: production {len(prod_trades)} vs '
                      f're-simulated {len(records)}')
    by_key = {(r['session_date'], r['direction'], r['setup'], r['entry_time']): r
              for r in records}
    checked = 0
    for t in prod_trades:
        key = (t['trade_date'], t['direction'], t['level'], t['entry_time'])
        r = by_key.get(key)
        if not r:
            issues.append(f'no re-simulated trade for {key}')
            continue
        checked += 1
        if abs(float(t['entry']) - r['entry']) > 0.011:
            issues.append(f'entry mismatch {key}: {t["entry"]} vs {r["entry"]}')
        if t['exit_reason'] != r['exit_reason']:
            issues.append(f'exit reason mismatch {key}: {t["exit_reason"]} vs {r["exit_reason"]}')
        elif abs(float(t['exit']) - r['exit_price']) > 0.011:
            issues.append(f'exit price mismatch {key}: {t["exit"]} vs {r["exit_price"]}')
    booked = round(sum(float(t['r_multiple']) for t in prod_trades), 3)
    realized = round(sum(r['realized_r'] for r in records), 3)
    return {
        'production_trades': len(prod_trades),
        'resimulated_trades': len(records),
        'matched': checked,
        'issues': issues,
        'production_booked_total_R': booked,
        'resimulated_realized_total_R': realized,
        'difference_R': round(realized - booked, 3),
        'consistent': not issues,
    }
