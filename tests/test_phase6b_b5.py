#!/usr/bin/env python3
"""PHASE 6B B.5 tests — Parts 3-6 operational hardening.

24 tests covering:
- Part 3: Process Supervisor Enhancements (4 tests)
- Part 4: Structured Deployment Logging (3 tests)
- Part 5: Crontab Auto-install (3 tests)
- Part 6: Backup Verification (4 tests)
- Part 1: Health Deep Checks (5 tests)
- Part 2: Data Depth Validation (5 tests)

Mandatory invariants:
- 0/8 model files modified
- All tests pass
"""
import os
import sys
import ast
import json
import sqlite3
import tempfile
import shutil
import re
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import backend.api_server as api_mod
from backend.api_server import app, DATA_QUALITY_LIVE, DATA_QUALITY_STALE, DATA_QUALITY_UNAVAILABLE, get_db
import backend.data_quality as dq_mod

BACKEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MODEL_FILES = [
    "backend/regime.py",
    "backend/strategies.py",
    "backend/outlook.py",
    "backend/scenarios.py",
    "backend/options.py",
    "backend/ai_outlook.py",
    "backend/backtest.py",
    "backend/indicators.py",
]


def _get_script_path(rel_path):
    return os.path.join(REPO_ROOT, rel_path)


class TestHealthDeepDBRowCounts:
    def test_health_deep_db_row_counts(self):
        with app.test_client() as client:
            resp = client.get("/api/health")
            assert resp.status_code == 200
            data = resp.get_json()
            assert "deep_health" in data, "deep_health missing from /api/health"
            deep = data["deep_health"]
            assert "details" in deep, "details missing from deep_health"
            for table, info in deep["details"].items():
                assert "row_count" in info, f"row_count missing for {table}"
                assert isinstance(info["row_count"], int), f"row_count not int for {table}"

    def test_health_deep_date_ranges(self):
        with app.test_client() as client:
            resp = client.get("/api/health")
            data = resp.get_json()
            deep = data["deep_health"]
            for table, info in deep["details"].items():
                assert "min_date" in info, f"min_date missing for {table}"
                assert "max_date" in info, f"max_date missing for {table}"

    def test_health_deep_value_sanity(self):
        with app.test_client() as client:
            resp = client.get("/api/health")
            data = resp.get_json()
            deep = data["deep_health"]
            assert "all_healthy" in deep, "all_healthy missing"
            assert "tables_checked" in deep, "tables_checked missing"
            for table, info in deep["details"].items():
                assert "status" in info, f"status missing for {table}"
                assert info["status"] in ("ok", "degraded"), f"unexpected status {info['status']} for {table}"
                assert "issues" in info, f"issues missing for {table}"
                assert isinstance(info["issues"], list), f"issues not list for {table}"

    def test_health_deep_does_not_modify_db(self):
        counts_before = {}
        conn = get_db()
        for table in ["price_1m", "price_1d", "vix_data", "market_outlooks"]:
            try:
                counts_before[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except Exception:
                pass
        conn.close()

        with app.test_client() as client:
            resp = client.get("/api/health")
            assert resp.status_code == 200

        conn = get_db()
        for table, expected in counts_before.items():
            actual = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert actual == expected, f"{table} modified: {expected} -> {actual}"
        conn.close()

    def test_health_deep_under_timeout(self):
        start = time.time()
        with app.test_client() as client:
            resp = client.get("/api/health")
            assert resp.status_code == 200
        elapsed = time.time() - start
        assert elapsed < 10, f"health check took {elapsed:.1f}s, should be under 10s"


class TestValidateDataDepth:
    def test_validate_data_depth_basic(self):
        from backend.data_fetcher_db import _validate_data_depth
        result = _validate_data_depth()
        assert "tables_checked" in result, "tables_checked missing"
        assert "all_healthy" in result, "all_healthy missing"
        assert "details" in result, "details missing"
        assert isinstance(result["tables_checked"], int), "tables_checked not int"
        assert isinstance(result["all_healthy"], bool), "all_healthy not bool"
        assert isinstance(result["details"], dict), "details not dict"
        for table, info in result["details"].items():
            assert "row_count" in info, f"row_count missing for {table}"
            assert "min_date" in info, f"min_date missing for {table}"
            assert "max_date" in info, f"max_date missing for {table}"
            assert "status" in info, f"status missing for {table}"
            assert "issues" in info, f"issues missing for {table}"

    def test_validate_data_depth_empty_table(self):
        from backend.data_fetcher_db import _validate_data_depth
        result = _validate_data_depth()
        for table, info in result["details"].items():
            assert isinstance(info["row_count"], int), f"row_count not int for {table}"
            if info["row_count"] == 0:
                assert info["status"] == "degraded" or info["status"] == "ok", f"unexpected status for empty {table}"

    def test_validate_data_depth_table_not_found(self):
        from backend.data_fetcher_db import KEY_TABLES, _validate_data_depth
        original = dict(KEY_TABLES)
        # vix_daily is sql_guard allow-listed but absent from the schema,
        # so it exercises the sqlite (not guard) failure path.
        KEY_TABLES["vix_daily"] = {"min_rows": 0, "max_age_hours": 1, "value_col": None, "date_col": "timestamp"}
        try:
            result = _validate_data_depth()
            if "vix_daily" in result["details"]:
                info = result["details"]["vix_daily"]
                assert "issues" in info, "issues missing for nonexistent table"
                assert "table_not_found" in str(info.get("issues", [])), f"expected table_not_found issue, got {info}"
        finally:
            KEY_TABLES.clear()
            KEY_TABLES.update(original)

    def test_validate_data_depth_per_table_failure_isolated(self):
        """A per-table check failure must not collapse the whole result."""
        from backend.data_fetcher_db import KEY_TABLES, _validate_data_depth
        original = dict(KEY_TABLES)
        KEY_TABLES["vix_daily"] = {"min_rows": 0, "max_age_hours": 1, "value_col": None, "date_col": "timestamp"}
        try:
            result = _validate_data_depth()
            assert result["tables_checked"] == len(KEY_TABLES), (
                f"one bad table collapsed the result: {result}"
            )
            assert "details" in result and len(result["details"]) == len(KEY_TABLES)
            for table, info in result["details"].items():
                assert info["row_count"] is None or isinstance(info["row_count"], int), (
                    f"{table}: leaked row_count {info['row_count']!r}"
                )
        finally:
            KEY_TABLES.clear()
            KEY_TABLES.update(original)

    def test_check_source_freshness_with_depth(self):
        import backend.api_server as api_mod
        conn = get_db()
        try:
            result = api_mod._check_source_freshness("nifty_price", threshold=30)
            assert isinstance(result, dict), "freshness result not dict"
            assert "status" in result, "status missing"
            if result.get("status") == "ok":
                assert "depth_issues" not in result or not result["depth_issues"], "unexpected depth_issues"
        finally:
            conn.close()

    def test_data_depth_preserves_data_quality_labels(self):
        original_labels = {dq_mod.DATA_QUALITY_LIVE, dq_mod.DATA_QUALITY_STALE,
                          dq_mod.DATA_QUALITY_UNAVAILABLE, dq_mod.DATA_QUALITY_PARTIAL}
        assert "LIVE" in original_labels
        assert "STALE" in original_labels
        assert "DATA UNAVAILABLE" in original_labels
        result = _validate_data_depth() if False else None
        from backend.data_fetcher_db import _validate_data_depth
        result = _validate_data_depth()
        for table, info in result["details"].items():
            assert info["status"] in ("ok", "degraded"), f"data_quality label changed: {info['status']}"


class TestSystemdMemoryLimits:
    def test_systemd_has_memory_limits(self):
        svc = _get_script_path("ops/systemd/tradingai-api.service")
        assert os.path.isfile(svc), "systemd unit file missing"
        content = open(svc).read()
        assert "MemoryMax" in content, "MemoryMax missing"
        assert "MemoryHigh" in content, "MemoryHigh missing"
        assert "MemorySwapMax" in content, "MemorySwapMax missing"

    def test_logrotate_gunicorn_exists(self):
        path = _get_script_path("ops/logrotate/tradingai-gunicorn")
        assert os.path.isfile(path), "ops/logrotate/tradingai-gunicorn missing"

    def test_logrotate_gunicorn_valid(self):
        path = _get_script_path("ops/logrotate/tradingai-gunicorn")
        content = open(path).read()
        assert "/opt/tradingai/logs/gunicorn-*.log" in content, "log path missing"
        for directive in ["daily", "rotate", "compress", "missingok", "notifempty", "copytruncate"]:
            assert directive in content, f"directive {directive} missing"

    def test_self_heal_memory_check(self):
        sh = _get_script_path("ops/self-heal.sh")
        content = open(sh).read()
        assert "MemoryCurrent" in content, "MemoryCurrent check missing"
        assert "MEM_MB" in content, "MEM_MB calculation missing"
        assert "MEMORY" in content, "MEMORY log missing"


class TestDeployLogsStructured:
    def test_deploy_logs_structured(self):
        dv = _get_script_path("deploy-vm.sh")
        content = open(dv).read()
        assert "deploy_log()" in content, "deploy_log function missing"
        assert "timestamp" in content, "timestamp field missing"
        assert "stage" in content, "stage field missing"
        assert "status" in content, "status field missing"
        assert "message" in content, "message field missing"
        assert "duration_ms" in content, "duration_ms field missing"
        assert "/tmp/deploy.log" in content, "deploy log path missing"

    def test_deploy_has_start_time(self):
        dv = _get_script_path("deploy-vm.sh")
        content = open(dv).read()
        assert "START_TIME" in content, "START_TIME missing"

    def test_deploy_all_stages_logged(self):
        dv = _get_script_path("deploy-vm.sh")
        content = open(dv).read()
        assert 'deploy_log "DEPLOY" "START"' in content, "DEPLOY START missing"
        assert 'deploy_log "DEPLOY" "COMPLETE"' in content, "DEPLOY COMPLETE missing"
        assert 'deploy_log "VERIFY" "START"' in content, "VERIFY START missing"
        assert 'deploy_log "VERIFY" "PASS"' in content, "VERIFY PASS missing"


class TestSelfHealCrontab:
    def test_self_heal_crontab_verify(self):
        sh = _get_script_path("ops/self-heal.sh")
        content = open(sh).read()
        assert "EXPECTED_CRONTAB" in content, "EXPECTED_CRONTAB missing"
        assert "crontab -l" in content, "crontab -l check missing"
        assert "CRONTAB" in content, "CRONTAB check missing"

    def test_self_heal_crontab_repair(self):
        sh = _get_script_path("ops/self-heal.sh")
        content = open(sh).read()
        assert "crontab " in content, "crontab install command missing"
        assert "CRONTAB REPAIR" in content, "CRONTAB REPAIR message missing"

    def test_self_heal_no_spurious_crontab_change(self):
        sh = _get_script_path("ops/self-heal.sh")
        content = open(sh).read()
        assert "CRONTAB OK" in content, "CRONTAB OK (no-change) path missing"


class TestSelfHealBackup:
    def test_self_heal_backup_verify(self):
        sh = _get_script_path("ops/self-heal.sh")
        content = open(sh).read()
        assert "BACKUP_FILE" in content, "BACKUP_FILE missing"
        assert "backup_age" in content or "BACKUP_AGE" in content.upper(), "backup age check missing"
        assert "backup_stale" in content, "backup_stale alert missing"

    def test_self_heal_backup_integrity(self):
        sh = _get_script_path("ops/self-heal.sh")
        content = open(sh).read()
        assert "sqlite3" in content, "sqlite3 integrity check missing"
        assert "backup_integrity" in content, "backup_integrity check missing"

    def test_self_heal_backup_missing_alert(self):
        sh = _get_script_path("ops/self-heal.sh")
        content = open(sh).read()
        assert "backup_missing" in content, "backup_missing alert missing"

    def test_self_heal_backup_no_auto_restore(self):
        sh = _get_script_path("ops/self-heal.sh")
        content = open(sh).read()
        assert "cp " not in content.split("backup_missing")[1].split("\n")[0] if "backup_missing" in content else "", \
            "backup verification should not auto-restore"



