"""Phase 10 tests: production deployment & operations.

Verifies the deployed stack without modifying it:
  nginx running + enabled, API service enabled + serving new code,
  webroot matches validated frontend source, HTTPS + proxy live.
"""
import sys, os, hashlib, ssl, urllib.request
sys.path.insert(0, '/opt/tradingai_new')

WEBROOT = '/var/www/tradingai.in/html'
SRC = '/opt/tradingai_new/frontend'
PAGES = ['index.html', 'indices/nifty.html', 'indices/banknifty.html',
         'backtest.html', 'methodology.html']


def _http(path, timeout=15):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen('https://127.0.0.1' + path, context=ctx,
                                timeout=timeout) as r:
        return r.status, r.read()


def test_nginx_running_and_enabled():
    import subprocess
    st = subprocess.run(['systemctl', 'is-active', 'nginx'], capture_output=True,
                        text=True, timeout=15).stdout.strip()
    en = subprocess.run(['systemctl', 'is-enabled', 'nginx'], capture_output=True,
                        text=True, timeout=15).stdout.strip()
    assert st == 'active', st
    assert en == 'enabled', en


def test_api_service_enabled_and_serving():
    import subprocess
    en = subprocess.run(['systemctl', 'is-enabled', 'tradingai-api.service'],
                        capture_output=True, text=True, timeout=15).stdout.strip()
    assert en == 'enabled', en
    status, body = _http('/api/health')
    assert status == 200
    assert b'/opt/tradingai_new/database/tradingai.db' in body


def _sha(p):
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()


def test_webroot_matches_validated_source():
    for page in PAGES:
        src, live = os.path.join(SRC, page), os.path.join(WEBROOT, page)
        assert os.path.exists(live), live
        assert _sha(src) == _sha(live), f'{page} differs from validated source'


def test_https_pages_live():
    for page in ['/'] + ['/' + p for p in PAGES]:
        status, body = _http(page)
        assert status == 200, (page, status)
        assert b'TradingAI' in body, page


def test_api_proxy_live():
    status, body = _http('/api/NIFTY/summary')
    assert status == 200
    import json
    data = json.loads(body.decode())
    assert data['state'] in ('MARKET_CLOSED', 'NO_TRADE', 'STALE', 'NO_DATA',
                             'PREMARKET', 'WEEKEND', 'QUALIFIED', 'LIVE'), data


def test_no_legacy_ghost_page():
    import urllib.error
    try:
        _http('/indices/market.html')
        status = 200
    except urllib.error.HTTPError as e:
        status = e.code
    assert status in (301, 302, 404), status
