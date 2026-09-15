"""TradingAI.in - Phase 1 Live Test Suite: Data Integrity Invariants.

Spec suite covered: INV (Data Integrity Invariants).
20 hard assertions - these MUST all pass.
"""
import os
import sys
import json
import re
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from backend.api_server import app, get_db

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DB_PATH = os.path.join(ROOT, "database", "tradingai.db")


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8", errors="ignore") as fh:
        return fh.read()


# ═══════════════════════════════════════════════════════════
# INV — Hard Data Integrity Invariants (20 asserts)
# ═══════════════════════════════════════════════════════════

class TestInvDatabaseIntegrity:
    """INV-1: Database file and schema integrity."""

    def test_001_db_file_exists(self):
        assert os.path.isfile(DB_PATH), "Database file must exist"

    def test_002_db_is_valid_sqlite(self):
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.execute("PRAGMA integrity_check").fetchone()
        finally:
            conn.close()

    def test_003_symbols_table_exists(self):
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='symbols'"
        ).fetchone()
        conn.close()
        assert row is not None, "symbols table must exist"

    def test_004_price_1m_table_exists(self):
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='price_1m'"
        ).fetchone()
        conn.close()
        assert row is not None, "price_1m table must exist"

    def test_005_vix_data_table_exists(self):
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='vix_data'"
        ).fetchone()
        conn.close()
        assert row is not None, "vix_data table must exist"


class TestInvAPISchema:
    """INV-2: API response schema invariants."""

    def test_006_health_returns_status_field(self):
        with app.test_client() as c:
            r = c.get("/api/health")
            data = r.get_json()
            assert "status" in data, "Health must have status field"

    def test_007_health_returns_timestamp(self):
        with app.test_client() as c:
            r = c.get("/api/health")
            data = r.get_json()
            assert "timestamp" in data, "Health must have timestamp"

    def test_008_market_has_required_keys(self):
        with app.test_client() as c:
            r = c.get("/api/market")
            if r.status_code == 200:
                data = r.get_json()
                for key in ("source", "last_updated", "data_quality",
                            "ai_outlook", "instruments", "data_completeness"):
                    assert key in data, f"Market response missing key: {key}"

    def test_009_market_source_not_empty(self):
        with app.test_client() as c:
            r = c.get("/api/market")
            if r.status_code == 200:
                data = r.get_json()
                assert data.get("source"), "Market source must not be empty"

    def test_010_price_nifty_has_data_or_404(self):
        with app.test_client() as c:
            r = c.get("/api/price/NIFTY")
            assert r.status_code in (200, 404), f"Price NIFTY got {r.status_code}"
            if r.status_code == 200:
                data = r.get_json()
                assert isinstance(data, dict), "Price must be dict"


class TestInvContentIntegrity:
    """INV-3: HTML content invariants."""

    def test_011_index_has_dashboard(self):
        t = read("index.html")
        assert 'id="dashboard"' in t, "Index must have dashboard div"

    def test_012_index_has_sebi_disclaimer(self):
        t = read("index.html")
        assert "SEBI" in t, "Index must have SEBI disclaimer"

    def test_013_index_has_canonical(self):
        t = read("index.html")
        assert '<link rel="canonical" href="https://tradingai.in/">' in t, \
            "Index must have canonical"

    def test_014_no_ghost_indices_market(self):
        t = read("index.html")
        assert "/indices/market.html" not in t, \
            "Index must not reference ghost URL"

    def test_015_404_has_noindex(self):
        t = read("404.html")
        assert "noindex" in t, "404 page must have noindex"


class TestInvCodeIntegrity:
    """INV-4: Code-level invariants."""

    def test_016_api_debug_is_false(self):
        src = read("backend/api_server.py")
        assert "debug=False" in src or "debug=False" in src, \
            "API must not run in debug mode"

    def test_017_no_bare_except_in_health(self):
        src = read("backend/api_server.py")
        health_start = src.find("def health():")
        assert health_start > 0, "Health function not found"
        health_end = src.find("\n\n", health_start)
        health_section = src[health_start:health_end]
        assert "except:" not in health_section, \
            "Health function must not have bare except"

    def test_018_flask_debug_assertion(self):
        src = read("backend/api_server.py")
        assert "FLASS_DEBUG" not in src, "Typo FLASS_DEBUG must not exist"
        assert "FLASK_DEBUG" in src, "FLASK_DEBUG assertion must exist"

    def test_019_sql_guard_active(self):
        src = read("backend/api_server.py")
        assert "assert_table_name" in src, \
            "assert_table_name must be called in api_server.py"

    def test_020_nginx_404_rule_exists(self):
        conf = read("ops/nginx-tradingai.conf")
        assert re.search(r"location ~\* \\.html\$", conf), \
            "nginx must have *.html 404 rule"
        assert "try_files $uri =404" in conf, \
            "nginx must have try_files =404"
        assert "error_page 404 /404.html" in conf, \
            "nginx must have error_page 404"
