"""Unit tests for the no-filter CPR trigger engine (pure functions, no DB I/O)."""
import sys
sys.path.insert(0, '/opt/tradingai')

from app.research.cpr_trigger_engine import (
    day_levels, bull_trigger, bear_trigger, first_trigger, exit_trade,
    aligned_ok, exits_opens, run_opens_range, decay_win, monday_of,
    weekly_levels, today_state)


def lv():
    # prev H=100, L=90, C=95 -> pp=95, bc=95, tc=95, r1=100, s1=90, r2=105, s2=85
    return day_levels(100, 90, 95)


def test_day_levels_math():
    L = lv()
    assert L['pp'] == 95 and L['tc'] == 95 and L['bc'] == 95
    assert L['r1'] == 100 and L['s1'] == 90
    assert L['r2'] == 105 and L['s2'] == 85
    assert L['pdh'] == 100 and L['pdl'] == 90


def test_day_levels_rejects_garbage():
    assert day_levels(0, 0, 0) is None
    assert day_levels(None, 90, 95) is None
    assert day_levels(90, 100, 95) is None  # high < low


def test_bull_triggers_priority():
    L = lv()
    assert bull_trigger({'low': 84, 'close': 94}, L) == 'S2'
    assert bull_trigger({'low': 89, 'close': 94}, L) == 'S1'
    assert bull_trigger({'low': 91, 'close': 94}, L) is None  # above S1/PDL, at/below TC
    assert bull_trigger({'low': 96, 'close': 96}, L) == 'ABOVE_CPR'


def test_bear_triggers_priority():
    L = lv()
    assert bear_trigger({'high': 106, 'close': 94}, L) == 'R2'
    assert bear_trigger({'high': 101, 'close': 94}, L) == 'R1'
    assert bear_trigger({'high': 94, 'close': 94}, L) == 'BELOW_CPR'
    assert bear_trigger({'high': 94, 'close': 96}, L) is None


def test_first_trigger_bear_wins_tie():
    L = lv()
    day = [{'timestamp': 't1', 'low': 95, 'high': 95, 'close': 95},
           {'timestamp': 't2', 'low': 96, 'high': 106, 'close': 95}]
    sig = first_trigger(day, L)
    assert sig['direction'] == 'BEAR' and sig['level'] == 'R2' and sig['index'] == 1


def test_first_trigger_none():
    L = lv()
    day = [{'timestamp': 't1', 'low': 95, 'high': 95, 'close': 95}]
    assert first_trigger(day, L) is None


def test_exit_bull_target():
    r, px, how = exit_trade('BULL', 100.0,
                            [{'high': 103, 'low': 99.5, 'close': 102}])
    assert r == 2.0 and how == 'TARGET'


def test_exit_bear_stop():
    r, px, how = exit_trade('BEAR', 100.0,
                            [{'high': 102, 'low': 99, 'close': 101}])
    assert r == -1.0 and how == 'STOP'


def test_exit_same_candle_conservative():
    r, px, how = exit_trade('BULL', 100.0,
                            [{'high': 103, 'low': 98, 'close': 101}])
    assert r == -1.0 and 'both' in how


def test_exit_eod_flat():
    r, px, how = exit_trade('BULL', 100.0,
                            [{'high': 101, 'low': 99.5, 'close': 100.5},
                             {'high': 101, 'low': 99.5, 'close': 101.0}])
    assert how == 'EOD' and abs(r - 1.0) < 1e-9


def test_aligned_ok_gates():
    wlv = {'tc': 102.0, 'bc': 98.0}
    assert aligned_ok('BULL', 103.0, wlv) is True
    assert aligned_ok('BULL', 101.0, wlv) is False
    assert aligned_ok('BEAR', 97.0, wlv) is True
    assert aligned_ok('BEAR', 99.0, wlv) is False
    assert aligned_ok('BULL', 103.0, None) is False
    assert aligned_ok('BULL', None, wlv) is False
    assert aligned_ok('SIDEWAYS', 103.0, wlv) is False


def test_exits_opens_stop_first():
    r, px, how, xt = exits_opens('BEAR', 100.0, 0.005, 0.02,
                                 [('t1', 100.6), ('t2', 97.0)])
    assert r == -1.0 and how == 'STOP' and xt == 't1'


def test_exits_opens_target():
    r, px, how, xt = exits_opens('BEAR', 100.0, 0.005, 0.02,
                                 [('t1', 99.0), ('t2', 97.5)])
    assert r == 4.0 and how == 'TARGET' and xt == 't2'


def test_exits_opens_skips_equal():
    assert exits_opens('BULL', 100.0, 0.005, 0.02, [('t1', 100.0)]) is None
    assert exits_opens('BULL', 100.0, 0.005, 0.02, []) is None


def test_run_opens_range_rejects_without_db():
    assert run_opens_range('SENSEX', '2026-09-01', '2026-09-02') == {'error': 'UNKNOWN_INSTRUMENT'}
    assert run_opens_range('NIFTY', '2026-09-01', '2026-09-02', 'silly') == {'error': 'UNKNOWN_VARIANT'}


