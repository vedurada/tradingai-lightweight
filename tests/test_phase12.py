"""Phase 12 tests: trader-facing NIFTY/BANKNIFTY product UI (20 items).

Static + API-level tests (no browser needed): page contracts, instrument
isolation, read-only behavior, state coverage, no-fabrication guards,
completed-candle display contract, freshness display, independence.
Full regression (suite + baselines) runs separately in the Phase 12 pass.
"""
import sys, re
sys.path.insert(0, '/opt/tradingai_new')

SRC = '/opt/tradingai_new/frontend/indices/'
PAGES = {'NIFTY': 'nifty.html', 'BANKNIFTY': 'banknifty.html'}


def page(sym):
    return open(SRC + PAGES[sym]).read()


def js(sym):
    return re.findall(r'<script>(.*?)</script>', page(sym), re.S)[0]


def test_nifty_page_loads():
    h = page('NIFTY')
    assert 'NIFTY' in h and 'id="decision-state"' in h and 'id="price"' in h


def test_banknifty_page_loads():
    h = page('BANKNIFTY')
    assert 'BANKNIFTY' in h and 'id="decision-state"' in h and 'id="price"' in h


def test_pages_use_own_instrument():
    assert 'var SYM = "NIFTY"' in js('NIFTY')
    assert 'var SYM = "BANKNIFTY"' in js('BANKNIFTY')


def test_no_cross_instrument_substitution():
    # nav text legitimately links both pages; isolation means: JS fetches only
    # the page's own instrument and decision rendering uses only SYM data.
    assert 'BANKNIFTY' not in js('NIFTY')
    assert re.search(r'\bNIFTY\b', js('BANKNIFTY')) is None
    assert '/api/" + SYM +' in js('NIFTY')  # all API calls derive from SYM


def test_get_decision_read_only_flag():
    from app.api.app import app
    for sym in ('NIFTY', 'BANKNIFTY'):
        r = app.test_client().get(f'/api/{sym}/decision')
        assert r.status_code == 200
        assert r.get_json()['data'].get('read_only') is True


def test_frontend_never_claims():
    for sym in ('NIFTY', 'BANKNIFTY'):
        low = js(sym).lower()
        assert 'decision/claim' not in low
        assert 'post' not in low  # no POST anywhere in page JS


def test_all_states_rendered():
    for sym in ('NIFTY', 'BANKNIFTY'):
        j = js(sym)
        for state in ('QUALIFIED', 'NO_TRADE', 'PREMARKET', 'MARKET_CLOSED',
                      'WEEKEND', 'STALE', 'NO_DATA', 'RATE_LIMITED', 'UNAVAILABLE'):
            assert state in j, (sym, state)


def test_no_data_not_collapsed_to_loading():
    for sym in ('NIFTY', 'BANKNIFTY'):
        j = js(sym)
        assert 'NO DATA' in j or 'NO_DATA' in j


def test_no_trade_first_class():
    for sym in ('NIFTY', 'BANKNIFTY'):
        j = js(sym)
        assert 'NO TRADE' in j and 'decision-reason' in j


def test_qualified_requires_backend_trade():
    for sym in ('NIFTY', 'BANKNIFTY'):
        assert 'd.state === "QUALIFIED" && s.trade' in js(sym), sym


def test_no_fabricated_option_legs():
    for sym in ('NIFTY', 'BANKNIFTY'):
        low = js(sym).lower().replace('range_premium_decay', '')
        for bad in ('strike', 'premium', 'expiry', '"ce"', '"pe"', ' ce ', ' pe ',
                    'decision/claim'):
            assert bad not in low, (sym, bad)
        assert 'Options data unavailable' in page(sym)


def test_forming_candle_never_completed():
    from app.api.app import app
    import app.api.app as appmod
    orig = appmod.market.get_5m_candles
    candles = [{'timestamp': f'2026-09-16T09:{m:02d}:00+05:30', 'open': 1, 'high': 2,
                'low': 1, 'close': 1.5, 'volume': 10, 'is_complete': i < 3}
               for i, m in enumerate((15, 20, 25, 30))]
    appmod.market.get_5m_candles = lambda symbol, periods=100, use_cache=True: {
        'candles': candles, 'source': 'yfinance', 'state': 'LIVE'}
    try:
        r = appmod.app.test_client().get('/api/NIFTY/candles?n=12')
        body = r.get_json()
        assert r.status_code == 200
        assert body['data'].get('forming_excluded') is True
        for c in body['data']['candles']:
            assert c['timestamp'] <= body['data']['completed_candle'], c
            assert c['is_complete'] is True
    finally:
        appmod.market.get_5m_candles = orig


def test_data_age_displayed():
    for sym in ('NIFTY', 'BANKNIFTY'):
        h = page(sym)
        for el in ('price-meta', 'decision-meta', 'chip-fresh', 'chip-session'):
            assert f'id="{el}"' in h, (sym, el)
        assert 'quote_age_seconds' in js(sym) and 'completed_age_minutes' in js(sym)


def test_price_blink_guarded_by_freshness():
    for sym in ('NIFTY', 'BANKNIFTY'):
        j = js(sym)
        assert 'prevQuoteTs' in j and 'prevPrice' in j
        assert 'quote_state' in j and 'flash' in j
        # blink only when the authoritative quote actually changed AND is fresh
        assert 'p !== prevPrice' in j and 'quote_timestamp !== prevQuoteTs' in j


def test_nifty_banknifty_apis_independent():
    from app.api.app import app
    client = app.test_client()
    a = client.get('/api/NIFTY/summary').get_json()
    b = client.get('/api/BANKNIFTY/summary').get_json()
    assert a['data']['instrument'] == 'NIFTY'
    assert b['data']['instrument'] == 'BANKNIFTY'


def test_mobile_viewport_and_layout():
    for sym in ('NIFTY', 'BANKNIFTY'):
        h = page(sym)
        assert 'name="viewport"' in h
        assert '@media' in h  # responsive breakpoint present
        assert 'max-width:960px' in h or 'max-width' in h


def test_nav_mutually_reachable():
    import os
    base = '/opt/tradingai_new/frontend'
    for sym in ('NIFTY', 'BANKNIFTY'):
        for link in ('/', '/indices/nifty.html', '/indices/banknifty.html', '/backtest.html'):
            assert link in page(sym), (sym, link)
            target = base + (link if link != '/' else '/index.html')
            assert os.path.exists(target), target


def test_no_business_logic_in_js():
    for sym in ('NIFTY', 'BANKNIFTY'):
        j = js(sym).lower()
        for bad in ('0.995', '0.99', '1.02', 'get_scenario', 'qualify(',
                    'risk_reward', 'target_price', 'stop_price'):
            assert bad not in j, (sym, bad)
