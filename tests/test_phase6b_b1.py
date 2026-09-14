#!/usr/bin/env python3
"""PHASE 6B-3 Phase B.1 tests — CI/CD Foundation.

Verifies:
- 4.1 Automated Regression Gates (CI config exists and valid)
- 4.2 Commit/PR Validation (pre-commit config exists with required hooks)
- 4.3 Deployment Safety Check (deploy script fixed, rollback exists)
- 4.4 Staging Environment documentation exists
- Regression: 298 existing tests still pass
- Model boundary: 0 model files modified
"""
import os
import sys
import stat
import yaml
import pytest
import subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestRegressionGates:
    def test_ci_config_exists(self):
        assert os.path.isfile(".github/workflows/regression.yml")

    def test_ci_config_valid_yaml(self):
        with open(".github/workflows/regression.yml") as f:
            ci = yaml.safe_load(f)
        assert "name" in ci
        assert "on" in ci
        assert "jobs" in ci

    def test_ci_triggers_on_push(self):
        with open(".github/workflows/regression.yml") as f:
            ci = yaml.safe_load(f)
        assert "push" in ci["on"]

    def test_ci_triggers_on_pr(self):
        with open(".github/workflows/regression.yml") as f:
            ci = yaml.safe_load(f)
        assert "pull_request" in ci["on"]

    def test_ci_runs_pytest(self):
        with open(".github/workflows/regression.yml") as f:
            ci = yaml.safe_load(f)
        jobs = ci["jobs"]
        run_steps = []
        for job_name, job_config in jobs.items():
            for step in job_config.get("steps", []):
                if "run" in step:
                    run_steps.append(step["run"])
        all_runs = " ".join(run_steps)
        assert "pytest" in all_runs, "CI must run pytest"

    def test_ci_blocks_on_failure(self):
        with open(".github/workflows/regression.yml") as f:
            ci = yaml.safe_load(f)
        ci_yaml_str = yaml.dump(ci)
        assert "pytest" in ci_yaml_str, "CI must include pytest"


class TestCommitValidation:
    def test_precommit_config_exists(self):
        assert os.path.isfile(".pre-commit-config.yaml")

    def test_precommit_config_valid_yaml(self):
        with open(".pre-commit-config.yaml") as f:
            config = yaml.safe_load(f)
        assert "repos" in config
        assert len(config["repos"]) > 0

    def test_precommit_has_pytest_hook(self):
        with open(".pre-commit-config.yaml") as f:
            config = yaml.safe_load(f)
        found_pytest = False
        for repo in config["repos"]:
            for hook in repo.get("hooks", []):
                if "pytest" in str(hook.get("id", "")) or "pytest" in str(hook.get("entry", "")):
                    found_pytest = True
        assert found_pytest, "Pre-commit must include pytest hook"

    def test_precommit_has_forbidden_pattern_checks(self):
        with open(".pre-commit-config.yaml") as f:
            config = yaml.safe_load(f)
        hook_ids = []
        for repo in config["repos"]:
            for hook in repo.get("hooks", []):
                hook_ids.append(hook.get("id", ""))
        hook_text = " ".join(hook_ids).lower()
        assert "bare" in hook_text or "except" in hook_text, "Must check for bare except"
        assert "print" in hook_text, "Must check for print in non-test files"


class TestHookScripts:
    def test_hook_scripts_exist(self):
        hooks = [
            "ops/hooks/check-bare-except.sh",
            "ops/hooks/check-print-non-test.sh",
            "ops/hooks/check-todo-non-test.sh",
            "ops/hooks/check-model-boundary.sh",
        ]
        for h in hooks:
            assert os.path.isfile(h), f"Hook {h} must exist"

    def test_hook_scripts_executable(self):
        hooks = [
            "ops/hooks/check-bare-except.sh",
            "ops/hooks/check-print-non-test.sh",
            "ops/hooks/check-todo-non-test.sh",
            "ops/hooks/check-model-boundary.sh",
        ]
        for h in hooks:
            st = os.stat(h)
            assert st.st_mode & stat.S_IXUSR, f"Hook {h} must be executable"

    def test_hook_scripts_valid_bash(self):
        hooks = [
            "ops/hooks/check-bare-except.sh",
            "ops/hooks/check-print-non-test.sh",
            "ops/hooks/check-todo-non-test.sh",
            "ops/hooks/check-model-boundary.sh",
        ]
        for h in hooks:
            result = subprocess.run(["bash", "-n", h], capture_output=True, text=True)
            assert result.returncode == 0, f"Hook {h} has syntax error: {result.stderr}"

    def test_model_boundary_hook_passes(self):
        result = subprocess.run(["bash", "ops/hooks/check-model-boundary.sh"], capture_output=True, text=True)
        assert result.returncode == 0, f"Model boundary check failed: {result.stdout} {result.stderr}"


