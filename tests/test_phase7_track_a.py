#!/usr/bin/env python3
"""PHASE 7 Track A tests — Security Hardening.

14 tests covering:
- A1 Nginx snippet (2)
- A2 Chat alert auth-gate (4)
- A3 HSTS (1)
- A4 Metrics lockdown (2)
- A5 CORS (2)
- A6 Key CLI (3)

Invariants: 469-test baseline green, 0/8 model files, no new error shapes.
"""
import os
import sys
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import backend.api_server as api_mod
from backend.api_server import app

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _repo(rel):
    return os.path.join(REPO_ROOT, rel)


@pytest.fixture
def tmp_auth_key(monkeypatch, tmp_path):
    # NOTE: api_server does `from auth import ...` (top-level module name via
    # backend/ on sys.path), so patch THAT module object, not backend.auth.
    import auth as auth_mod
    db = str(tmp_path / "auth_test.db")
    monkeypatch.setattr(auth_mod, "DB_PATH", db)
    auth_mod.ensure_schema()
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO users (username, created_at) VALUES (?, ?)", ("t", "now"))
    uid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()
    raw = auth_mod.store_api_key(uid, None, label="t")
    yield raw


class TestNginxSnippet:
    def test_snippet_covers_server_and_locations(self):
        content = open(_repo("ops/nginx-tradingai.conf")).read()
        assert content.count("include snippets/tradingai-security-headers.conf;") == 6, \
            "server + 5 self-headered locations must include the snippet"

    def test_snippet_has_all_headers(self):
        content = open(_repo("ops/nginx-snippets/tradingai-security-headers.conf")).read()
        for h in ("X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy",
                  "Strict-Transport-Security"):
            assert h in content, f"missing {h}"


class TestChatAlertGate:
    def test_unauth_alert_401(self):
        with app.test_client() as client:
            resp = client.post("/api/chat/messages", json={"text": "x", "kind": "alert"})
            assert resp.status_code == 401, f"spoofed alert must 401, got {resp.status_code}"
            assert resp.get_json()["error"]["code"] == "UNAUTHORIZED"

    def test_unauth_system_401(self):
        with app.test_client() as client:
            resp = client.post("/api/chat/messages", json={"text": "x", "kind": "system"})
            assert resp.status_code == 401

    def test_unauth_user_open(self):
        with app.test_client() as client:
            resp = client.post("/api/chat/messages", json={"text": "hello-track-a", "kind": "user"})
            assert resp.status_code in (200, 201), f"user chat must stay open: {resp.status_code}"

    def test_authed_alert_stored(self, tmp_auth_key):
        with app.test_client() as client:
            resp = client.post("/api/chat/messages", json={"text": "t", "kind": "alert"},
                               headers={"Authorization": f"Bearer {tmp_auth_key}"})
            assert resp.status_code in (200, 201), f"authed alert must store: {resp.status_code}"


class TestHSTS:
    def test_hsts_443_only(self):
        content = open(_repo("ops/nginx-tradingai.conf")).read()
        assert "Strict-Transport-Security" not in content.split("listen 443 ssl;")[0], \
            "HSTS must not appear before/in the port-80 block"
        assert "server_tokens off;" in content


class TestMetricsLockdown:
    def test_local_metrics_open(self):
        with app.test_client() as client:
            assert client.get("/api/metrics").status_code == 200

    def test_remote_metrics_401(self):
        with app.test_client() as client:
            resp = client.get("/api/metrics", environ_base={"REMOTE_ADDR": "8.8.8.8"})
            assert resp.status_code == 401, f"remote metrics must 401, got {resp.status_code}"

    def test_remote_metrics_authed(self, tmp_auth_key):
        with app.test_client() as client:
            resp = client.get("/api/metrics", environ_base={"REMOTE_ADDR": "8.8.8.8"},
                              headers={"Authorization": f"Bearer {tmp_auth_key}"})
            assert resp.status_code == 200


class TestCORS:
    def test_delete_preflight(self):
        with app.test_client() as client:
            resp = client.open("/api/portfolio/1", method="OPTIONS",
                               headers={"Origin": "https://tradingai.in",
                                        "Access-Control-Request-Method": "DELETE"})
            allow = resp.headers.get("Access-Control-Allow-Methods", "")
            assert "DELETE" in allow, f"DELETE missing from preflight: {allow}"

    def test_unit_pins_origins(self):
        content = open(_repo("ops/systemd/tradingai-api.service")).read()
        assert "TRADINGAI_CORS_ORIGINS=https://tradingai.in,https://www.tradingai.in" in content

    def test_nginx_denies_metrics_externally(self):
        content = open(_repo("ops/nginx-tradingai.conf")).read()
        idx = content.index("location = /api/metrics")
        assert "deny all;" in content[idx:idx + 200], "metrics must be denied at nginx layer"


class TestKeyCLI:
    def test_cli_roundtrip(self, tmp_path, monkeypatch):
        import auth as auth_mod
        db = str(tmp_path / "cli.db")
        monkeypatch.setattr(auth_mod, "DB_PATH", db)
        auth_mod.ensure_schema()
        conn = sqlite3.connect(db)
        conn.execute("INSERT INTO users (username, created_at) VALUES (?, ?)", ("u", "now"))
        uid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()
        raw = auth_mod.store_api_key(uid, None, label="cli")
        assert auth_mod.verify_api_key(raw) is not None
        keys = auth_mod.list_keys()
        assert keys and "key_hash" not in keys[0], "listing must not leak hashes"
        assert auth_mod.revoke_api_key_by_prefix(keys[0]["key_prefix"]) == 1
        assert auth_mod.verify_api_key(raw) is None, "revoked key must fail"
