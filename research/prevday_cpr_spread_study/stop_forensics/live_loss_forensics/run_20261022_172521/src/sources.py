"""Discovery and taxonomy of the candidate trade sources.

The study must never mix populations. Every table that contains something
trade-like is registered here with an explicit inclusion decision, so the
report can state exactly which records are actual live/paper trades and which
are simulated, vetoed, unfinished or test fixtures.
"""
import json

from . import config, dbutil


def _evidence(row):
    try:
        return json.loads(row.get('qualification_evidence') or '{}') or {}
    except (TypeError, ValueError):
        return {}


def load_sources(conn):
    """Return the registered source populations and their row-level records."""
    paper_trades = dbutil.rows(conn, config.T_PAPER_TRADES, order='created_at')
    paper_align = dbutil.rows(conn, config.T_PAPER_ALIGN,
                              order='session_date, instrument_id')
    journal = dbutil.rows(conn, config.T_TRADE_JOURNAL,
                           order='session_date, instrument_id')
    vetoes = dbutil.rows(conn, config.T_PAPER_ALIGN_VETO, order='session_date')
    obs = dbutil.rows(conn, config.T_LIVE_OBS, order='created_at')
    qualified = dbutil.rows(conn, config.T_QUALIFIED, order='created_at')
    triggers = dbutil.rows(conn, config.T_PAPER_TRIGGER, order='created_at')
    mistakes = dbutil.rows(conn, config.T_TRADE_MISTAKE)

    live, fixtures, void = [], [], []
    for row in paper_trades:
        ev = _evidence(row)
        if row.get('status') == 'VOID':
            void.append(row)
        elif ev.get('origin') == 'live-watch':
            live.append(row)
        else:
            fixtures.append(row)

    traded_align = [r for r in paper_align
                    if r.get('instrument_id') in config.TRADED_INSTRUMENTS]
    vix_align = [r for r in paper_align
                 if r.get('instrument_id') not in config.TRADED_INSTRUMENTS]

    return {
        'live_paper_trades': live,
        'test_fixture_trades': fixtures,
        'void_test_trades': void,
        'engine_signal_book': traded_align,
        'engine_signal_book_vix': vix_align,
        'legacy_journal': journal,
        'vetoed_signals': vetoes,
        'live_observations': obs,
        'qualified_trades': qualified,
        'paper_trigger': triggers,
        'trade_mistake': mistakes,
    }


