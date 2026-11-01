"""Shared fixtures: the snapshot, the ledger and the reconstructed paths."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config, dbutil, ledger, levels, paths, sources, taxonomy  # noqa: E402


@pytest.fixture(scope='session')
def conn():
    if not os.path.exists(config.SNAPSHOT):
        pytest.skip(f'snapshot not available: {config.SNAPSHOT}')
    connection = dbutil.connect()
    yield connection
    connection.close()


@pytest.fixture(scope='session')
def src(conn):
    return sources.load_sources(conn)


@pytest.fixture(scope='session')
def candles(conn):
    return paths.load_candles(conn)


@pytest.fixture(scope='session')
def rows(src, candles_global):
    records, _ = ledger.build_ledger(src)
    for record in records:
        path = paths.reconstruct(record, candles_global)
        level_info = levels.build(record, candles_global)
        confirmation = levels.confirmation_state(record, candles_global, level_info)
        features = paths.features(record, path, candles_global,
                                  level_info.get('level_price'))
        path.update(features)
        record.update(features)
        record.update(path)
        record.update({k: v for k, v in level_info.items()
                       if k not in ('swings', 'pivots', 'known_levels_at_entry')})
        record.update(taxonomy.classify(record, path, level_info, confirmation))
    return records


@pytest.fixture(scope='session')
def candles_global():
    if not os.path.exists(config.SNAPSHOT):
        pytest.skip(f'snapshot not available: {config.SNAPSHOT}')
    connection = dbutil.connect()
    data = paths.load_candles(connection)
    connection.close()
    return data


@pytest.fixture(scope='session')
def book_rows(rows):
    return [r for r in rows if r['population'] == ledger.POP_BOOK]


@pytest.fixture(scope='session')
def live_rows(rows):
    return [r for r in rows if r['population'] == ledger.POP_LIVE]
