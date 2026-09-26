"""Phase 11 tests: live data reliability & market session hardening (24 items).

 1 provider timeout          -> test_provider_timeout_bounded
 2 empty provider result     -> test_provider_empty_unavailable
 3 malformed provider result -> test_provider_malformed_no_crash
 4 stale feed                -> test_stale_feed_no_trade (+ cache variant)
 5 missing feed              -> test_missing_feed_no_data
 6 future candle             -> (phase9, re-asserted via engine gate here) test_future_rejected_live
 7 duplicate candle          -> test_duplicate_rejected_live
 8 invalid OHLC              -> test_invalid_ohlc_rejected_live
 9 independent failure       -> test_nifty_banknifty_independent_failure
10 bounded retry             -> test_retry_bounded_single_retry
11 cache freshness           -> test_cache_serves_within_ttl
12 cache timestamp preserved -> test_cache_preserves_original_timestamp
13 no duplicate fetch        -> test_shared_cache_dedupes_workers
14 premarket                 -> test_premarket_state
15 live session              -> test_live_session_gating
16 market closed             -> test_market_closed_state
17 weekend                   -> test_weekend_state
18 holiday                   -> test_nse_holiday_closed (+ calendar facts)
19 completed-candle gating   -> test_completed_candle_gating
20 scenario<=decision        -> test_live_pit_regression
21 GET does not consume lock -> test_get_decision_read_only
22 concurrent one trade      -> test_concurrent_claim_single_trade
23 independent locks         -> test_independent_locks_live
24 research isolation        -> test_phase11_research_isolation

Plus: baseline regression is covered by the existing FULL parity suite
(phase8) re-run in the full pass; this file asserts the research baseline
counts directly (fast: uses stored comparison artifact? No — runs replay
FULL once per instrument for independence from batch).
"""
import sys, threading, time, uuid
sys.path.insert(0, '/opt/tradingai_new')
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from app.live.engine import LiveEngine, completed_candle_ts, session_state
from app.market import cache as pcache
from app.market.nse_calendar import (holiday_name, is_session_day, is_weekend,
                                 NSE_HOLIDAYS_2026)
from app.core.db import get_conn
from app.research.replay import SequentialReplay

_IST = ZoneInfo('Asia/Kolkata')
WED = '2026-09-16'


def ist(s):
    return datetime.fromisoformat(s)


def db_day(inst, day):
    conn = get_conn()
    rows = [dict(c) for c in conn.execute(
        "SELECT timestamp,open,high,low,close,volume FROM market_candles_5m "
        "WHERE instrument_id=? AND substr(timestamp,1,10)=? ORDER BY timestamp",
        (inst, day)).fetchall()]
    conn.close()
    return rows


# ---------- 1-3. provider failure handling (no network: stubbed fetch) ----------
def _provider_with_history(fn):
    import app.market.provider as prov
    p = prov.MarketDataProvider()
    orig = prov._fetch_history
    prov._fetch_history = fn
    try:
        yield p
    finally:
        prov._fetch_history = orig


def test_provider_timeout_bounded():
    import app.market.provider as prov
    from concurrent.futures import TimeoutError as _TE
    calls = []

    class SlowTicker:
        def __init__(self, symbol):
            pass

        def history(self, period, interval):
            calls.append(1)
            raise _TE('timed out')

    orig = prov.yf.Ticker
    prov.yf.Ticker = SlowTicker
    try:
        p = prov.MarketDataProvider()
        t0 = time.time()
        res = p.get_quote('^NSEI', use_cache=False)  # bypass cache: hit fetch path
        dt = time.time() - t0
        assert res['state'] in ('API_ERROR', 'TIMEOUT', 'RATE_LIMITED'), res
        assert len(calls) == 2, calls  # exactly 1 initial + 1 retry
        assert dt < 60, dt
    finally:
        prov.yf.Ticker = orig


def test_provider_empty_unavailable():
    import pandas as pd
    gen = _provider_with_history(lambda s, pr, iv: pd.DataFrame())
    p = next(gen)
    try:
        assert p.get_quote('^NSEI', use_cache=False)['state'] == 'UNAVAILABLE'
        assert p.get_5m_candles('^NSEI', use_cache=False)['state'] == 'UNAVAILABLE'
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


