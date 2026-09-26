"""Phase 8 tests: point-in-time lookup, replay parity, live parity, locks,
levels, exits, APIs, isolation. DB mutations always reverted.

Spec-item coverage:
  1  scenario lookup cannot read future candidate      -> test_lookup_* (x3)
  2  lookup is instrument-scoped                       -> test_lookup_never_future_instrument_scoped
  3  lookup is timestamp-scoped                        -> test_lookup_*, test_lookup_none_before_any_candidate
  4  global-latest cannot influence historical decision-> test_future_candidate_no_effect (+phase7 PIT test)
  5  future candle mutation keeps current signal       -> test_future_candle_mutation_preserves_signal
  6  future scenario insertion keeps current signal    -> test_future_candidate_no_effect, test_future_scenario_metadata_no_effect
  7  replay processes candles chronologically          -> test_replay_chronological
  8  batch == sequential decisions/trades              -> test_batch_replay_parity_*
  9  (same as 8, full window)                          -> test_batch_replay_parity_full
  10 simulated live == sequential replay               -> test_simulated_live_parity (via live_sim module)
  11 first qualifying signal wins                      -> test_first_signal_wins, test_later_signal_cannot_replace_first
  12 later signals cannot replace first                -> test_later_signal_cannot_replace_first
  13 historical trade date used for lock               -> test_lock_keyed_to_trade_date
  14 research creates no live daily locks              -> test_research_isolation_replay (+lock table count)
  15 entry is signal-candle derived                    -> test_levels_signal_derived_scoped
  16 stop is signal-candle derived                     -> test_levels_signal_derived_scoped
  17 target is signal-candle derived                   -> test_levels_signal_derived_scoped
  18 future data cannot change entry/stop/target       -> test_future_candle_mutation_preserves_signal
  19 exit uses only post-entry candles                 -> test_pre_signal_mutation_preserves_exit, test_eod_exit_uses_last_close
  20 same-candle stop/target conservative              -> test_short_ambiguous_conservative, test_long_ambiguous_conservative
  21 research does not mutate qualified_trades         -> test_research_isolation_replay
  22 research does not mutate paper_trades             -> test_research_isolation_replay
  23 research does not mutate daily_trade_locks        -> test_research_isolation_replay
API + trace invariants (spec sections 4/17)           -> test_research_api_*, test_trace_pit_invariant_full,
                                                         test_lookup_deterministic_tiebreak
"""
import sys, uuid
sys.path.insert(0, '/opt/tradingai_new')
from app.core.db import get_conn
from app.research.backtest import BacktestEngine, IntradayExitEngine
from app.research.replay import SequentialReplay
from app.research.live_sim import SimulatedLive
from app.scenarios.engine import ScenarioEngine
from app.core.qualification import QualificationEngine

DAY_END = 'T23:59:59+05:30'

def replay_day(inst, day):
    r = SequentialReplay().run(inst, day, day + DAY_END)
    r['traces'] = [t for t in r['traces'] if t['trade_date'] == day]
    r['trades'] = [t for t in r['trades'] if t['trade_date'] == day]
    return r

# 1-3. scoped lookup: timestamp + instrument scoping
def test_lookup_never_future_instrument_scoped():
    conn = get_conn()
    se = ScenarioEngine()
    # All probed timestamps are at/after each instrument's first candidate,
    # so a scoped lookup must return a row (None is only valid pre-data).
    for inst in ('NIFTY', 'BANKNIFTY'):
        for ts in ('2026-08-15T12:00:00+05:30', '2026-09-16T14:15:00+05:30', '2026-09-18T15:25:00+05:30'):
            got = se.get_scenario_for_timestamp(inst, ts)
            assert got, (inst, ts)
            assert got['candidate']['instrument_id'] == inst
            assert got['candidate']['created_at'] <= ts, (inst, ts, got['candidate']['created_at'])
            if got['match']:
                assert got['match']['timestamp'] <= ts
    assert se.get_scenario_for_timestamp('NIFTY', '2020-01-01T00:00:00+05:30') is None
    conn.close()

# 3. full-day sweep: every candle's lookup is PIT-safe
def test_lookup_scoped_every_candle_of_day():
    conn = get_conn()
    se = ScenarioEngine()
    for inst in ('NIFTY', 'BANKNIFTY'):
        stamps = [r[0] for r in conn.execute(
            "SELECT timestamp FROM market_candles_5m WHERE instrument_id=? AND substr(timestamp,1,10)='2026-09-16' ORDER BY timestamp",
            (inst,)).fetchall()]
        assert len(stamps) == 75
        for ts in stamps:
            got = se.get_scenario_for_timestamp(inst, ts)
            if got is not None:
                assert got['candidate']['created_at'] <= ts, (inst, ts)
                assert got['candidate']['instrument_id'] == inst
                if got['match']:
                    assert got['match']['timestamp'] <= ts
    conn.close()

