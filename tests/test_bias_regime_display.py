"""Current bias / Market regime display fallback (owner-approved 2026-10-07).

With no active trade and no CONFIRMED scenario both cells used to read
UNAVAILABLE for the whole session. The fallback composes the SAME PIT
market_state the live engine already computed:

  bias   <- market_state.trend            (session trend)
  regime <- volatility HIGH -> VOLATILE, else TRENDING/RANGING from
           trend vs momentum agreement    (session character)

Read-only assertions against /api/<instrument>/decision. No DB writes.
"""
from app.api.app import app

client = app.test_client()

BIAS_OK = {'BULLISH', 'BULL', 'BEARISH', 'BEAR', 'NEUTRAL', 'UNAVAILABLE'}
REGIME_OK = {'TRENDING', 'RANGING', 'VOLATILE', 'UNAVAILABLE', 'ABOVE_CPR',
             'BREAKOUT', 'BULLISH_CONTINUATION', 'BEARISH_CONTINUATION',
             'BREAKOUT_FAILURE_REVERSAL', 'RANGE_PREMIUM_DECAY'}


def _decision(instrument='NIFTY'):
    r = client.get(f'/api/{instrument}/decision')
    assert r.status_code == 200
    return r.get_json()['data']


def test_bias_and_regime_vocabulary_never_fabricated():
    for inst in ('NIFTY', 'BANKNIFTY'):
        d = _decision(inst)
        # an engine no-data/error state may omit the composed fields entirely;
        # the page renders that as "Data temporarily unavailable"
        b = d.get('market_bias') or 'UNAVAILABLE'
        r = d.get('market_regime') or 'UNAVAILABLE'
        assert b in BIAS_OK, b
        assert r in REGIME_OK, r


def test_live_session_with_engine_state_reports_both():
    d = _decision('NIFTY')
    if 'market_bias' not in d or 'market_regime' not in d:
        return  # engine returned no composed view; page says unavailable
    ms = d.get('market_state') or {}
    live = (d.get('session') == 'LIVE'
            and d.get('data_status') in ('LIVE', 'RECENT'))
    if not live:
        return  # outside the gate: the old UNAVAILABLE display is correct
    if ms.get('trend') in ('BULLISH', 'BEARISH', 'NEUTRAL'):
        assert d['market_bias'] == ms['trend'], (d['market_bias'], ms)
        assert 'BIAS_SESSION_TREND' in d['reason_codes']
    if ms.get('volatility') == 'HIGH':
        assert d['market_regime'] == 'VOLATILE'
    elif ms.get('trend') and ms.get('momentum'):
        agree = ((ms['trend'] == 'BULLISH' and ms['momentum'] == 'POSITIVE') or
                 (ms['trend'] == 'BEARISH' and ms['momentum'] == 'NEGATIVE'))
        assert d['market_regime'] == ('TRENDING' if agree else 'RANGING')
        assert 'REGIME_SESSION_TREND_MOMENTUM' in d['reason_codes']


def test_trade_direction_still_wins_over_fallback():
    """A live trade's direction/scenario must not be replaced by the fallback."""
    d = _decision('NIFTY')
    if 'market_bias' not in d or not (d.get('trade') and d['trade'].get('direction')):
        return
    assert d['market_bias'] == d['trade']['direction']
    assert 'BIAS_SESSION_TREND' not in d['reason_codes']


def test_dashboard_plan_cells_can_display_values():
    h = open('/opt/tradingai/frontend/nifty-intraday-dashboard.html').read()
    assert 'id="pBias"' in h and 'id="pRegime"' in h
    assert 'market-state engine' in h  # honest source label, no "RegimeEngine"
