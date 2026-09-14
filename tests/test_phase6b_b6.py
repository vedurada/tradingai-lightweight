#!/usr/bin/env python3
"""PHASE 6B-3 B.6 tests — Reliability Core.

23 tests covering:
- B6.1 Thread-safe timeouts (3)
- B6.2 Circuit-breaker wiring (3)
- B6.3 Scheduled cleanup + DB size (2)
- B6.4 Connection-close hardening (2)
- B6.5 sql_guard coverage (2)
- B6.6 Backup 24h + restore verify (3)
- B6.7 Unified fetch health (3)
- B6.8 Central alert config (2)
- B6.9 Readiness split (3)

Mandatory invariants:
- 446/446 regression baseline maintained
- 0/8 model files modified
- Open breaker never synthesizes data
- /api/ready never implies data validity
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import backend.api_server as api_mod
from backend.api_server import app, get_db

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _get_script_path(rel_path):
    return os.path.join(REPO_ROOT, rel_path)


class TestThreadSafeTimeouts:
    def test_unit_uses_sync_workers(self):
        content = open(_get_script_path("ops/systemd/tradingai-api.service")).read()
        assert "--worker-class sync" in content, "gunicorn must use sync workers for SIGALRM enforcement"
        assert "gthread" not in content, "gthread leftovers would silently disable enforcement"

    def test_timeout_armed_without_error(self):
        with app.test_client() as client:
            resp = client.get("/api/health")
            assert resp.status_code in (200, 500), "before_request must not crash"

    def test_timeout_504_envelope(self):
        with app.test_request_context("/api/health"):
            resp, code = api_mod._handle_timeout(TimeoutError("slow"))
            assert code == 504, f"expected 504, got {code}"
            body = resp.get_json()
            assert body["error"]["code"] == "INTERNAL_ERROR", f"envelope broken: {body}"


class TestCircuitBreakerWiring:
    def test_breaker_opens_and_recovers(self):
        from backend.circuit_breaker import CircuitBreaker
        b = CircuitBreaker("test", failure_threshold=2, recovery_timeout=60)
        def boom():
            raise ConnectionError("down")
        with pytest.raises(ConnectionError):
            b.call(boom)
        with pytest.raises(ConnectionError):
            b.call(boom)
        assert b.state == "OPEN", "breaker must open at threshold"
        b.force_closed()
        assert b.state == "CLOSED"
        assert b.call(lambda: "ok") == "ok"

    def test_open_breaker_returns_empty_not_synthetic(self):
        import backend.data_fetcher_db as fetcher
        fetcher.YF_BREAKER.force_open()
        try:
            result = fetcher.fetch_yf_ohlcv("^NSEI", interval="1m", period="1d")
            assert result == [], f"open breaker must yield empty degradation, got {result!r}"
        finally:
            fetcher.YF_BREAKER.force_closed()

    def test_breaker_trip_recorded(self):
        import backend.nse_source as nse
        nse.NSE_BREAKER.force_open()
        try:
            result = nse.fetch_index_quotes()
            assert result == {}, "open NSE breaker must yield empty degradation"
            state = nse.nse_monitor.get_summary()["circuit_breakers"].get("nse_live", {})
            assert state.get("state") == "OPEN", f"trip not recorded: {state}"
        finally:
            nse.NSE_BREAKER.force_closed()


class TestScheduledCleanup:
    def test_crontab_has_cleanup(self):
        content = open(_get_script_path("ops/crontab.txt")).read()
        assert "ops/cleanup.sh" in content, "cleanup must be scheduled"

    def test_health_has_db_size(self):
        with app.test_client() as client:
            body = client.get("/api/health").get_json()
            assert "db_size_mb" in body, "health must carry db_size_mb"
            assert body["db_size_mb"] is None or isinstance(body["db_size_mb"], (int, float))


class TestConnectionCloseHardening:
    def test_pool_close_idempotent(self):
        pool = api_mod.db_pool
        before = pool.status["active"]
        conn = api_mod.get_db()
        mid = pool.status["active"]
        assert mid == before + 1
        conn.close()
        conn.close()
        assert pool.status["active"] == before, "double close must not corrupt count"

    def test_no_leak_on_view_paths(self):
        pool = api_mod.db_pool
        before = pool.status["active"]
        with app.test_client() as client:
            assert client.get("/api/regime/NIFTY").status_code in (200, 404)
            assert client.get("/api/regime/NOPE_XYZ").status_code == 404
            assert client.get("/api/strategy/NIFTY").status_code in (200, 404)
        assert pool.status["active"] == before, "view paths leaked pool slots"


class TestSqlGuardCoverage:
    def test_guard_extended_tables(self):
        from backend.sql_guard import assert_table_name
        for t in ("market_outlooks", "market_snapshots", "market_regime", "strategies"):
            assert_table_name(t)
        with pytest.raises(AssertionError):
            assert_table_name("users; DROP TABLE users")

    def test_unknown_source_unavailable_not_crash(self):
        result = api_mod._check_source_freshness("definitely_not_a_source", threshold=30)
        assert result["status"] == "unavailable", f"unexpected: {result}"


class TestBackupThreshold:
    def test_selfheal_backup_24h(self):
        content = open(_get_script_path("ops/self-heal.sh")).read()
        assert "MAX_BACKUP_AGE_DAYS=1" in content, "threshold must be 24h"

    def test_selfheal_row_compare(self):
        content = open(_get_script_path("ops/self-heal.sh")).read()
        assert "backup_diverged" in content
        assert "backup_row_compare" in content

    def test_selfheal_restore_verify(self):
        content = open(_get_script_path("ops/self-heal.sh")).read()
        assert "restore_integrity_failed" in content
        block = content[content.index("DB restore verify"):]
        assert block.index("restore integrity OK") < block.index("restart tradingai-api"), \
            "integrity must be verified before restart"


class TestFetchHealth:
    def test_record_fetch_result_writes(self):
        api_mod._record_fetch_result("b6_test_src", False, "boom")
        api_mod._record_fetch_result("b6_test_src", False, "boom2")
        api_mod._record_fetch_result("b6_test_src", True)
        conn = get_db()
        try:
            row = conn.execute("SELECT * FROM fetch_health WHERE source=?", ("b6_test_src",)).fetchone()
            assert row is not None, "fetch_health row missing"
            d = dict(row)
            assert d["consecutive_failures"] == 0, f"success must reset: {d}"
            assert d["error_count"] == 2, f"error count wrong: {d}"
            assert d["success_count"] == 1, f"success count wrong: {d}"
            conn.execute("DELETE FROM fetch_health WHERE source=?", ("b6_test_src",))
            conn.commit()
        finally:
            conn.close()

    def test_data_status_exposes_fetch_health(self):
        with app.test_client() as client:
            body = client.get("/api/data_status").get_json()
            assert isinstance(body, dict), f"expected dict envelope, got {type(body)}"
            assert "symbols" in body and "fetch_health" in body

    def test_fetch_health_schema(self):
        conn = get_db()
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(fetch_health)").fetchall()}
            for c in ("source", "success_count", "error_count", "consecutive_failures", "last_error", "last_ok_at"):
                assert c in cols, f"missing column {c}: {cols}"
        finally:
            conn.close()


class TestAlertConfig:
    def test_alerting_json_valid(self):
        cfg = json.load(open(_get_script_path("config/alerting.json")))
        for key in ("sustained_api_failures", "abnormal_latency", "backup_max_age_days",
                    "circuit_breaker", "pcr_put_heavy_max", "pcr_call_heavy_min"):
            assert key in cfg, f"missing key {key}"

    def test_alert_rules_loaded(self):
        assert api_mod.ALERT_RULES is not None, "alerting.json must load"
        assert api_mod.ALERT_RULES["backup_max_age_days"] == 1


class TestReadiness:
    def test_ready_endpoint(self):
        with app.test_client() as client:
            resp = client.get("/api/ready")
            assert resp.status_code == 200
            body = resp.get_json()
            assert body["ready"] is True, f"process should be ready: {body}"
            assert "data_freshness" not in body and "deep_health" not in body, \
                "ready must not carry data-validity signals"

    def test_ready_coexists_with_degraded_health(self):
        from unittest.mock import patch
        stale = {"status": "stale", "age_minutes": 999, "threshold": 30}
        with patch.object(api_mod, "_check_source_freshness", return_value=stale), \
             patch.object(api_mod, "_deep_health_check",
                          return_value={"tables_checked": 0, "all_healthy": False, "details": {}}):
            with app.test_client() as client:
                health = client.get("/api/health").get_json()
                assert health["status"] == "degraded", "setup failed: health not degraded"
                ready = client.get("/api/ready")
                assert ready.status_code == 200, "ready must not mirror data staleness"
                assert ready.get_json()["ready"] is True

    def test_gate_checks_ready_first(self):
        content = open(_get_script_path("ops/health_gate.sh")).read()
        assert "api/ready" in content and "api/health" in content
        assert content.index("api/ready") < content.index("api/health"), \
            "gate must check readiness before health"
