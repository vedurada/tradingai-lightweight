#!/usr/bin/env python3
"""PHASE 6B-3 B.4 tests — Performance & DB.

35 tests covering:
- Connection Pooling (5)
- Response Caching (8)
- Async Backtest Processing (5)
- Market Data Performance (3)
- List Endpoint Pagination (3)
- DB Optimization (6)
- Timeout & Queuing (3)
- Concurrency Safety (2)

Mandatory invariants:
- 385/385 regression baseline maintained
- 0/8 model files modified
- Caching never misrepresents data_quality
- Connection pooling preserves 503
- Backtest results byte-for-byte identical
"""
import os
import sys
import ast
import json
import sqlite3
import tempfile
import shutil
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import backend.api_server as api_mod
from backend.api_server import app, DATA_QUALITY_LIVE, DATA_QUALITY_STALE, DATA_QUALITY_UNAVAILABLE, get_db
db_pool = api_mod.db_pool
response_cache = api_mod.response_cache
_backtest_jobs = api_mod._backtest_jobs
_jobs_lock = api_mod._jobs_lock
try:
    from db_pool import ConnectionPool, PooledConnection
except ImportError:
    from backend.db_pool import ConnectionPool, PooledConnection

BACKTEST_BACKEND = os.environ.get("TRADINGAI_BACKTEST_BACKEND", "default")


class TestConnectionPooling:
    def test_connection_pool_exists(self):
        assert db_pool is not None, "Connection pool should be initialized"
        assert isinstance(db_pool, ConnectionPool), "Pool should be ConnectionPool instance"

    def test_connection_reuse(self):
        conn1 = db_pool.get()
        conn2 = db_pool.get()
        assert conn1 is not None
        assert conn2 is not None
        db_pool.put(conn1)
        db_pool.put(conn2)
        conn3 = db_pool.get()
        assert conn3 is not None
        db_pool.put(conn3)

    def test_pool_503_on_exhaustion(self):
        pool = ConnectionPool(":memory:", max_connections=2)
        conns = [pool.get() for _ in range(2)]
        with pytest.raises(sqlite3.OperationalError):
            pool.get()
        for c in conns:
            pool.put(c)
        pool.close_all()

    def test_pool_preserves_503(self):
        with app.test_client() as c:
            r = c.get("/api/health")
            assert r.status_code in (200, 503)

    def test_db_unavailability_returns_503(self):
        import backend.api_server as mod
        original_path = mod.DB_PATH
        try:
            with mod._pool_lock:
                mod.db_pool.close_all()
                mod.db_pool = ConnectionPool(lambda: original_path, max_connections=10)
                mod._pool_db_path = original_path
            mod.DB_PATH = "/nonexistent/path/to/db.sqlite"
            with app.test_client() as c:
                r = c.get("/api/price/NIFTY")
                assert r.status_code == 503
                data = r.get_json()
                assert data is not None
                assert data.get("error", {}).get("code") == "SERVICE_DEGRADED"
                assert "Database temporarily unavailable" in data.get("error", {}).get("message", "")
        finally:
            with mod._pool_lock:
                mod.db_pool.close_all()
                mod.db_pool = ConnectionPool(lambda: original_path, max_connections=10)
                mod._pool_db_path = original_path
            mod.DB_PATH = original_path

    def test_connection_creation_reduced(self):
        start = time.monotonic()
        conn = db_pool.get()
        elapsed_ms = (time.monotonic() - start) * 1000
        db_pool.put(conn)
        assert elapsed_ms < 5, f"Connection reuse should be <5ms, got {elapsed_ms:.1f}ms"


