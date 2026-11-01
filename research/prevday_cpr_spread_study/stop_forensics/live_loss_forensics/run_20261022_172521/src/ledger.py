"""Unified trade ledger and the loss definition.

The ledger keeps the source's own recorded outcome and independently
reconciles it against the recorded entry/exit prices. A trade is only called a
loss when the source says so AND the recorded prices agree with it.
"""
from . import config

OUTCOME_LOSS = 'LOSS'
OUTCOME_WIN = 'WIN'
OUTCOME_FLAT = 'FLAT'
OUTCOME_OPEN = 'OPEN'
OUTCOME_UNKNOWN = 'UNKNOWN_OR_INCONSISTENT'

POP_LIVE = 'LIVE_PAPER_TRADES'
POP_BOOK = 'ENGINE_SIGNAL_BOOK'
POP_LEGACY = 'LEGACY_JOURNAL'


def _num(value):
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _entry(ts):
    """Normalise the different timestamp formats used by the sources."""
    if not ts:
        return None
    text = str(ts).strip()
    if 'T' in text:
        return text.replace('T', ' ')[:19]
    return text[:19]


def _signed_move(direction, entry, exit_price):
    sign = config.direction_sign(direction)
    return (exit_price - entry) * sign


def classify_exit(reason):
    r = (reason or '').upper()
    if r.startswith('STOP'):
        return 'STOP'
    if r.startswith('TARGET'):
        return 'TARGET'
    if r.startswith('EOD'):
        return 'EOD'
    return 'OTHER'


def _reconcile(record, risk_pts, recorded_r, recorded_pnl):
    """Compare the source's recorded numbers with the arithmetic of its prices."""
    flags = []
    entry = record['entry_price']
    exit_price = record['exit_price']
    stop = record['stop_price']
    if entry is None or exit_price is None or not risk_pts:
        return None, None, flags + ['missing_entry_exit_or_risk']
    move = _signed_move(record['direction'], entry, exit_price)
    recomputed_r = move / risk_pts
    recomputed_pnl = move * config.lot(record['instrument']) - config.fees(record['instrument'])
    exit_kind = classify_exit(record.get('exit_reason'))
    if recorded_r is not None:
        if exit_kind in ('STOP', 'TARGET'):
            # The source clips R to the nominal value at a stop/target; the
            # recorded exit price may be a gap beyond the level.
            nominal = -1.0 if exit_kind == 'STOP' else config.PHASE3_TARGET_PCT / 0.005
            if abs(recorded_r - nominal) > 1e-6:
                flags.append(f'recorded_r_not_nominal_for_{exit_kind}')
            if exit_kind == 'STOP' and recomputed_r > recorded_r + 1e-9:
                flags.append('stop_exit_not_adverse')
            if exit_kind == 'TARGET' and recomputed_r < recorded_r - 1e-9:
                flags.append('target_exit_not_favourable')
            if abs(recomputed_r - recorded_r) > config.R_TOLERANCE:
                flags.append('exit_price_beyond_level_gap')
        elif abs(recomputed_r - recorded_r) > config.R_TOLERANCE:
            flags.append('r_mismatch_vs_recorded_prices')
    if recorded_pnl is not None:
        if abs(recomputed_pnl - recorded_pnl) > config.PNL_TOLERANCE_RS:
            flags.append('pnl_mismatch_vs_recorded_prices')
    return round(recomputed_r, 6), round(recomputed_pnl, 2), flags


def _pick(row, *names):
    """First non-null value among the given column names.

    The two live sources name the same fields differently:
    `paper_trades` uses entry/stop/target/scenario, `paper_align` uses
    entry_price/stop_price/target_price/level.
    """
    for name in names:
        value = row.get(name)
        if value is not None:
            return value
    return None


