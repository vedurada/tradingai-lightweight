#!/usr/bin/env python3
import json
import os
import sys
import shutil
import subprocess
from datetime import datetime, timezone, timedelta

DATA_DIR = "/opt/tradingai/data"
HEALTH_FILE = os.path.join(DATA_DIR, "health.json")
LOG_FILE = "/opt/tradingai/logs/monitor.log"
STALE_MINUTES = 15
DB_PATH = "/opt/tradingai/database/tradingai.db"

def log(msg):
    ts = datetime.now(timezone.utc).isoformat()
    line = f"[{ts}] {msg}"
    print(line)
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def check_db():
    try:
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM history")
        count = c.fetchone()[0]
        conn.close()
        return True, f"history rows: {count}"
    except Exception as e:
        return False, f"DB error: {e}"

def check_disk():
    try:
        usage = shutil.disk_usage("/")
        pct = (usage.used / usage.total) * 100
        return pct < 90, f"disk: {pct:.1f}%"
    except Exception as e:
        return False, f"disk error: {e}"

def check_cron():
    try:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=5)
        has_cron = "generate_data" in result.stdout or "generate_json" in result.stdout
        return has_cron, f"cron: {'configured' if has_cron else 'missing'}"
    except Exception as e:
        return False, f"cron error: {e}"

def check_data_freshness():
    try:
        for fname in ["nifty.json", "banknifty.json"]:
            fpath = os.path.join(DATA_DIR, fname)
            if not os.path.exists(fpath):
                return False, f"{fname} missing"
            mtime = datetime.fromtimestamp(os.path.getmtime(fpath), tz=timezone.utc)
            age = (datetime.now(timezone.utc) - mtime).total_seconds() / 60
            if age > STALE_MINUTES:
                return False, f"{fname} stale by {age:.0f}min"
        return True, "all data fresh"
    except Exception as e:
        return False, f"freshness error: {e}"

def check_health():
    checks = {
        "health_file": os.path.exists(HEALTH_FILE),
        "database": check_db(),
        "disk": check_disk(),
        "cron": check_cron(),
        "freshness": check_data_freshness(),
    }

    all_ok = True
    for name, result in checks.items():
        if isinstance(result, tuple):
            ok, msg = result
        else:
            ok = result
            msg = "OK" if ok else "FAIL"
        if not ok:
            all_ok = False
        log(f"CHECK {name}: {'PASS' if ok else 'FAIL'} - {msg}")

    now = datetime.now(timezone.utc)
    status = "healthy" if all_ok else "degraded"
    stale_instruments = []

    try:
        if os.path.exists(HEALTH_FILE):
            with open(HEALTH_FILE) as f:
                h = json.load(f)
                stale_instruments = h.get("stale_instruments", [])
                if h.get("status") != "healthy":
                    status = "degraded"
    except Exception:
        pass

    health = {
        "status": status,
        "stale_instruments": stale_instruments,
        "total_instruments": 13,
        "last_updated": now.isoformat(),
        "checks": {name: ("PASS" if (r[0] if isinstance(r, tuple) else r) else "FAIL") for name, r in checks.items()},
    }

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(HEALTH_FILE, "w") as f:
        json.dump(health, f, indent=2)

    log(f"Health check: {status}")
    return all_ok

if __name__ == "__main__":
    ok = check_health()
    sys.exit(0 if ok else 1)