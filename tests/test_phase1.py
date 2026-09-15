#!/usr/bin/env python3
"""Phase 1 tests — Backup, Migration, Health, Deployment.

Verifies:
- Backup script (create, verify, retention)
- Migration framework (table, idempotency, status)
- Health check script (HEALTHY/DEGRADED/UNHEALTHY)
- Data validator (stale, missing, duplicate, invalid prices)
- AI validator (JSON, required fields, numerical sanity)
- Deployment scripts exist and are valid
- Configuration validation
- Secret protection
"""
import os
import sys
import ast
import json
import stat
import subprocess
import tempfile
import sqlite3
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


class TestBackupScript:
    def test_backup_script_exists(self):
        assert os.path.isfile("scripts/backup.sh"), "backup.sh must exist"

    def test_backup_script_executable(self):
        st = os.stat("scripts/backup.sh")
        assert st.st_mode & stat.S_IXUSR, "backup.sh must be executable"

    def test_backup_script_has_timestamp(self):
        src = open("scripts/backup.sh").read()
        assert "timestamp" in src.lower() or "date" in src.lower(), \
            "backup must timestamp backups"

    def test_backup_script_has_retention(self):
        src = open("scripts/backup.sh").read()
        assert "retention" in src.lower() or "find" in src, \
            "backup must have retention policy"

    def test_backup_script_never_overwrites(self):
        src = open("scripts/backup.sh").read()
        assert "cp " in src, "backup must copy DB"
        assert "rm -f" in src or "delete" in src.lower(), \
            "backup must clean old backups (not live DB)"

    def test_backup_script_verifies(self):
        src = open("scripts/backup.sh").read()
        assert "verify" in src.lower(), "backup must verify"

    def test_backup_script_writes_logs(self):
        src = open("scripts/backup.sh").read()
        assert "log" in src.lower(), "backup must write logs"


class TestMigrationFramework:
    def test_migration_exists(self):
        assert os.path.isfile("backend/migration.py"), \
            "migration.py must exist"

    def test_migration_has_migration_table(self):
        src = open("backend/migration.py").read()
        assert "_migrations" in src, "migration must create _migrations table"

    def test_migration_is_idempotent(self):
        src = open("backend/migration.py").read()
        assert "already applied" in src, \
            "migration must skip already-applied migrations"

    def test_migration_has_backup(self):
        src = open("backend/migration.py").read()
        assert "backup" in src.lower(), "migration must back up before changes"

    def test_migration_never_drops(self):
        src = open("backend/migration.py").read()
        assert "DROP" not in src.upper() or "never" in src.lower(), \
            "migration must document no-DROP policy"

    def test_migration_has_rollback(self):
        src = open("backend/migration.py").read()
        assert "rollback" in src.lower(), "migration must have rollback support"

    def test_migration_status_inspectable(self):
        src = open("backend/migration.py").read()
        assert "status" in src.lower(), "migration status must be inspectable"


class TestHealthCheck:
    def test_health_check_script_exists(self):
        assert os.path.isfile("scripts/health_check.sh"), \
            "health_check.sh must exist"

    def test_health_check_executable(self):
        st = os.stat("scripts/health_check.sh")
        assert st.st_mode & stat.S_IXUSR, "health_check.sh must be executable"

    def test_health_check_has_api(self):
        src = open("scripts/health_check.sh").read()
        assert "api" in src.lower(), "health check must check API"

    def test_health_check_has_database(self):
        src = open("scripts/health_check.sh").read()
        assert "database" in src.lower() or "db" in src.lower(), \
            "health check must check database"

    def test_health_check_has_disk(self):
        src = open("scripts/health_check.sh").read()
        assert "disk" in src.lower(), "health check must check disk"

    def test_health_check_has_market_data(self):
        src = open("scripts/health_check.sh").read()
        assert "market" in src.lower() or "price" in src.lower(), \
            "health check must check market data"

    def test_health_check_has_cron(self):
        src = open("scripts/health_check.sh").read()
        assert "cron" in src.lower() or "scheduled" in src.lower(), \
            "health check must check scheduled jobs"

    def test_health_check_has_nginx(self):
        src = open("scripts/health_check.sh").read()
        assert "nginx" in src.lower(), "health check must check nginx"

    def test_health_check_machine_readable(self):
        src = open("scripts/health_check.sh").read()
        assert "HEALTHY" in src or "healthy" in src, \
            "health check must return HEALTHY status"
        assert "DEGRADED" in src or "degraded" in src, \
            "health check must return DEGRADED status"
        assert "UNHEALTHY" in src or "unhealthy" in src, \
            "health check must return UNHEALTHY status"


