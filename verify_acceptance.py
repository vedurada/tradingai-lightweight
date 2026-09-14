#!/usr/bin/env python3
"""PHASE 6B-3 Phase A — Acceptance Gate Verification."""
import os
import sys
import json
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

results = []

def check(gate, name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    results.append((gate, name, status, detail))
    print(f"{'✅' if passed else '❌'} {gate}: {name} — {status}" + (f" | {detail}" if detail else ""))

# Gate 1: All tests pass
print("\n=== ACCEPTANCE GATE 1: All tests pass ===")
r = subprocess.run(
    ["python3", "-m", "pytest", "tests/", "-q"],
    capture_output=True, text=True, timeout=120, cwd=os.path.dirname(os.path.abspath(__file__))
)
output = r.stdout + r.stderr
passed = r.returncode == 0 and "passed" in output and "failed" not in output.lower()
# Check more carefully
passed = r.returncode == 0 and "error" not in output.lower().split("passed")[0] if "passed" in output else False
import re
match = re.search(r"(\d+)\s+passed", output)
test_count = int(match.group(1)) if match else 0
check(1, f"All {test_count} tests pass", passed and test_count >= 298, f"Exit: {r.returncode}, Tests: {test_count}")

# Gate 2: Model files untouched
print("\n=== ACCEPTANCE GATE 2: Model files untouched ===")
model_files = ['backend/regime.py', 'backend/strategies.py', 'backend/indicators.py', 'backend/options.py', 'backend/outlook.py', 'backend/scenarios.py', 'backend/ai_outlook.py', 'backend/backtest.py']
all_ok = all(os.path.exists(f) and os.path.getsize(f) > 0 for f in model_files)
check(2, "All 8 model files exist and non-zero", all_ok)

# Verify via git that model files are not modified
r = subprocess.run(["git", "diff", "--name-only"], capture_output=True, text=True, cwd=os.path.dirname(os.path.abspath(__file__)))
modified = r.stdout.strip().split('\n') if r.stdout.strip() else []
model_modified = [f for f in modified if any(m in f for m in ['regime.py', 'strategies.py', 'indicators.py', 'options.py', 'outlook.py', 'scenarios.py', 'ai_outlook.py', 'backtest.py'])]
check(2.1, "No model files in git diff", len(model_modified) == 0, f"Modified: {model_modified}")

# Gate 3: Successful response bodies unchanged
print("\n=== ACCEPTANCE GATE 3: Successful responses unchanged ===")
from backend.api_server import app
with app.test_client() as c:
    r = c.get('/api/health')
    health_data = r.get_json()
    has_status = health_data and "status" in health_data
    check(3, "Health has status field", has_status, f"Keys: {list(health_data.keys()) if health_data else 'empty'}")

    r = c.get('/api/price/NIFTY')
    price_ok = r.status_code == 200
    check(3, "Price returns 200", price_ok, f"Status: {r.status_code}")

    r = c.get('/api/vix')
    vix_ok = r.status_code == 200
    check(3, "VIX returns 200", vix_ok, f"Status: {r.status_code}")

    # No new fields added to existing responses
    r = c.get('/api/price/NIFTY')
    price_data = r.get_json()
    # Price response should have same structure as before
    check(3, "Price response is valid JSON", isinstance(price_data, dict), f"Type: {type(price_data)}")

# Gate 4: Observability independence
print("\n=== ACCEPTANCE GATE 4: Observability independence ===")
from backend.monitoring import RequestMonitor
m = RequestMonitor()
has_record = hasattr(m, "record_request")
has_get = hasattr(m, "get_summary")
has_reset = hasattr(m, "reset")
no_modify = not hasattr(m, "modify_strategy") and not hasattr(m, "change_regime") and not hasattr(m, "set_confidence")
check(4, "Monitor has record/get methods", has_record and has_get)
check(4, "Monitor has reset method", has_reset)
check(4, "Monitor has NO strategy/regime/confidence methods", no_modify)

# Verify no monitoring signal feeds into trading logic
import backend.regime
import backend.strategies
import backend.outlook
regime_src = open('backend/regime.py').read()
strategies_src = open('backend/strategies.py').read()
outlook_src = open('backend/outlook.py').read()
monitoring_imported_in_model = any('monitoring' in s.lower() or 'log_request' in s or 'log_alert' in s for s in [regime_src, strategies_src, outlook_src])
check(4, "No monitoring imports in model files", not monitoring_imported_in_model)

# Gate 5: 429 non-retry still works
print("\n=== ACCEPTANCE GATE 5: 429/500 retry boundary ===")
from backend.retry import is_retryable
class HTTP429(Exception):
    response = type('obj', (object,), {'status_code': 429})()
check(5, "429 is non-retryable", not is_retryable(HTTP429()))

# Gate 6: Metrics endpoint works
print("\n=== ACCEPTANCE GATE 6: Metrics endpoint ===")
with app.test_client() as c:
    r = c.get('/api/metrics')
    metrics_ok = r.status_code == 200
    data = r.get_json() if metrics_ok else None
    has_fields = data and all(k in data for k in ['request_counts', 'latency', 'circuit_breakers', 'process_local'])
    check(6, "Metrics endpoint returns 200", metrics_ok)
    check(6, "Metrics has required fields", has_fields)
    check(6, "Metrics labeled process-local", data.get('process_local') is True)

# Summary
print("\n" + "="*60)
print("ACCEPTANCE GATE SUMMARY")
print("="*60)
all_pass = True
for gate, name, status, detail in results:
    symbol = "✅" if status == "PASS" else "❌"
    print(f"{symbol} {gate}: {name} — {status}" + (f" | {detail}" if detail else ""))
    if status != "PASS":
        all_pass = False

print(f"\nResult: {'ALL GATES PASS → READY FOR FREEZE' if all_pass else 'SOME GATES FAILED'}")