# 3b. no candidate knowable yet -> None (documents the 07-27 NIFTY / pre-07-29 BANKNIFTY gap)
def test_lookup_none_before_any_candidate():
    se = ScenarioEngine()
    assert se.get_scenario_for_timestamp('NIFTY', '2026-07-27T09:15:00+05:30') is None
    assert se.get_scenario_for_timestamp('BANKNIFTY', '2026-07-28T15:25:00+05:30') is None

# 2/3. deterministic tiebreak when several candidates share a timestamp
def test_lookup_deterministic_tiebreak():
    conn = get_conn()
    se = ScenarioEngine()
    ts = '2026-09-16T20:00:00+05:30'  # after market close: no real candidates tie here
    ids = ['SC-TIEB-' + uuid.uuid4().hex[:8] + '-A', '']
    ids[1] = ids[0][:-1] + 'B'
    try:
        for cid in ids:
            conn.execute("INSERT INTO scenario_candidates (candidate_id, instrument_id, session_id, scenario_type, historical_context, required_conditions, confirmation_conditions, invalidation_conditions, status, confidence, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         (cid, 'NIFTY', 'SESS-TIE', 'BREAKOUT', '{}', '{}', '{}', '{}', 'CONFIRMED', 0.5, ts, ts))
        conn.commit()
        first = se.get_scenario_for_timestamp('NIFTY', ts)
        second = se.get_scenario_for_timestamp('NIFTY', ts)
        assert first and second
        assert first['candidate']['candidate_id'] == second['candidate']['candidate_id'] == min(ids)
    finally:
        for cid in ids:
            conn.execute("DELETE FROM scenario_candidates WHERE candidate_id=?", (cid,))
        conn.commit()
        conn.close()

# 4/6. future candidate cannot influence historical decision
def test_future_candidate_no_effect():
    conn = get_conn()
    before = replay_day('NIFTY', '2026-09-16')
    cid = 'SC-T8-' + uuid.uuid4().hex[:8]
    mid = 'SM-' + cid
    fts = '2026-09-18T10:00:00+05:30'
    try:
        conn.execute("INSERT INTO scenario_candidates (candidate_id, instrument_id, session_id, scenario_type, historical_context, required_conditions, confirmation_conditions, invalidation_conditions, status, confidence, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     (cid, 'NIFTY', 'SESS-T8', 'BREAKOUT', '{}', '{}', '{}', '{}', 'CONFIRMED', 1.0, fts, fts))
        conn.execute("INSERT INTO scenario_matches (match_id, candidate_id, instrument_id, timestamp, match_state, evidence, confidence, confirmation_evidence, invalidation_evidence, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (mid, cid, 'NIFTY', fts, 'CONFIRMED', '[]', 1.0, '[]', '[]', fts))
        conn.commit()
        after = replay_day('NIFTY', '2026-09-16')
        b = [(t['entry_time'], t['entry_price'], t['stop_price'], t['target_price']) for t in before['trades']]
        a = [(t['entry_time'], t['entry_price'], t['stop_price'], t['target_price']) for t in after['trades']]
        assert a == b and len(b) == 1
    finally:
        conn.execute("DELETE FROM scenario_matches WHERE match_id=?", (mid,))
        conn.execute("DELETE FROM scenario_candidates WHERE candidate_id=?", (cid,))
        conn.commit()
        conn.close()

# 6C. future scenario metadata change cannot influence historical decision
def test_future_scenario_metadata_no_effect():
    conn = get_conn()
    before = replay_day('NIFTY', '2026-09-16')
    row = conn.execute("SELECT candidate_id, confidence FROM scenario_candidates WHERE instrument_id='NIFTY' AND created_at>'2026-09-17T15:30:00+05:30' LIMIT 1").fetchone()
    assert row
    try:
        conn.execute("UPDATE scenario_candidates SET confidence=0.01, status='INVALIDATED' WHERE candidate_id=?", (row[0],))
        conn.commit()
        after = replay_day('NIFTY', '2026-09-16')
        b = [(t['entry_time'], t['entry_price'], t['stop_price'], t['target_price']) for t in before['trades']]
        a = [(t['entry_time'], t['entry_price'], t['stop_price'], t['target_price']) for t in after['trades']]
        assert a == b
    finally:
        conn.execute("UPDATE scenario_candidates SET confidence=?, status='CONFIRMED' WHERE candidate_id=?", (row[1], row[0]))
        conn.commit()
        conn.close()

# 5/18. future candle mutation preserves signal + levels
def test_future_candle_mutation_preserves_signal():
    conn = get_conn()
    before = replay_day('NIFTY', '2026-09-16')
    sig = before['trades'][0]['entry_time']
    orig = [dict(c) for c in conn.execute(
        "SELECT timestamp,open,high,low,close,volume FROM market_candles_5m WHERE instrument_id='NIFTY' AND substr(timestamp,1,10)='2026-09-16' AND timestamp>?",
        (sig,)).fetchall()]
    try:
        conn.execute("UPDATE market_candles_5m SET high=high*1.05,low=low*1.05,close=close*1.05,open=open*1.05 WHERE instrument_id='NIFTY' AND substr(timestamp,1,10)='2026-09-16' AND timestamp>?",
                     (sig,))
        conn.commit()
        after = replay_day('NIFTY', '2026-09-16')
        assert [(t['timestamp'], t['qualification']) for t in after['traces'] if t['timestamp'] <= sig] == \
               [(t['timestamp'], t['qualification']) for t in before['traces'] if t['timestamp'] <= sig]
        assert [(t['entry_price'], t['stop_price'], t['target_price']) for t in after['trades']] == \
               [(t['entry_price'], t['stop_price'], t['target_price']) for t in before['trades']]
    finally:
        for c in orig:
            conn.execute("UPDATE market_candles_5m SET open=?,high=?,low=?,close=?,volume=? WHERE instrument_id='NIFTY' AND timestamp=?",
                         (c['open'], c['high'], c['low'], c['close'], c['volume'], c['timestamp']))
        conn.commit()
        conn.close()

# 7. chronological processing
def test_replay_chronological():
    r = replay_day('NIFTY', '2026-09-16')
    ts = [t['timestamp'] for t in r['traces']]
    assert len(ts) == 75 and ts == sorted(ts)

# 8/9. batch vs replay parity (3-day window: decisions + trades)
def test_batch_replay_parity_window():
    b = BacktestEngine().run('NIFTY', '2026-09-15', '2026-09-17' + DAY_END)
    r = SequentialReplay().run('NIFTY', '2026-09-15', '2026-09-17' + DAY_END)
    bk = [(t['trade_date'], t['entry_time'], t['entry_price'], t['exit_time'], t['exit_price'], t['R_multiple']) for t in b['trades']]
    rk = [(t['trade_date'], t['entry_time'], t['entry_price'], t['exit_time'], t['exit_price'], t['R_multiple']) for t in r['trades']]
    assert bk == rk

def test_batch_replay_parity_full():
    for inst in ('NIFTY', 'BANKNIFTY'):
        b = BacktestEngine().run(inst, '2026-07-27', '2026-09-19')
        r = SequentialReplay().run(inst, '2026-07-27', '2026-09-19')
        keys = ('trade_date', 'scenario', 'direction', 'entry_time', 'entry_price', 'stop_price',
                'target_price', 'exit_time', 'exit_price', 'exit_reason', 'R_multiple')
        assert [tuple(t[k] for k in keys) for t in b['trades']] == [tuple(t[k] for k in keys) for t in r['trades']]

# 10. simulated live == replay (same gate, one-candle-at-a-time feed)
def test_simulated_live_parity():
    live = SimulatedLive().run('NIFTY', '2026-09-15', '2026-09-16' + DAY_END)
    r = SequentialReplay().run('NIFTY', '2026-09-15', '2026-09-16' + DAY_END)
    live_dec = [(d['timestamp'], d['qualification']) for d in live['decisions']
                if d['trade_date'] in ('2026-09-15', '2026-09-16')]
    rd = [(t['timestamp'], t['qualification']) for t in r['traces'] if t['trade_date'] in ('2026-09-15', '2026-09-16')]
    assert live_dec == rd

# 11/12. first signal wins; later cannot replace
def test_first_signal_wins():
    r = replay_day('NIFTY', '2026-09-16')
    assert len(r['trades']) == 1 and r['trades'][0]['entry_time'] == '2026-09-16T14:15:00+05:30'
    quals = [t for t in r['traces'] if t['qualification'] == 'QUALIFIED_TRADE']
    assert len(quals) == 1
    after = [t for t in r['traces'] if t['timestamp'] > '2026-09-16T14:15:00+05:30']
    assert all('DAILY_TRADE_LIMIT_REACHED' in t['reasons'] or t['qualification'] == 'NO_TRADE' for t in after)

# 11/12D. one trade per day across the full window; entry == first qualified trace
def test_later_signal_cannot_replace_first():
    for inst in ('NIFTY', 'BANKNIFTY'):
        r = SequentialReplay().run(inst, '2026-07-27', '2026-09-19')
        by_day = {}
        for t in r['traces']:
            by_day.setdefault(t['trade_date'], []).append(t)
        for day, traces in sorted(by_day.items()):
            quals = [t for t in traces if t['qualification'] == 'QUALIFIED_TRADE']
            day_trades = [t for t in r['trades'] if t['trade_date'] == day]
            assert len(day_trades) <= 1, (inst, day, len(day_trades))
            if day_trades:
                assert len(quals) == 1, (inst, day)
                assert day_trades[0]['entry_time'] == quals[0]['timestamp'], (inst, day)

# 13. lock keyed to trade_date (uses the day's actual qualifying timestamp)
def test_lock_keyed_to_trade_date():
    q = QualificationEngine()
    q.reset_research_locks()
    ms = {'trend': 'BULLISH', 'vwap_relation': 'ABOVE', 'momentum': 'POSITIVE', 'volatility': 'NORMAL', 'price': 23000}
    d = q.qualify('NIFTY', ms, options_valid=True, research=True, trade_date='2026-09-16', as_of='2026-09-16T14:15:00+05:30')
    assert d['decision'] == 'QUALIFIED_TRADE'
    assert ('NIFTY', '2026-09-16') in q.research_daily_locks
    assert ('NIFTY', '2026-09-17') not in q.research_daily_locks

# 15-17. levels signal-derived (scoped engine)
def test_levels_signal_derived_scoped():
    conn = get_conn()
    r = replay_day('BANKNIFTY', '2026-08-31')
    assert r['trades'], 'expected trade'
    for t in r['trades']:
        sig = conn.execute("SELECT close FROM market_candles_5m WHERE instrument_id='BANKNIFTY' AND timestamp=?",
                           (t['entry_time'],)).fetchone()[0]
        assert abs(t['entry_price'] - round(sig * 0.995, 2)) < 0.011
        assert abs(t['stop_price'] - round(t['entry_price'] * 0.99, 2)) < 0.011
        assert abs(t['target_price'] - round(t['entry_price'] * 1.02, 2)) < 0.011
    conn.close()

# 19. pre-signal mutation cannot move exit (exit uses post-entry only)
def test_pre_signal_mutation_preserves_exit():
    conn = get_conn()
    before = replay_day('NIFTY', '2026-09-16')
    t0 = before['trades'][0]
    row = conn.execute("SELECT open,high,low,close,volume FROM market_candles_5m WHERE instrument_id='NIFTY' AND timestamp='2026-09-16T09:15:00+05:30'").fetchone()
    try:
        conn.execute("UPDATE market_candles_5m SET high=high*1.02 WHERE instrument_id='NIFTY' AND timestamp='2026-09-16T09:15:00+05:30'")
        conn.commit()
        after = replay_day('NIFTY', '2026-09-16')
        t1 = after['trades'][0]
        assert (t1['exit_time'], t1['exit_price'], t1['exit_reason']) == (t0['exit_time'], t0['exit_price'], t0['exit_reason'])
    finally:
        conn.execute("UPDATE market_candles_5m SET open=?,high=?,low=?,close=?,volume=? WHERE instrument_id='NIFTY' AND timestamp='2026-09-16T09:15:00+05:30'",
                     (row[0], row[1], row[2], row[3], row[4]))
        conn.commit()
        conn.close()

# 9/19. LONG exit rules: stop first, target otherwise
def test_long_exit_stop_target_rules():
    base = {'entry_price': 100.0, 'stop_price': 99.0, 'target_price': 102.0,
            'direction': 'LONG', 'entry_time': '2026-09-18T09:15:00+05:30'}
    ts, px, reason, _, _ = IntradayExitEngine.find_exit(
        dict(base), [{'timestamp': '2026-09-18T09:20:00+05:30', 'open': 100, 'high': 100.5, 'low': 98.5, 'close': 99.5}])
    assert reason == 'STOP' and px == 98.5
    ts, px, reason, _, _ = IntradayExitEngine.find_exit(
        dict(base), [{'timestamp': '2026-09-18T09:20:00+05:30', 'open': 100, 'high': 102.5, 'low': 99.5, 'close': 102.0}])
    assert reason == 'TARGET' and px == 102.0

# 9/20. LONG same-candle stop+target resolves conservatively (STOP side)
def test_long_ambiguous_conservative():
    ts, px, reason, _, _ = IntradayExitEngine.find_exit(
        {'entry_price': 100.0, 'stop_price': 99.0, 'target_price': 102.0, 'direction': 'LONG',
         'entry_time': '2026-09-18T09:15:00+05:30'},
        [{'timestamp': '2026-09-18T09:20:00+05:30', 'open': 100, 'high': 103.0, 'low': 98.0, 'close': 100}])
    assert reason == 'AMBIGUOUS_INTRABAR' and px == 99.0

# 20. SHORT ambiguous resolves STOP
def test_short_ambiguous_conservative():
    ts, px, reason, _, _ = IntradayExitEngine.find_exit(
        {'entry_price': 100.0, 'stop_price': 101.0, 'target_price': 98.0, 'direction': 'SHORT',
         'entry_time': '2026-09-18T09:15:00+05:30'},
        [{'timestamp': '2026-09-18T09:20:00+05:30', 'open': 100, 'high': 101.5, 'low': 97.5, 'close': 100}])
    assert reason == 'AMBIGUOUS_INTRABAR' and px == 101.0

# 9/19. EOD exit uses the last post-entry close
def test_eod_exit_uses_last_close():
    ts, px, reason, _, _ = IntradayExitEngine.find_exit(
        {'entry_price': 100.0, 'stop_price': 99.0, 'target_price': 102.0, 'direction': 'LONG',
         'entry_time': '2026-09-18T09:15:00+05:30'},
        [{'timestamp': '2026-09-18T09:20:00+05:30', 'open': 100, 'high': 100.6, 'low': 99.6, 'close': 100.4},
         {'timestamp': '2026-09-18T09:25:00+05:30', 'open': 100.4, 'high': 101.0, 'low': 99.8, 'close': 100.9}])
    assert reason == 'EOD' and px == 100.9 and ts == '2026-09-18T09:25:00+05:30'

# 4/5. every replay trace is point-in-time: scenario_timestamp <= timestamp (FULL, both instruments)
def test_trace_pit_invariant_full():
    for inst in ('NIFTY', 'BANKNIFTY'):
        r = SequentialReplay().run(inst, '2026-07-27', '2026-09-19')
        assert r['traces']
        for t in r['traces']:
            if t['scenario_timestamp'] is not None:
                assert t['scenario_timestamp'] <= t['timestamp'], (inst, t['timestamp'], t['scenario_timestamp'])
        counts = {}
        for t in r['traces']:
            counts.setdefault(t['trade_date'], []).append(t['scenario_count'])
        for day, cs in counts.items():
            assert cs == sorted(cs), (inst, day, 'scenario_count must be non-decreasing within a day')

# 17. research APIs return HTTP 200
def test_research_api_endpoints_200():
    from app.api.app import app
    client = app.test_client()
    assert client.get('/api/research/scenarios').status_code == 200
    assert client.get('/api/research/scenarios/NIFTY').status_code == 200
    assert client.get('/api/research/performance').status_code == 200
    r = client.get('/api/research/replay/NIFTY/2026-09-16/14:15:00+05:30')
    assert r.status_code == 200

# 17. replay endpoint reflects the requested timestamp, not global-latest state
def test_replay_endpoint_scoped_to_timestamp():
    from app.api.app import app
    client = app.test_client()
    early = client.get('/api/research/replay/NIFTY/2026-07-27/09:15:00+05:30').get_json()['data']
    late = client.get('/api/research/replay/NIFTY/2026-09-18/15:25:00+05:30').get_json()['data']
    assert all(s['created_at'] <= '2026-07-27T09:15:00+05:30' for s in early['scenario_state'])
    assert all(c['timestamp'] <= '2026-07-27T09:15:00+05:30' for c in early['candles_available_at_decision'])
    assert len(late['scenario_state']) > len(early['scenario_state'])

# 21-23. isolation
def test_research_isolation_replay():
    conn = get_conn()
    q = "SELECT (SELECT COUNT(*) FROM qualified_trades),(SELECT COUNT(*) FROM paper_trades),(SELECT COUNT(*) FROM daily_trade_locks)"
    before = tuple(conn.execute(q).fetchone())
    SequentialReplay().run('NIFTY', '2026-09-15', '2026-09-16' + DAY_END)
    BacktestEngine().run('BANKNIFTY', '2026-09-15', '2026-09-16' + DAY_END)
    SimulatedLive().run('NIFTY', '2026-09-15', '2026-09-16' + DAY_END)
    after = tuple(conn.execute(q).fetchone())
    conn.close()
    assert before == after == (0, 0, 0)