def _base_record(source, population, row, level_key='level'):
    direction = row.get('direction')
    entry = _num(_pick(row, 'entry', 'entry_price'))
    stop = _num(_pick(row, 'stop', 'stop_price'))
    exit_price = _num(_pick(row, 'exit_price'))
    risk_pts = abs(entry - stop) if (entry is not None and stop is not None) else None
    entry_time = _entry(row.get('entry_time'))
    session_date = str(row.get('session_date') or '')[:10] or None
    if not session_date and entry_time:
        session_date = entry_time[:10]
    row_id = row.get('trade_id') or row.get('journal_id')
    if not row_id:
        row_id = '_'.join([str(x) for x in (session_date, row.get('instrument_id'),
                                            entry_time or '', direction or '')
                           if x])
    return {
        'source': source,
        'population': population,
        'source_row_id': row_id,
        'instrument': row.get('instrument_id'),
        'session_date': session_date,
        'direction': direction,
        'level': row.get(level_key) or _pick(row, 'level', 'scenario'),
        'strategy': row.get('strategy'),
        'objective': row.get('objective'),
        'variant': row.get('variant'),
        'entry_time': entry_time,
        'entry_price': entry,
        'stop_price': stop,
        'target_price': _num(_pick(row, 'target', 'target_price')),
        'exit_time': _entry(row.get('exit_time')),
        'exit_price': exit_price,
        'exit_reason': row.get('exit_reason'),
        'exit_kind': classify_exit(row.get('exit_reason')),
        'risk_pts': risk_pts,
        'status': row.get('status'),
        'recorded_result': None,
        'recorded_r': None,
        'recorded_pnl': None,
        'recomputed_r': None,
        'recomputed_pnl': None,
        'outcome_class': None,
        'result_consistent': None,
        'flags': [],
    }


def build_ledger(sources):
    """Return (ledger, population_reports)."""
    ledger = []

    for row in sources['live_paper_trades']:
        rec = _base_record('paper_trades', POP_LIVE, row)
        rec['recorded_result'] = row.get('exit_reason')
        rec['recorded_pnl'] = _num(row.get('paper_pnl'))
        rec['recorded_r'] = None
        recomputed_r, recomputed_pnl, flags = _reconcile(
            rec, rec['risk_pts'], None, rec['recorded_pnl'])
        rec['recomputed_r'] = recomputed_r
        rec['recomputed_pnl'] = recomputed_pnl
        rec['flags'] = flags
        pnl = rec['recorded_pnl']
        if row.get('status') in ('ACTIVE', 'OPEN'):
            rec['outcome_class'] = OUTCOME_OPEN
        elif pnl is None:
            rec['outcome_class'] = OUTCOME_UNKNOWN
            rec['flags'].append('no_recorded_pnl')
        elif pnl < 0:
            rec['outcome_class'] = OUTCOME_LOSS
        elif pnl > 0:
            rec['outcome_class'] = OUTCOME_WIN
        else:
            rec['outcome_class'] = OUTCOME_FLAT
        rec['result_consistent'] = not [f for f in flags
                                        if f.startswith(('pnl_mismatch', 'stop_exit_not',
                                                         'target_exit_not'))]
        ledger.append(rec)

    for row in sources['engine_signal_book']:
        rec = _base_record('paper_align', POP_BOOK, row)
        rec['recorded_result'] = row.get('result')
        rec['recorded_r'] = _num(row.get('r_multiple'))
        recomputed_r, recomputed_pnl, flags = _reconcile(
            rec, rec['risk_pts'], rec['recorded_r'], None)
        rec['recomputed_r'] = recomputed_r
        rec['recomputed_pnl'] = recomputed_pnl
        rec['flags'] = flags
        rec['outcome_class'] = _class_from_label(
            rec['recorded_result'], rec['recorded_r'], recomputed_r, flags)
        rec['result_consistent'] = rec['outcome_class'] != OUTCOME_UNKNOWN
        ledger.append(rec)

    for row in sources['legacy_journal']:
        rec = _base_record('trade_journal', POP_LEGACY, row)
        rec['recorded_result'] = row.get('win_loss')
        rec['recorded_r'] = _num(row.get('r_multiple'))
        rec['recorded_pnl'] = None
        recomputed_r, recomputed_pnl, flags = _reconcile(
            rec, rec['risk_pts'], rec['recorded_r'], None)
        rec['recomputed_r'] = recomputed_r
        rec['recomputed_pnl'] = recomputed_pnl
        rec['flags'] = flags
        rec['outcome_class'] = _class_from_label(
            rec['recorded_result'], rec['recorded_r'], recomputed_r, flags)
        rec['result_consistent'] = rec['outcome_class'] != OUTCOME_UNKNOWN
        ledger.append(rec)

    return ledger, population_reports(ledger, sources)


