#!/usr/bin/env python3
"""PHASE 6B-3 Phase B.1 — Verification."""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

results = []

def check(gate, name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    results.append((gate, name, status, detail))
    symbol = "✅" if passed else "❌"
    print(f"{symbol} {gate}: {name} — {status}" + (f" | {detail}" if detail else ""))

# Gate 1: All tests pass
print("\n=== B.1 Gate 1: All tests pass ===")
r = subprocess.run(["python3", "-m", "pytest", "tests/", "-q"], capture_output=True, text=True, timeout=120)
output = r.stdout + r.stderr
match = re.search(r"(\d+)\s+passed", output)
test_count = int(match.group(1)) if match else 0
passed = r.returncode == 0 and test_count >= 300
check(1, f"All {test_count} tests pass", passed, f"Exit: {r.returncode}, Tests: {test_count}")

# Gate 2: Model files untouched
print("\n=== B.1 Gate 2: Model files untouched ===")
result = subprocess.run(["git", "diff", "--name-only"], capture_output=True, text=True)
modified = result.stdout.strip().split('\n') if result.stdout.strip() else []
model_files = ['backend/regime.py', 'backend/strategies.py', 'backend/indicators.py', 'backend/options.py', 'backend/outlook.py', 'backend/scenarios.py', 'backend/ai_outlook.py', 'backend/backtest.py']
model_modified = [f for f in modified if f in model_files]
check(2, "No model files modified", len(model_modified) == 0, f"Modified: {model_modified}")

# Gate 3: CI config valid
print("\n=== B.1 Gate 3: CI/CD config ===")
import yaml
try:
    ci = yaml.safe_load(open(".github/workflows/regression.yml"))
    ci_ok = "name" in ci and "on" in ci and "jobs" in ci and "regression" in ci["jobs"]
    check(3, "CI config valid", ci_ok)
except Exception as e:
    check(3, "CI config valid", False, str(e))

# Gate 4: Pre-commit config valid
print("\n=== B.1 Gate 4: Pre-commit config ===")
try:
    pc = yaml.safe_load(open(".pre-commit-config.yaml"))
    pc_ok = "repos" in pc and len(pc["repos"]) > 0
    has_pytest = False
    has_hook = False
    for repo in pc.get("repos", []):
        for hook in repo.get("hooks", []):
            if "pytest" in str(hook.get("id", "")):
                has_pytest = True
            if "forbidden" in str(hook.get("id", "")) or "bare" in str(hook.get("id", "")):
                has_hook = True
    check(4, "Pre-commit config valid", pc_ok and has_pytest and has_hook)
except Exception as e:
    check(4, "Pre-commit config valid", False, str(e))

# Gate 5: Deploy script fixed
print("\n=== B.1 Gate 5: Deploy script fixed ===")
dv = open("deploy-vm.sh").read()
check(5, "No || true in deploy", "|| true" not in dv)
check(5, "Health assertion present", '"status": "ok"' in dv)

# Gate 6: Rollback exists
print("\n=== B.1 Gate 6: Rollback script ===")
rb = os.path.isfile("ops/rollback.sh")
check(6, "Rollback exists", rb)
if rb:
    rb_content = open("ops/rollback.sh").read()
    check(6.1, "Rollback has git checkout", "git checkout" in rb_content)
    check(6.2, "Rollback has health check", "api/health" in rb_content)
    check(6.3, "Rollback executable", os.access("ops/rollback.sh", os.X_OK))

print("\n" + "="*50)
all_pass = all(s == "PASS" for _, _, s, _ in results)
print(f"B.1 Result: {'ALL GATES PASS' if all_pass else 'SOME GATES FAILED'}")