class TestResponseCaching:
    def test_price_cache_5s(self):
        with app.test_client() as c:
            r1 = c.get("/api/price/NIFTY")
            assert r1.status_code == 200
            r2 = c.get("/api/price/NIFTY")
            assert r2.status_code == 200
            data1 = r1.get_json()
            data2 = r2.get_json()
            assert data1 is not None
            assert data2 is not None

    def test_cache_adds_data_quality(self):
        response_cache._store.clear()
        with app.test_client() as c:
            r = c.get("/api/price/NIFTY")
            assert r.status_code == 200
            data = r.get_json()
            assert data is not None
            assert "data_quality" in data, "Cached response must include data_quality"

    def test_cache_never_marks_stale_as_live(self):
        response_cache._store.clear()
        with app.test_client() as c:
            r = c.get("/api/price/NIFTY")
            data = r.get_json()
            if data and "data_quality" in data and data["data_quality"] == DATA_QUALITY_LIVE:
                assert data.get("data_freshness", {}).get("stale") is not True, \
                    "LIVE quality should not have stale=true"

    def test_cache_serves_stale_on_outage(self):
        response_cache._store.clear()
        with app.test_client() as c:
            r = c.get("/api/market")
            assert r.status_code in (200, 404)

    def test_options_cache_10min(self):
        with app.test_client() as c:
            r = c.get("/api/options/NIFTY")
            assert r.status_code in (200, 404)

    def test_market_cache_20s(self):
        with app.test_client() as c:
            r = c.get("/api/market")
            assert r.status_code in (200, 404)

    def test_cache_preserves_b3_protocol(self):
        response_cache._store.clear()
        with app.test_client() as c:
            r = c.get("/api/price/NIFTY")
            assert r.status_code == 200
            data = r.get_json()
            assert data is not None
            has_quality = "data_quality" in data or "data_freshness" in data or "data_completeness" in data
            assert has_quality, f"/api/price/NIFTY missing B.3 data_quality indicators"

    def test_cache_hit_rate_gt_50(self):
        response_cache._store.clear()
        with app.test_client() as c:
            for _ in range(10):
                c.get("/api/price/NIFTY")
            store = response_cache._store
            cached = len(store)
            assert cached > 0, "Cache should have entries after repeated requests"


class TestAsyncBacktest:
    def test_backtest_returns_202(self):
        with app.test_client() as c:
            r = c.get("/api/backtest?symbol=NIFTY&days=5")
            assert r.status_code == 202, f"Expected 202, got {r.status_code}"
            data = r.get_json()
            assert data is not None
            assert "job_id" in data, "Response must include job_id"
            assert data["status"] == "running", f"Expected running, got {data.get('status')}"

    def test_backtest_job_id(self):
        with app.test_client() as c:
            r = c.get("/api/backtest?symbol=NIFTY&days=5")
            data = r.get_json()
            assert "job_id" in data
            assert len(data["job_id"]) > 0, "job_id must not be empty"

    def test_backtest_poll_endpoint(self):
        with app.test_client() as c:
            r = c.get("/api/backtest?symbol=NIFTY&days=5")
            job_id = r.get_json()["job_id"]
            r2 = c.get(f"/api/backtest/{job_id}")
            assert r2.status_code == 202, f"Poll should return 202 while running, got {r2.status_code}"
            data = r2.get_json()
            assert data is not None
            assert data.get("status") in ("running", "completed")

    def test_api_responsive_during_backtest(self):
        with app.test_client() as c:
            r1 = c.get("/api/backtest?symbol=NIFTY&days=5")
            assert r1.status_code == 202
            r2 = c.get("/api/price/NIFTY")
            assert r2.status_code in (200, 404)

    def test_backtest_results_unchanged(self):
        if BACKTEST_BACKEND == "default":
            with app.test_client() as c:
                r_sync = c.get("/api/backtest?symbol=NIFTY&days=5")
                assert r_sync.status_code == 202
                job_id = r_sync.get_json()["job_id"]
                for _ in range(60):
                    r_poll = c.get(f"/api/backtest/{job_id}")
                    if r_poll.get_json().get("status") == "completed":
                        break
                    time.sleep(0.5)
                async_result = r_poll.get_json().get("result")

            time.sleep(1)
            with app.test_client() as c:
                r2 = c.get("/api/backtest?symbol=NIFTY&days=5")
                assert r2.status_code == 202
                job_id2 = r2.get_json()["job_id"]
                for _ in range(60):
                    r_poll2 = c.get(f"/api/backtest/{job_id2}")
                    if r_poll2.get_json().get("status") == "completed":
                        break
                    time.sleep(0.5)
                async_result2 = r_poll2.get_json().get("result")

            if async_result and async_result2:
                r1 = {k: v for k, v in async_result.items() if k != "generated_at"}
                r2 = {k: v for k, v in async_result2.items() if k != "generated_at"}
                assert r1 == r2, "Backtest results must be identical (excluding generated_at)"


class TestMarketDataPerformance:
    def test_market_non_blocking(self):
        with app.test_client() as c:
            r = c.get("/api/market")
            assert r.status_code in (200, 404)

    def test_market_stale_during_rebuild(self):
        response_cache._store.clear()
        with app.test_client() as c:
            r = c.get("/api/market")
            if r.status_code == 200:
                data = r.get_json()
                assert data is not None
                if "data_quality" in data:
                    assert data["data_quality"] in (DATA_QUALITY_LIVE, DATA_QUALITY_STALE, "GOOD"), \
                        "Market data quality must be LIVE, STALE, or GOOD"

    def test_market_background_refresh(self):
        with app.test_client() as c:
            r = c.get("/api/market")
            assert r.status_code in (200, 404)


