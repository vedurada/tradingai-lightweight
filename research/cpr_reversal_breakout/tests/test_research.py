"""Unit tests for the CPR reversal/breakout research engine.

Covers: level math parity with production, boundary conditions, reversal
confirmation, breakout confirmation and failed-break handling, trade
duplication, entry-window limits, P&L reconciliation, exit-model parity,
determinism of the baseline, and an explicit no-look-ahead property test.
"""
import json
import os

import pytest

import common
import candidate as C
import metrics as M
import runner
from common import day_levels, exits_opens_abs, prev_session_ohlc, ro_conn

DAY = '2026-08-05'
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = json.load(open(os.path.join(ROOT, 'strategy_config.json')))


def ts(i, day=DAY, start=9 * 60 + 15):
    m = start + 5 * i
    return f'{day}T{m // 60:02d}:{m % 60:02d}:00+05:30'


def mk(i, o, h, l, c, day=DAY):
    return {'timestamp': ts(i, day), 'open': float(o), 'high': float(h),
            'low': float(l), 'close': float(c)}


def levels():
    return day_levels(25000, 24600, 24900)


def base_cfg(**over):
    """base_params + the global sections the runner needs (periods, costs)."""
    c = dict(CFG['base_params'])
    c['periods'] = CFG['periods']
    c['costs'] = CFG['costs']
    c.update(over)
    return c


def flat(n=75, price=25000, day=DAY):
    """n candles (09:15..) with a tight range below all resistance."""
    return [mk(i, price, price + 8, price - 8, price + 2, day)
            for i in range(n)]


# ---------------------------------------------------------------- levels
def test_level_math_matches_production():
    from app.research.cpr_trigger_engine import day_levels as prod_dl
    for h, l, c in ((25000, 24600, 24900), (24000, 24000, 24000),
                    (25500.25, 25100.5, 25300.75), (100, 90, 95)):
        assert day_levels(h, l, c) == prod_dl(h, l, c)


def test_cpr_tc_bc_ordering_and_values():
    # Production derives tc from the UNROUNDED pp/bc, then rounds each to 4dp.
    ph, pl, pc = 25000, 24600, 24900
    lv = day_levels(ph, pl, pc)
    pp_raw = (ph + pl + pc) / 3
    bc_raw = (ph + pl) / 2
    assert lv['pp'] == round(pp_raw, 4)
    assert lv['bc'] == round(bc_raw, 4)
    assert lv['tc'] == round(2 * pp_raw - bc_raw, 4)
    assert lv['tc'] >= lv['bc']              # stays ordered when inverted
    assert lv['r1'] == 2 * lv['pp'] - pl
    assert lv['s1'] == 2 * lv['pp'] - ph
    assert lv['r2'] == lv['pp'] + (ph - pl)
    assert lv['s2'] == lv['pp'] - (ph - pl)
    assert lv['pdh'] == 25000 and lv['pdl'] == 24600


def test_day_levels_none_safe():
    assert day_levels(None, 1, 1) is None
    assert day_levels(10, 20, 15) is None        # high < low
    assert day_levels(0, 0, 0) is None


def test_prev_session_ohlc_strictly_prior_and_matches_production():
    from app.research.cpr_trigger_engine import prev_session_ohlc as prod_pso
    conn = ro_conn()
    try:
        for inst in ('NIFTY', 'BANKNIFTY'):
            days = common.load_sessions(conn, inst, '2026-08-01', '2026-08-31')
            assert days, f'no sessions for {inst}'
            for d in days:
                a = prev_session_ohlc(conn, inst, d)
                assert a == prod_pso(conn, inst, d)
                if a:
                    assert a['date'] < d          # point-in-time: strictly prior
    finally:
        conn.close()


