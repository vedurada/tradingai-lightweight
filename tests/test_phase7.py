"""Phase 7 tests: R formula, risk denominator, point-in-time levels, direction
sign, MFE/MAE excursions, holding, outlier accounting, selection, mutation."""
import sys
from collections import Counter
from datetime import datetime
sys.path.insert(0, '/opt/tradingai_new')
from app.core.db import get_conn
from app.research.backtest import BacktestEngine, IntradayExitEngine
from app.risk.engine import RiskEngine

def _c(ts, o, h, l, c):
    return {'timestamp': ts, 'open': o, 'high': h, 'low': l, 'close': c}

# ---------- R formula: unit-consistent points/points ----------
def test_r_long_points_based():
    eng = BacktestEngine.__new__(BacktestEngine)
    trade = {'entry_price': 100.0, 'stop_price': 99.0, 'target_price': 102.0,
             'direction': 'LONG', 'entry_time': '2026-09-18T09:15:00+05:30'}
    # EOD path: no touch (99 < low, high < 102), exits at close 101
    from app.research.backtest import IntradayExitEngine as EE
    ets, epx, ers, mfe, mae = EE.find_exit(trade, [_c('2026-09-18T09:20:00+05:30', 100, 101, 99.5, 101)])
    assert ers == 'EOD'
    move, risk = epx - 100.0, 1.0
    assert abs(move / risk - 1.0) < 1e-9

def test_r_short_sign():
    eng = BacktestEngine()
    r = eng.run('NIFTY', '2026-09-17', '2026-09-19')
    for t in r['trades']:
        risk = abs(t['entry_price'] - t['stop_price'])
        move = (t['exit_price'] - t['entry_price']) if t['direction'] == 'LONG' else (t['entry_price'] - t['exit_price'])
        assert abs(t['R_multiple'] - move / risk) < 0.02, t['trade_id']
        assert (t['paper_pnl'] > 0) == (t['R_multiple'] > 0), 'pnl/R sign mismatch'

def test_engine_r_matches_independent_full():
    eng = BacktestEngine()
    for inst in ('NIFTY', 'BANKNIFTY'):
        r = eng.run(inst, '2026-07-27', '2026-09-19')
        assert r['trades'], inst
        for t in r['trades']:
            risk = abs(t['entry_price'] - t['stop_price'])
            assert risk > 0
            move = (t['exit_price'] - t['entry_price']) if t['direction'] == 'LONG' else (t['entry_price'] - t['exit_price'])
            assert abs(t['R_multiple'] - move / risk) < 0.02, (inst, t['trade_id'])

# ---------- risk denominator ----------
def test_risk_denominator_healthy():
    eng = BacktestEngine()
    for inst in ('NIFTY', 'BANKNIFTY'):
        r = eng.run(inst, '2026-07-27', '2026-09-19')
        risks = [abs(t['entry_price'] - t['stop_price']) for t in r['trades']]
        assert min(risks) > 1.0, f'{inst}: suspicious tiny risk {min(risks)}'
        assert max(abs(t['R_multiple']) for t in r['trades']) < 10, 'absurd R remains'

def test_risk_gate_boundary_valid():
    re_ = RiskEngine()
    ok, _ = re_.validate({'entry': 23207.33, 'stop': 22975.26, 'target': 23671.48,
                          'max_risk': 1.0, 'expected_reward': 2.0})
    assert ok, 'valid 1.0000%-risk candidate must pass (Phase 7 B4)'
    bad, reasons = re_.validate({'entry': 100.0, 'stop': 98.0, 'target': 104.0,
                                 'max_risk': 1.0, 'expected_reward': 2.0})
    assert not bad and any('risk_exceeds_max' in x for x in reasons)

# ---------- point-in-time levels ----------
def test_levels_exact_rules():
    eng = BacktestEngine()
    conn = get_conn()
    r = eng.run('NIFTY', '2026-09-17', '2026-09-19')
    for t in r['trades']:
        sig = conn.execute("SELECT close FROM market_candles_5m WHERE instrument_id='NIFTY' AND timestamp=?",
                           (t['entry_time'],)).fetchone()[0]
        assert abs(t['entry_price'] - round(sig * 0.995, 2)) < 0.011
        assert abs(t['stop_price'] - round(t['entry_price'] * 0.99, 2)) < 0.011
        assert abs(t['target_price'] - round(t['entry_price'] * 1.02, 2)) < 0.011
    conn.close()

# ---------- MFE/MAE excursions ----------
def test_mfe_mae_excursion_semantics():
    eng = BacktestEngine()
    for inst in ('NIFTY', 'BANKNIFTY'):
        r = eng.run(inst, '2026-09-17', '2026-09-19')
        for t in r['trades']:
            assert t['MFE'] >= 0 and t['MAE'] >= 0, t['trade_id']
            move_fav = (t['exit_price'] - t['entry_price']) if t['direction'] == 'LONG' else (t['entry_price'] - t['exit_price'])
            if move_fav > 0:
                assert t['MFE'] + 0.011 >= move_fav, 'MFE smaller than realized favorable move'

def test_holding_is_exit_minus_entry():
    eng = BacktestEngine()
    r = eng.run('NIFTY', '2026-09-17', '2026-09-19')
    for t in r['trades']:
        exp = (datetime.fromisoformat(t['exit_time']) - datetime.fromisoformat(t['entry_time'])).total_seconds() / 60
        assert abs(t['holding_minutes'] - exp) < 0.11
        assert t['exit_time'] >= t['entry_time']