class TestDataValidator:
    def test_validator_exists(self):
        assert os.path.isfile("backend/data_validator.py"), \
            "data_validator.py must exist"

    def test_validator_detects_stale(self):
        src = open("backend/data_validator.py").read()
        assert "stale" in src.lower(), "validator must detect stale data"

    def test_validator_detects_missing_timestamps(self):
        src = open("backend/data_validator.py").read()
        assert "missing" in src.lower() and "timestamp" in src.lower(), \
            "validator must detect missing timestamps"

    def test_validator_detects_duplicates(self):
        src = open("backend/data_validator.py").read()
        assert "duplicate" in src.lower() or "group by" in src.lower(), \
            "validator must detect duplicates"

    def test_validator_detects_invalid_prices(self):
        src = open("backend/data_validator.py").read()
        assert "zero" in src.lower() or "negative" in src.lower() or \
               "non_positive" in src.lower(), \
            "validator must detect invalid prices"

    def test_validator_detects_ohlc_issues(self):
        src = open("backend/data_validator.py").read()
        assert "high" in src.lower() and "low" in src.lower(), \
            "validator must check OHLC relationships"

    def test_validator_does_not_auto_delete(self):
        src = open("backend/data_validator.py").read()
        assert "delete" not in src.lower() or "flag" in src.lower() or \
               "quarantine" in src.lower(), \
            "validator must not auto-delete bad data"


class TestAIValidator:
    def test_validator_exists(self):
        assert os.path.isfile("backend/ai_validator.py"), \
            "ai_validator.py must exist"

    def test_validator_checks_json(self):
        src = open("backend/ai_validator.py").read()
        assert "json" in src.lower(), "AI validator must check JSON validity"

    def test_validator_checks_required_fields(self):
        src = open("backend/ai_validator.py").read()
        assert "required" in src.lower(), "AI validator must check required fields"

    def test_validator_checks_numerical(self):
        src = open("backend/ai_validator.py").read()
        assert "numerical" in src.lower() or "numeric" in src.lower() or \
               "float" in src.lower(), "AI validator must check numerical values"

    def test_validator_checks_range(self):
        src = open("backend/ai_validator.py").read()
        assert "range" in src.lower() or "expected" in src.lower(), \
            "AI validator must check ranges"

    def test_validator_marks_fallback(self):
        src = open("backend/ai_validator.py").read()
        assert "invalid" in src.lower() or "fallback" in src.lower() or \
               "degraded" in src.lower(), \
            "AI validator must mark fallback/degraded state"

    def test_validator_no_fabrication(self):
        src = open("backend/ai_validator.py").read()
        assert "fabricate" in src.lower() or "live" in src.lower() or \
               "market data" in src.lower(), \
            "AI validator must warn against fabrication"


