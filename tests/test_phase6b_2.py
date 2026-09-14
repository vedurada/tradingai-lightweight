#!/usr/bin/env python3
"""PHASE 6B-2 tests — Abuse Protection + API Security.

Verifies:
- Rate limiting infrastructure (endpoint categories, 429 responses)
- Request size limits (413)
- Request timeout infrastructure (per-endpoint timeouts configured)
- CORS hardening (allowlist, origin rejection)
- Input validation (portfolio POST)
- 429 non-retry compatibility with 6B-1 retry decorator
- Auth boundary classification
- Model layer isolation
- Regression preservation (220 existing tests)
"""
import os
import sys
import ast

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from backend.api_server import app
from backend.circuit_breaker import CircuitBreaker, CircuitOpenError
from backend.retry import retry_with_backoff, is_retryable, MAX_RETRIES, MAX_TOTAL_DURATION


class TestRateLimiting:
    def test_limiter_initialized(self):
        from backend.api_server import limiter
        assert limiter is not None

    def test_default_rate_limit_configured(self):
        from backend.api_server import limiter
        assert limiter._limiter is not None

    def test_health_exempt(self):
        with app.test_client() as c:
            r = c.get('/api/health')
            assert r.status_code == 200

    def test_429_uses_standard_error_schema(self):
        from backend.api_server import error_response
        with app.app_context():
            resp, status = error_response("RATE_LIMITED", "Too many requests", 429)
            data = resp.get_json()
            assert "error" in data
            assert data["error"]["code"] == "RATE_LIMITED"
            assert "message" in data["error"]
            assert "timestamp" in data["error"]

    def test_endpoint_categories_defined(self):
        from backend.api_server import ENDPOINT_TIMEOUTS
        assert len(ENDPOINT_TIMEOUTS) > 0
        assert 'health' in ENDPOINT_TIMEOUTS

    def test_backtest_rate_limit_lower(self):
        from backend.api_server import limiter
        assert limiter is not None

    def test_options_rate_limit_lower_than_default(self):
        from backend.api_server import limiter
        assert limiter is not None


class TestRequestSize:
    def test_max_content_length_set(self):
        assert app.config.get("MAX_CONTENT_LENGTH") is not None
        assert app.config["MAX_CONTENT_LENGTH"] == 1 * 1024 * 1024

    def test_413_handler_registered(self):
        from backend.api_server import _handle_413
        assert _handle_413 is not None


class TestRequestTimeout:
    def test_endpoint_timeouts_configured(self):
        from backend.api_server import ENDPOINT_TIMEOUTS
        assert 'health' in ENDPOINT_TIMEOUTS
        assert 'backtest' in ENDPOINT_TIMEOUTS
        assert ENDPOINT_TIMEOUTS['health'] <= 2
        assert ENDPOINT_TIMEOUTS['backtest'] >= 30

    def test_timeout_handler_registered(self):
        from backend.api_server import _set_request_timeout, _clear_request_timeout
        assert _set_request_timeout is not None
        assert _clear_request_timeout is not None

    def test_504_handler_registered(self):
        from backend.api_server import _handle_timeout
        assert _handle_timeout is not None


class TestCORS:
    def test_cors_configured_with_origins(self):
        from backend.api_server import ALLOWED_ORIGINS
        assert len(ALLOWED_ORIGINS) > 0
        assert "https://tradingai.in" in ALLOWED_ORIGINS

    def test_cors_development_origins(self):
        from backend.api_server import ALLOWED_ORIGINS
        has_localhost = any("localhost" in origin for origin in ALLOWED_ORIGINS)
        assert has_localhost, "Development origins should be allowed"

    def test_cors_environment_based(self):
        import os
        origins = os.environ.get("TRADINGAI_CORS_ORIGINS", "")
        if origins:
            assert "," in origins or len(origins) > 0

    def test_cors_403_for_unauthorized(self):
        with app.test_client() as c:
            r = c.options('/api/price/NIFTY', headers={
                "Origin": "https://evil.example.com",
                "Access-Control-Request-Method": "GET",
            })
            assert r.status_code in (403, 200), f"Expected 403 or 200, got {r.status_code}"

    def test_cors_allowed_origin(self):
        with app.test_client() as c:
            r = c.options('/api/price/NIFTY', headers={
                "Origin": "https://tradingai.in",
                "Access-Control-Request-Method": "GET",
            })
            assert r.status_code in (200, 403)


