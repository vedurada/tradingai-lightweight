"""No-lookahead: the entry-time analysis must not see the future."""
import copy

from src import config, levels, paths, taxonomy


def _replace_future(candles, record):
    """A copy of the candles where every bar after the entry is an extreme bar."""
    mutated = copy.deepcopy(candles)
    inst = record['instrument']
    date = record['session_date']
    entry_ts = (record.get('entry_time') or '')[:16]
    bars = mutated.get(inst, {}).get(date, [])
    for bar in bars:
        if bar['timestamp'][:16] > entry_ts:
            bar['open'] = bar['close'] = bar['high'] = 1e6
            bar['low'] = 1.0
    return mutated


def test_entry_time_structure_does_not_depend_on_the_future(book_rows, candles_global):
    checked = 0
    for record in book_rows:
        if record.get('entry_time') is None or record.get('entry_price') is None:
            continue
        base = levels.build(record, candles_global)
        future = levels.build(record, _replace_future(candles_global, record))
        assert base['level_price'] == future['level_price']
        assert base['level_price_source'] == future['level_price_source']
        assert base['entry_extension_pct'] == future['entry_extension_pct']
        assert base['touches_before_entry'] == future['touches_before_entry']
        assert base['entry_is_first_touch'] == future['entry_is_first_touch']
        assert base['prev_high'] == future['prev_high']
        assert base['prev_low'] == future['prev_low']
        assert base['running_high_at_entry'] == future['running_high_at_entry']
        assert base['running_low_at_entry'] == future['running_low_at_entry']
        checked += 1
    assert checked > 0


def test_pre_entry_features_do_not_depend_on_the_future(book_rows, candles_global):
    checked = 0
    for record in book_rows:
        if record.get('entry_time') is None or record.get('entry_price') is None:
            continue
        base_path = paths.reconstruct(record, candles_global)
        base = paths.features(record, base_path, candles_global, None)
        mutated = _replace_future(candles_global, record)
        future_path = paths.reconstruct(record, mutated)
        future = paths.features(record, future_path, mutated, None)
        assert base['pre_entry_move_pct'] == future['pre_entry_move_pct']
        assert base['pre_entry_range_pct'] == future['pre_entry_range_pct']
        assert base['is_choppy'] == future['is_choppy']
        checked += 1
    assert checked > 0


def test_confirmation_window_ends_at_the_entry(book_rows, candles_global):
    checked = 0
    for record in book_rows:
        if record.get('entry_time') is None:
            continue
        conf = levels.confirmation_state(record, candles_global)
        assert conf['bars_in_confirmation_window'] <= config.PHASE3_EXPIRY_BARS
        checked += 1
    assert checked > 0


def test_classification_is_deterministic(book_rows, candles_global):
    checked = 0
    for record in book_rows[:20]:
        path = paths.reconstruct(record, candles_global)
        level_info = levels.build(record, candles_global)
        confirmation = levels.confirmation_state(record, candles_global, level_info)
        features = paths.features(record, path, candles_global, level_info.get('level_price'))
        path.update(features)
        first = taxonomy.classify(record, path, level_info, confirmation)
        second = taxonomy.classify(record, path, level_info, confirmation)
        assert first == second
        checked += 1
    assert checked > 0
