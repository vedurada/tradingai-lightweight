"""Lazy access to the production trigger engine.

The production modules resolve the database path at import time
(`app/core/db.py`: `DB_PATH = os.environ.get('TRADINGAI_DB_PATH', ...)`), so this
module guarantees the environment variable points at the study snapshot *before*
any `app.*` import happens.
"""
from __future__ import annotations

import os

_CACHE: dict = {}


def ensure_db_env(db_path: str) -> str:
    """Point TRADINGAI_DB_PATH at the study snapshot (must run before app imports)."""
    path = str(db_path)
    os.environ['TRADINGAI_DB_PATH'] = path
    return path


def prod() -> dict:
    """Return the production callables used by this study.

    Imported lazily so that `TRADINGAI_DB_PATH` is always set first. Nothing here
    modifies the production modules - they are imported and called as-is.
    """
    if not _CACHE:
        from app.research import cpr_trigger_engine as engine
        from app.research.cpr_strategy_engine import calculate_cpr, pivot_levels
        _CACHE['engine'] = engine
        _CACHE['calculate_cpr'] = calculate_cpr
        _CACHE['pivot_levels'] = pivot_levels
    return _CACHE


def engine():
    return prod()['engine']