# ---------------------------------------------------- reversal confirmation
def test_bear_rejection_requires_all_conditions():
    r1 = levels()['r1']
    cfg = base_cfg()
    ok, ev = C.bear_rejects(mk(0, r1 - 20, r1 + 10, r1 - 40, r1 - 25), r1, cfg)
    assert ok and ev['close'] < r1 and ev['high'] >= r1
    # tests the level but CLOSES above it -> a break, not a rejection
    ok, ev = C.bear_rejects(mk(0, r1 - 5, r1 + 20, r1 - 10, r1 + 15), r1, cfg)
    assert not ok and ev.get('closed_above_level')
    # wick-only pierce that closes above
    ok, ev = C.bear_rejects(mk(0, r1 - 30, r1 + 40, r1 - 35, r1 + 5), r1, cfg)
    assert not ok and ev.get('closed_above_level')
    # bullish body -> not a bearish rejection
    ok, ev = C.bear_rejects(mk(0, r1 - 40, r1 + 10, r1 - 45, r1 - 10), r1, cfg)
    assert not ok and ev.get('not_bearish_body')
    # never touched the level
    ok, ev = C.bear_rejects(mk(0, 24900, 24950, 24890, 24920), r1, cfg)
    assert not ok and ev.get('tested') is False
    # insufficient upper shadow
    ok, ev = C.bear_rejects(mk(0, r1 - 1, r1 + 5, r1 - 60, r1 - 30), r1, cfg)
    assert not ok and 'upper_shadow_too_small' in ev


def test_bull_support_hold_and_breakdown_distinguished():
    s1 = levels()['s1']
    cfg = base_cfg()
    ok, ev = C.bull_holds(mk(0, s1 + 20, s1 + 40, s1 - 10, s1 + 35), s1, cfg)
    assert ok
    # close THROUGH the level = breakdown / failed reclaim, not a hold
    ok, ev = C.bull_holds(mk(0, s1 + 20, s1 + 30, s1 - 10, s1 - 5), s1, cfg)
    assert not ok and ev.get('closed_below_level')
    # bearish body at support -> not a bullish response
    ok, ev = C.bull_holds(mk(0, s1 + 40, s1 + 45, s1 - 5, s1 + 5), s1, cfg)
    assert not ok and ev.get('not_bullish_body')
    # never tested
    ok, ev = C.bull_holds(mk(0, s1 + 200, s1 + 210, s1 + 190, s1 + 205), s1, cfg)
    assert not ok and ev.get('tested') is False


def test_reversal_trigger_breaks_confirmation_extreme():
    conf = mk(5, 25050, 25080, 25030, 25040)
    candles = [mk(i, 25000, 25010, 24990, 25000) for i in range(5)]
    candles += [conf, mk(6, 25045, 25060, 25040, 25050)]   # holds above the low
    assert C._reversal_trigger(candles, 5, 'BEAR', base_cfg()) is None
    # wick-only break below the low (close back above): triggers by default,
    # suppressed when a closing break is required
    candles.append(mk(7, 25035, 25040, 25015, 25040))
    j, reason = C._reversal_trigger(candles, 5, 'BEAR', base_cfg())
    assert j == 7 and reason['confirm_low'] == 25030 and reason['close'] > 25030
    assert C._reversal_trigger(candles, 5, 'BEAR',
                               base_cfg(trigger_require_close=True)) is None
    candles[-1] = mk(7, 25035, 25040, 25015, 25018)        # closes below too
    j3, r3 = C._reversal_trigger(candles, 5, 'BEAR',
                                 base_cfg(trigger_require_close=True))
    assert j3 == 7 and r3['close'] <= 25030


def test_bull_trigger_breaks_confirmation_high():
    conf = mk(3, 24690, 24710, 24650, 24700)
    candles = [mk(i, 24700, 24710, 24690, 24700) for i in range(3)] + [conf]
    assert C._reversal_trigger(candles, 3, 'BULL', base_cfg()) is None
    candles.append(mk(4, 24705, 24715, 24700, 24710))      # high >= 24710
    j, r = C._reversal_trigger(candles, 3, 'BULL', base_cfg())
    assert j == 4 and r['confirm_high'] == 24710


# ---------------------------------------------------- breakout confirmation
def test_fresh_cross_never_fires_on_wick_only():
    r1, s1 = levels()['r1'], levels()['s1']
    assert C.fresh_cross(mk(1, r1 - 10, r1 + 30, r1 - 15, r1 + 20),
                         r1 - 5, r1, 'BULL')
    # wick beyond but close back below -> not a cross
    assert not C.fresh_cross(mk(1, r1 - 10, r1 + 30, r1 - 15, r1 - 5),
                             r1 - 5, r1, 'BULL')
    # already above yesterday -> not FRESH
    assert not C.fresh_cross(mk(1, r1 + 10, r1 + 30, r1 + 5, r1 + 20),
                             r1 + 5, r1, 'BULL')
    assert C.fresh_cross(mk(1, s1 + 10, s1 + 15, s1 - 20, s1 - 15),
                         s1 + 5, s1, 'BEAR')
    assert not C.fresh_cross(mk(1, s1 + 10, s1 + 15, s1 - 20, s1 + 5),
                             s1 + 5, s1, 'BEAR')