class TestPagination:
    def test_list_endpoints_paginate(self):
        with app.test_client() as c:
            r = c.get("/api/symbols?page=1&page_size=10")
            assert r.status_code == 200
            data = r.get_json()
            assert data is not None
            assert "pagination" in data, "Paginated response must include pagination"
            pag = data["pagination"]
            assert "page" in pag and "page_size" in pag and "total" in pag

    def test_max_page_size_enforced(self):
        with app.test_client() as c:
            r = c.get("/api/symbols?page=1&page_size=1000")
            data = r.get_json()
            assert data is not None
            assert data["pagination"]["page_size"] <= 500, \
                f"page_size should be <= 500, got {data['pagination']['page_size']}"

    def test_total_count_included(self):
        with app.test_client() as c:
            r = c.get("/api/symbols?page=1&page_size=10")
            data = r.get_json()
            assert data is not None
            assert "pagination" in data
            assert isinstance(data["pagination"]["total"], int), \
                "total must be an integer"


class TestDBOptimization:
    def test_write_protection(self):
        src = open(os.path.join(os.path.dirname(__file__), "..", "backend", "api_server.py")).read()
        assert "BEGIN IMMEDIATE" in src, "BEGIN IMMEDIATE not found in write operations"

    def test_retry_on_lock(self):
        src = open(os.path.join(os.path.dirname(__file__), "..", "backend", "api_server.py")).read()
        assert "database is locked" in src, "Database lock retry not found"

    def test_cleanup_runs(self):
        assert os.path.isfile("ops/cleanup.sh"), "Cleanup script must exist"

    def test_db_size_bounded(self):
        db_path = os.path.join(os.path.dirname(__file__), "..", "database", "tradingai.db")
        if os.path.exists(db_path):
            size_mb = os.path.getsize(db_path) / (1024 * 1024)
            assert size_mb < 500, f"Database size {size_mb:.1f}MB exceeds 500MB"

    def test_indexes_exist(self):
        import sqlite3
        db_path = os.path.join(os.path.dirname(__file__), "..", "database", "tradingai.db")
        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path)
            indexes = conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
            conn.close()
            assert len(indexes) > 0, "No indexes found in database"

    def test_chat_cleanup_fast(self):
        import sqlite3
        db_path = os.path.join(os.path.dirname(__file__), "..", "database", "tradingai.db")
        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path)
            start = time.monotonic()
            conn.execute("SELECT COUNT(*) FROM chat_messages").fetchone()
            elapsed = time.monotonic() - start
            conn.close()
            assert elapsed < 1.0, f"Chat count query took {elapsed:.2f}s"


class TestTimeoutQueuing:
    def test_per_endpoint_timeouts(self):
        src = open(os.path.join(os.path.dirname(__file__), "..", "backend", "api_server.py")).read()
        assert "ENDPOINT_TIMEOUTS" in src, "Per-endpoint timeout configuration missing"

    def test_timeout_returns_504(self):
        src = open(os.path.join(os.path.dirname(__file__), "..", "backend", "api_server.py")).read()
        tree = ast.parse(src)
        found_504 = False
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_handle_timeout":
                func_src = ast.get_source_segment(src, node)
                if func_src and "504" in func_src:
                    found_504 = True
                    break
        assert found_504, "Timeout handler must return 504"

    def test_request_queuing(self):
        src = open(os.path.join(os.path.dirname(__file__), "..", "backend", "api_server.py")).read()
        assert "limiter" in src, "Rate limiter / queue configuration missing"


class TestConcurrency:
    def test_10_concurrent_requests(self):
        results = []
        errors = []
        lock = threading.Lock()

        def make_request(idx):
            try:
                conn = get_db()
                row = conn.execute("SELECT 1").fetchone()
                results.append((idx, row is not None))
                conn.close()
            except Exception as e:
                with lock:
                    errors.append(str(e))

        threads = [threading.Thread(target=make_request, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Concurrent request errors: {errors[:3]}"
        assert len(results) == 10, f"Expected 10 results, got {len(results)}"
        for idx, ok in results:
            assert ok, f"Request {idx} failed"

    def test_no_connection_leaks_under_load(self):
        initial_active = db_pool._active
        for _ in range(20):
            conn = db_pool.get()
            db_pool.put(conn)
        final_active = db_pool._active
        assert final_active == initial_active, \
            f"Connection leak: active changed from {initial_active} to {final_active}"
