"""Research test isolation.

Mirrors the production tests/conftest.py pattern: if TRADINGAI_DB_PATH is not
already set (run_all.py sets it to its snapshot), take a consistent SQLite
backup of the production database into a temp file so the research tests can
read real data and can never touch the live file. sys.path gets src/ (the
research modules) and /opt/tradingai (the production `app` package).
"""
import atexit
import os
import shutil
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, 'src')
for p in (SRC, os.environ.get('TRADINGAI_BASE', '/opt/tradingai')):
    if p not in sys.path:
        sys.path.insert(0, p)

if not os.environ.get('TRADINGAI_DB_PATH'):
    _prod = os.path.join(os.environ.get('TRADINGAI_BASE', '/opt/tradingai'),
                         'database', 'tradingai.db')
    _tmp_dir = tempfile.mkdtemp(prefix='cpr_research_tests_')
    _tmp_db = os.path.join(_tmp_dir, 'tradingai.db')
    if os.path.exists(_prod):
        _src = sqlite3.connect(f'file:{_prod}?mode=ro', uri=True)
        _dst = sqlite3.connect(_tmp_db)
        try:
            _src.backup(_dst)
        finally:
            _dst.close()
            _src.close()
    os.environ['TRADINGAI_DB_PATH'] = _tmp_db
    atexit.register(lambda: shutil.rmtree(_tmp_dir, ignore_errors=True))
