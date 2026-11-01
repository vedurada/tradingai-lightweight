"""Loss definition and reconciliation."""
import pytest

from src import config, ledger


def test_populations_are_never_mixed(live_rows, book_rows):
    assert live_rows, 'the live population must not be empty'
    assert book_rows, 'the engine book must not be empty'
    assert all(r['population'] == ledger.POP_LIVE for r in live_rows)
    assert all(r['population'] == ledger.POP_BOOK for r in book_rows)
    live_ids = {r['source_row_id'] for r in live_rows}
    book_ids = {(r['session_date'], r['instrument']) for r in book_rows}
    assert not (live_ids & book_ids)


def test_live_population_contains_only_live_watch_rows(live_rows):
    for r in live_rows:
        assert r['source'] == 'paper_trades'
        assert r['flags'] == [] or 'missing_entry_exit_or_risk' in r['flags']


def test_engine_book_excludes_vix(book_rows):
    assert all(r['instrument'] in config.TRADED_INSTRUMENTS for r in book_rows)


def test_no_open_trade_is_counted_as_a_loss(book_rows, live_rows):
    for r in book_rows + live_rows:
        if r['outcome_class'] == ledger.OUTCOME_LOSS:
            assert r['exit_kind'] in ('STOP', 'TARGET', 'EOD', 'OTHER')
            assert r.get('recorded_result') or r.get('exit_reason')


def test_label_must_agree_with_its_own_arithmetic(book_rows):
    """A WIN whose recomputed R is negative must be UNKNOWN, never a loss."""
    checked = 0
    for r in book_rows:
        if r['recorded_result'] == 'WIN' and r.get('recomputed_r') is not None:
            checked += 1
            if r['recomputed_r'] < 0:
                assert r['outcome_class'] == ledger.OUTCOME_UNKNOWN
            else:
                assert r['outcome_class'] in (ledger.OUTCOME_WIN, ledger.OUTCOME_UNKNOWN)
    assert checked > 0, 'no WIN rows were available for the check'


def test_loss_rows_have_a_negative_outcome(book_rows, live_rows):
    for r in book_rows + live_rows:
        if r['outcome_class'] == ledger.OUTCOME_LOSS:
            if r['population'] == ledger.POP_BOOK:
                assert r['recomputed_r'] < 0 or r['recorded_r'] < 0
            else:
                assert r['recorded_pnl'] < 0


def test_recomputed_pnl_matches_the_production_formula(live_rows):
    for r in live_rows:
        if r.get('recorded_pnl') is None or r.get('recomputed_pnl') is None:
            continue
        assert abs(r['recorded_pnl'] - r['recomputed_pnl']) <= config.PNL_TOLERANCE_RS


def test_denominators_add_up(rows):
    for population in (ledger.POP_LIVE, ledger.POP_BOOK):
        subset = [r for r in rows if r['population'] == population]
        assert len(subset) == len({id(r) for r in subset})
        counts = {}
        for r in subset:
            counts[r['outcome_class']] = counts.get(r['outcome_class'], 0) + 1
        assert sum(counts.values()) == len(subset)


def test_no_duplicate_trade_ids(live_rows, book_rows):
    assert len({r['source_row_id'] for r in live_rows}) == len(live_rows)
    assert len({(r['session_date'], r['instrument']) for r in book_rows}) == len(book_rows)


@pytest.mark.parametrize('instrument,expected', [('NIFTY', 65), ('BANKNIFTY', 30)])
def test_lot_sizes(instrument, expected):
    assert config.lot(instrument) == expected