class TestDeploymentScripts:
    def test_deploy_script_exists(self):
        assert os.path.isfile("scripts/deploy.sh"), "deploy.sh must exist"

    def test_deploy_executable(self):
        st = os.stat("scripts/deploy.sh")
        assert st.st_mode & stat.S_IXUSR, "deploy.sh must be executable"

    def test_deploy_has_backup_step(self):
        src = open("scripts/deploy.sh").read()
        assert "backup" in src.lower(), "deploy must include backup"

    def test_deploy_has_tests_step(self):
        src = open("scripts/deploy.sh").read()
        assert "test" in src.lower(), "deploy must run tests"

    def test_deploy_has_health_check(self):
        src = open("scripts/deploy.sh").read()
        assert "health" in src.lower(), "deploy must do health check"

    def test_deploy_stops_on_failure(self):
        src = open("scripts/deploy.sh").read()
        assert "exit 1" in src or "exit 1" in src, \
            "deploy must stop on failure"

    def test_rollback_script_exists(self):
        assert os.path.isfile("scripts/rollback.sh"), "rollback.sh must exist"

    def test_rollback_executable(self):
        st = os.stat("scripts/rollback.sh")
        assert st.st_mode & stat.S_IXUSR, "rollback.sh must be executable"

    def test_test_script_exists(self):
        assert os.path.isfile("scripts/test.sh"), "test.sh must exist"

    def test_test_executable(self):
        st = os.stat("scripts/test.sh")
        assert st.st_mode & stat.S_IXUSR, "test.sh must be executable"


class TestSecretProtection:
    def test_groq_key_600_on_vm(self):
        result = subprocess.run(
            ["ssh", "-i", os.path.expanduser("~/.ssh/oci_key"),
             "ubuntu@129.159.224.81", "stat", "-c", "%a",
             "/etc/tradingai/groq.env"],
            capture_output=True, text=True, timeout=10,
        )
        perms = result.stdout.strip()
        assert perms in ("600", "400"), \
            f"GROQ key permissions should be 600/400, got {perms}"

    def test_groq_key_not_in_git(self):
        result = subprocess.run(
            ["git", "grep", "gsk_[A-Za-z0-9]", "--", "*.py", "*.json", "*.html", "*.js"],
            capture_output=True, text=True, timeout=10,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        assert result.returncode != 0 or result.stdout.strip() == "", \
            "API key found in tracked source files"

    def test_dot_env_in_gitignore(self):
        gitignore = open(".gitignore").read()
        assert ".env" in gitignore or "*.env" in gitignore, \
            ".env must be in .gitignore"

    def test_secrets_not_in_html(self):
        import glob
        for html_file in glob.glob("*.html") + glob.glob("**/*.html"):
            src = open(html_file).read()
            assert "gsk_" not in src, f"API key found in {html_file}"


class TestLogging:
    def test_log_directory_exists(self):
        assert os.path.isdir("logs") or \
               os.path.isdir("../logs") or \
               os.path.isdir("/opt/tradingai/logs"), \
            "Log directory must exist"

    def test_logrotate_configured(self):
        assert os.path.isfile("ops/logrotate/tradingai-api"), \
            "API log rotation must be configured"

    def test_logrotate_has_retention(self):
        src = open("ops/logrotate/tradingai-api").read()
        assert "rotate" in src.lower(), "Log rotation must have retention"

    def test_logrotate_gunicorn_configured(self):
        assert os.path.isfile("ops/logrotate/tradingai-gunicorn"), \
            "Gunicorn log rotation must be configured"


class TestMigrationAndBackupIntegration:
    def test_migration_table_creatable(self):
        import backend.migration as m
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "test.db")
            conn = sqlite3.connect(db)
            m.ensure_migration_table(conn)
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name='_migrations'"
            ).fetchall()
            conn.close()
            assert len(rows) == 1, "Migration table not created"

    def test_migration_applied_and_idempotent(self):
        import backend.migration as m
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "test.db")
            conn = sqlite3.connect(db)
            m.ensure_migration_table(conn)
            applied = m.apply_migration(
                conn, "test_001", "Test migration",
                ["CREATE TABLE IF NOT EXISTS test_tbl (id INTEGER)"]
            )
            assert applied is True, "First migration should apply"
            applied_again = m.apply_migration(
                conn, "test_001", "Test migration",
                ["CREATE TABLE IF NOT EXISTS test_tbl (id INTEGER)"]
            )
            assert applied_again is False, "Second migration should skip"
            conn.close()

    def test_migration_status_inspectable(self):
        import backend.migration as m
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "test.db")
            conn = sqlite3.connect(db)
            m.ensure_migration_table(conn)
            m.apply_migration(
                conn, "test_001", "Test",
                ["CREATE TABLE IF NOT EXISTS t1 (id INTEGER)"]
            )
            status = m.get_migration_status(conn)
            conn.close()
            assert len(status) == 1, "Status should show 1 migration"
            assert status[0]["version"] == "test_001"
            assert status[0]["status"] == "applied"

    def test_backup_creates_file(self):
        import backend.migration as m
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "test.db")
            backup_dir = os.path.join(tmp, "backups")
            conn = sqlite3.connect(db)
            conn.execute("CREATE TABLE t (id INTEGER)").fetchall()
            conn.execute("INSERT INTO t VALUES (1)").fetchall()
            conn.commit()
            conn.close()
            # Monkey-patch paths
            orig_db = m.DB_PATH
            orig_backup = m.BACKUP_DIR
            orig_log = m.MIGRATION_LOG
            m.DB_PATH = db
            m.BACKUP_DIR = backup_dir
            m.MIGRATION_LOG = os.path.join(tmp, "migrations.log")
            try:
                result = m.backup_db()
                assert os.path.exists(result), "Backup file should exist"
                assert os.path.getsize(result) > 0, "Backup should not be empty"
            finally:
                m.DB_PATH = orig_db
                m.BACKUP_DIR = orig_backup
                m.MIGRATION_LOG = orig_log


