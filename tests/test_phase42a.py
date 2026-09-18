from __future__ import annotations

import os
import sys
import tempfile
import sqlite3
import json
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from db_schema import init_database
from research_collector import (
    ResearchCollector,
    generate_setup_id,
    generate_setup_fingerprint,
    ENGINE_VERSION,
)
from research_exports import ResearchExporter
from deploy_validator import PAGE_IDENTITY_MARKERS, generate_expected_manifest, generate_page_hash

TEST_DB = os.path.join(tempfile.gettempdir(), f"tradingai_test_phase42a_{int(time.time())}.db")


def _unique_ts():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(time.time()*1000000)%1000000:06d}Z"


def setup_module():
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    init_database(TEST_DB)


def teardown_module():
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)


def get_collector():
    return ResearchCollector(TEST_DB)


def get_exporter():
    return ResearchExporter(TEST_DB)


class TestPhase42ASchema:
    def setup_method(self):
        setup_module()

    def teardown_method(self):
        teardown_module()
        setup_module()

    def test_research_setup_identity_table_exists(self):
        conn = sqlite3.connect(TEST_DB)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        conn.close()
        assert "research_setup_identity" in tables

    def test_research_reentry_log_table_exists(self):
        conn = sqlite3.connect(TEST_DB)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        conn.close()
        assert "research_reentry_log" in tables

    def test_research_ai_call_log_table_exists(self):
        conn = sqlite3.connect(TEST_DB)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        conn.close()
        assert "research_ai_call_log" in tables

    def test_research_outcome_tracking_table_exists(self):
        conn = sqlite3.connect(TEST_DB)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        conn.close()
        assert "research_outcome_tracking" in tables

    def test_research_data_health_table_exists(self):
        conn = sqlite3.connect(TEST_DB)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        conn.close()
        assert "research_data_health" in tables

    def test_research_manifest_table_exists(self):
        conn = sqlite3.connect(TEST_DB)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        conn.close()
        assert "research_manifest" in tables


class TestSetupIdentity:
    def setup_method(self):
        setup_module()

    def teardown_method(self):
        teardown_module()
        setup_module()

    def test_setup_id_deterministic(self):
        sid1 = generate_setup_id("NIFTY", "2026-09-17T10:00:00Z", "BULLISH")
        sid2 = generate_setup_id("NIFTY", "2026-09-17T10:00:00Z", "BULLISH")
        assert sid1 == sid2

    def test_setup_id_unique(self):
        sid1 = generate_setup_id("NIFTY", "2026-09-17T10:00:00Z", "BULLISH")
        sid2 = generate_setup_id("NIFTY", "2026-09-17T10:01:00Z", "BULLISH")
        assert sid1 != sid2

    def test_fingerprint_deterministic(self):
        fp1 = generate_setup_fingerprint("NIFTY", "2026-09-17", "BULLISH", "BULLISH", "TRADE", "CALL_DEBIT_SPREAD", "{}", "")
        fp2 = generate_setup_fingerprint("NIFTY", "2026-09-17", "BULLISH", "BULLISH", "TRADE", "CALL_DEBIT_SPREAD", "{}", "")
        assert fp1 == fp2

    def test_record_setup_identity(self):
        collector = get_collector()
        result = collector.record_setup_identity(
            instrument="NIFTY",
            candle_timestamp=_unique_ts(),
            direction="BULLISH",
            regime="BULLISH",
            trade_state="TRADE",
            strategy="CALL_DEBIT_SPREAD",
            evidence_summary={"trend": "BULLISH"},
            ai_outlook_id="OUT-TEST",
        )
        assert result["created"] is True
        assert "setup_id" in result
        assert "setup_fingerprint" in result

    def test_setup_no_future_fields(self):
        fp = generate_setup_fingerprint("NIFTY", "2026-09-17", "BULLISH", "BULLISH", "TRADE", "STRATEGY", "", "")
        assert "2026-09-18" not in fp
        assert "future" not in fp.lower()

    def test_setup_id_contains_required_fields(self):
        collector = get_collector()
        ts = _unique_ts()
        result = collector.record_setup_identity(
            instrument="NIFTY",
            candle_timestamp=ts,
            direction="BULLISH",
            regime="BULLISH",
            trade_state="TRADE",
            strategy="CALL_DEBIT_SPREAD",
        )
        setup_id = result["setup_id"]
        assert setup_id.startswith("SETUP-")
        stored = collector.get_setup_by_fingerprint(result["setup_fingerprint"])
        assert stored is not None
        assert stored["instrument"] == "NIFTY"
        assert stored["candle_timestamp"] == ts


class TestReentryInstrumentation:
    def setup_method(self):
        setup_module()

    def teardown_method(self):
        teardown_module()
        setup_module()

    def test_record_reentry(self):
        collector = get_collector()
        result = collector.record_reentry(
            trade_id="PT-TEST-001",
            instrument="NIFTY",
            candle_timestamp=_unique_ts(),
            setup_id="SETUP-TEST-001",
            previous_trade_id="PT-TEST-000",
            previous_exit_timestamp=_unique_ts(),
            seconds_since_previous_exit=120,
            previous_direction="BULLISH",
            current_direction="BULLISH",
            previous_regime="BULLISH",
            current_regime="BULLISH",
            same_setup_fingerprint=1,
            direction_changed=0,
            regime_changed=0,
            reentry_type="SAME_SETUP",
        )
        assert result["recorded"] is True

    def test_reentry_no_classification(self):
        collector = get_collector()
        result = collector.record_reentry(
            trade_id="PT-TEST-002",
            instrument="NIFTY",
            candle_timestamp=_unique_ts(),
            setup_id="SETUP-TEST-002",
            reentry_type="UNKNOWN",
        )
        assert result["recorded"] is True


