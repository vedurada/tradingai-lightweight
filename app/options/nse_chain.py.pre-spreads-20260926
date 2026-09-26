"""NSE option-chain fetcher (DORMANT: NSE 403s datacenter IPs).

Tries the public option-chain-indices endpoint with browser headers + homepage
cookies. Expected to return UNAVAILABLE from blocked networks; the spread
engine treats that as structure-only (no invented premiums). Activates
automatically if the network path ever succeeds (or behind a proxy/VPN).

Never raises: all failures -> {'state': 'UNAVAILABLE', 'reason': ...}.
"""
import logging
import time

log = logging.getLogger('tradingai.nse_chain')

_CACHE = {}
_CACHE_TTL_S = 300

_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
       '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')
_VALID = ('NIFTY', 'BANKNIFTY')
_YMAP = {'NIFTY': 'NIFTY', 'BANKNIFTY': 'BANKNIFTY'}


def _fresh(key):
    hit = _CACHE.get(key)
    if hit and (time.time() - hit[0]) < _CACHE_TTL_S:
        return hit[1]
    return None


def fetch_chain(instrument, timeout=12):
    """Fetch normalized chain. Returns (state, payload)."""
    inst = (instrument or '').upper()
    if inst not in _VALID:
        return 'UNAVAILABLE', {'instrument': inst, 'reason': 'UNKNOWN_INSTRUMENT'}
    hit = _fresh(inst)
    if hit is not None:
        return hit[0], dict(hit[1], cached=True)
    try:
        import requests
    except Exception as e:
        return 'UNAVAILABLE', {'instrument': inst, 'reason': 'NO_HTTP_LIB',
                               'error': str(e)[:120]}
    try:
        s = requests.Session()
        s.headers.update({'User-Agent': _UA,
                          'Accept': 'application/json,text/plain,*/*',
                          'Accept-Language': 'en-US,en;q=0.9',
                          'Referer': 'https://www.nseindia.com/'})
        h = s.get('https://www.nseindia.com/', timeout=timeout)
        if h.status_code != 200:
            out = {'instrument': inst, 'reason': 'NSE_BLOCKED',
                   'http': h.status_code}
            _CACHE[inst] = (time.time(), ('UNAVAILABLE', out))
            return 'UNAVAILABLE', out
        r = s.get('https://www.nseindia.com/api/option-chain-indices?symbol='
                  + _YMAP[inst], timeout=timeout)
        if r.status_code != 200:
            out = {'instrument': inst, 'reason': 'CHAIN_HTTP',
                   'http': r.status_code}
            _CACHE[inst] = (time.time(), ('UNAVAILABLE', out))
            return 'UNAVAILABLE', out
        d = r.json()
        rec = d.get('records', {}) or {}
        rows = []
        for row in rec.get('data', []) or []:
            try:
                k = float(row.get('strikePrice'))
            except (TypeError, ValueError):
                continue
            ce, pe = row.get('CE') or {}, row.get('PE') or {}
            rows.append({'strike': k,
                         'ce': {'ltp': ce.get('lastPrice'), 'iv': ce.get('impliedVolatility'),
                                'oi': ce.get('openInterest')},
                         'pe': {'ltp': pe.get('lastPrice'), 'iv': pe.get('impliedVolatility'),
                                'oi': pe.get('openInterest')}})
        out = {'instrument': inst, 'underlying': rec.get('underlyingValue'),
               'expiries': rec.get('expiryDates', []),
               'strikes': sorted(rows, key=lambda x: x['strike']),
               'fetched_at': time.time()}
        _CACHE[inst] = (time.time(), ('LIVE', out))
        return 'LIVE', out
    except Exception as e:
        msg = str(e).lower()
        reason = 'RATE_LIMITED' if ('429' in msg or 'rate limit' in msg) else 'FETCH_ERROR'
        log.warning('nse chain instrument=%s err=%s', inst, str(e)[:120])
        return 'UNAVAILABLE', {'instrument': inst, 'reason': reason,
                               'error': str(e)[:160]}


def get_credit(instrument, legs):
    """Net credit in points from live LTPs. None when unavailable.

    legs: [{side SELL|BUY, type CE|PE, strike}]. SELL adds, BUY subtracts."""
    state, chain = fetch_chain(instrument)
    if state != 'LIVE':
        return None
    lut = {s['strike']: s for s in chain.get('strikes', [])}
    total = 0.0
    for leg in legs or []:
        try:
            k = float(leg['strike'])
        except (TypeError, ValueError, KeyError):
            return None
        node = lut.get(k)
        if not node:
            return None
        leg_px = (node.get('ce') or {}).get('ltp') if leg.get('type') == 'CE' \
            else (node.get('pe') or {}).get('ltp')
        try:
            leg_px = float(leg_px)
        except (TypeError, ValueError):
            return None
        total += leg_px if leg.get('side') == 'SELL' else -leg_px
    return round(total, 2)