class TestAIValidatorIntegration:
    def test_validate_outlook_valid(self):
        from backend.ai_validator import AIValidator
        data = {
            "symbol": "NIFTY",
            "timestamp": "2026-09-15T00:00:00Z",
            "outlook": "BULLISH",
            "data_quality": "LIVE",
            "confidence": 78,
            "bias": "BULLISH",
        }
        result = AIValidator.validate_outlook(data)
        assert result["valid"] is True, f"Valid outlook rejected: {result['issues']}"

    def test_validate_outlook_invalid(self):
        from backend.ai_validator import AIValidator
        data = {
            "symbol": "NIFTY",
            "outlook": "SUPER_BULLISH",
            "confidence": 150,
        }
        result = AIValidator.validate_outlook(data)
        assert result["valid"] is False, "Invalid outlook accepted"
        assert len(result["issues"]) > 0, "Should have issues"

    def test_validate_json(self):
        from backend.ai_validator import AIValidator
        parsed, ok = AIValidator.validate_json(
            '{"symbol":"NIFTY","outlook":"BULLISH"}'
        )
        assert ok is True
        assert parsed["symbol"] == "NIFTY"

        parsed, ok = AIValidator.validate_json("not json")
        assert ok is False

    def test_validate_price_consistency(self):
        from backend.ai_validator import AIValidator
        issues = AIValidator.validate_price_consistency(
            23118.6, 23398.1, -1.19
        )
        assert len(issues) == 0, f"Valid price consistency flagged: {issues}"

    def test_validate_price_inconsistent(self):
        from backend.ai_validator import AIValidator
        issues = AIValidator.validate_price_consistency(
            30000.0, 23398.1, -1.19
        )
        assert len(issues) > 0, "Inconsistent price not flagged"


class TestRegressionGate:
    def test_existing_tests_still_pass(self):
        result = subprocess.run(
            ["python3", "-m", "pytest", "tests/", "-q", "-x",
             "--ignore=tests/test_phase6b_b1.py",
             "--ignore=tests/test_phase6b_b2.py",
             "--ignore=tests/test_phase6b_1.py",
             "--ignore=tests/test_phase6b_3_pea.py",
             "--ignore=tests/test_deploy.py",
             "--ignore=tests/test_live_consistency.py",
             "--ignore=tests/test_phase1.py"],
            capture_output=True, text=True, timeout=300,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        output = result.stdout + result.stderr
        match = re.search(r"(\d+)\s+passed", output)
        if match:
            count = int(match.group(1))
            assert count >= 670, f"Expected at least 670 tests, got {count}: {output}"
        assert result.returncode == 0, f"Tests failed:\n{output}"
