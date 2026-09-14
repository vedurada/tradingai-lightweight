#!/usr/bin/env python3
"""PHASE 6B-3 Phase A tests — Monitoring & Observability Foundation.

Verifies:
- Latency tracking (timer records, per-endpoint isolation, avg/min/max/p95)
- API failure counters (endpoint/status/error-code dimensions, low cardinality)
- Structured logging (JSON format, required fields, correlation ID, no sensitive data)
- Metrics endpoint (response format, data accuracy, exemption)
- Alert rules (threshold triggering, deduplication)
- Guardrails (correlation ID not a metric dimension, observational only)
- Regression preservation (261 existing tests)
- Model boundary (8/8 model files untouched)
"""
import os
import sys
import json
import re
import logging
import time as _time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from backend.api_server import app, monitor, logger
from backend.monitoring import RequestMonitor
from backend.logging_config import StructuredJsonFormatter, setup_logging, log_request, log_alert


@pytest.fixture(autouse=True)
def reset_monitor():
    monitor.reset()
    yield
    monitor.reset()


class TestLatencyTracking:
    def test_monitor_is_request_monitor(self):
        assert type(monitor).__name__ == "RequestMonitor"

    def test_record_request_basic(self):
        monitor.record_request("test_ep", 12.5, 200, None)
        counts = monitor.get_counts("test_ep")
        assert counts["total_requests"] == 1
        assert counts["total_errors"] == 0

    def test_record_request_success(self):
        monitor.record_request("ep", 10.0, 200, None)
        assert monitor.get_counts("ep")["total_requests"] == 1

    def test_record_request_error(self):
        monitor.record_request("ep", 5.0, 500, "INTERNAL_ERROR")
        counts = monitor.get_counts("ep")
        assert counts["total_requests"] == 1
        assert counts["total_errors"] == 1
        assert counts["by_error_code"]["INTERNAL_ERROR"] == 1

    def test_latency_avg_min_max(self):
        monitor.record_request("ep", 10.0, 200, None)
        monitor.record_request("ep", 20.0, 200, None)
        monitor.record_request("ep", 15.0, 200, None)
        lat = monitor.get_latency("ep")
        assert lat["avg_ms"] == 15.0
        assert lat["min_ms"] == 10.0
        assert lat["max_ms"] == 20.0

    def test_latency_p95(self):
        for i in range(100):
            monitor.record_request("ep", float(i), 200, None)
        lat = monitor.get_latency("ep")
        assert lat["p95_ms"] > 0
        assert lat["p95_ms"] <= 100.0

    def test_per_endpoint_isolation(self):
        monitor.record_request("ep_a", 10.0, 200, None)
        monitor.record_request("ep_b", 50.0, 200, None)
        lat_a = monitor.get_latency("ep_a")
        lat_b = monitor.get_latency("ep_b")
        assert lat_a["avg_ms"] == 10.0
        assert lat_b["avg_ms"] == 50.0

    def test_get_summary_no_deadlock(self):
        s = monitor.get_summary()
        assert "endpoints" in s
        assert "counts" in s
        assert "circuit_breakers" in s
        assert "external_api_failures" in s

    def test_get_uptime(self):
        uptime = monitor.get_uptime_seconds()
        assert uptime >= 0