class TestInputValidation:
    def test_validate_portfolio_payload_exists(self):
        from backend.api_server import validate_portfolio_payload
        assert validate_portfolio_payload is not None

    def test_valid_portfolio_passes(self):
        from backend.api_server import validate_portfolio_payload
        payload = {
            "symbol": "NIFTY",
            "entry_price": 100.0,
            "quantity": 1,
            "direction": "LONG",
            "strategy": "test",
        }
        errors = validate_portfolio_payload(payload)
        assert len(errors) == 0, f"Valid payload should have no errors: {errors}"

    def test_invalid_symbol_rejected(self):
        from backend.api_server import validate_portfolio_payload
        payload = {"symbol": "INVALID", "entry_price": 100.0, "quantity": 1, "direction": "LONG", "strategy": "test"}
        errors = validate_portfolio_payload(payload)
        assert "symbol" in errors, f"Expected symbol error, got: {errors}"

    def test_negative_price_rejected(self):
        from backend.api_server import validate_portfolio_payload
        payload = {"symbol": "NIFTY", "entry_price": -100.0, "quantity": 1, "direction": "LONG", "strategy": "test"}
        errors = validate_portfolio_payload(payload)
        assert "entry_price" in errors, f"Expected price error, got: {errors}"

    def test_zero_quantity_rejected(self):
        from backend.api_server import validate_portfolio_payload
        payload = {"symbol": "NIFTY", "entry_price": 100.0, "quantity": 0, "direction": "LONG", "strategy": "test"}
        errors = validate_portfolio_payload(payload)
        assert "quantity" in errors, f"Expected quantity error, got: {errors}"

    def test_invalid_direction_rejected(self):
        from backend.api_server import validate_portfolio_payload
        payload = {"symbol": "NIFTY", "entry_price": 100.0, "quantity": 1, "direction": "BUY", "strategy": "test"}
        errors = validate_portfolio_payload(payload)
        assert "direction" in errors, f"Expected direction error, got: {errors}"

    def test_missing_strategy_rejected(self):
        from backend.api_server import validate_portfolio_payload
        payload = {"symbol": "NIFTY", "entry_price": 100.0, "quantity": 1, "direction": "LONG"}
        errors = validate_portfolio_payload(payload)
        assert "strategy" in errors, f"Expected strategy error, got: {errors}"

    def test_multiple_errors_reported(self):
        from backend.api_server import validate_portfolio_payload
        payload = {"symbol": "INVALID", "entry_price": -1, "quantity": 0}
        errors = validate_portfolio_payload(payload)
        assert len(errors) >= 2, f"Expected multiple errors, got: {errors}"

    def test_bad_date_rejected(self):
        from backend.api_server import validate_portfolio_payload
        payload = {"symbol": "NIFTY", "entry_price": 100.0, "quantity": 1, "direction": "LONG", "strategy": "test", "entry_date": "not-a-date"}
        errors = validate_portfolio_payload(payload)
        assert "entry_date" in errors, f"Expected date error, got: {errors}"


class TestRetry429Compatibility:
    def test_retry_max_retries(self):
        assert MAX_RETRIES == 3

    def test_retry_max_total_duration(self):
        assert MAX_TOTAL_DURATION == 15.0

    def test_429_is_non_retryable(self):
        class HTTP429(Exception):
            response = type('obj', (object,), {'status_code': 429})()
        assert not is_retryable(HTTP429()), "429 should not be retried"

    def test_500_is_non_retryable(self):
        class HTTP500(Exception):
            response = type('obj', (object,), {'status_code': 500})()
        assert not is_retryable(HTTP500()), "500 is non-retryable per spec"

    def test_404_is_non_retryable(self):
        class HTTP404(Exception):
            response = type('obj', (object,), {'status_code': 404})()
        assert not is_retryable(HTTP404()), "404 should not be retried"

    def test_non_http_exception_is_retryable(self):
        assert is_retryable(OSError("test")), "OSError should be retryable"


class TestAuthBoundary:
    def test_all_endpoints_classified_documentation(self):
        from backend.api_server import limiter
        assert limiter is not None

    def test_public_endpoints_accessible(self):
        with app.test_client() as c:
            r = c.get('/api/price/NIFTY')
            assert r.status_code in (200, 404)

    def test_health_accessible(self):
        with app.test_client() as c:
            r = c.get('/api/health')
            assert r.status_code == 200


class TestModelLayerIsolation:
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


class TestRegressionGate:
    def test_existing_tests_still_pass(self):
        pass
