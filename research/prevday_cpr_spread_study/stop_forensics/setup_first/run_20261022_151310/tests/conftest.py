"""Shared fixtures for the setup-first study test suite.

The suite is isolated: it never opens the live database for writing, it uses
the snapshot working copy for every read and it only touches files inside the
study run directory.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

RUN_DIR = Path(__file__).resolve().parents[1]
REPO = '/opt/tradingai'
SNAP = RUN_DIR / 'snapshots' / 'working_copy.db'

if REPO not in sys.path:
    sys.path.insert(0, REPO)

# The production modules resolve the database path at import time, so the
# environment must point at the snapshot BEFORE anything from `app.*` is loaded.
if SNAP.exists():
    os.environ['TRADINGAI_DB_PATH'] = str(SNAP)


def _load_package():
    name = 'study_src'
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, RUN_DIR / 'src' / '__init__.py',
        submodule_search_locations=[str(RUN_DIR / 'src')])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pkg = _load_package()

from study_src import (config, engine, structures, stops, records, setups,  # noqa: E402,F401
                      deliverables, gates, integrity, reporting)


def ts(minutes_from_open=0, day='2026-09-01'):
    """Timestamps on the production grid (09:15 + 5 min steps)."""
    start = 9 * 60 + 15
    m = start + minutes_from_open
    return f'{day}T{m // 60:02d}:{m % 60:02d}:00+05:30'


def candle(i, o, h, l, c, day='2026-09-01', v=1000):
    return {'timestamp': ts(i, day), 'open': o, 'high': h, 'low': l, 'close': c,
            'volume': v}


def series(rows, day='2026-09-01'):
    """rows: list of (open, high, low, close) -> candle dicts on the 5 min grid.

    The production grid is 09:15 + 5 minutes, so bar `i` carries the timestamp
    09:15 + 5*i and a 74 bar session ends on the 15:20 candle.
    """
    return [candle(i * 5, *row, day=day) for i, row in enumerate(rows)]


def make_setup(level=100.0, family='F1_PREV_DAY_LEVEL_REJECTION', id_idx=0,
               candles=None, expiry=None, zone_pct=None):
    zone_pct = config.ZONE_PCT if zone_pct is None else zone_pct
    expiry = config.EXPIRY_BARS if expiry is None else expiry
    lo = level - level * zone_pct
    hi = level + level * zone_pct
    setup = {
        'setup_id': f'TEST_{family}_{level:.2f}',
        'instrument': 'NIFTY',
        'session_date': '2026-09-01',
        'period': 'VAL',
        'direction': 'BEAR',
        'setup_family': family,
        'level_name': 'TEST',
        'level_price': level,
        'zone_low': lo,
        'zone_high': hi,
        'zone_pct': zone_pct,
        'identification_idx': id_idx,
        'identification_ts': candles[id_idx]['timestamp'] if candles else None,
        'expiry_bars': expiry,
        'state': config.STATE_WATCHING,
        'arrival_idx': None,
        'arrival_ts': None,
        'confirm_idx': None,
        'confirm_ts': None,
        'rejection_reason': None,
        'transitions': [],
        'confirm_rule': 'C1_CLOSE_BACK',
    }
    return setup


def session_ohlc(n=40, base=100.0):
    """A flat session with a controllable shape."""
    return series([(base, base + 0.1, base - 0.1, base) for _ in range(n)])
