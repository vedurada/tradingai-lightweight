#!/usr/bin/env python3
"""End-to-end verification for the independent SMA9 HIGH live system."""
import json
import os
import sqlite3
import subprocess
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

BASE = "/opt/tradingai"
DB = os.path.join(BASE, "database", "sma9_high.db")
LOCK_ROOT = os.path.join(BASE, "sma9_high_scanner")
IST = ZoneInfo("Asia/Kolkata")


def http_json(url):
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status, json.loads(r.read().decode())
    except Exception as e:
        return None, {"error": str(e)}


def http_code(url):
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status
    except Exception as e:
        return str(e)


c = sqlite3.connect(DB)
c.row_factory = sqlite3.Row
one = lambda q, p=(): c.execute(q, p).fetchone()[0]
checks = {}
checks["live_rows"] = one("SELECT COUNT(*) FROM sma9_high_trades WHERE dataset='LIVE'")
checks["open_positions"] = one("SELECT COUNT(*) FROM sma9_high_open_positions")
checks["duplicate_live_entries"] = len(list(c.execute(
    "SELECT option_type, entry_candle_start, COUNT(*) n FROM sma9_high_trades "
    "WHERE dataset='LIVE' GROUP BY option_type, entry_candle_start HAVING n>1")))
checks["bad_exit"] = len(list(c.execute(
    "SELECT trade_id FROM sma9_high_trades WHERE dataset='LIVE' AND "
    "(exit_timestamp != entry_candle_end OR ABS(exit_price - candle_close) > 0.011)")))
checks["bad_pnl"] = len(list(c.execute(
    "SELECT trade_id FROM sma9_high_trades WHERE dataset='LIVE' AND "
    "ABS(pnl_points - ROUND(exit_price-entry_price,2)) > 0.011")))
checks["missing_fields"] = len(list(c.execute(
    "SELECT trade_id FROM sma9_high_trades WHERE dataset='LIVE' AND "
    "(sma_value IS NULL OR condition_a IS NULL OR condition_b IS NULL "
    "OR entry_candle_start IS NULL)")))
c.close()

api = {}
for path in ["/api/sma9-high/scanner-status", "/api/sma9-high/live-status",
             "/api/sma9-high/today", "/api/sma9-high/recent-trades?limit=2",
             "/api/sma9-high/daily-summary", "/api/sma9-high/legacy-audit",
             "/api/sma9-high/trades?limit=2", "/api/sma9-high/open-positions"]:
    code, body = http_json("http://127.0.0.1:8000" + path)
    api[path] = {"status": code, "success": body.get("success")}

public = {
    "dashboard": http_code("https://tradingai.in/live/sma9-high/"),
    "scanner_status": http_code("https://tradingai.in/api/sma9-high/scanner-status"),
    "today": http_code("https://tradingai.in/api/sma9-high/today"),
}

services = {}
for svc in ["tradingai-sma9-high-scanner.service", "tradingai-api.service"]:
    services[svc] = {
        "active": subprocess.run(["systemctl", "is-active", svc],
                                 capture_output=True, text=True).stdout.strip(),
        "enabled": subprocess.run(["systemctl", "is-enabled", svc],
                                  capture_output=True, text=True).stdout.strip(),
    }

src = ""
for f in ["sma9_high_scanner/app/sma9_high_engine.py",
          "sma9_high_scanner/app/live_sma9_high_scanner.py"]:
    src += open(os.path.join(BASE, f)).read()
checks["no_broker_order_calls"] = ("place_order" not in src
                                   and "order_id" not in src)

manifest = os.path.join(LOCK_ROOT, "MANIFEST.sha256")
if os.path.exists(manifest):
    p = subprocess.run(["sha256sum", "-c", "--quiet", manifest],
                       cwd=LOCK_ROOT, capture_output=True, text=True)
    checks["integrity_ok"] = p.returncode == 0
else:
    checks["integrity_ok"] = None
checks["service_user"] = subprocess.run(
    ["systemctl", "show", "tradingai-sma9-high-scanner.service", "-p", "User",
     "--value"], capture_output=True, text=True).stdout.strip()

state = {}
code, body = http_json("http://127.0.0.1:8000/api/sma9-high/live-status")
state = body.get("data", {})

passed = (
    not checks["duplicate_live_entries"] and not checks["bad_exit"]
    and not checks["bad_pnl"] and not checks["missing_fields"]
    and all(v.get("status") == 200 for v in api.values())
    and all(v == 200 for v in public.values())
    and all(v["active"] == "active" for v in services.values())
    and checks["no_broker_order_calls"]
    and checks["integrity_ok"] is True
    and checks["service_user"] == "sma9high"
)
print(json.dumps({
    "verified_at": datetime.now(IST).isoformat(),
    "overall_pass": passed,
    "checks": checks,
    "api": api,
    "public": public,
    "services": services,
    "scanner_state": {
        "status": state.get("status"),
        "last_scan_at": state.get("last_scan_at"),
        "spot": state.get("spot"),
        "atm_strike": state.get("atm_strike"),
        "expiry": state.get("expiry"),
        "errors": state.get("errors"),
        "today": state.get("today"),
    },
}, indent=2, default=str))
raise SystemExit(0 if passed else 1)
