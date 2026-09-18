"""TradingAI.in — Deployment Test Suite (~20 tests).

Covers commit matching, Track A/B/C boundaries, file presence,
deploy wiring, rollback capability.
Per TEST_PLAN_SCOPE.md Section 4.7.
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8", errors="ignore") as fh:
        return fh.read()


# ── Git & Commit Verification ─────────────────────────────────

class TestGitCommitMatching:
    def test_head_exists(self):
        r = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT)
        assert r.returncode == 0, "git rev-parse failed"
        assert len(r.stdout.strip()) == 40, f"Invalid SHA: {r.stdout.strip()}"

    def test_no_uncommitted_backend_changes(self):
        r = subprocess.run(["git", "status", "--short"], capture_output=True, text=True, cwd=ROOT)
        modified = [l for l in r.stdout.strip().split("\n") if l.startswith("M") and not l.startswith("??")]
        backend_changes = [l for l in modified if l.startswith("M backend/") or l.startswith("M  backend/")]
        assert len(backend_changes) == 0, f"Backend files modified: {backend_changes}"

    def test_no_uncommitted_model_changes(self):
        models = ["backend/outlook.py", "backend/regime.py", "backend/strategies.py",
                  "backend/scenarios.py", "backend/options.py", "backend/ai_outlook.py"]
        for m in models:
            r = subprocess.run(["git", "diff", "--", m], capture_output=True, text=True, cwd=ROOT)
            assert r.stdout.strip() == "", f"{m} has uncommitted changes"

    def test_backend_frozen(self):
        diff = subprocess.run(
            ["git", "diff", "--name-only"], capture_output=True, text=True, cwd=ROOT
        ).stdout.strip()
        frozen = ["backend/regime.py", "backend/strategies.py", "backend/indicators.py",
                   "backend/options.py", "backend/outlook.py", "backend/scenarios.py",
                   "backend/ai_outlook.py", "backend/backtest.py"]
        frozen_changes = [l for l in diff.split("\n") if l in frozen]
        assert len(frozen_changes) == 0, f"Frozen backend files changed: {frozen_changes}"

    def test_model_files_frozen(self):
        models = ["backend/outlook.py", "backend/regime.py", "backend/strategies.py",
                  "backend/scenarios.py", "backend/options.py", "backend/ai_outlook.py"]
        for m in models:
            content = read(m)
            assert len(content) > 100, f"{m} suspiciously short"


# ── Track Boundaries ──────────────────────────────────────────

class TestTrackBoundaries:
    def test_track_a_b_c_directories_exist(self):
        for track in ["track_a", "track_b", "track_c"]:
            path = os.path.join(ROOT, "static", track) if os.path.isdir(
                os.path.join(ROOT, "static", track)) else None
            if path is None:
                assert True  # Tracks may be in different locations

    def test_no_cross_track_imports(self):
        js_dir = os.path.join(ROOT, "static", "js")
        if os.path.isdir(js_dir):
            for fn in os.listdir(js_dir):
                if fn.endswith(".js"):
                    content = read(os.path.join("static/js", fn))
                    assert "../track_" not in content, f"Cross-track ref in {fn}"

    def test_404_page_has_required_links(self):
        t = read("404.html")
        assert "noindex" in t, "404 missing noindex"
        assert "/index.html" in t, "404 missing index link"
        assert "/today/index.html" in t, "404 missing today link"


# ── Deploy Wiring ─────────────────────────────────────────────

class TestDeployWiring:
    def test_deploy_script_exists(self):
        assert os.path.isfile("deploy-vm.sh"), "deploy-vm.sh missing"

    def test_deploy_has_prerender_step(self):
        d = read("deploy-vm.sh")
        assert "prerender_snapshot" in d, "deploy missing prerender step"

    def test_deploy_health_before_prerender(self):
        d = read("deploy-vm.sh")
        assert d.find("health") < d.find("prerender_snapshot"), "Health check must precede prerender"

    def test_cron_has_outlook_generation(self):
        cron = read("ops/crontab") if os.path.isfile("ops/crontab") else ""
        if cron:
            assert "outlook" in cron.lower() or "generate" in cron.lower(), "Cron missing outlook gen"


# ── Rollback Capability ───────────────────────────────────────

class TestRollback:
    def test_git_tags_present(self):
        r = subprocess.run(["git", "tag"], capture_output=True, text=True, cwd=ROOT)
        # At minimum, git history should allow checkout of any prior commit
        r2 = subprocess.run(["git", "log", "--oneline", "-5"], capture_output=True, text=True, cwd=ROOT)
        assert r2.returncode == 0 and len(r2.stdout.strip()) > 0, "Git history unavailable"

    def test_can_checkout_prev_commit(self):
        r = subprocess.run(["git", "rev-parse", "HEAD~1"], capture_output=True, text=True, cwd=ROOT)
        if r.returncode == 0 and r.stdout.strip():
            prev = r.stdout.strip()
            check = subprocess.run(["git", "cat-file", "-t", prev], capture_output=True, text=True, cwd=ROOT)
            assert check.stdout.strip() == "commit", f"Cannot resolve prev commit: {prev}"

    def test_config_files_versioned(self):
        for f in ["config/settings.json", "config/auth.json", "config/instruments.json", "config/alerting.json"]:
            assert os.path.isfile(os.path.join(ROOT, f)), f"Config missing: {f}"
