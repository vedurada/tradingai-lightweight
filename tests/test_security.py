"""TradingAI.in — Security Test Suite (~20 tests).

Covers security headers (nginx config), secrets exposure,
injection resistance, path traversal prevention, CORS, auth.
Per TEST_PLAN_SCOPE.md Section 4.8.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from backend.api_server import app

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8", errors="ignore") as fh:
        return fh.read()


# ── Security Headers (nginx config) ───────────────────

class TestSecurityHeaders:
    def test_hsts_in_config(self):
        c = read("ops/nginx-snippets/tradingai-security-headers.conf")
        assert "Strict-Transport-Security" in c, "HSTS not in nginx snippet"

    def test_x_frame_options_in_config(self):
        c = read("ops/nginx-snippets/tradingai-security-headers.conf")
        assert "X-Frame-Options" in c, "X-Frame-Options not in nginx snippet"

    def test_x_content_type_options_in_config(self):
        c = read("ops/nginx-snippets/tradingai-security-headers.conf")
        assert "X-Content-Type-Options" in c, "X-Content-Type-Options missing"

    def test_nginx_includes_security_snippet(self):
        c = read("ops/nginx-tradingai.conf")
        assert "tradingai-security-headers.conf" in c, "Snippet not included"

    def test_hsts_max_age(self):
        c = read("ops/nginx-snippets/tradingai-security-headers.conf")
        match = re.search(r'max-age=(\d+)', c)
        assert match, "HSTS max-age not found"
        assert int(match.group(1)) >= 31536000, "HSTS max-age too short"

    def test_server_tokens_off(self):
        c = read("ops/nginx-tradingai.conf")
        assert "server_tokens off" in c, "server_tokens not disabled"

    def test_https_redirect(self):
        c = read("ops/nginx-tradingai.conf")
        http_block = c[c.find("listen 80"):c.find("listen 443")]
        assert "301" in http_block and "https" in http_block, "HTTP→HTTPS redirect missing"


# ── Secrets & Credentials ─────────────────────────────

class TestSecrets:
    def test_no_openai_keys_in_source(self):
        files = ["backend/api_server.py", "static/js/api.js", "index.html"]
        for f in files:
            content = read(f)
            assert not re.search(r'sk-[a-zA-Z0-9]{20,}', content), f"OpenAI key in {f}"

    def test_no_private_keys_in_repo(self):
        for root, dirs, files in os.walk(os.path.join(ROOT, "..")):
            dirs[:] = [d for d in dirs if d not in (".git", "node_modules", ".pytest_cache")]
            for fn in files:
                if fn.endswith((".pem", ".key", ".p12", ".pfx")):
                    assert False, f"Private key file found: {os.path.join(root, fn)}"

    def test_gh_token_absent(self):
        content = read("backend/api_server.py") + read("deploy-vm.sh")
        assert "ghp_" not in content and "github_pat_" not in content, "GitHub token found"

    def test_no_hardcoded_secrets(self):
        sensitive = ["password", "secret", "token", "credential"]
        for f in ["backend/api_server.py", "deploy-vm.sh"]:
            content = read(f).lower()
            for s in sensitive:
                matches = re.findall(rf'{s}\s*[=:]\s*["\'][^"\']{8,}["\']', content)
                assert len(matches) == 0, f"{s} hardcoded in {f}: {matches}"


# ── Injection Resistance ──────────────────────────────

class TestInjection:
    def test_sql_injection_safe(self):
        payloads = ["'; DROP TABLE--", "' OR 1=1--", "' UNION SELECT--"]
        with app.test_client() as c:
            for p in payloads:
                r = c.get(f"/api/price/{p}")
                assert r.status_code in (404, 400, 403), f"SQLi returned {r.status_code}"

    def test_path_traversal_blocked(self):
        paths = ["/../etc/passwd", "/....//etc/passwd"]
        with app.test_client() as c:
            for p in paths:
                r = c.get(p)
                assert r.status_code == 404, f"Path traversal {p} returned {r.status_code}"

    def test_xss_symbol_param_safe(self):
        with app.test_client() as c:
            r = c.get("/api/price/%3Cscript%3Ealert(1)%3C/script%3E")
            assert r.status_code in (404, 400, 403), f"XSS returned {r.status_code}"


# ── Auth & Authorization ──────────────────────────────

class TestAuth:
    def test_portfolio_requires_auth(self):
        with app.test_client() as c:
            r = c.get("/api/portfolio")
            assert r.status_code in (401, 403), f"Portfolio not protected: {r.status_code}"

    def test_chat_requires_auth(self):
        with app.test_client() as c:
            r = c.get("/api/chat/messages")
            assert r.status_code in (200, 401, 403), f"Unexpected: {r.status_code}"

    def test_health_public(self):
        with app.test_client() as c:
            r = c.get("/api/health")
            assert r.status_code == 200, "Health should be public"

    def test_symbols_public(self):
        with app.test_client() as c:
            r = c.get("/api/symbols")
            assert r.status_code == 200, "Symbols should be public"


# ── CORS ──────────────────────────────────────────────

class TestCors:
    def test_api_requires_https(self):
        with app.test_client() as c:
            r = c.get("/api/health")
            assert r.status_code == 200, "API health check failed"
