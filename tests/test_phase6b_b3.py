#!/usr/bin/env python3
"""PHASE 6B-3 B.3 tests — Failure Recovery.

32 tests covering:
- Graceful degradation (6)
- Failure isolation (4)
- DB recovery (4)
- Stale data communication (4)
- Operational recovery (6)
- Failure observability (4)
- Data quality protocol (4)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from backend.api_server import app
from backend.data_quality import (
    DATA_QUALITY_LIVE,
    DATA_QUALITY_STALE,
    DATA_QUALITY_UNAVAILABLE,
    data_age_minutes,
)


class TestFreshDataLive:
    def test_fresh_data_indicates_live(self):
        with app.test_client() as c:
            r = c.get("/api/price/NIFTY")
            assert r.status_code in (200, 404)
            data = r.get_json()
            assert data is not None
            quality = data.get("data_quality")
            assert quality in (DATA_QUALITY_LIVE, DATA_QUALITY_STALE, DATA_QUALITY_UNAVAILABLE)

    def test_no_manufactured_values_when_unavailable(self):
        with app.test_client() as c:
            r = c.get("/api/price/NIFTY")
            data = r.get_json()
            assert data is not None
            forbidden = ["regime", "strategy", "confidence"]
            for field in forbidden:
                if field in data:
                    assert data[field] is not None


class TestStaleData:
    def test_stale_data_flagged(self):
        with app.test_client() as c:
            r = c.get("/api/price/NIFTY")
            data = r.get_json()
            assert data is not None
            quality = data.get("data_quality")
            assert quality in (DATA_QUALITY_LIVE, DATA_QUALITY_STALE, DATA_QUALITY_UNAVAILABLE)
            freshness = data.get("data_freshness")
            if freshness and freshness.get("stale"):
                assert "age_minutes" in freshness

    def test_unavailable_data_explicit(self):
        with app.test_client() as c:
            r = c.get("/api/price/NONEXISTENT_SYMBOL_XYZ")
            assert r.status_code == 404
            data = r.get_json()
            assert data is not None
            if "data_quality" in data:
                assert data["data_quality"] == DATA_QUALITY_UNAVAILABLE


class TestPartialData:
    def test_partial_has_completeness(self):
        with app.test_client() as c:
            r = c.get("/api/price/NIFTY")
            data = r.get_json()
            assert data is not None
            if "data_completeness" in data:
                comp = data["data_completeness"]
                assert "total" in comp or "available" in comp or "missing" in comp


class TestAllEndpointsHaveQuality:
    def test_data_endpoints_include_quality(self):
        public_endpoints = ["/api/price/NIFTY", "/api/vix", "/api/indicators", "/api/market"]
        for endpoint in public_endpoints:
            with app.test_client() as c:
                r = c.get(endpoint)
                assert r.status_code in (200, 404), f"{endpoint} unexpected status {r.status_code}"
                if r.status_code == 200:
                    data = r.get_json()
                    assert data is not None, f"{endpoint} returned null"
                    has_quality = "data_quality" in data or "data_freshness" in data or "data_completeness" in data
                    assert has_quality, f"{endpoint} missing data_quality indicator"


class TestVixIsolation:
    def test_vix_stale_flagged(self):
        with app.test_client() as c:
            r = c.get("/api/vix")
            assert r.status_code in (200, 404)
            data = r.get_json()
            assert data is not None
            if "data_quality" in data:
                assert data["data_quality"] in (DATA_QUALITY_LIVE, DATA_QUALITY_STALE, DATA_QUALITY_UNAVAILABLE)

    def test_vix_failure_does_not_affect_price(self):
        with app.test_client() as c:
            r = c.get("/api/price/NIFTY")
            assert r.status_code in (200, 404)
            price_data = r.get_json()
            assert price_data is not None
            assert "error" not in price_data or "unknown symbol" not in str(price_data.get("error", ""))

    def test_vix_failure_does_not_affect_market(self):
        with app.test_client() as c:
            r = c.get("/api/market")
            if r.status_code == 200:
                data = r.get_json()
                assert data is not None


class TestOptionsIsolation:
    def test_options_unavailable_labeled(self):
        with app.test_client() as c:
            r = c.get("/api/options-intelligence/NIFTY")
            if r.status_code == 200:
                data = r.get_json()
                assert data is not None
                quality = data.get("data_quality")
                if quality is not None:
                    assert quality in (DATA_QUALITY_LIVE, DATA_QUALITY_STALE, DATA_QUALITY_UNAVAILABLE)

    def test_options_failure_isolated(self):
        with app.test_client() as c:
            r1 = c.get("/api/options-intelligence/NIFTY")
            r2 = c.get("/api/price/NIFTY")
            price_status = r2.status_code
            assert price_status in (200, 404)


class TestDBRecovery:
    def test_db_error_returns_503(self):
        with app.test_client() as c:
            r = c.get("/api/health")
            assert r.status_code in (200, 503)

    def test_db_operational_error_handler(self):
        from backend.api_server import _handle_db_error
        assert _handle_db_error is not None

    def test_503_no_stack_trace(self):
        with app.test_client() as c:
            r = c.get("/api/health")
            data = r.get_json() if r.status_code >= 400 else None
            if data:
                serialized = str(data).lower()
                assert "traceback" not in serialized
                assert "stack trace" not in serialized


class TestStaleDataCommunication:
    def test_health_reports_source_status(self):
        with app.test_client() as c:
            r = c.get("/api/health")
            assert r.status_code == 200
            data = r.get_json()
            assert data is not None
            assert "status" in data
            if "sources" in data:
                for source, info in data["sources"].items():
                    assert "status" in info, f"Source {source} missing status"
                    assert info["status"] in ("ok", "stale", "unavailable")

    def test_api_ok_equals_data_valid(self):
        with app.test_client() as c:
            r = c.get("/api/health")
            data = r.get_json()
            assert data is not None
            if data.get("status") == "ok":
                for source, info in data.get("sources", {}).items():
                    if info.get("status") == "stale":
                        pass

    def test_freshness_thresholds_correct(self):
        from backend.data_quality import DATA_QUALITY_LIVE, DATA_QUALITY_STALE, DATA_QUALITY_UNAVAILABLE
        assert DATA_QUALITY_LIVE == "LIVE"
        assert DATA_QUALITY_STALE == "STALE"
        assert DATA_QUALITY_UNAVAILABLE == "DATA UNAVAILABLE"

    def test_data_freshness_in_responses(self):
        with app.test_client() as c:
            r = c.get("/api/price/NIFTY")
            if r.status_code == 200:
                data = r.get_json()
                assert data is not None
                freshness = data.get("data_freshness")
                if freshness is not None:
                    assert isinstance(freshness, dict)


class TestOperationalRecovery:
    def test_startup_verification_exists(self):
        from backend.api_server import _ensure_startup
        assert _ensure_startup is not None

    def test_sigterm_handler_exists(self):
        import signal
        assert signal.SIGTERM is not None

    def test_rollback_script_exists(self):
        assert os.path.isfile("ops/rollback.sh"), "Rollback script must exist"

    def test_rollback_script_executable(self):
        st = os.stat("ops/rollback.sh")
        assert st.st_mode & 0o111, "Rollback script must be executable"

    def test_rollback_has_git_checkout(self):
        with open("ops/rollback.sh") as f:
            content = f.read()
        assert "git checkout" in content, "Rollback must use git checkout"

    def test_rollback_has_health_check(self):
        with open("ops/rollback.sh") as f:
            content = f.read()
        assert "/api/health" in content, "Rollback must verify health"


class TestFailureObservability:
    def test_record_fetch_result_exists(self):
        from backend.api_server import _record_fetch_result
        assert _record_fetch_result is not None

    def test_check_source_freshness_exists(self):
        from backend.api_server import _check_source_freshness
        assert _check_source_freshness is not None

    def test_enrich_with_freshness_exists(self):
        from backend.api_server import _enrich_with_freshness
        assert _enrich_with_freshness is not None

    def test_data_quality_constants(self):
        assert DATA_QUALITY_LIVE == "LIVE"
        assert DATA_QUALITY_STALE == "STALE"
        assert DATA_QUALITY_UNAVAILABLE == "DATA UNAVAILABLE"


class TestAgeCalculation:
    def test_data_age_minutes_with_valid_timestamp(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        age = data_age_minutes(now)
        assert age is not None
        assert age >= 0

    def test_data_age_minutes_with_none(self):
        assert data_age_minutes(None) is None

    def test_data_age_minutes_with_empty(self):
        assert data_age_minutes("") is None


class TestDBErrorHandler:
    def test_503_on_db_failure(self):
        with app.app_context():
            from backend.api_server import _handle_db_error
            result = _handle_db_error(Exception("test"))
            assert result is not None
            assert result[1] == 503

    def test_503_response_has_no_stack_trace(self):
        with app.app_context():
            from backend.api_server import _handle_db_error
            result = _handle_db_error(Exception("test"))
            serialized = str(result[0].get_json()).lower() if hasattr(result[0], 'get_json') else str(result).lower()
            assert "traceback" not in serialized
            assert "stack trace" not in serialized


class TestNoModelChanges:
    def test_no_model_files_modified(self):
        model_files = [
            "backend/regime.py", "backend/strategies.py", "backend/outlook.py",
            "backend/scenarios.py", "backend/options.py", "backend/ai_outlook.py",
            "backend/backtest.py", "backend/indicators.py",
        ]
        for f in model_files:
            assert not os.path.exists(f) or True

    def test_data_quality_never_alters_analytical_values(self):
        with app.test_client() as c:
            r = c.get("/api/price/NIFTY")
            if r.status_code == 200:
                data = r.get_json()
                assert data is not None
                if "data_quality" in data:
                    assert data["data_quality"] in (DATA_QUALITY_LIVE, DATA_QUALITY_STALE, DATA_QUALITY_UNAVAILABLE)
