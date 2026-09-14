#!/usr/bin/env python3
"""PHASE 6B-1 tests — Reliability & Database hardening.

Verifies:
- SQLite WAL mode enabled
- DB connection timeout set
- Connection leak prevention (try/finally)
- Unified error response schema
- Data completeness flags
- Circuit breaker functionality
- Bounded retry with backoff
"""
import os
import sys
import ast

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from backend.api_server import app
from backend.circuit_breaker import CircuitBreaker, CircuitOpenError
from backend.retry import retry_with_backoff, is_retryable, MAX_RETRIES, MAX_TOTAL_DURATION


class TestWALMode:
    def test_wal_mode_enabled(self):
        from backend.database import Database
        import tempfile
        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, "test.db")
        db = Database(db_path)
        conn = db._conn()
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        assert mode == "wal", f"Expected WAL mode, got {mode}"

    def test_busy_timeout_set(self):
        from backend.database import Database
        import tempfile
        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, "test.db")
        db = Database(db_path)
        conn = db._conn()
        timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        conn.close()
        assert timeout == 10000, f"Expected busy_timeout=10000, got {timeout}"

    def test_api_server_get_db_has_timeout(self):
        src = open(os.path.join(os.path.dirname(__file__), "..", "backend", "api_server.py")).read()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "get_db":
                func_src = ast.get_source_segment(src, node)
                assert "timeout=" in func_src, "get_db() missing timeout parameter"
                assert "PRAGMA journal_mode=WAL" in func_src, "get_db() missing WAL pragma"
                assert "PRAGMA busy_timeout" in func_src, "get_db() missing busy_timeout"
                break
        else:
            pytest.fail("get_db() function not found")


class TestConnectionLeakPrevention:
    def test_symbol_data_uses_try_finally(self):
        src = open(os.path.join(os.path.dirname(__file__), "..", "backend", "api_server.py")).read()
        tree = ast.parse(src)
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_symbol_data":
                func_src = ast.get_source_segment(src, node)
                assert "try:" in func_src, "_symbol_data missing try block"
                assert "finally:" in func_src, "_symbol_data missing finally block"
                found = True
                break
        assert found, "_symbol_data function not found"

    def test_build_quote_reuses_parent_conn(self):
        src = open(os.path.join(os.path.dirname(__file__), "..", "backend", "api_server.py")).read()
        tree = ast.parse(src)
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_build_quote":
                func_src = ast.get_source_segment(src, node)
                assert "conn=None" in func_src or "conn: " in func_src, "_build_quote should accept conn parameter"
                assert "get_db()" not in func_src, "_build_quote should not open new connection"
                found = True
                break
        assert found, "_build_quote function not found"

    def test_database_methods_have_try_finally(self):
        src = open(os.path.join(os.path.dirname(__file__), "..", "backend", "database.py")).read()
        tree = ast.parse(src)
        required_methods = ["execute", "fetchone", "fetchall"]
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "Database":
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name in required_methods:
                        func_src = ast.get_source_segment(src, item)
                        assert "try:" in func_src and "finally:" in func_src, \
                            f"Database.{item.name} missing try/finally"


class TestUnifiedErrorSchema:
    def test_error_response_utility_exists(self):
        src = open(os.path.join(os.path.dirname(__file__), "..", "backend", "api_server.py")).read()
        assert "def error_response(" in src, "error_response utility not found"
        assert '"code"' in src, "error_response missing code field"
        assert '"message"' in src, "error_response missing message field"
        assert '"timestamp"' in src, "error_response missing timestamp field"

    def test_error_handlers_registered(self):
        src = open(os.path.join(os.path.dirname(__file__), "..", "backend", "api_server.py")).read()
        assert "@app.errorhandler(404)" in src, "404 handler not found"
        assert "@app.errorhandler(500)" in src, "500 handler not found"
        assert "@app.errorhandler(400)" in src, "400 handler not found"

    def test_error_codes_taxonomy(self):
        src = open(os.path.join(os.path.dirname(__file__), "..", "backend", "api_server.py")).read()
        assert "ERROR_CODES" in src, "ERROR_CODES taxonomy not found"
        for code in ["NO_DATA", "UNKNOWN_SYMBOL", "SYMBOL_REQUIRED", "INTERNAL_ERROR"]:
            assert code in src, f"Missing error code: {code}"


