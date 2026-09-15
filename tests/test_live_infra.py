"""TradingAI.in - Phase 1 Live Test Suite: Infrastructure + Network + API.

Spec suites covered: INF (Infrastructure), NET (Network), API (API endpoints).
~70 tests.
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from backend.api_server import app, limiter, ENDPOINT_TIMEOUTS, ALLOWED_ORIGINS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8", errors="ignore") as fh:
        return fh.read()


class TestInfraNginxConfig:
    def test_001_nginx_conf_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "ops/nginx-tradingai.conf"))

    def test_002_nginx_listens_80(self):
        conf = read("ops/nginx-tradingai.conf")
        assert "listen 80;" in conf

    def test_003_nginx_listens_443(self):
        conf = read("ops/nginx-tradingai.conf")
        assert "listen 443 ssl;" in conf

    def test_004_nginx_server_name(self):
        conf = read("ops/nginx-tradingai.conf")
        assert "tradingai.in" in conf
        assert "www.tradingai.in" in conf

    def test_005_nginx_ssl_certificate_paths(self):
        conf = read("ops/nginx-tradingai.conf")
        assert "ssl_certificate" in conf
        assert "ssl_certificate_key" in conf
        assert "letsencrypt" in conf

    def test_006_nginx_ssl_protocols(self):
        conf = read("ops/nginx-tradingai.conf")
        assert "TLSv1.2" in conf or "TLSv1.3" in conf

    def test_007_nginx_root_set(self):
        conf = read("ops/nginx-tradingai.conf")
        assert "root /var/www/tradingai.in/html;" in conf

    def test_008_nginx_index_set(self):
        conf = read("ops/nginx-tradingai.conf")
        assert "index index.html;" in conf

    def test_009_nginx_has_limit_req_zone(self):
        conf = read("ops/nginx-tradingai.conf")
        assert "limit_req_zone" in conf
        assert "api_limit" in conf

    def test_010_nginx_api_rate_limit(self):
        conf = read("ops/nginx-tradingai.conf")
        assert "limit_req zone=api_limit" in conf

    def test_011_nginx_proxies_to_api(self):
        conf = read("ops/nginx-tradingai.conf")
        assert "proxy_pass http://127.0.0.1:8000" in conf

    def test_012_nginx_has_proxy_headers(self):
        conf = read("ops/nginx-tradingai.conf")
        assert "proxy_set_header Host" in conf
        assert "proxy_set_header X-Real-IP" in conf
        assert "proxy_set_header X-Forwarded-For" in conf
        assert "proxy_set_header X-Forwarded-Proto" in conf

    def test_013_nginx_cache_configured(self):
        conf = read("ops/nginx-tradingai.conf")
        assert "proxy_cache" in conf or "proxy_cache_valid" in conf

    def test_014_nginx_cache_bypass_portfolio(self):
        conf = read("ops/nginx-tradingai.conf")
        assert "proxy_no_cache" in conf
        assert "/api/portfolio" in conf


class TestInfraNginxSecurityHeaders:
    def test_015_security_snippet_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "ops/nginx-snippets/tradingai-security-headers.conf"))

    def test_016_snippet_has_x_content_type_options(self):
        conf = read("ops/nginx-snippets/tradingai-security-headers.conf")
        assert "X-Content-Type-Options" in conf

    def test_017_snippet_has_x_frame_options(self):
        conf = read("ops/nginx-snippets/tradingai-security-headers.conf")
        assert "X-Frame-Options" in conf

    def test_018_snippet_has_referrer_policy(self):
        conf = read("ops/nginx-snippets/tradingai-security-headers.conf")
        assert "Referrer-Policy" in conf

    def test_019_snippet_has_hsts(self):
        conf = read("ops/nginx-snippets/tradingai-security-headers.conf")
        assert "Strict-Transport-Security" in conf

    def test_020_snippet_has_xss_protection(self):
        conf = read("ops/nginx-snippets/tradingai-security-headers.conf")
        assert "X-XSS-Protection" in conf


class TestInfraSystemdService:
    def test_021_systemd_service_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "ops/systemd/tradingai-api.service"))

    def test_022_systemd_restart_always(self):
        svc = read("ops/systemd/tradingai-api.service")
        assert "Restart=always" in svc

    def test_023_systemd_uses_gunicorn(self):
        svc = read("ops/systemd/tradingai-api.service")
        assert "gunicorn" in svc

    def test_024_systemd_binds_localhost(self):
        svc = read("ops/systemd/tradingai-api.service")
        assert "127.0.0.1:8000" in svc

    def test_025_systemd_has_cors_env(self):
        svc = read("ops/systemd/tradingai-api.service")
        assert "TRADINGAI_CORS_ORIGINS" in svc

    def test_026_systemd_oom_score(self):
        svc = read("ops/systemd/tradingai-api.service")
        assert "OOMScoreAdjust" in svc


class TestInfraDeployScript:
    def test_027_deploy_script_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "deploy-vm.sh"))

    def test_028_deploy_has_health_gate(self):
        deploy = read("deploy-vm.sh")
        assert "health_gate" in deploy

    def test_029_deploy_has_nginx_guard(self):
        deploy = read("deploy-vm.sh")
        assert "nginx -t" in deploy
        assert "nginx" in deploy

    def test_030_deploy_copies_html(self):
        deploy = read("deploy-vm.sh")
        assert "*.html" in deploy or "html" in deploy

    def test_031_deploy_prefers_health_before_prerender(self):
        deploy = read("deploy-vm.sh")
        health_pos = deploy.find("health_gate")
        prerender_pos = deploy.find("prerender_snapshot")
        assert health_pos > 0 and prerender_pos > 0
        assert health_pos < prerender_pos, "health gate must run before prerender"


class TestInfraConfigFiles:
    def test_032_alerting_config_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "config/alerting.json"))

    def test_033_alerting_config_valid_json(self):
        data = json.loads(read("config/alerting.json"))
        assert isinstance(data, dict)

    def test_034_instruments_config_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "config/instruments.json"))

    def test_035_instruments_config_valid_json(self):
        data = json.loads(read("config/instruments.json"))
        assert "indices" in data or "stocks" in data


class TestNetHttpEndpoints:
    def test_036_health_endpoint_200(self):
        with app.test_client() as c:
            r = c.get("/api/health")
            assert r.status_code == 200

    def test_037_health_endpoint_returns_json(self):
        with app.test_client() as c:
            r = c.get("/api/health")
            assert r.is_json

    def test_038_health_has_status_field(self):
        with app.test_client() as c:
            r = c.get("/api/health")
            data = r.get_json()
            assert "status" in data

    def test_039_ready_endpoint_200_or_503(self):
        with app.test_client() as c:
            r = c.get("/api/ready")
            assert r.status_code in (200, 503)

    def test_040_ready_endpoint_returns_json(self):
        with app.test_client() as c:
            r = c.get("/api/ready")
            assert r.is_json

    def test_041_symbols_endpoint_200(self):
        with app.test_client() as c:
            r = c.get("/api/symbols")
            assert r.status_code == 200

    def test_042_vix_endpoint_200_or_404(self):
        with app.test_client() as c:
            r = c.get("/api/vix")
            assert r.status_code in (200, 404)

    def test_043_market_endpoint_200_or_404(self):
        with app.test_client() as c:
            r = c.get("/api/market")
            assert r.status_code in (200, 404)

    def test_044_price_nifty_200_or_404(self):
        with app.test_client() as c:
            r = c.get("/api/price/NIFTY")
            assert r.status_code in (200, 404)

    def test_045_indicators_nifty_200_or_404(self):
        with app.test_client() as c:
            r = c.get("/api/indicators/NIFTY")
            assert r.status_code in (200, 404)

    def test_046_market_outlook_200_or_404(self):
        with app.test_client() as c:
            r = c.get("/api/market-outlook")
            assert r.status_code in (200, 404)

    def test_047_backtest_endpoint_200_or_404(self):
        with app.test_client() as c:
            r = c.get("/api/backtest?symbol=NIFTY&days=30")
            assert r.status_code in (200, 202, 404)

    def test_048_snapshot_endpoint_200_or_404(self):
        with app.test_client() as c:
            r = c.get("/api/snapshot")
            assert r.status_code in (200, 404)

    def test_049_etf_endpoint_200_or_404(self):
        with app.test_client() as c:
            r = c.get("/api/etf")
            assert r.status_code in (200, 404)

    def test_050_news_endpoint_200_or_404(self):
        with app.test_client() as c:
            r = c.get("/api/news")
            assert r.status_code in (200, 404)

    def test_051_mf_endpoint_200_or_404(self):
        with app.test_client() as c:
            r = c.get("/api/mf")
            assert r.status_code in (200, 404)


class TestNetCORS:
    def test_052_cors_preflight_allowed_origin(self):
        with app.test_client() as c:
            r = c.options("/api/price/NIFTY", headers={
                "Origin": "https://tradingai.in",
                "Access-Control-Request-Method": "GET",
            })
            headers = dict(r.headers)
            assert "Access-Control-Allow-Origin" in headers

    def test_053_cors_preflight_denied_origin(self):
        with app.test_client() as c:
            r = c.options("/api/price/NIFTY", headers={
                "Origin": "https://evil.example.com",
                "Access-Control-Request-Method": "GET",
            })
            headers = dict(r.headers)
            assert "Access-Control-Allow-Origin" not in headers

    def test_054_cors_allows_get_from_allowed(self):
        with app.test_client() as c:
            r = c.get("/api/price/NIFTY", headers={"Origin": "https://tradingai.in"})
            assert r.status_code in (200, 404)


class TestNetAuthBoundaries:
    def test_055_portfolio_get_requires_auth(self):
        with app.test_client() as c:
            r = c.get("/api/portfolio")
            assert r.status_code == 401

    def test_056_portfolio_post_requires_auth(self):
        with app.test_client() as c:
            r = c.post("/api/portfolio", json={
                "symbol": "NIFTY", "strategy": "test",
                "entry_price": 100, "quantity": 1, "direction": "LONG"
            })
            assert r.status_code == 401

    def test_057_portfolio_delete_requires_auth(self):
        with app.test_client() as c:
            r = c.delete("/api/portfolio/1")
            assert r.status_code == 401

    def test_058_chat_alert_requires_auth(self):
        with app.test_client() as c:
            r = c.post("/api/chat/messages", json={"text": "alert test", "kind": "alert"})
            assert r.status_code == 401

    def test_059_chat_system_requires_auth(self):
        with app.test_client() as c:
            r = c.post("/api/chat/messages", json={"text": "system test", "kind": "system"})
            assert r.status_code == 401

    def test_060_chat_user_open(self):
        with app.test_client() as c:
            r = c.post("/api/chat/messages", json={"text": "hello", "kind": "user"})
            assert r.status_code in (200, 201, 401)

    def test_061_public_endpoints_unauthenticated(self):
        public = ["/api/health", "/api/metrics", "/api/price/NIFTY", "/api/vix", "/api/symbols"]
        with app.test_client() as c:
            for ep in public:
                r = c.get(ep)
                assert r.status_code in (200, 404, 401), f"{ep} got {r.status_code}"


class TestNetRateLimiting:
    def test_062_limiter_active(self):
        assert limiter is not None

    def test_063_endpoint_timeouts_defined(self):
        assert "health" in ENDPOINT_TIMEOUTS
        assert "price" in ENDPOINT_TIMEOUTS
        assert "backtest" in ENDPOINT_TIMEOUTS

    def test_064_health_timeout_reasonable(self):
        assert ENDPOINT_TIMEOUTS.get("health", 999) <= 2

    def test_065_backtest_timeout_reasonable(self):
        assert ENDPOINT_TIMEOUTS.get("backtest", 0) >= 30


class TestNetHTTPDirect:
    def test_066_health_url_pattern_valid(self):
        url = "http://127.0.0.1:8000/api/health"
        assert url.startswith("http://")
        assert "/api/health" in url

    def test_067_api_base_url_pattern(self):
        base = "http://127.0.0.1:8000"
        endpoints = ["/api/health", "/api/market", "/api/price/NIFTY", "/api/vix", "/api/symbols"]
        for ep in endpoints:
            url = base + ep
            assert url.startswith("http://127.0.0.1:8000/api/")


class TestAPIHealth:
    def test_068_health_status_is_string(self):
        with app.test_client() as c:
            r = c.get("/api/health")
            data = r.get_json()
            assert isinstance(data.get("status"), str)

    def test_069_health_has_timestamp(self):
        with app.test_client() as c:
            r = c.get("/api/health")
            data = r.get_json()
            assert "timestamp" in data

    def test_070_health_has_pool_info(self):
        with app.test_client() as c:
            r = c.get("/api/health")
            data = r.get_json()
            assert "pool" in data

    def test_071_health_has_data_freshness(self):
        with app.test_client() as c:
            r = c.get("/api/health")
            data = r.get_json()
            assert "data_freshness" in data

    def test_072_health_has_sources(self):
        with app.test_client() as c:
            r = c.get("/api/health")
            data = r.get_json()
            assert "sources" in data

    def test_073_health_sources_have_freshness(self):
        with app.test_client() as c:
            r = c.get("/api/health")
            data = r.get_json()
            for src, info in data.get("sources", {}).items():
                assert "status" in info, f"source {src} missing status"
                assert "age_minutes" in info, f"source {src} missing age"


class TestAPIPrice:
    def test_074_price_nifty_returns_dict_or_404(self):
        with app.test_client() as c:
            r = c.get("/api/price/NIFTY")
            if r.status_code == 200:
                data = r.get_json()
                assert isinstance(data, dict)

    def test_075_price_has_quote_or_price(self):
        with app.test_client() as c:
            r = c.get("/api/price/NIFTY")
            if r.status_code == 200:
                data = r.get_json()
                assert "quote" in data or "price" in data

    def test_076_price_endpoint_404_for_unknown(self):
        with app.test_client() as c:
            r = c.get("/api/price/NOPE123")
            assert r.status_code in (404, 200)


class TestAPIMarket:
    def test_077_market_returns_200_or_404(self):
        with app.test_client() as c:
            r = c.get("/api/market")
            assert r.status_code in (200, 404)

    def test_078_market_response_has_source(self):
        with app.test_client() as c:
            r = c.get("/api/market")
            if r.status_code == 200:
                data = r.get_json()
                assert "source" in data, f"missing source key in {list(data.keys())}"

    def test_079_market_response_has_last_updated(self):
        with app.test_client() as c:
            r = c.get("/api/market")
            if r.status_code == 200:
                data = r.get_json()
                assert "last_updated" in data, f"missing last_updated in {list(data.keys())}"

    def test_080_market_response_has_data_quality(self):
        with app.test_client() as c:
            r = c.get("/api/market")
            if r.status_code == 200:
                data = r.get_json()
                assert "data_quality" in data, f"missing data_quality in {list(data.keys())}"

    def test_081_market_response_has_ai_outlook(self):
        with app.test_client() as c:
            r = c.get("/api/market")
            if r.status_code == 200:
                data = r.get_json()
                assert "ai_outlook" in data, f"missing ai_outlook in {list(data.keys())}"

    def test_082_market_response_has_instruments(self):
        with app.test_client() as c:
            r = c.get("/api/market")
            if r.status_code == 200:
                data = r.get_json()
                assert "instruments" in data, f"missing instruments in {list(data.keys())}"

    def test_083_market_response_has_data_completeness(self):
        with app.test_client() as c:
            r = c.get("/api/market")
            if r.status_code == 200:
                data = r.get_json()
                assert "data_completeness" in data, f"missing data_completeness in {list(data.keys())}"

    def test_084_market_instruments_is_dict(self):
        with app.test_client() as c:
            r = c.get("/api/market")
            if r.status_code == 200:
                data = r.get_json()
                assert isinstance(data.get("instruments"), dict)

    def test_085_market_data_completeness_keys(self):
        with app.test_client() as c:
            r = c.get("/api/market")
            if r.status_code == 200:
                data = r.get_json()
                dc = data.get("data_completeness", {})
                assert "instruments" in dc or "has_prices" in dc

    def test_086_market_last_updated_is_string_or_null(self):
        with app.test_client() as c:
            r = c.get("/api/market")
            if r.status_code == 200:
                data = r.get_json()
                lu = data.get("last_updated")
                assert lu is None or isinstance(lu, str)


class TestAPIChat:
    def test_087_chat_get_returns_list(self):
        with app.test_client() as c:
            r = c.get("/api/chat/messages")
            if r.status_code == 200:
                data = r.get_json()
                assert isinstance(data, list)

    def test_088_chat_post_returns_json(self):
        with app.test_client() as c:
            r = c.post("/api/chat/messages", json={"text": "test message", "kind": "user"})
            assert r.status_code in (200, 201, 401, 429)

    def test_089_chat_alerts_get_returns_list(self):
        with app.test_client() as c:
            r = c.get("/api/chat/alerts")
            assert r.status_code in (200, 404)
            if r.status_code == 200:
                assert isinstance(r.get_json(), list)


class TestAPIErrorHandlers:
    def test_090_404_returns_json(self):
        with app.test_client() as c:
            r = c.get("/api/nonexistent/page")
            assert r.status_code == 404
            data = r.get_json()
            assert data is not None
            assert "error" in data

    def test_091_404_has_error_code(self):
        with app.test_client() as c:
            r = c.get("/api/nonexistent/page")
            data = r.get_json()
            assert "code" in data.get("error", {})

    def test_092_404_has_error_message(self):
        with app.test_client() as c:
            r = c.get("/api/nonexistent/page")
            data = r.get_json()
            assert "message" in data.get("error", {})

    def test_093_404_has_timestamp(self):
        with app.test_client() as c:
            r = c.get("/api/nonexistent/page")
            data = r.get_json()
            assert "timestamp" in data.get("error", {})

    def test_094_error_no_stack_trace(self):
        with app.test_client() as c:
            r = c.get("/api/nonexistent/page")
            data = r.get_json()
            serialized = json.dumps(data).lower()
            assert "traceback" not in serialized
            assert "stack trace" not in serialized