def test_failed_breakout_is_rejected_before_entry():
    """A cross followed by a close back through the level must not trade."""
    r1 = levels()['r1']
    candles = flat()
    candles[10] = mk(10, 25040, 25090, 25030, 25080)   # closes above r1 (25066.67)
    candles[11] = mk(11, 25075, 25085, 25020, 25040)   # close back below r1
    cfg = base_cfg(mode='breakout', breakout_sides=['UP'], follow_through=1)
    cands, counters = C.scan_session(candles, levels(), cfg)
    assert not cands
    assert counters['rejected_failed_break'] >= 1


def test_breakout_followthrough_entry_timing():
    r1 = levels()['r1']
    candles = flat()
    candles[10] = mk(10, 25040, 25090, 25030, 25080)   # close-cross of r1
    candles[11] = mk(11, 25085, 25100, 25075, 25095)   # follow-through close
    candles[12] = mk(12, 25095, 25110, 25090, 25100)
    cfg = base_cfg(mode='breakout', breakout_sides=['UP'], follow_through=1)
    cands, _ = C.scan_session(candles, levels(), cfg)
    assert len(cands) == 1
    c = cands[0]
    assert c.family == 'C_UP_R1' and c.direction == 'BULL'
    assert c.trigger_idx == 11
    assert c.entry_idx == 12
    assert c.entry == candles[12]['open']
    assert c.entry_time == candles[12]['timestamp']
    # every decision candle completes before the entry candle
    assert c.confirm_idx < c.trigger_idx < c.entry_idx


def test_breakout_retest_variant_waits_for_holding_pullback():
    r1 = levels()['r1']
    cfg = base_cfg(mode='breakout', breakout_sides=['UP'], require_retest=True)
    candles = flat()
    candles[10] = mk(10, 25040, 25090, 25030, 25080)   # close-cross
    candles[11] = mk(11, 25070, 25075, 25040, 25050)   # closes BELOW r1 -> fail
    cands, counters = C.scan_session(candles, levels(), cfg)
    assert not cands and counters['rejected_failed_break'] >= 1

    candles = flat()
    candles[10] = mk(10, 25040, 25090, 25030, 25080)   # close-cross
    candles[11] = mk(11, 25070, 25072, 25055, 25075)   # holds: close > r1
    candles[12] = mk(12, 25080, 25090, 25070, 25085)
    cands, _ = C.scan_session(candles, levels(), cfg)
    assert len(cands) == 1
    assert cands[0].trigger_idx == 11
    assert cands[0].entry_idx == 12
    assert cands[0].evidence['retest']['kind'] == 'retest_hold'


def test_breakout_reward_filter_counts_rejections():
    candles = flat()
    candles[10] = mk(10, 25040, 25090, 25030, 25080)
    candles[11] = mk(11, 25085, 25100, 25075, 25095)
    candles[12] = mk(12, 25100, 25110, 25090, 25100)
    cfg = base_cfg(mode='breakout', breakout_sides=['UP'], min_level_rr=1e9)
    cands, counters = C.scan_session(candles, levels(), cfg)
    assert not cands and counters['rejected_reward_filter'] >= 1


# ------------------------------------------------------------- entry window
def test_entry_window_boundaries():
    def ok_at(time_hhmm):
        m = int(time_hhmm[:2]) * 60 + int(time_hhmm[3:])
        stub = {'timestamp': '2026-08-05T'
                             f'{m // 60:02d}:{m % 60:02d}:00+05:30',
                'open': 1.0, 'high': 1.0, 'low': 1.0, 'close': 1.0}
        return C._entry_window_ok([mk(0, 1, 1, 1, 1), stub], 0)
    assert not ok_at('09:15')       # first candle open, before the window
    assert ok_at('09:20')           # window opens (inclusive)
    assert ok_at('15:15')           # last legal entry
    assert not ok_at('15:20')       # window is [09:20, 15:20)
    assert not ok_at('15:25')