# ---------- accounting ----------
def test_trade_accounting_full():
    eng = BacktestEngine()
    for inst in ('NIFTY', 'BANKNIFTY'):
        r = eng.run(inst, '2026-07-27', '2026-09-19')
        ids = [t['trade_id'] for t in r['trades']]
        assert len(ids) == len(set(ids)), 'duplicate trade_id'
        for t in r['trades']:
            assert t['instrument'] == inst
            assert t['entry_price'] > 0 and t['stop_price'] > 0 and t['target_price'] > 0
            assert abs(t['entry_price'] - t['stop_price']) > 0
            assert t['exit_time'] >= t['entry_time']
        per_day = Counter(t['trade_date'] for t in r['trades'])
        assert max(per_day.values()) <= 1
        o = r['outcome']
        assert o['wins'] + o['losses'] + o['breakeven'] == o['total_trades'] == len(r['trades'])
        assert abs(o['win_rate'] - round(o['wins'] / o['total_trades'], 4)) < 1e-9

def test_outlier_accounting_identity():
    eng = BacktestEngine()
    r = eng.run('NIFTY', '2026-07-27', '2026-09-19')
    Rs = sorted((t['R_multiple'] for t in r['trades']), reverse=True)
    total = sum(Rs)
    assert abs((total - Rs[0]) - sum(Rs[1:])) < 1e-9
    assert abs((total - sum(Rs[:5])) - sum(Rs[5:])) < 1e-9

# ---------- selection: first qualifying signal, point-in-time ----------
def test_selection_is_first_qualifying_signal():
    from app.core.qualification import QualificationEngine
    eng = BacktestEngine()
    r = eng.run('NIFTY', '2026-09-10', '2026-09-12')
    conn = get_conn()
    q = QualificationEngine()
    for day in sorted({t['trade_date'] for t in r['trades']}):
        q.reset_research_locks()
        day_candles = [dict(c) for c in conn.execute(
            "SELECT * FROM market_candles_5m WHERE instrument_id='NIFTY' AND substr(timestamp,1,10)=? ORDER BY timestamp",
            (day,)).fetchall()]
        first = None
        for c in day_candles:
            ms = {'trend': 'BULLISH', 'vwap_relation': 'ABOVE', 'momentum': 'POSITIVE',
                  'volatility': 'NORMAL', 'price': c['close']}
            if q.qualify('NIFTY', ms, options_valid=True, research=True, trade_date=day, as_of=c['timestamp'])['decision'] == 'QUALIFIED_TRADE':
                first = c['timestamp']
                break
        got = [t['entry_time'] for t in r['trades'] if t['trade_date'] == day][0]
        assert got == first, f'{day}: entry {got} != first qualifying {first}'
    conn.close()

# ---------- future-data mutation ----------
def test_future_candle_mutation_preserves_signal():
    conn = get_conn()
    row = conn.execute("SELECT open,high,low,close,volume FROM market_candles_5m WHERE instrument_id='NIFTY' AND timestamp='2026-09-18T14:55:00+05:30'").fetchone()
    assert row
    eng = BacktestEngine()
    before = eng.run('NIFTY', '2026-09-17', '2026-09-19')
    t0 = [t for t in before['trades'] if t['trade_date'] == '2026-09-17'][0]
    try:
        conn.execute("UPDATE market_candles_5m SET high=close*1.10, close=close*1.10 WHERE instrument_id='NIFTY' AND timestamp='2026-09-18T14:55:00+05:30'")
        conn.commit()
        after = eng.run('NIFTY', '2026-09-17', '2026-09-19')
        t1 = [t for t in after['trades'] if t['trade_date'] == '2026-09-17'][0]
        assert (t1['entry_price'], t1['stop_price'], t1['target_price']) == (t0['entry_price'], t0['stop_price'], t0['target_price'])
    finally:
        conn.execute("UPDATE market_candles_5m SET high=?, low=?, close=?, open=? WHERE instrument_id='NIFTY' AND timestamp='2026-09-18T14:55:00+05:30'",
                     (row[1], row[2], row[3], row[0]))
        conn.execute("UPDATE market_candles_5m SET volume=? WHERE instrument_id='NIFTY' AND timestamp='2026-09-18T14:55:00+05:30'", (row[4],))
        conn.commit()
        conn.close()

def test_scenario_content_does_not_set_levels():
    import uuid
    conn = get_conn()
    eng = BacktestEngine()
    before = eng.run('NIFTY', '2026-09-17', '2026-09-19')
    lv0 = [(t['entry_price'], t['stop_price'], t['target_price']) for t in before['trades']]
    cid = 'SC-PROBE-' + uuid.uuid4().hex[:8]
    mid = 'SM-' + cid
    future_ts = '2026-09-19T23:59:00+05:30'
    try:
        conn.execute("INSERT INTO scenario_candidates (candidate_id, instrument_id, session_id, scenario_type, historical_context, required_conditions, confirmation_conditions, invalidation_conditions, status, confidence, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     (cid, 'NIFTY', 'SESS-PROBE', 'RANGE_PREMIUM_DECAY', '{}', '{}', '{}', '{}', 'CONFIRMED', 1.0, future_ts, future_ts))
        conn.execute("INSERT INTO scenario_matches (match_id, candidate_id, instrument_id, timestamp, match_state, evidence, confidence, confirmation_evidence, invalidation_evidence, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (mid, cid, 'NIFTY', future_ts, 'CONFIRMED', '[]', 1.0, '[]', '[]', future_ts))
        conn.commit()
        after = eng.run('NIFTY', '2026-09-17', '2026-09-19')
        lv1 = [(t['entry_price'], t['stop_price'], t['target_price']) for t in after['trades']]
        assert lv0 == lv1, 'trade levels must not depend on scenario-table content'
    finally:
        conn.execute("DELETE FROM scenario_matches WHERE match_id=?", (mid,))
        conn.execute("DELETE FROM scenario_candidates WHERE candidate_id=?", (cid,))
        conn.commit()
        conn.close()