def describe(sources, conn):
    """Machine-readable description of every source: size, range, decision."""
    candles = dbutil.rows(conn, config.T_CANDLES,
                           order='timestamp')
    per_instrument = {}
    for c in candles:
        per_instrument.setdefault(c['instrument_id'], []).append(c)
    candle_info = {}
    for inst, cs in per_instrument.items():
        dates = sorted({c['timestamp'][:10] for c in cs})
        candle_info[inst] = {
            'rows': len(cs),
            'first': dates[0] if dates else None,
            'last': dates[-1] if dates else None,
            'sessions': len(dates),
            'incomplete_rows': sum(1 for c in cs if not c.get('is_complete')),
        }

    def rng(rows, key='session_date'):
        vals = sorted({str(r.get(key) or '')[:10] for r in rows if r.get(key)})
        return {'first': vals[0] if vals else None, 'last': vals[-1] if vals else None,
                'sessions': len(vals)}

    def instr(rows):
        return sorted({r.get('instrument_id') for r in rows if r.get('instrument_id')})

    return {
        'live_paper_trades': {
            'table': config.T_PAPER_TRADES,
            'filter': "status<>'VOID' AND qualification_evidence.origin='live-watch'",
            'role': 'ACTUAL LIVE/PAPER TRADES',
            'rows': len(sources['live_paper_trades']),
            'instruments': instr(sources['live_paper_trades']),
            'range': rng(sources['live_paper_trades'], 'entry_time'),
            'note': 'Written by the live watcher (scripts/tg_alerts.py --watch) through '
                    'PaperTradeEngine.create_paper_trade. This is the population the '
                    "production code itself treats as genuine ('_is_live').",
        },
        'test_fixture_trades': {
            'table': config.T_PAPER_TRADES,
            'filter': "status<>'VOID' AND qualification_evidence.origin IS NULL",
            'role': 'EXCLUDED - historical test fixtures / research re-runs',
            'rows': len(sources['test_fixture_trades']),
            'instruments': instr(sources['test_fixture_trades']),
            'range': rng(sources['test_fixture_trades'], 'entry_time'),
            'note': "The production code (app/paper_trade/performance.py, engine.py) "
                    "excludes rows without origin='live-watch' and reports them as "
                    'excluded_test_records. Their own price/label semantics are '
                    'internally inconsistent (see DATA_QUALITY_AND_RECONCILIATION.md).',
        },
        'void_test_trades': {
            'table': config.T_PAPER_TRADES,
            'filter': "status='VOID'",
            'role': 'EXCLUDED - voided test rows',
            'rows': len(sources['void_test_trades']),
            'note': 'exit_reason=TEST_ROW_VOID; no market outcome.',
        },
        'engine_signal_book': {
            'table': config.T_PAPER_ALIGN,
            'filter': "state='SIGNAL' AND instrument_id IN ('NIFTY','BANKNIFTY')",
            'role': 'LIVE-ENGINE SIGNAL BOOK WITH MODELLED (opens-execution) OUTCOMES',
            'rows': len(sources['engine_signal_book']),
            'instruments': instr(sources['engine_signal_book']),
            'range': rng(sources['engine_signal_book']),
            'note': 'The approved-spec opens-execution book that drives paper.html and '
                    'signals, refreshed by the running service up to the latest session '
                    '(app/research/cpr_trigger_engine.exits_opens, stop 0.5% / target 2%, '
                    'STOP-first). Outcomes are modelled from index candle opens, so these '
                    'are SIMULATED executions of real live-engine signals, not fills.',
        },
        'engine_signal_book_vix': {
            'table': config.T_PAPER_ALIGN,
            'filter': "instrument_id NOT IN ('NIFTY','BANKNIFTY')",
            'role': 'EXCLUDED - INDIA_VIX is not traded or alerted',
            'rows': len(sources['engine_signal_book_vix']),
            'instruments': instr(sources['engine_signal_book_vix']),
            'note': 'scripts/shadow_friday.py states INDIA_VIX is not traded or alerted '
                    '(tg_alerts watches NIFTY/BANKNIFTY only).',
        },
        'legacy_journal': {
            'table': config.T_TRADE_JOURNAL,
            'filter': 'all rows',
            'role': 'LEGACY SIMULATED JOURNAL - reference only',
            'rows': len(sources['legacy_journal']),
            'instruments': instr(sources['legacy_journal']),
            'range': rng(sources['legacy_journal']),
            'note': 'scripts/shadow_friday.py: the old trade_journal source has had no '
                    'production writer since the Phase-9 backend was removed and was '
                    'stale at its last session. Reported for context only, never mixed '
                    'with the live populations.',
        },
        'vetoed_signals': {
            'table': config.T_PAPER_ALIGN_VETO,
            'filter': 'all rows',
            'role': 'EXCLUDED - signals vetoed before an entry existed',
            'rows': len(sources['vetoed_signals']),
            'note': 'No entry, therefore not a trade.',
        },
        'live_observations': {
            'table': config.T_LIVE_OBS,
            'filter': 'all rows',
            'role': 'EXCLUDED - decisions without an entry',
            'rows': len(sources['live_observations']),
            'range': rng(sources['live_observations'], 'market_timestamp'),
            'note': 'Decision log; most rows are MARKET_CLOSED/WEEKEND observations.',
        },
        'qualified_trades': {
            'table': config.T_QUALIFIED,
            'filter': 'all rows',
            'role': 'EXCLUDED - qualification records without a recorded outcome',
            'rows': len(sources['qualified_trades']),
            'note': 'Signal qualification ledger; no exit price or outcome.',
        },
        'paper_trigger': {
            'table': config.T_PAPER_TRIGGER,
            'filter': 'all rows',
            'role': 'REFERENCE - trigger-level records',
            'rows': len(sources['paper_trigger']),
        },
        'trade_mistake': {
            'table': config.T_TRADE_MISTAKE,
            'filter': 'all rows (joined to the legacy journal)',
            'role': 'REFERENCE - the engine-side mistake labels of the legacy journal',
            'rows': len(sources['trade_mistake']),
        },
        'candles': {
            'table': config.T_CANDLES,
            'filter': 'all rows',
            'role': 'PRICE PATH SOURCE (5-minute index candles)',
            'rows': len(candles),
            'instruments': sorted(candle_info),
            'per_instrument': candle_info,
        },
    }