def test_short_session_is_rejected():
    cands, counters = C.scan_session(flat(9), levels(), base_cfg())
    assert not cands and counters['rejected_short_day'] == 1


# ---------------------------------------------------------- selection rules
def test_one_trade_per_session_and_breakout_priority():
    lv = levels()
    counters = C.new_counters()
    b = C.Candidate(kind='BREAKOUT', family='C_UP_R1', direction='BULL',
                    level_name='R1', level=lv['r1'], confirm_idx=3,
                    trigger_idx=4, entry_idx=5, entry=25090, entry_time='x')
    r = C.Candidate(kind='REVERSAL', family='A1', direction='BEAR',
                    level_name='R1', level=lv['r1'], confirm_idx=2,
                    trigger_idx=3, entry_idx=4, entry=25080, entry_time='y')
    chosen = C.select_candidate([r, b], base_cfg(), counters)
    assert chosen is b and counters['duplicate_suppressed'] == 1


def test_conflicting_reversals_earliest_wins_and_reject_variant():
    lv = levels()
    bull = C.Candidate(kind='REVERSAL', family='B1', direction='BULL',
                       level_name='S1', level=lv['s1'], confirm_idx=1,
                       trigger_idx=2, entry_idx=3, entry=1, entry_time='a')
    bear = C.Candidate(kind='REVERSAL', family='A1', direction='BEAR',
                       level_name='R1', level=lv['r1'], confirm_idx=5,
                       trigger_idx=6, entry_idx=7, entry=1, entry_time='b')
    c1 = C.new_counters()
    assert C.select_candidate([bear, bull],
                              base_cfg(conflict_rule='earliest_wins'),
                              c1) is bull
    c2 = C.new_counters()
    assert C.select_candidate([bear, bull],
                              base_cfg(conflict_rule='reject'), c2) is None
    assert c2['rejected_conflict'] == 1
    # tie -> BEAR (production priority)
    bear.confirm_idx = bull.confirm_idx
    c3 = C.new_counters()
    assert C.select_candidate([bull, bear],
                              base_cfg(conflict_rule='earliest_wins'),
                              c3) is bear


def test_no_signal_records_no_trade():
    c = C.new_counters()
    assert C.select_candidate([], base_cfg(), c) is None and c['no_confirmation'] == 1


# ----------------------------------------------------------- exit mechanics
def test_exits_opens_abs_matches_production_exits_opens():
    from app.research.cpr_trigger_engine import exits_opens
    entry = 25000.0
    stop_pct, tgt_pct = 0.005, 0.02
    for direction in ('BULL', 'BEAR'):
        stop = entry * (1 - stop_pct) if direction == 'BULL' else entry * (1 + stop_pct)
        tgt = entry * (1 + tgt_pct) if direction == 'BULL' else entry * (1 - tgt_pct)
        drift = 20 if direction == 'BULL' else -20        # never resolves
        cases = [
            [(ts(i), entry + drift) for i in range(1, 6)],
            [(ts(i), entry - 100) for i in range(1, 6)],
            [(ts(i), entry + 100) for i in range(1, 6)],
            [(ts(i), entry) for i in range(1, 6)],
            [(ts(i), entry) for i in range(1, 3)] + [(ts(3), entry + 500)],
        ]
        for opens in cases:
            a = exits_opens(direction, entry, stop_pct, tgt_pct, opens)
            b = exits_opens_abs(direction, entry, stop, tgt, opens)
            assert (a is None) == (b is None), (direction, opens)
            if a is not None:
                assert a[1] == b[1] and a[2] == b[2], (direction, a, b)
                assert abs(a[0] - b[0]) < 1e-6


def test_stop_checked_before_target_on_same_open():
    entry = 25000.0
    stop, tgt = entry * 1.005, entry * 0.98
    opens = [(ts(1), entry * 1.01)]           # above the BEAR stop
    r, px, why, _ = exits_opens_abs('BEAR', entry, stop, tgt, opens)
    assert why == 'STOP' and r == -1.0


