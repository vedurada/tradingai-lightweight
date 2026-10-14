"""Unit tests for the CPR + gap 09:45 walk-forward engine.

DB-independent: exercises the pure decision helpers (_choose_trade strike
geometry, touch/win classification, by-setup aggregation) and the summary
shape of run_walkforward against stored 5m candles (read-only).

Validated reference (LEVEL_RESEARCH_REPORT.md, vm5m_* exports): 44 trades,
41 touch wins (93.2%), 43 15:15-exit wins (97.7%). Points are the EXACT
index move per directional leg (bull: exit-entry, bear: entry-exit, iron
condor: -|exit-entry|), which over the full range sums to -1380.7 pts.
"""
import sys
sys.path.insert(0, '/opt/tradingai')

from dataclasses import dataclass

from app.research.cpr_gap_walkforward_engine import (
    run_walkforward, Config, _choose_trade, _round_down, _round_up)


def row(close=24000, first30_open=23950, first30_close=24010, first30_low=23940,
        first30_high=24020, open_=24050, prev_close=23900, prev_low=23850,
        prev_high=24100, bc=23970, tc=24030, exit_price=24015,
        post_entry_high=24040, post_entry_low=23930):
    return {
        'first30_open': first30_open, 'first30_close': first30_close,
        'first30_low': first30_low, 'first30_high': first30_high,
        'open': open_, 'prev_close': prev_close, 'prev_low': prev_low,
        'prev_high': prev_high, 'bc': bc, 'tc': tc, 'exit_price': exit_price,
        'post_entry_high': post_entry_high, 'post_entry_low': post_entry_low,
        'entry_price': first30_close,
    }


def test_rounding():
    assert _round_down(24001) == 24000
    assert _round_up(24001) == 24050
    assert _round_down(23999) == 23950


def test_large_gap_up_picks_bull_put():
    r = row(first30_close=24100, first30_open=23950, first30_low=24060,
            open_=24200, prev_close=23800, bc=23880, tc=23960)
    t = _choose_trade(r, 'normal', 'gap_up', Config())
    assert t['setup'] == 'A_BULL_PUT' and t['signal'] == 'BULL_PUT_CREDIT_SPREAD'
    assert t['short_put'] < r['first30_low']  # cushion below reference
    assert t['short_put'] - t['long_put'] == 100


def test_large_gap_down_picks_bear_call():
    r = row(first30_close=23600, first30_open=23750, first30_high=23590,
            open_=23400, prev_close=23800, bc=23820, tc=23900)
    t = _choose_trade(r, 'normal', 'gap_down', Config())
    assert t['setup'] == 'A_BEAR_CALL' and t['signal'] == 'BEAR_CALL_CREDIT_SPREAD'
    assert t['short_call'] > r['first30_high']  # cushion above reference
    assert t['long_call'] - t['short_call'] == 100


def test_above_cpr_green_picks_bull_put():
    r = row(close=24050, first30_close=24040, first30_open=23990, bc=23800, tc=23900)
    t = _choose_trade(r, 'normal', 'flat', Config())
    assert t['setup'] == 'B_BULL_PUT' and t['direction'] == 'BULL'


def test_below_cpr_red_picks_bear_call():
    r = row(close=23700, first30_close=23690, first30_open=23740, bc=23840, tc=23960)
    t = _choose_trade(r, 'normal', 'flat', Config())
    assert t['setup'] == 'B_BEAR_CALL' and t['direction'] == 'BEAR'


def test_inside_cpr_defaults_to_iron_condor():
    r = row(first30_close=24000, bc=23970, tc=24030)
    t = _choose_trade(r, 'normal', 'flat', Config())
    assert t['setup'] == 'C_INSIDE_CPR_IC' and t['signal'] == 'IRON_CONDOR'
    assert t['short_call'] > t['short_put']
    assert t['short_put'] - t['long_put'] == 100
    assert t['long_call'] - t['short_call'] == 100


def test_wide_cpr_reduces_to_condor():
    # Above TC but red first 30m, wide CPR -> wide iron condor (not B_BULL_PUT).
    r = row(first30_close=24130, first30_open=24150, first30_low=24110,
            first30_high=24180, bc=23900, tc=24120, prev_low=23850, prev_high=24200)
    t = _choose_trade(r, 'wide', 'flat', Config())
    assert t['setup'] == 'C_WIDE_CPR_IC'


def test_run_walkforward_reproduces_validated_totals():
    r = run_walkforward('NIFTY')
    assert 'error' not in r
    assert r['signals'] == 44
    assert r['wins'] == 41
    assert r['exit_price_wins'] == 43
    assert r['total_points'] == -1380.7
    assert r['avg_points'] == -31.38
    assert r['win_rate'] == 93.2
    assert r['exit_price_win_rate'] == 97.7
    trades = [t for t in r['trades'] if t['signal'] != 'NO_TRADE']
    assert len(trades) == 44
    assert trades[0]['trade_date'].startswith('2026-08-04')


def test_run_walkforward_unknown_instrument():
    assert run_walkforward('BANKNIFTY')['error'] == 'UNKNOWN_INSTRUMENT'
    assert run_walkforward('NIFTY', '2030-01-01', '2030-12-31')['signals'] == 0


def test_run_walkforward_subrange_matches_local():
    # 08-12..10-06: 38 trades / 35 touch / 37 exit wins; exact index move
    # sums to -1392.4 pts over that window.
    r = run_walkforward('NIFTY', '2026-08-12', '2026-10-06')
    assert r['signals'] == 38
    assert r['wins'] == 35
    assert r['exit_price_wins'] == 37
    assert r['total_points'] == -1392.4