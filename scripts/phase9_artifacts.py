#!/usr/bin/env python3
"""Phase 9 machine-readable diagnostics (compact, deterministic).

Writes data/generated/:
  phase9_deployment_audit.json  - nginx/service/webroot facts
  phase9_freshness_results.json - STALE/NO_DATA/PREMARKET/CLOSED probe outcomes
  phase9_live_replay_parity.json- per-candle live-vs-replay MATCH rows (09-16 NIFTY)
  phase9_api_audit.json         - localhost endpoint statuses (no nginx needed)
  phase9_live_data_audit.json   - provider contract facts
Follows project conventions (git-ignored like Phase 7/8 JSONs).
"""
import sys, json, urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
sys.path.insert(0, '/opt/tradingai_new')
from app.live.engine import LiveEngine, STALE_AFTER_MIN
from app.core.db import get_conn
from app.research.replay import SequentialReplay

_IST = ZoneInfo('Asia/Kolkata')
GEN = '/opt/tradingai_new/data/generated'
WED = '2026-09-16'


def dump(name, obj):
    json.dump(obj, open(f'{GEN}/{name}', 'w'), indent=1)
    print('wrote', name)


# ---- deployment ----
ng = open('/etc/nginx/sites-enabled/tradingai').read()
svc = open('/etc/systemd/system/tradingai-api.service').read()
import os
dump('phase9_deployment_audit.json', {
    'server_name': 'tradingai.in + www.tradingai.in' if 'server_name tradingai.in' in ng else 'UNKNOWN',
    'nginx_root': '/var/www/tradingai.in/html',
    'nginx_root_entries': sorted(os.listdir('/var/www/tradingai.in/html')),
    'api_proxy': 'http://127.0.0.1:8000' if 'proxy_pass http://127.0.0.1:8000;' in ng else 'UNKNOWN',
    'gunicorn_workdir': '/opt/tradingai_new' if 'WorkingDirectory=/opt/tradingai_new' in svc else 'UNKNOWN',
    'gunicorn_app': 'app.api.app:app' if 'app.api.app:app' in svc else 'UNKNOWN',
    'legacy_webroot_var_www_tradingai': 'ABSENT' if not os.path.exists('/var/www/tradingai/html') else 'PRESENT',
    'opt_served_by_nginx': '/opt/tradingai_new' in ng,
})

# ---- data source ----
from app.market.provider import MarketDataProvider
dump('phase9_live_data_audit.json', {
    'source': 'yfinance', 'symbols': {'NIFTY': '^NSEI', 'BANKNIFTY': '^NSEBANK'},
    'candle_convention': 'timestamp == candle OPEN, Asia/Kolkata +05:30',
    'completion_rule': 'complete once wall time >= open+5m; provider flags is_complete',
    'quote_timestamp_semantics': 'latest candle timestamp (never wall-clock); age_seconds exposed',
    'collector_daemon': 'NONE - on-demand fetch per API call',
    'stale_after_min': STALE_AFTER_MIN,
})

# ---- freshness probes (injected feed, deterministic) ----
conn = get_conn()
rows = [dict(c) for c in conn.execute(
    "SELECT timestamp,open,high,low,close,volume FROM market_candles_5m "
    "WHERE instrument_id='NIFTY' AND substr(timestamp,1,10)=? ORDER BY timestamp", (WED,)).fetchall()]
conn.close()


def eng_with(upto):
    return LiveEngine(
        quote_fn=lambda i: {'price': 1.0, 'timestamp': upto[-1]['timestamp'],
                            'age_seconds': 60.0, 'state': 'LIVE', 'source': 'test'},
        candles_fn=lambda i, c: upto)


def ev(upto, now):
    return LiveEngine(
        quote_fn=lambda i: {'price': 1.0, 'timestamp': upto[-1]['timestamp'] if upto else None,
                            'age_seconds': 60.0, 'state': 'LIVE', 'source': 'test'},
        candles_fn=lambda i, c: upto).evaluate('NIFTY', now=datetime.fromisoformat(now), dry_run=True)


upto_55 = [c for c in rows if c['timestamp'] <= f'{WED}T09:55:00+05:30']
upto_30 = [c for c in rows if c['timestamp'] <= f'{WED}T09:30:00+05:30']
probes = {
    'dead_feed_becomes_STALE': ev(upto_55, f'{WED}T10:11:00+05:30')['state'],
    'missing_completed_becomes_NO_DATA': ev(upto_30, f'{WED}T09:40:00+05:30')['state'],
    'premarket': ev(upto_30, f'{WED}T08:00:00+05:30')['state'],
    'weekend_closed': ev(upto_30, '2026-09-19T10:00:00+05:30')['state'],  # WEEKEND since Phase 11
    'stale_trades_nothing': 'trade' in ev(upto_55, f'{WED}T10:11:00+05:30'),
}
dump('phase9_freshness_results.json', {
    'stale_after_min': STALE_AFTER_MIN, 'probes': probes,
    'verdict': 'PASS' if probes == {'dead_feed_becomes_STALE': 'STALE',
                                    'missing_completed_becomes_NO_DATA': 'NO_DATA',
                                    'premarket': 'PREMARKET', 'weekend_closed': 'WEEKEND',
                                    'stale_trades_nothing': False} else 'FAIL'})


# ---- live/replay parity (09-16 NIFTY, per-candle rows) ----
def candles_fn(inst, completed):
    return [c for c in rows if c['timestamp'] <= completed.isoformat()]


def quote_fn(inst):
    return {'price': rows[-1]['close'], 'timestamp': rows[-1]['timestamp'],
            'age_seconds': 60.0, 'state': 'LIVE', 'source': 'test'}


eng = LiveEngine(quote_fn=quote_fn, candles_fn=candles_fn)
rep = SequentialReplay().run('NIFTY', WED, WED + 'T23:59:59+05:30')
trace = {t['timestamp']: t for t in rep['traces'] if t['trade_date'] == WED}
rows_out, mismatch = [], 0
for c in rows:
    now = datetime.fromisoformat(c['timestamp']) + timedelta(minutes=5, seconds=30)
    st = eng.evaluate('NIFTY', now=now, dry_run=True)
    if st.get('decision_timestamp') is None:
        continue
    live_q = 'QUALIFIED_TRADE' if st['state'] == 'QUALIFIED' else 'NO_TRADE'
    want = trace[st['decision_timestamp']]['qualification']
    rows_out.append({'candle': st['decision_timestamp'], 'live': live_q, 'replay': want,
                     'verdict': 'MATCH' if live_q == want else 'MISMATCH'})
    mismatch += (live_q != want)
dump('phase9_live_replay_parity.json', {
    'day': WED, 'instrument': 'NIFTY', 'compared': len(rows_out),
    'mismatches': mismatch, 'verdict': 'PASS' if mismatch == 0 else 'FAIL',
    'rows': rows_out})

# ---- API audit (localhost; nginx currently down) ----
api = {}
for path in ['/api/health', '/api/NIFTY/summary', '/api/BANKNIFTY/summary',
             '/api/research/scenarios', '/api/research/scenarios/NIFTY',
             '/api/research/performance',
             '/api/research/replay/NIFTY/2026-09-16/14:15:00+05:30']:
    try:
        with urllib.request.urlopen('http://127.0.0.1:8000' + path, timeout=15) as r:
            body = json.loads(r.read().decode())
        api[path] = {'http': r.status,
                     'state': body.get('state'),
                     'has_reasons_or_data': bool(body.get('data'))}
    except Exception as e:
        api[path] = {'http': 'ERROR', 'detail': str(e)[:120]}
dump('phase9_api_audit.json', api)