def test_decay_win_labels():
    assert decay_win('BEAR', 24000.0, 23980.0, 0.167, 'NIFTY') == 'WIN'
    assert decay_win('BEAR', 24000.0, 24020.0, -0.167, 'NIFTY') == 'WIN'  # 20pt < 30
    assert decay_win('BEAR', 24000.0, 24120.0, -1.0, 'NIFTY') == 'LOSS'  # stop-sized
    assert decay_win('BEAR', 55000.0, 55050.0, -0.4, 'BANKNIFTY') == 'WIN'  # 50 < 60
    assert decay_win('BEAR', 55000.0, 55070.0, -0.5, 'BANKNIFTY') == 'LOSS'  # 70 > 60
    assert decay_win('BULL', 100.0, 100.0, 0.0, 'NIFTY') == 'FLAT'
    assert decay_win('BULL', 100.0, None, -0.5, 'NIFTY') is None


def test_monday_of():
    assert monday_of('2026-09-23') == '2026-09-21'
    assert monday_of('2026-09-21') == '2026-09-21'
    assert monday_of('2026-09-27') == '2026-09-21'


def test_today_state_rejects_variant_without_db():
    assert today_state('NIFTY', variant='silly') == {'error': 'UNKNOWN_VARIANT'}
    assert today_state('SENSEX') == {'error': 'UNKNOWN_INSTRUMENT'}


def test_weekly_levels_history():
    from app.core.db import get_conn
    conn = get_conn()
    try:
        w = weekly_levels(conn, 'NIFTY', '2026-09-21')
        assert w and w['tc'] > 0 and w['bc'] > 0
        assert weekly_levels(conn, 'NIFTY', '2026-07-06') is None
    finally:
        conn.close()


def test_run_opens_range_happy_path():
    r = run_opens_range('NIFTY', '2026-09-24', '2026-09-25', 'plain')
    assert r['signals'] >= 1
    assert set(('wins', 'losses', 'skipped', 'by_level')) <= set(r)
    assert sum(v['wins'] for v in r['by_level'].values()) == r['wins']
    for t in r['trades']:
        assert t['win_loss'] in ('WIN', 'LOSS', 'FLAT')
    assert r['wins'] + sum(1 for t in r['trades'] if t['win_loss'] == 'LOSS') <= r['signals']
    assert r['net_R'] == round(r['total_R'] - 0.10 * r['signals'], 2)


def test_scenario_bear_arm_symmetric():
    from app.scenarios.engine import ScenarioEngine
    se = ScenarioEngine()
    try:
        bull = se.evaluate_match('NIFTY', {'trend': 'BULLISH', 'vwap_relation': 'ABOVE',
                                           'momentum': 'POSITIVE', 'volatility': 'NORMAL'},
                                 {'direction': 'BULLISH'})
        assert bull['match_state'] == 'CONFIRMED'
        bear = se.evaluate_match('NIFTY', {'trend': 'BEARISH', 'vwap_relation': 'BELOW',
                                           'momentum': 'NEGATIVE', 'volatility': 'NORMAL'},
                                 {'direction': 'BEARISH'})
        assert bear['match_state'] == 'CONFIRMED'
        inv = se.evaluate_match('NIFTY', {'trend': 'BEARISH', 'vwap_relation': 'BELOW',
                                          'momentum': 'POSITIVE', 'volatility': 'NORMAL'},
                                {'direction': 'BEARISH'})
        assert inv['match_state'] == 'INVALIDATED'
    finally:
        se.conn.close()


def test_live_signal_no_data_without_candles():
    from app.research.cpr_strategy_engine import live_signal
    cpr = {'pp': 23000.0, 'tc': 23020.0, 'bc': 22990.0, 'width_pct': 0.1}
    out = live_signal('NIFTY', cpr, 0.0, 'NEUTRAL', False)
    assert out['state'] == 'NO_DATA'
    assert out['selected_strategy'] is None and out['direction'] is None


def test_risk_engine_reads_nested_config():
    from app.risk.engine import RiskEngine
    cfg = {'risk': {'max_risk_pct': 3.0, 'min_reward_risk': 2.0, 'max_holding_hours': 5}}
    e = RiskEngine(cfg)
    assert (e.max_risk_pct, e.min_reward_risk, e.max_holding_hours) == (3.0, 2.0, 5)
    e2 = RiskEngine(None)
    assert (e2.max_risk_pct, e2.min_reward_risk) == (2.0, 1.5)


def _mkcandles(highs, base=100.0):
    out = []
    for i, h in enumerate(highs):
        out.append({'timestamp': '2026-09-25T09:%02d:00+05:30' % (15 + i * 5),
                    'open': base, 'high': h, 'low': h - 1.0,
                    'close': h - 0.2, 'volume': 0})
    return out


def test_market_state_up_day():
    from app.live.engine import build_market_state
    cs = _mkcandles([100, 101, 102, 103, 104], base=99.0)
    ms = build_market_state(104.0, cs)
    assert ms['trend'] == 'BULLISH'
    assert ms['momentum'] == 'POSITIVE'
    assert ms['price'] == 104.0


def test_market_state_down_day():
    from app.live.engine import build_market_state
    cs = _mkcandles([104, 103, 102, 101, 100], base=104.0)
    ms = build_market_state(100.0, cs)
    assert ms['trend'] == 'BEARISH'
    assert ms['momentum'] == 'NEGATIVE'
    assert ms['vwap_relation'] in ('ABOVE', 'BELOW')


def test_market_state_empty_never_fabricates():
    from app.live.engine import build_market_state
    ms = build_market_state(None, [])
    assert ms['trend'] is None and ms['momentum'] is None
    ms2 = build_market_state(100.0, [])
    assert ms2['price'] == 100.0 and ms2['trend'] is None