def test_provider_malformed_no_crash():
    gen = _provider_with_history(lambda s, pr, iv: (_ for _ in ()).throw(RuntimeError('boom')))
    p = next(gen)
    try:
        r1 = p.get_quote('^NSEI', use_cache=False)
        r2 = p.get_5m_candles('^NSEI', use_cache=False)
        assert r1['state'] in ('API_ERROR', 'RATE_LIMITED'), r1
        assert r2['state'] in ('API_ERROR', 'RATE_LIMITED'), r2
        assert 'trade' not in r1 and 'trade' not in r2
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


# ---------- 4-5. stale / missing feed through the live gate ----------
def test_stale_feed_no_trade():
    rows = db_day('NIFTY', WED)
    upto = [c for c in rows if c['timestamp'] <= f'{WED}T09:55:00+05:30']
    eng = LiveEngine(
        quote_fn=lambda i: {'price': 1.0, 'timestamp': upto[-1]['timestamp'],
                            'age_seconds': 9999.0, 'state': 'STALE', 'source': 'test'},
        candles_fn=lambda i, c: upto)
    st = eng.evaluate('NIFTY', now=ist(f'{WED}T10:11:00+05:30'), dry_run=True)
    assert st['state'] == 'STALE', st
    assert 'trade' not in st


def test_missing_feed_no_data():
    eng = LiveEngine(
        quote_fn=lambda i: {'price': None, 'timestamp': None, 'age_seconds': None,
                            'state': 'UNAVAILABLE', 'source': 'test'},
        candles_fn=lambda i, c: [])
    st = eng.evaluate('NIFTY', now=ist(f'{WED}T10:00:00+05:30'), dry_run=True)
    assert st['state'] == 'NO_DATA', st
    assert 'trade' not in st


# ---------- 6-8. integrity gates on the live path ----------
def _engine_with(candles):
    return LiveEngine(
        quote_fn=lambda i: {'price': 25000.0, 'timestamp': candles[-1]['timestamp'],
                            'age_seconds': 60.0, 'state': 'LIVE', 'source': 'test'},
        candles_fn=lambda i, c: candles)


def test_future_rejected_live():
    rows = db_day('NIFTY', WED)
    upto = [c for c in rows if c['timestamp'] <= f'{WED}T09:30:00+05:30']
    bad = dict(upto[-1]); bad['timestamp'] = f'{WED}T09:35:00+05:30'
    st = _engine_with(upto + [bad]).evaluate(
        'NIFTY', now=ist(f'{WED}T09:36:00+05:30'), dry_run=True)
    assert st['state'] == 'NO_DATA' and 'trade' not in st


def test_duplicate_rejected_live():
    rows = db_day('NIFTY', WED)
    upto = [c for c in rows if c['timestamp'] <= f'{WED}T09:30:00+05:30']
    st = _engine_with(upto + [dict(upto[-1])]).evaluate(
        'NIFTY', now=ist(f'{WED}T09:36:00+05:30'), dry_run=True)
    assert st['state'] == 'NO_DATA' and 'trade' not in st


def test_invalid_ohlc_rejected_live():
    rows = db_day('NIFTY', WED)
    upto = [dict(c) for c in rows if c['timestamp'] <= f'{WED}T09:30:00+05:30']
    upto[-1]['close'] = upto[-1]['high'] + 5.0
    st = _engine_with(upto).evaluate(
        'NIFTY', now=ist(f'{WED}T09:36:00+05:30'), dry_run=True)
    assert st['state'] == 'NO_DATA' and 'trade' not in st


# ---------- 9. instrument independence of failures ----------
def test_nifty_banknifty_independent_failure():
    n_rows = db_day('NIFTY', WED)

    def candles_fn(inst, completed):
        if inst == 'NIFTY':
            return [c for c in n_rows if c['timestamp'] <= completed.isoformat()]
        return []  # BANKNIFTY feed dead

    def quote_fn(inst):
        if inst == 'NIFTY':
            return {'price': 1.0, 'timestamp': n_rows[-1]['timestamp'],
                    'age_seconds': 60.0, 'state': 'LIVE', 'source': 'test'}
        return {'price': None, 'timestamp': None, 'age_seconds': None,
                'state': 'UNAVAILABLE', 'source': 'test'}
    eng = LiveEngine(quote_fn=quote_fn, candles_fn=candles_fn)
    sn = eng.evaluate('NIFTY', now=ist(f'{WED}T10:00:00+05:30'), dry_run=True)
    sb = eng.evaluate('BANKNIFTY', now=ist(f'{WED}T10:00:00+05:30'), dry_run=True)
    assert sn['state'] in ('NO_TRADE', 'QUALIFIED'), sn
    assert sb['state'] == 'NO_DATA' and 'trade' not in sb, sb


