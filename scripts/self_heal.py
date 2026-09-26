#!/usr/bin/env python3
"""TradingAI self-heal watchdog (runs every 2 min via systemd timer).

Checks API health, homepage serve path, disk headroom and DB readability.
On consecutive API failures it restarts tradingai-api (cooldown-guarded).
Always exits 0 after logging; state in logs/selfheal.state.json.
Read-only vs business data (SELECT 1 probe only).
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

BASE = '/opt/tradingai'
LOGS = os.path.join(BASE, 'logs')
STATE = os.path.join(LOGS, 'selfheal.state.json')
LOGF = os.path.join(LOGS, 'selfheal.log')
FAIL_STREAK = 3
RESTART_COOLDOWN_S = 600
MIN_DISK_PCT = 10.0


def log(msg):
    line = '%s selfheal %s' % (
        time.strftime('%Y-%m-%dT%H:%M:%S%z'), msg)
    try:
        with open(LOGF, 'a') as f:
            f.write(line + '\n')
    except OSError:
        pass
    print(line, flush=True)


def load_state():
    try:
        with open(STATE) as f:
            st = json.load(f)
            return int(st.get('fail_streak', 0)), float(st.get('last_restart', 0))
    except (OSError, ValueError, TypeError):
        return 0, 0.0


def save_state(streak, last_restart):
    try:
        with open(STATE, 'w') as f:
            json.dump({'fail_streak': streak, 'last_restart': last_restart}, f)
    except OSError as e:
        log('state-write failed: %s' % e)


def http_ok(url, timeout=10):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= r.status < 300
    except Exception as e:
        log('probe %s failed: %s: %s' % (url, type(e).__name__, str(e)[:100]))
        return False


def disk_ok():
    try:
        free_pct = shutil.disk_usage('/').free * 100.0 / shutil.disk_usage('/').total
        if free_pct < MIN_DISK_PCT:
            log('disk low: %.1f%% free' % free_pct)
            return False
        return True
    except Exception as e:
        log('disk check failed: %s' % e)
        return False


def db_ok():
    try:
        import sqlite3
        c = sqlite3.connect(os.path.join(BASE, 'database', 'tradingai.db'),
                            timeout=5)
        c.execute('SELECT 1').fetchone()
        c.close()
        return True
    except Exception as e:
        log('db probe failed: %s' % e)
        return False


def svc_active(name):
    try:
        out = subprocess.run(['systemctl', 'is-active', name],
                             capture_output=True, text=True, timeout=15)
        return out.stdout.strip() == 'active'
    except Exception as e:
        log('systemctl probe failed: %s' % e)
        return False


def restart_api():
    try:
        r = subprocess.run(['sudo', '-n', 'systemctl', 'restart', 'tradingai-api'],
                           capture_output=True, text=True, timeout=90)
        log('restart tradingai-api rc=%d err=%s' % (r.returncode, r.stderr.strip()[:120]))
        return r.returncode == 0
    except Exception as e:
        log('restart failed: %s' % e)
        return False


def main():
    streak, last_restart = load_state()
    api = http_ok('http://127.0.0.1:8000/api/health')
    disk_ok()
    db_ok()
    nginx = svc_active('nginx')
    if not nginx:
        log('nginx not active')
    if api:
        if streak:
            log('api recovered after streak=%d' % streak)
        save_state(0, last_restart)
        log('ok')
        return 0
    streak += 1
    now = time.time()
    if streak >= FAIL_STREAK and (now - last_restart) >= RESTART_COOLDOWN_S:
        log('api down streak=%d -> restarting' % streak)
        if restart_api():
            time.sleep(8)
            if http_ok('http://127.0.0.1:8000/api/health'):
                log('restart recovered api')
                save_state(0, now)
                return 0
            log('restart did not recover api')
        save_state(streak, now)
    else:
        log('api down streak=%d (cooldown)' % streak)
        save_state(streak, last_restart)
    return 0


if __name__ == '__main__':
    sys.exit(main())