def _class_from_label(label, recorded_r, recomputed_r, flags):
    label = (label or '').upper()
    if label in ('OPEN', 'PENDING'):
        return OUTCOME_OPEN
    if label == 'FLAT':
        return OUTCOME_FLAT
    if label not in ('WIN', 'LOSS'):
        return OUTCOME_UNKNOWN
    if recorded_r is None and recomputed_r is None:
        return OUTCOME_UNKNOWN
    value = recomputed_r if recomputed_r is not None else recorded_r
    if value is None:
        return OUTCOME_UNKNOWN
    if label == 'LOSS' and value >= 0:
        return OUTCOME_UNKNOWN
    if label == 'WIN' and value < 0:
        return OUTCOME_UNKNOWN
    return OUTCOME_LOSS if label == 'LOSS' else OUTCOME_WIN


def population_reports(ledger, sources):
    """Counts with explicit denominators for every population."""
    reports = {}
    for pop in (POP_LIVE, POP_BOOK, POP_LEGACY):
        rows = [r for r in ledger if r['population'] == pop]
        counts = {'total': len(rows)}
        for outcome in (OUTCOME_LOSS, OUTCOME_WIN, OUTCOME_FLAT, OUTCOME_OPEN,
                        OUTCOME_UNKNOWN):
            counts[outcome.lower()] = sum(1 for r in rows
                                           if r['outcome_class'] == outcome)
        closed = counts[OUTCOME_LOSS.lower()] + counts[OUTCOME_WIN.lower()] + \
            counts[OUTCOME_FLAT.lower()]
        counts['closed'] = closed
        counts['losses'] = counts['loss']
        counts['wins'] = counts['win']
        counts['unknown'] = counts['unknown_or_inconsistent']
        counts['loss_rate_pct'] = round(100.0 * counts['loss'.lower()] / closed, 2) \
            if closed else None
        by_instrument = {}
        for inst in sorted({r['instrument'] for r in rows if r['instrument']}):
            sub = [r for r in rows if r['instrument'] == inst]
            sub_closed = sum(1 for r in sub if r['outcome_class'] in
                             (OUTCOME_LOSS, OUTCOME_WIN, OUTCOME_FLAT))
            sub_loss = sum(1 for r in sub if r['outcome_class'] == OUTCOME_LOSS)
            by_instrument[inst] = {
                'total': len(sub),
                'closed': sub_closed,
                'losses': sub_loss,
                'wins': sum(1 for r in sub if r['outcome_class'] == OUTCOME_WIN),
                'flat': sum(1 for r in sub if r['outcome_class'] == OUTCOME_FLAT),
                'unknown': sum(1 for r in sub if r['outcome_class'] == OUTCOME_UNKNOWN),
                'loss_rate_pct': round(100.0 * sub_loss / sub_closed, 2) if sub_closed else None,
            }
        counts['by_instrument'] = by_instrument
        counts['by_exit_reason'] = _counter(rows, 'exit_reason')
        counts['by_level'] = _counter(rows, 'level')
        counts['by_direction'] = _counter(rows, 'direction')
        counts['by_date'] = _counter(rows, 'session_date')
        counts['flagged'] = sorted({f for r in rows for f in r['flags']})
        reports[pop] = counts
    reports['excluded'] = {
        'test_fixture_trades': len(sources['test_fixture_trades']),
        'void_test_trades': len(sources['void_test_trades']),
        'engine_signal_book_vix': len(sources['engine_signal_book_vix']),
        'vetoed_signals': len(sources['vetoed_signals']),
        'live_observations': len(sources['live_observations']),
        'qualified_trades': len(sources['qualified_trades']),
    }
    return reports


def _counter(rows, key):
    out = {}
    for r in rows:
        value = str(r.get(key))
        out[value] = out.get(value, 0) + 1
    return dict(sorted(out.items()))