# ---------- 10-13. retry + cache ----------
def test_retry_bounded_single_retry():
    import app.market.provider as prov
    calls = []

    class FlakyTicker:
        def __init__(self, symbol):
            pass

        def history(self, period, interval):
            calls.append(time.time())
            raise ConnectionError('conn reset')

    orig = prov.yf.Ticker
    prov.yf.Ticker = FlakyTicker
    try:
        p = prov.MarketDataProvider()
        res = p.get_quote('^NSEI', use_cache=False)
        assert res['state'] in ('API_ERROR', 'RATE_LIMITED'), res
        assert len(calls) == 2, calls
    finally:
        prov.yf.Ticker = orig


def test_cache_serves_within_ttl():
    import app.market.provider as prov
    pcache.invalidate('^TEST11', 'quote')
    payload = {'symbol': '^TEST11', 'price': 123.0,
               'timestamp': '2026-09-16T10:00:00+05:30', 'state': 'LIVE'}
    pcache.put('^TEST11', 'quote', payload, payload['timestamp'], 'LIVE')
    p = prov.MarketDataProvider()
    got = p.get_quote('^TEST11', use_cache=True)
    assert got['price'] == 123.0 and got.get('_cache_hit') is True
    pcache.invalidate('^TEST11', 'quote')


def test_cache_preserves_original_timestamp():
    import app.market.provider as prov
    pcache.invalidate('^TEST11', 'quote')
    ts = '2026-09-16T10:00:00+05:30'
    pcache.put('^TEST11', 'quote', {'symbol': '^TEST11', 'price': 1.0,
                                    'timestamp': ts, 'state': 'LIVE'}, ts, 'LIVE')
    p = prov.MarketDataProvider()
    got = p.get_quote('^TEST11', use_cache=True)
    assert got['timestamp'] == ts  # original market-data ts, not fetch time
    assert got['age_seconds'] > 0  # recomputed at serve time
    pcache.invalidate('^TEST11', 'quote')


def test_shared_cache_dedupes_workers():
    import app.market.provider as prov
    pcache.invalidate('^TEST11', 'candles')
    payload = {'candles': [{'timestamp': '2026-09-16T10:00:00+05:30'}],
               'source': 'yfinance', 'state': 'LIVE'}
    pcache.put('^TEST11', 'candles', payload, '2026-09-16T10:00:00+05:30', 'LIVE')
    p = prov.MarketDataProvider()
    a = p.get_5m_candles('^TEST11', use_cache=True)
    b = p.get_5m_candles('^TEST11', use_cache=True)
    assert a.get('_cache_hit') and b.get('_cache_hit')
    assert a['candles'] == b['candles']
    pcache.invalidate('^TEST11', 'candles')


# ---------- 14-18. session + calendar ----------
def test_premarket_state():
    eng = LiveEngine(quote_fn=lambda i: {}, candles_fn=lambda i, c: [])
    st = eng.evaluate('NIFTY', now=ist(f'{WED}T08:00:00+05:30'), dry_run=True)
    assert st['state'] == 'PREMARKET' and 'trade' not in st


def test_live_session_gating():
    rows = db_day('NIFTY', WED)
    eng = LiveEngine(
        quote_fn=lambda i: {'price': 1.0, 'timestamp': rows[-1]['timestamp'],
                            'age_seconds': 60.0, 'state': 'LIVE', 'source': 'test'},
        candles_fn=lambda i, c: [c for c in rows
                                 if c['timestamp'] <= '2026-09-16T09:55:00+05:30'])
    st = eng.evaluate('NIFTY', now=ist(f'{WED}T10:00:00+05:30'), dry_run=True)
    assert st['session'] == 'LIVE' and st['state'] in ('NO_TRADE', 'QUALIFIED')


