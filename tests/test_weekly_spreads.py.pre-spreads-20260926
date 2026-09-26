"""Unit tests: weekly spreads grid/expiry/payoff + NSE fetcher failure shape."""
import sys
sys.path.insert(0, '/opt/tradingai')

from datetime import date
from app.options.weekly_spreads import (
    next_expiry, build_spread, spread_points_at_expiry, max_outcome)
from app.options import nse_chain


def test_nifty_weekly_tuesday():
    assert next_expiry('NIFTY', date(2026, 9, 26)) == '2026-09-29'
    assert next_expiry('NIFTY', date(2026, 9, 29)) == '2026-10-06'


def test_banknifty_last_tuesday():
    assert next_expiry('BANKNIFTY', date(2026, 9, 26)) == '2026-09-29'
    assert next_expiry('BANKNIFTY', date(2026, 9, 30)) == '2026-10-27'


def test_bear_spread_above_spot():
    s = build_spread('NIFTY', 'BEAR', 23140.5)
    assert s['strategy'] == 'Bear Call Spread'
    assert s['legs'] == [{'side': 'SELL', 'type': 'CE', 'strike': 23150.0},
                         {'side': 'BUY', 'type': 'CE', 'strike': 23350.0}]
    assert s['lot'] == 65 and s['width'] == 200.0


def test_bull_spread_below_spot():
    s = build_spread('BANKNIFTY', 'BULL', 55580.4)
    assert s['legs'] == [{'side': 'SELL', 'type': 'PE', 'strike': 55500.0},
                         {'side': 'BUY', 'type': 'PE', 'strike': 55100.0}]
    assert s['lot'] == 30 and s['width'] == 400.0


def test_spread_bad_inputs():
    assert build_spread('SENSEX', 'BEAR', 100)['error'] == 'UNKNOWN_INSTRUMENT'
    assert build_spread('NIFTY', 'SIDEWAYS', 100)['error'] == 'UNKNOWN_DIRECTION'
    assert build_spread('NIFTY', 'BEAR', None)['error'] == 'BAD_SPOT'


def test_payoff_math():
    s = build_spread('NIFTY', 'BEAR', 23140.5)
    assert spread_points_at_expiry(s, 23150.0) == 0.0
    assert spread_points_at_expiry(s, 23400.0) == -200.0
    assert spread_points_at_expiry(s, 23000.0) == 0.0
    m = max_outcome(s, 40.0)
    assert m == {'max_profit_pts': 40.0, 'max_loss_pts': -160.0,
                 'breakeven': 23190.0, 'note': 'with live credit'}
    m2 = max_outcome(s, None)
    assert m2['max_profit_pts'] is None and m2['breakeven'] is None


def test_nse_unknown_instrument_no_network():
    state, payload = nse_chain.fetch_chain('SENSEX')
    assert state == 'UNAVAILABLE'
    assert payload['reason'] == 'UNKNOWN_INSTRUMENT'
    assert nse_chain.get_credit('SENSEX', []) is None
