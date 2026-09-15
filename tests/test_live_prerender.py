"""TradingAI.in - Phase 1 Live Test Suite: Prerender Tests.

Spec suite covered: PRE (Prerender).
~15 tests.
"""
import os
import sys
import re
import subprocess
import threading
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from backend.api_server import app

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8", errors="ignore") as fh:
        return fh.read()


# ═══════════════════════════════════════════════════════════
# PRE — Prerender Configuration & Wiring
# ═══════════════════════════════════════════════════════════

class TestPrerenderScript:
    def test_001_prerender_script_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "ops/prerender_snapshot.py"))

    def test_002_prerender_has_cli(self):
        script = read("ops/prerender_snapshot.py")
        assert "argparse" in script or "ArgumentParser" in script or "--root" in script

    def test_003_prerender_has_api_base(self):
        script = read("ops/prerender_snapshot.py")
        assert "api-base" in script or "api_base" in script or "--api" in script

    def test_004_prerender_reads_index_html(self):
        script = read("ops/prerender_snapshot.py")
        assert "index.html" in script or "root" in script


class TestPrerenderDeployWiring:
    def test_005_deploy_has_prerender(self):
        deploy = read("deploy-vm.sh")
        assert "prerender_snapshot" in deploy

    def test_006_deploy_prerender_after_health(self):
        deploy = read("deploy-vm.sh")
        health_pos = deploy.find("health_gate")
        prerender_pos = deploy.find("prerender_snapshot")
        assert health_pos > 0 and prerender_pos > 0
        assert health_pos < prerender_pos, "Health gate must precede prerender"

    def test_007_deploy_prerender_in_cron(self):
        deploy = read("deploy-vm.sh")
        count = deploy.count("prerender_snapshot.py --root")
        assert count >= 1, "Prerender must be in deploy script"

    def test_008_deploy_prefers_health_first(self):
        """API health gate must pass before prerender runs."""
        deploy = read("deploy-vm.sh")
        # Find DEPLOY SUCCESS marker
        deploy_success = deploy.find("DEPLOY SUCCESS")
        health_gate = deploy.find("health_gate")
        prerender = deploy.find("prerender_snapshot")
        assert health_gate > 0, "health_gate must be in deploy"
        assert prerender > 0, "prerender must be in deploy"
        assert health_gate < prerender, "Health gate must run before prerender"


class TestPrerenderNginx:
    def test_009_nginx_supports_html_routing(self):
        conf = read("ops/nginx-tradingai.conf")
        assert "try_files" in conf

    def test_010_nginx_has_root(self):
        conf = read("ops/nginx-tradingai.conf")
        assert "root /var/www/tradingai.in/html" in conf

    def test_011_nginx_index_configured(self):
        conf = read("ops/nginx-tradingai.conf")
        assert "index index.html" in conf


class TestPrerenderSnapshot:
    PAYLOAD = {"instruments": {
        "NIFTY": {"quote": {"price": 26150.5},
                  "regime": {"regime": "TRENDING_BULLISH"}},
        "FINNIFTY": {"quote": {"price": 27410.25},
                      "regime": {"regime": "TRENDING_BEARISH"}},
        "VIX": {"quote": {"price": 13.42, "change_pct": 2.15}}}}

    def test_012_prerender_runs_without_error(self, tmp_path):
        import shutil
        shutil.copy(os.path.join(ROOT, "index.html"), str(tmp_path))
        payload = self.PAYLOAD

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *a):
                pass

        srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_port}"
        try:
            r = subprocess.run(
                ["python3", "ops/prerender_snapshot.py", "--root",
                 str(tmp_path), "--api-base", base],
                capture_output=True, text=True, cwd=ROOT, timeout=60)
            assert r.returncode == 0, r.stdout + r.stderr
        finally:
            srv.shutdown()

    def test_013_prerender_injects_prices(self, tmp_path):
        import shutil
        shutil.copy(os.path.join(ROOT, "index.html"), str(tmp_path))
        payload = self.PAYLOAD

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *a):
                pass

        srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_port}"
        try:
            r = subprocess.run(
                ["python3", "ops/prerender_snapshot.py", "--root",
                 str(tmp_path), "--api-base", base],
                capture_output=True, text=True, cwd=ROOT, timeout=60)
            assert r.returncode == 0, r.stdout + r.stderr
            t = (tmp_path / "index.html").read_text(encoding="utf-8", errors="ignore")
            assert 'id="s-nifty-price">26,150.50' in t
            assert 'id="s-finnifty-price">27,410.25' in t
        finally:
            srv.shutdown()

    def test_014_prerender_does_not_fabricate(self, tmp_path):
        import shutil
        shutil.copy(os.path.join(ROOT, "index.html"), str(tmp_path))
        payload = self.PAYLOAD

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *a):
                pass

        srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_port}"
        try:
            r = subprocess.run(
                ["python3", "ops/prerender_snapshot.py", "--root",
                 str(tmp_path), "--api-base", base],
                capture_output=True, text=True, cwd=ROOT, timeout=60)
            t = (tmp_path / "index.html").read_text(encoding="utf-8", errors="ignore")
            assert 'id="s-sensex-price">---' in t or "SENSEX" in t
        finally:
            srv.shutdown()

    def test_015_prerender_idempotent(self, tmp_path):
        import shutil
        shutil.copy(os.path.join(ROOT, "index.html"), str(tmp_path))
        payload = self.PAYLOAD

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *a):
                pass

        srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_port}"
        try:
            r1 = subprocess.run(
                ["python3", "ops/prerender_snapshot.py", "--root",
                 str(tmp_path), "--api-base", base],
                capture_output=True, text=True, cwd=ROOT, timeout=60)
            assert r1.returncode == 0
            t1 = (tmp_path / "index.html").read_text(encoding="utf-8", errors="ignore")
            r2 = subprocess.run(
                ["python3", "ops/prerender_snapshot.py", "--root",
                 str(tmp_path), "--api-base", base],
                capture_output=True, text=True, cwd=ROOT, timeout=60)
            assert r2.returncode == 0
            t2 = (tmp_path / "index.html").read_text(encoding="utf-8", errors="ignore")
            assert t1 == t2, "Prerender should be idempotent"
        finally:
            srv.shutdown()