# ------------------------------------------------- baseline reproduction
def test_baseline_is_deterministic():
    from app.research.cpr_trigger_engine import run_opens_range
    a = run_opens_range('NIFTY', '2026-09-01', '2026-09-30', 'plain')
    b = run_opens_range('NIFTY', '2026-09-01', '2026-09-30', 'plain')
    assert a['signals'] == b['signals'] and a['total_R'] == b['total_R']
    assert [t['entry'] for t in a['trades']] == [t['entry'] for t in b['trades']]
    for k in ('wins', 'losses', 'win_rate', 'net_R', 'skipped'):
        assert a[k] == b[k]


def test_baseline_normalisation_round_trips_pnl():
    import baseline as bl
    res = bl.run_baseline('NIFTY', '2026-09-01', '2026-09-30', CFG)
    assert res['trades']
    for t in res['trades']:
        assert t['entry'] > 0 and t['risk_pts'] > 0
        pts = (t['exit'] - t['entry']) if t['direction'] == 'BULL' \
            else (t['entry'] - t['exit'])
        assert abs(t['points'] - pts) < 0.11      # both sides round to 2dp
        assert t['period'] == 'VAL'
        assert t['win_loss'] in ('WIN', 'LOSS', 'FLAT')
        assert t['signal_kind'] in ('REVERSAL', 'BREAKOUT')


# ------------------------------------------------------- integrated runner
@pytest.mark.parametrize('instrument', ['NIFTY', 'BANKNIFTY'])
def test_candidate_run_has_no_duplicates_and_valid_entries(instrument):
    vcfg = dict(base_cfg())
    vcfg.update(CFG['variants'][0]['overrides'])
    res = runner.run_and_label(instrument, '2026-09-01', '2026-09-30', vcfg,
                               db_path=os.environ['TRADINGAI_DB_PATH'],
                               variant_id='combined_parity')
    dates = [t['session_date'] for t in res['trades']]
    assert len(dates) == len(set(dates)), 'more than one trade in a session'
    for t in res['trades']:
        assert '09:20' <= t['entry_time'][11:16] < '15:20', t['entry_time']
        assert t['risk_pts'] > 0 and t['entry'] > 0
        assert t['entry_time'] > t['trigger_time']
        assert t['trigger_time'] >= t['signal_time']
        assert t['win_loss'] in ('WIN', 'LOSS', 'FLAT')
        assert t['period'] == 'VAL'


@pytest.mark.parametrize('instrument', ['NIFTY', 'BANKNIFTY'])
def test_baseline_run_entries_inside_window(instrument):
    import baseline as bl
    out = bl.run_baseline(instrument, '2026-09-01', '2026-09-30', CFG)
    assert out['trades']
    for t in out['trades']:
        assert '09:20' <= t['entry_time'][11:16] < '15:20', t['entry_time']


# ------------------------------------------------------------ reconciliation
def test_trade_pnl_reconciles_with_daily_and_totals():
    vcfg = dict(base_cfg())
    vcfg.update(CFG['variants'][0]['overrides'])
    res = runner.run_and_label('NIFTY', '2026-09-01', '2026-09-30', vcfg,
                               db_path=os.environ['TRADINGAI_DB_PATH'])
    assert res['trades'], 'expected at least one candidate trade'
    m = M.compute(res['trades'], sessions=None, capital_base=700000,
                  cost_r_grid=[0.0, 0.1])
    total = sum(float(t['pnl_net_rs']) for t in res['trades'])
    assert abs(m['net_pnl_rs'] - total) < 0.01
    assert abs(sum(d['net_rs'] for d in m['daily_pnl']) - total) < 0.01
    assert abs(m['total_R'] - sum(float(t['r_multiple'])
                                  for t in res['trades'])) < 0.01
    n = m['total_trades']
    assert m['winning_trades'] + m['losing_trades'] + m['breakeven_trades'] == n
    cost = float(res['trades'][0]['cost_rs'])
    assert abs(m['net_pnl_rs'] - (m['gross_pnl_rs'] - n * cost)) < 0.5