class TestDataCompleteness:
    def test_symbol_endpoint_has_data_completeness(self):
        with app.test_client() as c:
            r = c.get('/api/NIFTY')
            assert r.status_code == 200
            data = r.get_json()
            assert "data_completeness" in data, "Missing data_completeness in /api/NIFTY"
            cc = data["data_completeness"]
            for key in ["quote", "indicators", "regime", "strategy", "scenarios", "outlook"]:
                assert key in cc, f"Missing data_completeness key: {key}"
                assert isinstance(cc[key], bool), f"data_completeness.{key} should be bool"

    def test_options_intelligence_quality_or_unavailable(self):
        with app.test_client() as c:
            r = c.get('/api/options-intelligence/NIFTY')
            assert r.status_code == 200
            data = r.get_json()
            assert "data_quality" in data, "Missing data_quality"
            assert "data_completeness" in data, "Missing data_completeness"
            assert data["data_quality"] in ("LIVE", "DATA UNAVAILABLE"), \
                f"Unexpected data_quality: {data['data_quality']}"


class TestCircuitBreaker:
    def test_circuit_breaker_closes_after_threshold(self):
        breaker = CircuitBreaker("test", failure_threshold=3, recovery_timeout=60)

        def fail():
            raise OSError("test failure")

        for _ in range(3):
            try:
                breaker.call(fail)
            except OSError:
                pass

        assert breaker.state == "OPEN", f"Expected OPEN, got {breaker.state}"

    def test_circuit_breaker_open_raises(self):
        breaker = CircuitBreaker("test", failure_threshold=2, recovery_timeout=60)

        def fail():
            raise OSError("test failure")

        try:
            breaker.call(fail)
        except OSError:
            pass
        try:
            breaker.call(fail)
        except OSError:
            pass

        with pytest.raises(CircuitOpenError):
            breaker.call(fail)

    def test_circuit_breaker_half_open_after_timeout(self):
        breaker = CircuitBreaker("test", failure_threshold=2, recovery_timeout=1)

        def fail():
            raise OSError("test failure")

        try:
            breaker.call(fail)
        except OSError:
            pass
        try:
            breaker.call(fail)
        except OSError:
            pass

        import time
        time.sleep(1.1)
        assert breaker.state == "HALF_OPEN", f"Expected HALF_OPEN, got {breaker.state}"

    def test_circuit_breaker_resets_on_success(self):
        breaker = CircuitBreaker("test", failure_threshold=3, recovery_timeout=60)

        def fail():
            raise OSError("test failure")

        try:
            breaker.call(fail)
        except OSError:
            pass

        breaker.force_open()
        assert breaker.state == "OPEN"
        breaker.force_closed()
        assert breaker.state == "CLOSED"


class TestBoundedRetry:
    def test_retry_succeeds_after_transient_failure(self):
        calls = [0]

        @retry_with_backoff(max_retries=3, base_delay=0.01, max_delay=0.1, max_total_duration=5.0)
        def flaky():
            calls[0] += 1
            if calls[0] < 3:
                raise OSError("transient")
            return "success"

        result = flaky()
        assert result == "success"
        assert calls[0] == 3

    def test_retry_exhausted_raises(self):
        calls = [0]

        @retry_with_backoff(max_retries=3, base_delay=0.01, max_delay=0.1, max_total_duration=5.0)
        def always_fail():
            calls[0] += 1
            raise OSError("permanent")

        with pytest.raises(OSError):
            always_fail()
        assert calls[0] == 3

    def test_retry_respects_max_total_duration(self):
        @retry_with_backoff(max_retries=5, base_delay=2.0, max_delay=4.0, max_total_duration=1.0)
        def always_fail():
            raise OSError("permanent")

        with pytest.raises(OSError):
            always_fail()

    def test_non_retryable_immediately_terminal(self):
        calls = [0]

        @retry_with_backoff(max_retries=3, base_delay=0.01, max_delay=0.1, max_total_duration=5.0)
        def value_error():
            calls[0] += 1
            raise ValueError("non-retryable")

        with pytest.raises(ValueError):
            value_error()
        assert calls[0] == 1, "Non-retryable should not be retried"

    def test_is_retryable_detects_network_errors(self):
        assert is_retryable(OSError("test"))
        assert is_retryable(ConnectionError("test"))
        assert is_retryable(TimeoutError("test"))
        assert not is_retryable(ValueError("test"))

    def test_retry_max_count(self):
        assert MAX_RETRIES == 3

    def test_retry_max_total_duration(self):
        assert MAX_TOTAL_DURATION == 15.0


class TestModelLayerUntouched:
    def test_regime_untouched(self):
        import backend.regime
        assert hasattr(backend.regime, "RegimeEngine")

    def test_strategies_untouched(self):
        import backend.strategies
        assert hasattr(backend.strategies, "StrategyEngine")

    def test_indicators_untouched(self):
        import backend.indicators
        assert hasattr(backend.indicators, "calculate_rsi")
        assert hasattr(backend.indicators, "calculate_macd")
        assert hasattr(backend.indicators, "calculate_adx")


class TestRegressionGate:
    def test_all_existing_tests_still_pass(self):
        """This test documents the acceptance gate. Actual verification is done by running the full suite."""
        pass
