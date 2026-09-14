"""Track C tests: intelligence presentation (webroot/frontend/nginx only).

Boundary: no backend changes. S5 is diagnosis-only and has no code assertions
beyond the empty-payload guard (S3), which is presentation-layer.
"""
import glob
import hashlib
import json
import os
import re
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = "5280b03"  # P1 commit: backend must match it byte-for-byte
MODELS = ["backend/regime.py", "backend/strategies.py", "backend/outlook.py",
          "backend/scenarios.py", "backend/options.py", "backend/ai_outlook.py",
          "backend/backtest.py", "backend/indicators.py"]


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8",
              errors="ignore") as fh:
        return fh.read()


class TestSoft404:
    def test_nginx_html_404_rule(self):
        conf = read("ops/nginx-tradingai.conf")
        assert re.search(r"location ~\* \\.html\$", conf)
        assert "try_files $uri =404" in conf
        assert "error_page 404 /404.html" in conf

    def test_ghost_guard_intact(self):
        conf = read("ops/nginx-tradingai.conf")
        assert "location = /indices/market.html" in conf
        assert "return 301 /market.html" in conf

    def test_404_page(self):
        t = read("404.html")
        assert "noindex" in t and "/index.html" in t and "/market.html" in t
        assert "s-nifty-price" not in t  # no fake market content


class TestEmptyGuard:
    def test_helper_present_and_wired(self):
        js = read("static/js/ai-outlook.js")
        assert "function isEmptyOutlook" in js
        assert "'{}'" in js
        assert "if (isEmptyOutlook(outlook))" in js

    def test_guard_behavior_executes(self):
        js = read("static/js/ai-outlook.js")
        helper = js[js.find("function isEmptyOutlook"):]
        helper = helper[:helper.find("\n    }\n") + len("\n    }\n")]
        cases = {"": "true", "{}": "true", "  ": "true",
                 "not-json{{{": "true", '{"a":1}': "false"}
        for raw, expected in cases.items():
            prog = helper + f"\nconsole.log(isEmptyOutlook({json.dumps(raw)}));"
            r = subprocess.run(["node", "-e", prog], capture_output=True,
                               text=True, cwd=ROOT)
            assert r.stdout.strip() == expected, (raw, r.stderr)


class TestFinniftyCard:
    def test_static_card_present(self):
        t = read("index.html")
        for sid in ("s-finnifty-price", "s-finnifty-trend", "s-finnifty-vix"):
            assert f'id="{sid}"' in t, sid


class TestMaxPain:
    def test_observational_wording(self):
        t = read("index.html")
        assert "no reliable" in t and "context, not a forecast" in t
        assert "gravitate toward Max Pain" not in t


class TestCanonicalLock:
    def test_homepage_canonical(self):
        t = read("index.html")
        assert '<link rel="canonical" href="https://tradingai.in/">' in t


class TestPrerender:
    PAYLOAD = {"instruments": {
        "NIFTY": {"quote": {"price": 26150.5},
                  "regime": {"regime": "TRENDING_BULLISH"}},
        "FINNIFTY": {"quote": {"price": 27410.25},
                     "regime": {"regime": "TRENDING_BEARISH"}},
        "VIX": {"quote": {"price": 13.42, "change_pct": 2.15}}}}

    def _run(self, tmp_path):
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
            for _ in range(2):  # run twice: idempotency
                r = subprocess.run(
                    ["python3", "ops/prerender_snapshot.py", "--root",
                     str(tmp_path), "--api-base", base],
                    capture_output=True, text=True, cwd=ROOT)
                assert r.returncode == 0, r.stdout + r.stderr
        finally:
            srv.shutdown()
        return (tmp_path / "index.html").read_text(encoding="utf-8",
                                                   errors="ignore")

    def test_values_injected_and_stamp_single(self, tmp_path):
        t = self._run(tmp_path)
        assert 'id="s-nifty-price">26,150.50' in t
        assert 'id="s-finnifty-price">27,410.25' in t
        assert 'id="s-sensex-price">—' in t  # absent payload: never fabricate
        assert t.count("data-prerendered") == 1

    def test_deploy_and_cron_wiring(self):
        deploy = read("deploy-vm.sh")
        # deploy-time invocation AFTER the health gate (API guaranteed up)
        assert deploy.find("DEPLOY SUCCESS") < deploy.find(
            "prerender_snapshot.py --root /var/www/tradingai.in/html "
            "--api-base http://127.0.0.1:8000")
        # cron invocation after BOTH outlook generations (mirrors injector)
        assert deploy.count(
            "ops/prerender_snapshot.py --root /var/www/tradingai.in/html "
            ">> /opt/tradingai/logs/prerender.log 2>&1") == 2


class TestSectionOrder:
    def test_s9_order(self):
        js = read("static/js/ai-outlook.js")
        seq = ["buildKeyLevels", "buildOptionsIntelligence",
               "buildStrategies", "buildDecision", "buildRisk"]
        pos = [js.find("html += " + s) for s in seq]
        assert all(p >= 0 for p in pos)
        assert pos == sorted(pos)


class TestFrozenBoundary:
    def test_no_backend_changes_vs_baseline(self):
        diff = subprocess.run(
            ["git", "diff", f"{BASELINE}..HEAD", "--name-only"] + MODELS,
            capture_output=True, text=True, cwd=ROOT).stdout.strip()
        staged = subprocess.run(
            ["git", "diff", "--cached", "--name-only"] + MODELS,
            capture_output=True, text=True, cwd=ROOT).stdout.strip()
        work = subprocess.run(
            ["git", "diff", "--name-only"] + MODELS,
            capture_output=True, text=True, cwd=ROOT).stdout.strip()
        assert diff == "" and staged == "" and work == ""

    def test_outlook_py_byte_identical(self):
        cur = hashlib.sha256(read("backend/outlook.py").encode()).hexdigest()
        frozen = subprocess.run(
            ["git", "show", f"{BASELINE}:backend/outlook.py"],
            capture_output=True, cwd=ROOT).stdout
        assert hashlib.sha256(frozen).hexdigest() == cur