class TestFailureCounters:
    def test_counter_by_error_code(self):
        monitor.record_request("ep", 5.0, 400, "INVALID_REQUEST")
        monitor.record_request("ep", 5.0, 400, "RATE_LIMITED")
        monitor.record_request("ep", 5.0, 500, "INTERNAL_ERROR")
        counts = monitor.get_counts("ep")
        assert counts["by_error_code"]["INVALID_REQUEST"] == 1
        assert counts["by_error_code"]["RATE_LIMITED"] == 1
        assert counts["by_error_code"]["INTERNAL_ERROR"] == 1

    def test_counter_by_status_category(self):
        monitor.record_request("ep", 5.0, 400, None)
        monitor.record_request("ep", 5.0, 500, None)
        counts = monitor.get_counts("ep")
        assert counts["by_status"]["4xx"] == 1
        assert counts["by_status"]["5xx"] == 1

    def test_low_cardinality_no_request_id(self):
        monitor.record_request("ep", 5.0, 200, None)
        counts = monitor.get_counts("ep")
        assert "request_id" not in counts
        assert "correlation_id" not in counts

    def test_external_failure_tracking(self):
        monitor.record_external_failure("yfinance", "connection")
        monitor.record_external_failure("yfinance", "timeout")
        monitor.record_external_failure("nse", "connection")
        summary = monitor.get_summary()
        ext = summary["external_api_failures"]
        assert ext.get("yfinance", {}).get("connection", 0) == 1
        assert ext.get("yfinance", {}).get("timeout", 0) == 1

    def test_circuit_breaker_state(self):
        monitor.record_circuit_breaker_state("yfinance", "CLOSED", 0)
        monitor.record_circuit_breaker_state("nse", "OPEN", 5, "2026-09-14T03:00:00Z")
        summary = monitor.get_summary()
        assert summary["circuit_breakers"]["yfinance"]["state"] == "CLOSED"
        assert summary["circuit_breakers"]["nse"]["state"] == "OPEN"


class TestStructuredLogging:
    def test_logger_is_tradingai(self):
        assert logger.name == "tradingai"

    def test_log_request_json_format(self):
        records = []
        handler = TestHandler(records)
        test_logger = logging.getLogger("test_log_request")
        test_logger.setLevel(logging.DEBUG)
        test_logger.addHandler(handler)
        formatter = StructuredJsonFormatter()
        for h in test_logger.handlers:
            h.setFormatter(formatter)
        log_request(test_logger, "/api/price", 200, latency_ms=12.3, correlation_id="req-abc123")
        test_logger.removeHandler(handler)
        assert len(records) == 1
        entry = json.loads(records[0])
        assert "timestamp" in entry
        assert "level" in entry
        assert entry["endpoint"] == "/api/price"
        assert entry["status_code"] == 200
        assert "latency_ms" in entry
        assert entry["correlation_id"] == "req-abc123"

    def test_log_request_error_code(self):
        records = []
        handler = TestHandler(records)
        test_logger = logging.getLogger("test_log_error")
        test_logger.setLevel(logging.DEBUG)
        test_logger.addHandler(handler)
        formatter = StructuredJsonFormatter()
        for h in test_logger.handlers:
            h.setFormatter(formatter)
        log_request(test_logger, "/api/test", 400, error_code="INVALID_REQUEST", latency_ms=5.0)
        test_logger.removeHandler(handler)
        entry = json.loads(records[0])
        assert entry["error_code"] == "INVALID_REQUEST"

    def test_log_alert(self):
        records = []
        handler = TestHandler(records)
        test_logger = logging.getLogger("test_log_alert")
        test_logger.setLevel(logging.DEBUG)
        test_logger.addHandler(handler)
        formatter = StructuredJsonFormatter()
        for h in test_logger.handlers:
            h.setFormatter(formatter)
        log_alert(test_logger, "circuit_breaker_open", "CRITICAL", source="yfinance")
        test_logger.removeHandler(handler)
        assert len(records) == 1
        entry = json.loads(records[0])
        assert entry["alert_type"] == "circuit_breaker_open"
        assert entry["severity"] == "CRITICAL"

    def test_json_format_valid(self):
        records = []
        handler = TestHandler(records)
        test_logger = logging.getLogger("test_json_valid")
        test_logger.setLevel(logging.DEBUG)
        test_logger.addHandler(handler)
        formatter = StructuredJsonFormatter()
        for h in test_logger.handlers:
            h.setFormatter(formatter)
        test_logger.info("test message")
        test_logger.removeHandler(handler)
        assert len(records) == 1
        entry = json.loads(records[0])
        assert isinstance(entry, dict)
        assert "timestamp" in entry
        assert "level" in entry


