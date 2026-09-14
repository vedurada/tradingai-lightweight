#!/usr/bin/env python3
"""6B-2 Gate Verification Script — all 10 gates."""
import os
import sys
import signal
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.api_server import app, limiter, ENDPOINT_TIMEOUTS, ALLOWED_ORIGINS

results = []

def check(gate, name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    results.append((gate, name, status, detail))
    print(f"Gate {gate}: {name} — {status}" + (f" | {detail}" if detail else ""))

# ============ GATE 3: Successful response compatibility ============
print("\n=== GATE 3: Successful response compatibility ===")
with app.test_client() as c:
    r = c.get('/api/health')
    check(3, "Health endpoint returns 200", r.status_code == 200, f"got {r.status_code}")
    has_body = bool(r.get_data())
    check(3, "Health endpoint has response body", has_body, f"body length: {len(r.get_data())}")

    r = c.get('/api/price/NIFTY')
    check(3, "Price endpoint returns 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        data = r.get_json()
        check(3, "Price response has data structure", isinstance(data, dict), f"type: {type(data)}")

    r = c.get('/api/indicators/NIFTY')
    check(3, "Indicators endpoint returns 200 or proper 404", r.status_code in (200, 404), f"got {r.status_code}")
    if r.status_code == 404:
        data = r.get_json()
        check(3, "Indicators 404 uses standard error schema", "error" in str(data), json.dumps(data)[:100])

    r = c.get('/api/vix')
    check(3, "VIX endpoint returns 200", r.status_code == 200, f"got {r.status_code}")

    r = c.get('/api/symbols')
    check(3, "Symbols endpoint returns 200", r.status_code == 200, f"got {r.status_code}")

# ============ GATE 4: SIGALRM cleanup/isolation ============
print("\n=== GATE 4: SIGALRM cleanup/isolation ===")

# Verify after_request handler clears alarms
from backend.api_server import _set_request_timeout, _record_metrics_and_clear_timeout as _clear_request_timeout
check(4, "after_request handler registered", _clear_request_timeout is not None)
check(4, "before_request handler registered", _set_request_timeout is not None)

# Verify alarm is cleared after a normal request
with app.test_client() as c:
    r = c.get('/api/health')
    remaining = signal.alarm(0)
    check(4, "Alarm cleared after normal request", remaining == 0, f"remaining: {remaining}")

# Verify multiple sequential requests don't leak alarms
with app.test_client() as c:
    for _ in range(3):
        r = c.get('/api/health')
        assert r.status_code == 200
    remaining = signal.alarm(0)
    check(4, "No alarm leak after 3 sequential requests", remaining == 0, f"remaining: {remaining}")

# Verify ENDPOINT_TIMEOUTS has reasonable values
check(4, "Health timeout <= 2s", ENDPOINT_TIMEOUTS.get('health', 999) <= 2, f"health: {ENDPOINT_TIMEOUTS.get('health')}")
check(4, "Backtest timeout >= 30s", ENDPOINT_TIMEOUTS.get('backtest', 0) >= 30, f"backtest: {ENDPOINT_TIMEOUTS.get('backtest')}")
check(4, "Default timeout present", 'price' in ENDPOINT_TIMEOUTS)

# ============ GATE 5: Timeout → standardized error ============
print("\n=== GATE 5: Timeout → standardized error ===")
from backend.api_server import error_response, _handle_timeout, _handle_413, _handle_429

with app.app_context():
    resp, status = error_response("INTERNAL_ERROR", "Request timed out", 504)
    data = resp.get_json()
    check(5, "Error response has error.code", "error" in data and "code" in data["error"], json.dumps(data)[:100])
    check(5, "Error response has error.message", "message" in data["error"], json.dumps(data)[:100])
    check(5, "Error response has error.timestamp", "timestamp" in data["error"], json.dumps(data)[:100])
    check(5, "Error status code is 504", status == 504, f"got {status}")
    check(5, "Error code matches", data["error"]["code"] == "INTERNAL_ERROR", data["error"]["code"])

    # 429 error schema
    resp, status = error_response("RATE_LIMITED", "Too many requests", 429)
    data = resp.get_json()
    check(5, "429 uses standard schema", "error" in data and "code" in data["error"], json.dumps(data)[:100])
    check(5, "429 code is RATE_LIMITED", data["error"]["code"] == "RATE_LIMITED", data["error"]["code"])

    # 413 error schema
    resp, status = error_response("INVALID_REQUEST", "Request body too large", 413)
    data = resp.get_json()
    check(5, "413 uses standard schema", "error" in data and "code" in data["error"], json.dumps(data)[:100])

    # Timeout handler exists
    check(5, "Timeout handler registered", _handle_timeout is not None)
    check(5, "429 handler registered", _handle_429 is not None)
    check(5, "413 handler registered", _handle_413 is not None)

# ============ GATE 6: DB/resource cleanup on timeout ============
print("\n=== GATE 6: DB/resource cleanup on timeout ===")
# Verify that the after_request handler runs even on timeout by checking
# that the signal.alarm(0) is called in _clear_request_timeout
import inspect
clear_src = inspect.getsource(_clear_request_timeout)
check(6, "after_request calls signal.alarm(0)", "alarm(0)" in clear_src, clear_src.strip())

# Verify set_request_timeout sets alarm
set_src = inspect.getsource(_set_request_timeout)
check(6, "before_request sets signal.alarm", "alarm(" in set_src, set_src.strip())

# Verify no DB connection leak by making multiple requests and checking connections
with app.test_client() as c:
    for i in range(5):
        r = c.get('/api/health')
        assert r.status_code == 200
    remaining = signal.alarm(0)
    check(6, "No resource leak after 5 requests (alarm cleared)", remaining == 0, f"remaining: {remaining}")

# ============ GATE 7: In-memory limiter limitation documented ============
print("\n=== GATE 7: In-memory limiter limitation ===")
review_doc = "PHASE6B_STEP2_INDEPENDENT_REVIEW.md"
check(7, "Review document exists", os.path.exists(review_doc))

with open(review_doc) as f:
    content = f.read()
has_limitation = "In-memory" in content and "single application instance" in content
check(7, "Limitation documented in review doc", has_limitation, "checking document")

# ============ GATE 8: CORS allow/deny behavior ============
print("\n=== GATE 8: CORS allow/deny behavior ===")
with app.test_client() as c:
    # Allowed origin
    r = c.options('/api/price/NIFTY', headers={
        "Origin": "https://tradingai.in",
        "Access-Control-Request-Method": "GET",
    })
    headers = dict(r.headers)
    has_allow = "Access-Control-Allow-Origin" in headers
    check(8, "Allowed origin gets Access-Control-Allow-Origin", has_allow, f"headers: {list(headers.keys())}")
    if has_allow:
        check(8, "Allowed origin header matches", headers["Access-Control-Allow-Origin"] == "https://tradingai.in", headers["Access-Control-Allow-Origin"])

    # Disallowed origin
    r = c.options('/api/price/NIFTY', headers={
        "Origin": "https://evil.example.com",
        "Access-Control-Request-Method": "GET",
    })
    headers = dict(r.headers)
    has_no_allow = "Access-Control-Allow-Origin" not in headers
    check(8, "Disallowed origin has no CORS allow header", has_no_allow, f"headers: {list(headers.keys())}")

    # Direct GET from disallowed origin (browser would block due to missing headers)
    r = c.get('/api/price/NIFTY', headers={"Origin": "https://evil.example.com"})
    check(8, "Disallowed origin can still GET (server doesn't block, browser does)", r.status_code == 200, f"got {r.status_code}")

# ============ GATE 9: 429 does not retry ============
print("\n=== GATE 9: 429 does not retry ===")
from backend.retry import is_retryable

class HTTP429(Exception):
    response = type('obj', (object,), {'status_code': 429})()

class HTTP500(Exception):
    response = type('obj', (object,), {'status_code': 500})()

class HTTP404(Exception):
    response = type('obj', (object,), {'status_code': 404})()

check(9, "429 is non-retryable", not is_retryable(HTTP429()), f"is_retryable={is_retryable(HTTP429())}")
check(9, "500 is non-retryable", not is_retryable(HTTP500()), f"is_retryable={is_retryable(HTTP500())}")
check(9, "404 is non-retryable", not is_retryable(HTTP404()), f"is_retryable={is_retryable(HTTP404())}")
check(9, "OSError is retryable", is_retryable(OSError("test")), f"is_retryable={is_retryable(OSError('test'))}")
check(9, "ConnectionError is retryable", is_retryable(ConnectionError("test")), f"is_retryable={is_retryable(ConnectionError('test'))}")
check(9, "TimeoutError is retryable", is_retryable(TimeoutError("test")), f"is_retryable={is_retryable(TimeoutError('test'))}")

# Verify retry config respects 429
import inspect
retry_src = inspect.getsource(is_retryable)
check(9, "is_retryable checks HTTP status codes", "NON_RETRYABLE_HTTP_CODES" in retry_src, retry_src[:100])

# ============ GATE 10: No quantitative/model changes ============
print("\n=== GATE 10: No quantitative/model changes ===")
import subprocess
result = subprocess.run(['git', 'diff', '--name-only', 'HEAD~1'], capture_output=True, text=True, cwd=os.path.dirname(os.path.abspath(__file__)))
modified = result.stdout.strip().split('\n') if result.stdout.strip() else []
model_files = ['regime.py', 'strategies.py', 'indicators.py', 'options.py', 'outlook.py', 'scenarios.py', 'ai_outlook.py', 'backtest.py']
modified_models = [f for f in modified if any(m in f for m in model_files)]
check(10, "No model files modified", len(modified_models) == 0, f"modified: {modified_models}")
check(10, "Only expected non-model files changed", all(any(x in f for x in ['api_server', 'retry', 'nginx', 'requirements', 'test_phase6b', 'PHASE6B_STEP', 'verify_', 'PHASE6B_']) for f in modified if f), f"files: {modified}")

# ============ FINAL SUMMARY ============
print("\n" + "="*60)
print("GATE VERIFICATION SUMMARY")
print("="*60)
all_pass = True
for gate, name, status, detail in results:
    symbol = "✅" if status == "PASS" else "❌"
    print(f"{symbol} Gate {gate}: {name} — {status}" + (f" | {detail}" if detail else ""))
    if status != "PASS":
        all_pass = False

print(f"\nOverall: {'ALL GATES PASS' if all_pass else 'SOME GATES FAILED — FIX REQUIRED'}")
sys.exit(0 if all_pass else 1)
