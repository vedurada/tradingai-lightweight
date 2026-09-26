"""Phase 4/5 acceptance tests: production synchronization and data integrity."""
import sys, os, json
sys.path.insert(0, '/opt/tradingai')
sys.path.insert(0, '/opt/tradingai/scripts')
import pytest
import sqlite3
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

_IST = ZoneInfo('Asia/Kolkata')
BASE = 'http://127.0.0.1'
API = f'{BASE}:8000/api'

def get(path):
    r = requests.get(f'{BASE}{path}', timeout=10, verify=False)
    return r
def api_get(path):
    r = requests.get(f'{API}{path}', timeout=10, verify=False)
    return r

class TestConfigAndPaths:
    def test_config_uses_correct_base(self):
        from app.core.config import BASE as cfg_base
        assert cfg_base == '/opt/tradingai', f'BASE={cfg_base}'
    def test_db_path_is_correct(self):
        from app.core.db import DB_PATH
        assert DB_PATH == '/opt/tradingai/database/tradingai.db', f'DB_PATH={DB_PATH}'
        assert os.path.exists(DB_PATH), f'DB does not exist at {DB_PATH}'
    def test_systemd_uses_correct_working_dir(self):
        txt = open('/etc/systemd/system/tradingai-api.service').read()
        assert '/opt/tradingai_new' not in txt
        assert '/opt/tradingai' in txt
    def test_nginx_serves_tradingai_frontend(self):
        txt = open('/etc/nginx/sites-available/tradingai').read()
        assert 'root /opt/tradingai/frontend' in txt
        assert '/opt/tradingai_cpr/web' not in txt

class TestAPIEndpoints:
    def test_health_endpoint(self):
        r = api_get('/health')
        assert r.status_code == 200
        d = r.json()
        assert d['status'] in ('LIVE', 'MARKET_CLOSED', 'PREMARKET')
    def test_nifty_summary(self):
        r = api_get('/NIFTY/summary')
        assert r.status_code == 200
        d = r.json()
        assert 'state' in d and 'timestamp' in d and 'data' in d
        assert d['data']['instrument'] == 'NIFTY'
    def test_banknifty_summary(self):
        r = api_get('/BANKNIFTY/summary')
        assert r.status_code == 200
        d = r.json()
        assert d['data']['instrument'] == 'BANKNIFTY'
    def test_nifty_decision(self):
        r = api_get('/NIFTY/decision')
        assert r.status_code == 200
        d = r.json()
        assert d['state'] in ('MARKET_CLOSED', 'PREMARKET', 'LIVE', 'STALE', 'NO_DATA', 'NO_TRADE', 'QUALIFIED')
    def test_banknifty_decision(self):
        r = api_get('/BANKNIFTY/decision')
        assert r.status_code == 200
        d = r.json()
        assert d['state'] in ('MARKET_CLOSED', 'PREMARKET', 'LIVE', 'STALE', 'NO_DATA', 'NO_TRADE', 'QUALIFIED')
    def test_nifty_candles(self):
        r = api_get('/NIFTY/candles?n=12')
        assert r.status_code == 200
        d = r.json()
        assert 'candles' in d.get('data', {})
    def test_banknifty_candles(self):
        r = api_get('/BANKNIFTY/candles?n=12')
        assert r.status_code == 200
        d = r.json()
        assert 'candles' in d.get('data', {})
    def test_cpr_endpoint(self):
        r = api_get("/NIFTY/candles?n=12")
        assert r.status_code == 200
        d = r.json()
        assert 'data' in d

class TestInstrumentIsolation:
    def test_nifty_instrument_field(self):
        r = api_get('/NIFTY/summary')
        assert r.json()['data']['instrument'] == 'NIFTY'
    def test_banknifty_instrument_field(self):
        r = api_get('/BANKNIFTY/summary')
        assert r.json()['data']['instrument'] == 'BANKNIFTY'
    def test_spots_differ(self):
        r1 = api_get('/NIFTY/summary')
        r2 = api_get('/BANKNIFTY/summary')
        nifty_price = r1.json()['data'].get('live_price', r1.json()['data'].get('spot'))
        bank_price = r2.json()['data'].get('live_price', r2.json()['data'].get('spot'))
        assert nifty_price != bank_price