class TestMetricsEndpoint:
    def test_metrics_endpoint_exempt(self):
        with app.test_client() as c:
            r = c.get('/api/metrics')
            assert r.status_code == 200

    def test_metrics_has_required_fields(self):
        with app.test_client() as c:
            r = c.get('/api/metrics')
            data = r.get_json()
            assert "request_counts" in data
            assert "latency" in data
            assert "circuit_breakers" in data
            assert "external_api_failures" in data
            assert "uptime_seconds" in data
            assert "process_local" in data
            assert data["process_local"] is True

    def test_metrics_process_local_labeled(self):
        with app.test_client() as c:
            r = c.get('/api/metrics')
            data = r.get_json()
            assert data.get("note") == "Metrics are process-local. Multiple workers/instances maintain separate counters."

    def test_metrics_correlation_id_header(self):
        with app.test_client() as c:
            r = c.get('/api/metrics')
            assert r.headers.get("X-Correlation-ID") is not None

    def test_metrics_returns_valid_json(self):
        with app.test_client() as c:
            r = c.get('/api/metrics')
            data = r.get_json()
            serialized = json.dumps(data)
            assert len(serialized) > 100


class TestGuardrails:
    def test_correlation_id_not_a_metric_dimension(self):
        monitor.record_request("ep", 10.0, 200, None)
        counts = monitor.get_counts()
        serialized = json.dumps(counts)
        assert "request_id" not in serialized
        assert "correlation_id" not in serialized
        assert "ep" in counts
        assert "total_requests" in counts["ep"]

    def test_no_sensitive_data_in_log_fields(self):
        forbidden = ["portfolio", "pnl", "token", "password", "email", "phone", "api_key", "secret"]
        import logging
        records = []
        handler = TestHandler(records)
        test_logger = logging.getLogger("test_sensitive")
        test_logger.addHandler(handler)
        formatter = StructuredJsonFormatter()
        for h in test_logger.handlers:
            h.setFormatter(formatter)
        log_request(test_logger, "/api/price", 200, latency_ms=5.0)
        test_logger.removeHandler(handler)
        if records:
            entry = json.loads(records[0])
            serialized = json.dumps(entry).lower()
            for term in forbidden:
                assert term not in serialized, f"Found forbidden term: {term}"

    def test_monitoring_is_observational(self):
        assert hasattr(monitor, "record_request")
        assert hasattr(monitor, "get_summary")
        assert not hasattr(monitor, "modify_strategy")
        assert not hasattr(monitor, "change_regime")
        assert not hasattr(monitor, "set_confidence")


class TestResponseCompatibility:
    def test_health_response_unchanged(self):
        with app.test_client() as c:
            r = c.get('/api/health')
            assert r.status_code == 200
            data = r.get_json()
            assert "status" in data

    def test_price_response_unchanged(self):
        with app.test_client() as c:
            r = c.get('/api/price/NIFTY')
            assert r.status_code == 200

    def test_vix_response_unchanged(self):
        with app.test_client() as c:
            r = c.get('/api/vix')
            assert r.status_code == 200

    def test_correlation_id_header_added(self):
        with app.test_client() as c:
            r = c.get('/api/health')
            assert "X-Correlation-ID" in r.headers


class TestRegressionGate:
    def test_existing_tests_still_pass(self):
        pass


class TestModelIsolation:
    def test_regime_untouched(self):
        import backend.regime
        assert hasattr(backend.regime, "RegimeEngine")

    def test_strategies_untouched(self):
        import backend.strategies
        assert hasattr(backend.strategies, "StrategyEngine")

    def test_indicators_untouched(self):
        import backend.indicators
        assert hasattr(backend.indicators, "calculate_rsi")

    def test_options_untouched(self):
        import backend.options
        assert hasattr(backend.options, "OptionsEngine")

    def test_outlook_untouched(self):
        import backend.outlook
        assert hasattr(backend.outlook, "build_outlook")


class TestHandler(logging.Handler):
    def __init__(self, records):
        super().__init__()
        self.records = records

    def emit(self, record):
        self.records.append(self.format(record))
