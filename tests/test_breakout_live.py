"""Live-path regression for the breakout add-on (2026-10-17).

Live-path regressions for breakout and close-confirmed support reversal signals.
Uses stored candles; read-only (no writes)."""
import sys
sys.path.insert(0, '/opt/tradingai')

from datetime import datetime

from app.core.db import get_conn
from app.live.engine import (_cpr_book_signal, _live_source,
                             _frozen_trade_passes_gate)

FRI = '2026-10-16'   # Friday with a NIFTY BRK_TC upside breakout at 09:40


def _day(inst, day):
    conn = get_conn()
    rows = [dict(c) for c in conn.execute(
        "SELECT timestamp,open,high,low,close,volume FROM market_candles_5m "
        "WHERE instrument_id=? AND substr(timestamp,1,10)=? ORDER BY timestamp",
        (inst, day)).fetchall()]
    conn.close()
    return rows


def test_live_source_labels():
    assert _live_source({'breakout': True}) == 'live_breakout'
    assert _live_source({'no_chase_reanchor': True}) == 'live_no_chase'
    assert _live_source({}) == 'live_next_open'
    assert _live_source(None) == 'live_next_open'


def test_live_breakout_signal_is_bull_brk():
    rows = _day('NIFTY', FRI)
    assert rows, '2026-10-16 NIFTY candles missing'
    completed = datetime.fromisoformat(FRI + 'T09:40:00+05:30')
    close = next(r['close'] for r in rows if r['timestamp'] == completed.isoformat())
    out = _cpr_book_signal('NIFTY', rows, completed, live_price=close, now=completed)
    tr = out.get('trade')
    assert tr is not None, out
    assert tr['direction'] == 'BULL', tr
    assert tr['scenario'].startswith('BRK_'), tr
    assert tr['breakout'] is True, tr
    assert tr['strategy'] == 'Bull Put Spread', tr
    assert tr['stop'] == round(tr['entry'] * 0.995, 2), tr
    assert tr['target'] == round(tr['entry'] * 1.02, 2), tr


def test_live_confirmed_pdl_reversal_emits_bull():
    rows = _day('NIFTY', '2026-10-13')
    assert rows, '2026-10-13 NIFTY candles missing'
    completed = datetime.fromisoformat('2026-10-13T09:15:00+05:30')
    out = _cpr_book_signal('NIFTY', rows, completed, live_price=None, now=completed)
    tr = out.get('trade')
    assert tr is not None, out
    assert tr['direction'] == 'BULL' and tr['scenario'] == 'PDL', tr
    assert tr['signal_time'] == '2026-10-13T09:15:00+05:30', tr
    assert tr['entry_time'] == '2026-10-13T09:20:00+05:30', tr
    assert _frozen_trade_passes_gate(tr, '2026-10-13') is True


def test_live_breakout_frozen_gate():
    # A breakout BULL passes the frozen gate on its Friday and on a Monday.
    f = {'direction': 'BULL', 'scenario': 'BRK_TC', 'breakout': True}
    assert _frozen_trade_passes_gate(f, FRI) is True
    assert _frozen_trade_passes_gate(f, '2026-10-19') is True
    # Confirmed support BULL passes; CPR continuation BULL remains gated.
    assert _frozen_trade_passes_gate(
        {'direction': 'BULL', 'scenario': 'S1'}, '2026-10-19') is True
    assert _frozen_trade_passes_gate(
        {'direction': 'BULL', 'scenario': 'ABOVE_CPR'}, '2026-10-19') is False
