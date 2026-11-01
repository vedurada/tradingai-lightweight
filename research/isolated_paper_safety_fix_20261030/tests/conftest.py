"""Test isolation (audit R-01).

Production is a live system whose SQLite file doubles as the market-data
store. Before this file existed the test suite imported the shipped app and
wrote straight into /opt/tradingai/database/tradingai.db: tests/test_phase6.py
inserted real paper_trades rows (entry=23400.0) into production on every run
(14 such rows had accumulated by 2026-10-18).

This conftest is imported by pytest before any test module, so the environment
is redirected at a throwaway copy of the production database first. Both
app.core.db and scripts/tg_alerts.py honour TRADINGAI_DB_PATH / TRADINGAI_BASE,
so tests still read real data but can never mutate production.
"""
import atexit
import os
import shutil
import sqlite3
import tempfile

_PROD_BASE = "/opt/tradingai"
_PROD_DB = os.path.join(_PROD_BASE, "database", "tradingai.db")

if not os.environ.get("TRADINGAI_DB_PATH"):
    _tmp_dir = tempfile.mkdtemp(prefix="tradingai_tests_")
    _tmp_db = os.path.join(_tmp_dir, "tradingai.db")
    if os.path.exists(_PROD_DB):
        _src = sqlite3.connect("file:%s?mode=ro" % _PROD_DB, uri=True)
        try:
            _dst = sqlite3.connect(_tmp_db)
            try:
                _src.backup(_dst)
            finally:
                _dst.close()
        finally:
            _src.close()
    os.environ["TRADINGAI_DB_PATH"] = _tmp_db
    os.environ.setdefault("TRADINGAI_BASE", _PROD_BASE)
    atexit.register(lambda: shutil.rmtree(_tmp_dir, ignore_errors=True))