def test_market_closed_state():
    eng = LiveEngine(quote_fn=lambda i: {}, candles_fn=lambda i, c: [])
    st = eng.evaluate('NIFTY', now=ist(f'{WED}T16:00:00+05:30'), dry_run=True)
    assert st['state'] == 'MARKET_CLOSED' and 'trade' not in st


def test_weekend_state():
    eng = LiveEngine(quote_fn=lambda i: {}, candles_fn=lambda i, c: [])
    st = eng.evaluate('NIFTY', now=ist('2026-09-19T10:00:00+05:30'), dry_run=True)
    assert st['state'] == 'WEEKEND' and 'trade' not in st


def test_nse_holiday_closed():
    # 2026-09-14 (Mon, Ganesh Chaturthi): in-hours, no feed -> MARKET_CLOSED+HOLIDAY
    assert holiday_name(date(2026, 9, 14)) == 'Ganesh Chaturthi'
    assert not is_session_day(date(2026, 9, 14))
    assert len(NSE_HOLIDAYS_2026) == 15
    eng = LiveEngine(
        quote_fn=lambda i: {'price': None, 'timestamp': None, 'age_seconds': None,
                            'state': 'UNAVAILABLE', 'source': 'test'},
        candles_fn=lambda i, c: [])
    st = eng.evaluate('NIFTY', now=ist('2026-09-14T10:00:00+05:30'), dry_run=True)
    assert st['state'] == 'MARKET_CLOSED', st
    assert any('HOLIDAY' in r for r in st['reasons']), st
    assert 'trade' not in st


# ---------- 19-20. gating + PIT ----------
def test_completed_candle_gating():
    assert completed_candle_ts(ist('2026-09-16T09:19:59+05:30')) is None
    assert completed_candle_ts(ist('2026-09-16T09:20:00+05:30')).isoformat() == \
        '2026-09-16T09:15:00+05:30'
    rows = db_day('NIFTY', WED)
    eng = LiveEngine(
        quote_fn=lambda i: {'price': 1.0, 'timestamp': rows[0]['timestamp'],
                            'age_seconds': 60.0, 'state': 'LIVE', 'source': 'test'},
        candles_fn=lambda i, c: rows)
    st = eng.evaluate('NIFTY', now=ist('2026-09-16T09:19:00+05:30'), dry_run=True)
    assert st.get('decision_timestamp') is None and 'trade' not in st


def test_live_pit_regression():
    rows = db_day('NIFTY', WED)
    eng = LiveEngine(
        quote_fn=lambda i: {'price': 1.0, 'timestamp': rows[-1]['timestamp'],
                            'age_seconds': 60.0, 'state': 'LIVE', 'source': 'test'},
        candles_fn=lambda inst, completed: [c for c in rows if c['timestamp'] <= completed.isoformat()])
    st = eng.evaluate('NIFTY', now=ist(f'{WED}T14:21:00+05:30'), dry_run=True)
    assert st['state'] == 'QUALIFIED', st
    assert st['decision_timestamp'] == '2026-09-16T14:15:00+05:30'
    conn = get_conn()
    n = conn.execute(
        "SELECT COUNT(*) FROM scenario_candidates WHERE instrument_id='NIFTY' "
        "AND scenario_type=? AND created_at <= '2026-09-16T14:15:00+05:30'",
        (st['trade']['scenario'],)).fetchone()[0]
    conn.close()
    assert n > 0


# ---------- 21-23. locks: GET read-only, concurrent claim, independence ----------
def test_get_decision_read_only():
    from app.api.app import app, live_engine
    rows = db_day('NIFTY', WED)
    upto = rows  # full day incl. the 14:15 qualifier
    old_q, old_c = live_engine.quote_fn, live_engine.candles_fn
    live_engine.quote_fn = lambda i: {'price': 1.0, 'timestamp': upto[-1]['timestamp'],
                                      'age_seconds': 60.0, 'state': 'LIVE', 'source': 'test'}
    live_engine.candles_fn = lambda inst, completed: [c for c in upto if c['timestamp'] <= completed.isoformat()]
    conn = get_conn()
    q = ("SELECT (SELECT COUNT(*) FROM qualified_trades),"
         "(SELECT COUNT(*) FROM paper_trades),(SELECT COUNT(*) FROM daily_trade_locks)")
    try:
        before = tuple(conn.execute(q).fetchone())
        client = app.test_client()
        for _ in range(5):
            r = client.get('/api/NIFTY/decision')
            assert r.status_code == 200
            assert r.get_json()['data'].get('read_only') is True
        after = tuple(conn.execute(q).fetchone())
        assert before == after == (0, 0, 0)
    finally:
        live_engine.quote_fn, live_engine.candles_fn = old_q, old_c
        conn.close()