class TestAILogging:
    def setup_method(self):
        setup_module()

    def teardown_method(self):
        teardown_module()
        setup_module()

    def test_record_ai_call(self):
        collector = get_collector()
        result = collector.record_ai_call(
            instrument="NIFTY",
            candle_timestamp=_unique_ts(),
            trigger="MATERIAL_CHANGE",
            model="groq",
            provider="groq",
            prompt_version="5m-v1",
            success=1,
            latency_ms=150,
            token_usage=500,
        )
        assert result["recorded"] is True

    def test_record_ai_call_failure(self):
        collector = get_collector()
        result = collector.record_ai_call(
            instrument="NIFTY",
            candle_timestamp=_unique_ts(),
            trigger="MATERIAL_CHANGE",
            success=0,
            error="LLM timeout",
            fallback_used=1,
        )
        assert result["recorded"] is True

    def test_no_fake_ai_history(self):
        collector = get_collector()
        conn = sqlite3.connect(TEST_DB)
        rows = conn.execute(
            "SELECT COUNT(*) FROM research_ai_call_log WHERE call_timestamp IS NULL"
        ).fetchone()[0]
        conn.close()
        assert rows == 0


class TestOutcomeTracking:
    def setup_method(self):
        setup_module()

    def teardown_method(self):
        teardown_module()
        setup_module()

    def test_record_outcome_separate_from_decision(self):
        collector = get_collector()
        result = collector.record_outcome(
            outlook_id="OUT-TEST-001",
            setup_id="SETUP-TEST-001",
            instrument="NIFTY",
            candle_timestamp=_unique_ts(),
            outcome_5m="WIN",
            outcome_5m_timestamp=_unique_ts(),
            outcome_5m_price=23200,
            outcome_5m_return_pct=0.5,
            outcome_5m_direction="BULLISH",
        )
        assert result["recorded"] is True


class TestDataQuality:
    def setup_method(self):
        setup_module()

    def teardown_method(self):
        teardown_module()
        setup_module()

    def test_record_health_valid(self):
        collector = get_collector()
        result = collector.record_data_health(
            check_type="candle_completeness",
            status="VALID",
            instrument="NIFTY",
            detail="All 5m candles present",
        )
        assert result["recorded"] is True

    def test_record_health_stale(self):
        collector = get_collector()
        result = collector.record_data_health(
            check_type="candle_completeness",
            status="STALE",
            instrument="NIFTY",
            detail="Last candle older than 10 minutes",
        )
        assert result["recorded"] is True


class TestResearchExports:
    def setup_method(self):
        setup_module()

    def teardown_method(self):
        teardown_module()
        setup_module()

    def test_export_setup_identity_empty(self):
        exporter = get_exporter()
        data = exporter.export_setup_identity(limit=10)
        assert isinstance(data, list)

    def test_export_summary(self):
        exporter = get_exporter()
        summary = exporter.export_summary()
        assert "research_setup_identity" in summary
        assert "research_reentry_log" in summary
        assert "research_ai_call_log" in summary

    def test_export_manifest(self):
        exporter = get_exporter()
        manifest = exporter.export_manifest()
        assert isinstance(manifest, list)

    def test_get_research_datasets_info(self):
        exporter = get_exporter()
        datasets = exporter.get_research_datasets_info()
        assert len(datasets) > 0
        dataset_names = [d["name"] for d in datasets]
        assert "setup_research" in dataset_names
        assert "outcome_research" in dataset_names


class TestDeployValidation:
    def test_page_identity_markers_defined(self):
        assert "index.html" in PAGE_IDENTITY_MARKERS
        assert "today/index.html" in PAGE_IDENTITY_MARKERS
        assert "indices/nifty.html" in PAGE_IDENTITY_MARKERS
        assert "indices/banknifty.html" in PAGE_IDENTITY_MARKERS

    def test_generate_page_hash(self):
        h1 = generate_page_hash("test content")
        h2 = generate_page_hash("test content")
        h3 = generate_page_hash("different content")
        assert h1 == h2
        assert h1 != h3

    def test_generate_expected_manifest(self):
        pages_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        manifest = generate_expected_manifest(pages_dir)
        assert isinstance(manifest, dict)


class TestTimeStandards:
    def test_utc_timestamp_format(self):
        from research_collector import _now_utc
        ts = _now_utc()
        assert ts.endswith("Z")
        assert len(ts) == 20

    def test_setup_id_no_future_info(self):
        sid = generate_setup_id("NIFTY", "2026-09-17T10:00:00Z", "BULLISH")
        assert "2026" in sid or "SETUP" in sid
        assert generate_setup_id("NIFTY", "2026-09-17T10:00:00Z", "BULLISH") == sid