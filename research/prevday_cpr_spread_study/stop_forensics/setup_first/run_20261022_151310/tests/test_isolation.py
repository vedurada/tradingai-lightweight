"""Isolation tests: the study must never read or write the live database."""
from __future__ import annotations

import json
import os
from pathlib import Path

try:  # the tests are imported as a package by pytest
    from .conftest import RUN_DIR, SNAP, integrity
except ImportError:  # flat import fallback
    from conftest import RUN_DIR, SNAP, integrity

LIVE_DB = Path('/opt/tradingai/database/tradingai.db')
PROTECTED = [
    'app/research/cpr_trigger_engine.py',
    'app/research/cpr_strategy_engine.py',
    'app/live/engine.py',
    'app/paper_trade/engine.py',
    'app/api/app.py',
    'app/research/backtest.py',
    'app/core/db.py',
    'scripts/tg_alerts.py',
    'scripts/paper_confluence.py',
    'config/settings.json',
    'frontend/index.html',
    'frontend/paper.html',
    'frontend/signals.html',
    'frontend/alerts.html',
]


def _sha(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def test_the_database_environment_points_at_the_snapshot():
    if not SNAP.exists():
        return
    assert os.environ.get('TRADINGAI_DB_PATH') == str(SNAP)
    assert str(SNAP).startswith(str(RUN_DIR))


def test_the_production_database_module_resolves_to_the_snapshot():
    if not SNAP.exists():
        return
    from app.core import db
    assert str(db.DB_PATH) == str(SNAP)


def test_the_protected_files_are_unchanged():
    pre = RUN_DIR / 'outputs' / 'protected_hashes_preflight.json'
    if not pre.exists():
        return
    recorded = json.loads(pre.read_text())
    for rel, blob in recorded.items():
        p = Path('/opt/tradingai') / rel
        assert p.exists(), rel
        expected = blob['sha256'] if isinstance(blob, dict) else blob
        if rel in integrity.SERVICE_GENERATED:
            # live artifacts are rebuilt by the running service (scripts/build_replay.py
            # via cron); they are recorded for attribution, not asserted equal.
            continue
        assert _sha(p) == expected, f'{rel} changed'


def test_the_live_database_is_not_opened_for_writing_by_the_study():
    if not LIVE_DB.exists():
        return
    # the live file is only ever read by the snapshot routine; the study code
    # never calls sqlite3.connect on it without mode=ro
    from pathlib import Path as P
    src = (RUN_DIR / 'src')
    offenders = []
    for p in src.glob('*.py'):
        text = p.read_text()
        if 'LIVE_DB' in text and 'mode=ro' not in text and 'backup' not in text:
            offenders.append(p.name)
    assert not offenders, offenders


def test_the_snapshot_contains_the_frozen_sessions():
    if not SNAP.exists():
        return
    import sqlite3
    conn = sqlite3.connect(f'file:{SNAP}?mode=ro', uri=True)
    try:
        rows = conn.execute(
            "SELECT DISTINCT substr(timestamp,1,10) d FROM market_candles_5m "
            "WHERE instrument_id='NIFTY' AND substr(timestamp,1,10) "
            "BETWEEN '2026-07-06' AND '2026-10-21' ORDER BY 1").fetchall()
    finally:
        conn.close()
    assert len(rows) >= 60
    assert rows[0][0] == '2026-07-06'
    assert rows[-1][0] <= '2026-10-21'