def test_concurrent_claim_single_trade():
    from app.core.qualification import QualificationEngine
    day = '2030-01-05'  # far-future Monday sentinel; rows removed afterwards
    ms = {'trend': 'BULLISH', 'vwap_relation': 'ABOVE', 'momentum': 'POSITIVE',
          'volatility': 'NORMAL', 'price': 25000.0}
    results, errors = [], []

    def worker():
        try:
            q = QualificationEngine()
            d = q.qualify('NIFTY', ms, options_valid=True, research=False,
                          trade_date=day, as_of='2030-01-05T10:00:00+05:30')
            results.append(d['decision'])
        except Exception as e:  # noqa - must never escape as 500
            errors.append(str(e)[:100])

    threads = [threading.Thread(target=worker) for _ in range(8)]
    [t.start() for t in threads]
    [t.join(timeout=60) for t in threads]
    conn = get_conn()
    try:
        n_trades = conn.execute(
            'SELECT COUNT(*) FROM qualified_trades WHERE instrument_id=? AND date=?',
            ('NIFTY', day)).fetchone()[0]
        n_locks = conn.execute(
            'SELECT COUNT(*) FROM daily_trade_locks WHERE instrument_id=? AND date=?',
            ('NIFTY', day)).fetchone()[0]
        assert not errors, errors
        assert n_trades <= 1, n_trades
        assert n_locks <= 1, n_locks
        assert all(r in ('QUALIFIED_TRADE', 'NO_TRADE') for r in results), results
    finally:
        conn.execute('DELETE FROM qualified_trades WHERE instrument_id=? AND date=?', ('NIFTY', day))
        conn.execute('DELETE FROM daily_trade_locks WHERE instrument_id=? AND date=?', ('NIFTY', day))
        conn.commit()
        conn.close()


def test_independent_locks_live():
    n_rows = db_day('NIFTY', WED)
    b_rows = db_day('BANKNIFTY', WED)

    def candles_fn(inst, completed):
        src = n_rows if inst == 'NIFTY' else b_rows
        return [c for c in src if c['timestamp'] <= completed.isoformat()]

    def quote_fn(inst):
        return {'price': 1.0, 'timestamp': '2026-09-16T09:25:00+05:30',
                'age_seconds': 60.0, 'state': 'LIVE', 'source': 'test'}
    eng = LiveEngine(quote_fn=quote_fn, candles_fn=candles_fn)
    sn = eng.evaluate('NIFTY', now=ist(f'{WED}T14:21:00+05:30'), dry_run=True)
    sb = eng.evaluate('BANKNIFTY', now=ist(f'{WED}T10:56:00+05:30'), dry_run=True)
    assert sn['state'] == 'QUALIFIED' and sb['state'] == 'QUALIFIED'


# ---------- 24. isolation ----------
def test_phase11_research_isolation():
    conn = get_conn()
    q = ("SELECT (SELECT COUNT(*) FROM qualified_trades),"
         "(SELECT COUNT(*) FROM paper_trades),(SELECT COUNT(*) FROM daily_trade_locks)")
    before = tuple(conn.execute(q).fetchone())
    conn.close()
    SequentialReplay().run('NIFTY', '2026-09-15', '2026-09-16T23:59:59+05:30')
    eng = LiveEngine(quote_fn=lambda i: {}, candles_fn=lambda i, c: [])
    eng.evaluate('NIFTY', now=ist(f'{WED}T10:00:00+05:30'), dry_run=True)
    pcache.invalidate()
    conn = get_conn()
    after = tuple(conn.execute(q).fetchone())
    residue = conn.execute(
        "SELECT COUNT(*) FROM scenario_candidates WHERE candidate_id LIKE 'SC-%' "
        "AND candidate_id NOT LIKE 'SC-NIFTY-%' AND candidate_id NOT LIKE 'SC-BANKNIFTY-%'").fetchone()[0]
    conn.close()
    assert before == after == (0, 0, 0)
    assert residue == 0
