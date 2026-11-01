"""Taxonomy, controls and the Phase 3 reproduction."""
import os

import pytest

from src import config, controls, phase3, taxonomy


def test_every_loss_has_a_primary_category_in_every_dimension(book_rows):
    losses = [r for r in book_rows if r['outcome_class'] == 'LOSS']
    assert losses
    for r in losses:
        for dim in ('A', 'B', 'C', 'D'):
            assert r.get(f'{dim}_primary'), f"{r['source_row_id']} has no {dim} category"


def test_stop_dimension_is_not_applicable_outside_stop_exits(book_rows):
    for r in book_rows:
        if r['exit_kind'] != 'STOP':
            assert r['C_primary'] == taxonomy.C_NOT_APPLICABLE
        else:
            assert r['C_primary'] != taxonomy.C_NOT_APPLICABLE


def test_secondary_categories_never_repeat_the_primary(book_rows):
    for r in book_rows:
        for dim in ('A', 'B', 'C', 'D'):
            secondary = r.get(f'{dim}_secondary') or []
            assert r.get(f'{dim}_primary') not in secondary
            assert len(secondary) == len(set(secondary))


def test_control_group_is_built_from_the_same_population(book_rows):
    result = controls.build(book_rows)
    assert result['losers'] + result['winners'] <= len(book_rows)
    assert result['losers'] > 0 and result['winners'] > 0
    metrics = {c['metric'] for c in result['comparison']}
    assert 'mae_hl_r' in metrics and 'mfe_hl_r' in metrics
    assert result['clustering']['max_losses_in_one_session'] >= 1


def test_control_rows_carry_the_group_label(book_rows):
    rows = controls.per_trade_rows(book_rows)
    assert rows
    groups = {r['group'] for r in rows}
    assert 'LOSS' in groups and 'WIN' in groups


@pytest.mark.skipif(not os.path.isdir(config.P3_DIR),
                    reason='the Phase 3 artifacts are not available here')
def test_phase3_headline_figures_are_reproduced():
    result = phase3.reproduce()
    assert result['all_checks_pass'], result['checks']
    assert result['reproduced']['identified'] == 600
    assert result['reproduced']['trade_eligible'] == 134
    assert result['baseline_trades'] == 129
    assert result['candidate_trades_artifact'] == 98
    assert result['verdict'] == 'INCONCLUSIVE'
    assert result['experiment_d_run'] is False


@pytest.mark.skipif(not os.path.isdir(config.P3_DIR),
                    reason='the Phase 3 artifacts are not available here')
def test_phase3_reason_counts_use_the_identified_setup_as_denominator():
    result = phase3.reproduce()
    reasons = result['reasons']
    assert reasons['setups'] == 600
    assert sum(reasons['decisions'].values()) == 600
    assert sum(reasons['reasons'].values()) >= 1


def test_comparison_rows_carry_denominators(book_rows, candles_global):
    losses = [r for r in book_rows if r['outcome_class'] == 'LOSS']
    stop_losses = [r for r in losses if r['exit_kind'] == 'STOP']
    fake = {'reproduced': {'identified': 600, 'zone_reached': 374, 'confirmed': 305,
                           'expired': 203, 'invalidated': 92, 'trade_eligible': 134,
                           'missed': 31, 'no_trade': 140},
            'baseline_trades': 129,
            'stop_out_forensics': {'baseline': {}, 'candidate': {}},
            'reasons': {'setups': 600, 'reasons': {}}}
    rows = phase3.comparison_table(fake, losses, stop_losses)
    assert rows
    for row in rows:
        assert 'verdict' in row and row['verdict']
        assert row['live_denominator'] in (len(losses), len(stop_losses))