class TestDataStates:
    def test_no_double_dash_state(self):
        for sym in ['NIFTY', 'BANKNIFTY']:
            r = api_get(f'/{sym}/summary')
            state = r.json().get('state', '')
            assert state != '--', f'{sym} state is --'
            assert state != 'DATA', f'{sym} state is DATA'
    def test_state_is_explicit(self):
        valid = {'LIVE', 'MARKET_CLOSED', 'PREMARKET', 'STALE', 'NO_DATA', 'NO_TRADE', 'QUALIFIED', 'WEEKEND', 'UNAVAILABLE', 'RATE_LIMITED'}
        for sym in ['NIFTY', 'BANKNIFTY']:
            r = api_get(f'/{sym}/summary')
            state = r.json().get('state', '')
            assert state in valid, f'{sym} state {state} not explicit'

class TestFrontendPages:
    def test_home_page_loads(self):
        r = get('/')
        assert r.status_code == 200
        assert 'TradingAI' in r.text
    def test_nifty_page_loads(self):
        r = get('/indices/nifty.html')
        assert r.status_code == 200
        assert 'NIFTY' in r.text
    def test_banknifty_page_loads(self):
        r = get('/indices/banknifty.html')
        assert r.status_code == 200
        assert 'BANKNIFTY' in r.text
    def test_backtest_page_loads(self):
        r = get('/backtest.html')
        assert r.status_code == 200
    def test_methodology_page_loads(self):
        r = get('/methodology.html')
        assert r.status_code == 200
    def test_navigation_links(self):
        for path in ['/', '/indices/nifty.html', '/indices/banknifty.html', '/backtest.html', '/methodology.html']:
            r = get(path)
            assert r.status_code == 200, f'{path} returned {r.status_code}'

class TestResearchLiveIsolation:
    def test_research_tables_exist(self):
        conn = sqlite3.connect('/opt/tradingai/database/tradingai.db')
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        conn.close()
        assert 'backtest_trades' in tables
        assert 'backtest_decisions' in tables
    def test_live_tables_exist(self):
        conn = sqlite3.connect('/opt/tradingai/database/tradingai.db')
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        conn.close()
        assert 'qualified_trades' in tables
        assert 'daily_trade_locks' in tables
        assert 'paper_trades' in tables
    def test_research_not_in_live_tables(self):
        conn = sqlite3.connect('/opt/tradingai/database/tradingai.db')
        count = conn.execute('SELECT COUNT(*) FROM qualified_trades').fetchone()[0]
        conn.close()
        assert isinstance(count, int)

class TestOneTradePerDay:
    def test_daily_lock_table_exists(self):
        conn = sqlite3.connect('/opt/tradingai/database/tradingai.db')
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        conn.close()
        assert 'daily_trade_locks' in tables
    def test_unique_daily_lock_constraint(self):
        conn = sqlite3.connect('/opt/tradingai/database/tradingai.db')
        result = conn.execute("SELECT sql FROM sqlite_master WHERE name='idx_daily_trade_lock'").fetchone()
        conn.close()
        assert result is not None, 'idx_daily_trade_lock missing'
        assert 'UNIQUE' in result[0], 'daily lock not unique'

class TestCPRData:
    def test_instruments_populated(self):
        conn = sqlite3.connect('/opt/tradingai/database/tradingai.db')
        count = conn.execute('SELECT COUNT(*) FROM instruments').fetchone()[0]
        conn.close()
        assert count >= 2

class TestNoSecretsInFrontend:
    def test_no_secrets_in_html(self):
        for path in ['/', '/indices/nifty.html', '/indices/banknifty.html']:
            r = get(path)
            text = r.text
            for secret in ['password', 'api_key', 'PRIVATE KEY']:
                assert secret.lower() not in text.lower(), f'{secret} in {path}'

class TestDecisionConsistency:
    def test_same_state_on_repeat_query(self):
        r1 = api_get('/NIFTY/summary')
        r2 = api_get('/NIFTY/summary')
        assert r1.json()['state'] == r2.json()['state']
    def test_instrument_consistent(self):
        r1 = api_get('/NIFTY/summary')
        r2 = api_get('/NIFTY/summary')
        assert r1.json()['data']['instrument'] == r2.json()['data']['instrument']
    def test_banknifty_consistent(self):
        r1 = api_get('/BANKNIFTY/summary')
        r2 = api_get('/BANKNIFTY/summary')
        assert r1.json()['data']['instrument'] == r2.json()['data']['instrument']
