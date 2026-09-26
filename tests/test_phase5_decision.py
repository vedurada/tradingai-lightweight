"""Phase 5: no-lookahead + decision-mapping tests (VM, no mocks of prod logic).

DB-touching tests use instrument_id='TEST_PIT' (never NIFTY/BANKNIFTY, so
live dry-run polls cannot observe them) and delete all rows afterwards.
"""
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from app.live.engine import (
    completed_candle_ts, validate_candles, session_state)
from app.core.db import DB_PATH
from app.decision.view import build_decision

IST = ZoneInfo('Asia/Kolkata')
D = lambda s: datetime.fromisoformat(s)


def test_completed_candle_boundaries():
    assert completed_candle_ts(D('2026-09-25T09:19:59+05:30')) is None
    assert completed_candle_ts(D('2026-09-25T09:20:00+05:30')).isoformat() == '2026-09-25T09:15:00+05:30'
    assert completed_candle_ts(D('2026-09-25T09:30:00+05:30')).isoformat() == '2026-09-25T09:25:00+05:30'
    assert completed_candle_ts(D('2026-09-25T15:35:00+05:30')).isoformat() == '2026-09-25T15:30:00+05:30'


def test_future_candle_rejected_no_lookahead():
    cc = D('2026-09-25T09:25:00+05:30')
    mk = lambda ts: {'timestamp': ts, 'open': 1, 'high': 2, 'low': 1, 'close': 1.5}
    ok, issues, _ = validate_candles(
        [mk('2026-09-25T09:15:00+05:30'), mk('2026-09-25T09:25:00+05:30'),
         mk('2026-09-25T09:30:00+05:30')], cc)
    assert not ok and any(i.startswith('FUTURE_CANDLE') for i in issues)


def test_session_boundaries():
    assert session_state(D('2026-09-25T09:00:00+05:30')) == 'PREMARKET'
    assert session_state(D('2026-09-25T09:20:00+05:30'), True) == 'LIVE'
    assert session_state(D('2026-09-25T15:31:00+05:30')) == 'MARKET_CLOSED'
    assert session_state(D('2026-09-26T10:00:00+05:30')) == 'WEEKEND'  # Saturday


def test_scenario_pit_no_future_read():
    from app.scenarios.engine import ScenarioEngine
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        con.execute("INSERT INTO scenario_candidates (candidate_id, instrument_id, scenario_type, status, confidence, created_at, updated_at) VALUES ('PIT-TEST-1','TEST_PIT','BREAKOUT','CONFIRMED',0.9,'2026-09-25T10:00:00+05:30','2026-09-25T10:00:00+05:30')")
        con.execute("INSERT INTO scenario_matches (match_id, candidate_id, instrument_id, timestamp, match_state, created_at) VALUES ('PITM-1','PIT-TEST-1','TEST_PIT','2026-09-25T10:00:00+05:30','CONFIRMED','2026-09-25T10:00:00+05:30')")
        con.commit()
        eng = ScenarioEngine()
        assert eng.get_scenario_for_timestamp('TEST_PIT', '2026-09-25T09:30:00+05:30') is None
        got = eng.get_scenario_for_timestamp('TEST_PIT', '2026-09-25T10:00:00+05:30')
        assert got and got['match']['match_state'] == 'CONFIRMED'
    finally:
        con.execute("DELETE FROM scenario_matches WHERE candidate_id='PIT-TEST-1'")
        con.execute("DELETE FROM scenario_candidates WHERE candidate_id='PIT-TEST-1'")
        con.commit(); con.close()


def test_build_decision_shape_and_zero_writes():
    con = sqlite3.connect(DB_PATH)
    before = {t: con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
              for t in ('qualified_trades', 'daily_trade_locks', 'paper_trades', 'scenario_candidates')}
    n = build_decision('NIFTY')
    b = build_decision('BANKNIFTY')
    after = {t: con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
             for t in ('qualified_trades', 'daily_trade_locks', 'paper_trades', 'scenario_candidates')}
    con.close()
    assert before == after
    for d, inst in ((n, 'NIFTY'), (b, 'BANKNIFTY')):
        assert d['instrument'] == inst
        assert d['decision'] in ('TRADE', 'WAIT', 'NO TRADE')
        assert d['data_status'] in ('LIVE', 'RECENT', 'STALE', 'UNAVAILABLE')
        assert isinstance(d['reason_codes'], list) and d['reason_codes']
        assert 'cpr' in d and 'explanation' in d
        assert d['market_bias'] in ('BULLISH', 'BEARISH', 'NEUTRAL', 'UNAVAILABLE')
    assert n is not b


def test_unknown_instrument_rejected():
    try:
        build_decision('RELIANCE')
    except ValueError as e:
        assert 'UNKNOWN' in str(e)
    else:
        raise AssertionError('expected ValueError')


def test_map_decision_combinations():
    from app.decision.view import map_decision
    assert map_decision('QUALIFIED', 'LIVE', [], True, False)[0] == 'TRADE'
    assert map_decision('NO_TRADE', 'LIVE', ['scenario_not_matched'], False, False)[0] == 'WAIT'
    assert map_decision('NO_TRADE', 'LIVE', ['scenario_watch'], False, False)[0] == 'WAIT'
    assert map_decision('NO_TRADE', 'LIVE', ['no_active_scenario'], False, False)[0] == 'WAIT'
    assert map_decision('NO_TRADE', 'LIVE', ['options_data_unavailable'], False, False)[0] == 'NO TRADE'
    assert map_decision('NO_TRADE', 'LIVE', [], False, True) == ('NO TRADE', ['DAILY_TRADE_LIMIT_REACHED'])
    assert map_decision('STALE', 'LIVE', ['x'], False, False)[0] == 'NO TRADE'
    assert map_decision('PREMARKET', 'PREMARKET', ['NO_COMPLETED_CANDLE_YET'], False, False)[0] == 'NO TRADE'
    assert map_decision('MARKET_CLOSED', 'MARKET_CLOSED', [], False, False)[0] == 'NO TRADE'
    assert map_decision('WEEKEND', 'WEEKEND', [], False, False)[0] == 'NO TRADE'


def test_instrument_independence_mapping():
    from app.decision.view import map_decision
    nifty = map_decision('QUALIFIED', 'LIVE', [], True, False)
    bank = map_decision('NO_TRADE', 'LIVE', ['scenario_watch'], False, False)
    assert nifty[0] == 'TRADE' and bank[0] == 'WAIT'
    n2 = build_decision('NIFTY')
    b2 = build_decision('BANKNIFTY')
    assert n2['instrument'] == 'NIFTY' and b2['instrument'] == 'BANKNIFTY'
    assert n2 is not b2 and n2['reason_codes'] is not b2['reason_codes']