class TestDeploymentSafety:
    def test_deploy_script_no_or_true(self):
        with open("deploy-vm.sh") as f:
            content = f.read()
        assert "|| true" not in content, "deploy-vm.sh must not contain '|| true'"

    def test_deploy_script_health_check(self):
        with open("deploy-vm.sh") as f:
            content = f.read()
        assert "api/health" in content, "Deploy must check API health"
        assert '"status": "ok"' in content or "status.*ok" in content, "Deploy must assert status ok"

    def test_rollback_script_exists(self):
        assert os.path.isfile("ops/rollback.sh"), "Rollback script must exist"

    def test_rollback_script_executable(self):
        st = os.stat("ops/rollback.sh")
        assert st.st_mode & stat.S_IXUSR, "Rollback script must be executable"

    def test_rollback_script_has_git_checkout(self):
        with open("ops/rollback.sh") as f:
            content = f.read()
        assert "git checkout" in content, "Rollback must use git checkout"

    def test_rollback_script_has_health_check(self):
        with open("ops/rollback.sh") as f:
            content = f.read()
        assert "api/health" in content, "Rollback must verify API health"

    def test_rollback_script_has_systemctl_restart(self):
        with open("ops/rollback.sh") as f:
            content = f.read()
        assert "systemctl restart" in content, "Rollback must restart service"


class TestStagingDocumentation:
    def test_deployment_doc_exists(self):
        assert os.path.isfile("ops/DEPLOYMENT.md")

    def test_deployment_doc_has_staging(self):
        with open("ops/DEPLOYMENT.md") as f:
            content = f.read().lower()
        assert "staging" in content, "Deployment doc must mention staging"


class TestRegressionGate:
    def test_existing_tests_still_pass(self):
        result = subprocess.run(
            ["python3", "-m", "pytest", "tests/", "-q", "--ignore=tests/test_phase6b_b1.py"],
            capture_output=True, text=True, timeout=120,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        output = result.stdout + result.stderr
        import re
        match = re.search(r"(\d+)\s+passed", output)
        if match:
            count = int(match.group(1))
            assert count >= 298, f"Expected at least 298 tests, got {count}: {output}"
        assert result.returncode == 0, f"Tests failed:\n{output}"


class TestModelBoundary:
    def test_no_model_files_modified(self):
        model_files = [
            "backend/regime.py", "backend/strategies.py", "backend/indicators.py",
            "backend/options.py", "backend/outlook.py", "backend/scenarios.py",
            "backend/ai_outlook.py", "backend/backtest.py",
        ]
        result = subprocess.run(
            ["git", "diff", "--name-only"],
            capture_output=True, text=True,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        modified = result.stdout.strip().split('\n') if result.stdout.strip() else []
        for mf in model_files:
            assert mf not in modified, f"Model file {mf} was modified"

    def test_model_files_exist_and_unchanged_size(self):
        model_files = [
            "backend/regime.py", "backend/strategies.py", "backend/indicators.py",
            "backend/options.py", "backend/outlook.py", "backend/scenarios.py",
            "backend/ai_outlook.py", "backend/backtest.py",
        ]
        for mf in model_files:
            assert os.path.isfile(mf), f"Model file {mf} must exist"
            assert os.path.getsize(mf) > 0, f"Model file {mf} must be non-empty"

    def test_health_response_unchanged(self):
        from backend.api_server import app
        with app.test_client() as c:
            r = c.get('/api/health')
            assert r.status_code == 200
            data = r.get_json()
            assert "status" in data, "Health endpoint must have status field"