def test_wilson_and_drawdown_helpers():
    lo, hi = M.wilson_ci(10, 20)
    assert lo is not None and hi is not None and lo < 0.5 < hi
    dd, p, t, r, dur = M.max_drawdown([0, 10, 5, -5, 0, 20])
    assert dd == 15 and p == 1 and t == 3 and dur >= 1
    assert M.max_drawdown([]) == (0.0, None, None, None, 0)
    mean, lo, hi = M.block_bootstrap_expectancy([10.0] * 10 + [-10.0] * 10,
                                                n_boot=500, block=5)
    assert lo is not None and lo <= mean <= hi


# -------------------------------------------------------- no-look-ahead
def test_no_lookahead_property_synthetic():
    candles = flat()
    candles[20] = mk(20, 25050, 25075, 25030, 25040)   # rejects R1
    candles[21] = mk(21, 25035, 25045, 25010, 25020)   # breaks the low
    candles[22] = mk(22, 25020, 25030, 24980, 24990)
    cfg = base_cfg(mode='reversal')
    full, _ = C.scan_session(candles, levels(), cfg)
    assert full, 'synthetic session must produce at least one candidate'
    for k in range(1, len(candles) + 1):
        trunc, _ = C.scan_session(candles[:k], levels(), cfg)
        for a in trunc:
            # every candidate found on a prefix must be reproduced identically
            # in the full run: the signal cannot depend on later candles
            assert any(b.family == a.family and b.confirm_idx == a.confirm_idx
                       and b.trigger_idx == a.trigger_idx and b.entry == a.entry
                       for b in full), \
                f'prefix candidate {a.family}@{a.confirm_idx} not in full run'
        assert len(trunc) <= len(full)


def test_no_lookahead_property_real_session():
    conn = ro_conn()
    try:
        days = common.load_sessions(conn, 'NIFTY', '2026-09-01', '2026-09-15')
        candles_by_day = {d: common.load_candles(conn, 'NIFTY', d) for d in days}
        prev_by_day = {d: prev_session_ohlc(conn, 'NIFTY', d) for d in days}
    finally:
        conn.close()
    cfg = base_cfg()
    checked = 0
    for d in days:
        candles, prev = candles_by_day[d], prev_by_day[d]
        if not prev or len(candles) < 12:
            continue
        lv = day_levels(prev['high'], prev['low'], prev['close'])
        full, _ = C.scan_session(candles, lv, cfg)
        for k in (5, 10, 20, 30, 40, 50, 60):
            trunc, _ = C.scan_session(candles[:k], lv, cfg)
            for a in trunc:
                assert any(b.family == a.family and b.confirm_idx == a.confirm_idx
                           and b.trigger_idx == a.trigger_idx for b in full), \
                    f'{d}: prefix candidate not reproduced'
        checked += 1
    assert checked, 'no real sessions exercised'


def test_signal_uses_only_prior_session_levels():
    conn = ro_conn()
    try:
        for d in common.load_sessions(conn, 'NIFTY', '2026-09-01', '2026-09-20'):
            a = prev_session_ohlc(conn, 'NIFTY', d)
            if a:
                assert a['date'] < d
    finally:
        conn.close()


def test_data_quality_pit_check_passes():
    """Full-range PIT recomputation must show zero level mismatches."""
    import data_quality as dq
    q = dq.run_report('2026-07-06', '2026-10-19',
                      db_path=os.environ['TRADINGAI_DB_PATH'])
    pit = q['pit_level_check']
    assert pit['verdict'] == 'PASS', pit['examples'][:2]
    assert pit['mismatches'] == 0
    assert q['structure']['duplicate_candles'] == 0
    assert q['structure']['ohlc_violations'] == 0


@pytest.mark.parametrize('instrument', ['NIFTY', 'BANKNIFTY'])
def test_position_risk_positive_for_all_produced_trades(instrument):
    vcfg = dict(base_cfg())
    vcfg.update(CFG['variants'][0]['overrides'])
    res = runner.run_and_label(instrument, '2026-07-06', '2026-10-19', vcfg,
                               db_path=os.environ['TRADINGAI_DB_PATH'])
    for t in res['trades']:
        assert t['risk_pts'] > 0
        assert t['lot_size'] == common.LOT_SIZES[instrument]
        assert abs(t['pnl_net_rs'] - (t['pnl_gross_rs'] - t['cost_rs'])) < 0.02
