"""TradingAI.in Telegram alerts (Path B, owner-authorized).

Modes:
  --test     send a test message
  --morning  levels snapshot: photo (homepage) + levels text
  --watch    poll decisions; alert once per new TRADE signal (+ chart photo)
  --eod      end-of-day recap text

Secrets: /opt/tradingai/.tg_env (0600, gitignored). State: data/tg_state.json.
Read-only vs trading logic: only reads decision APIs + screenshots pages.
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
import urllib.parse
from datetime import datetime
from zoneinfo import ZoneInfo

BASE = '/opt/tradingai'
IST = ZoneInfo('Asia/Kolkata')
API = 'http://127.0.0.1:8000'
CHANNEL = '@tradingai_cpr'
ARCHIVE = os.path.join(BASE, 'data', 'tg_alerts_archive.jsonl')
ALERTS_PAGE = os.path.join(BASE, 'scripts', 'build_alerts_page.py')

NAV_MARKUP = __import__('json').dumps({
    "inline_keyboard": [
        [{"text": "Home", "url": "https://tradingai.in/"},
         {"text": "Nifty", "url": "https://tradingai.in/indices/nifty.html"},
         {"text": "BankNifty", "url": "https://tradingai.in/indices/banknifty.html"}],
        [{"text": "Backtest", "url": "https://tradingai.in/backtest.html"},
         {"text": "Paper", "url": "https://tradingai.in/paper.html"}],
        [{"text": "Join Telegram", "url": "https://t.me/tradingai_cpr"}]
    ]
})


def token():
    with open(os.path.join(BASE, '.tg_env')) as f:
        return f.read().strip()


_TG_WARNED = set()


def _tg_desc(e):
    try:
        return json.load(e).get('description') or e.reason
    except Exception:
        return e.reason


def _fail(method, msg):
    """Warn once per run; return a failed result so callers take their ok==False path."""
    key = msg[:60]
    if key not in _TG_WARNED:
        _TG_WARNED.add(key)
        print(f'ALERT DELIVERY PROBLEM [{method}]: {msg}')
    return {'ok': False, 'description': msg}


def tg(method, payload, photo=None, timeout=30):
    tok = token()
    if photo is None:
        data = urllib.parse.urlencode(payload).encode()
        req = urllib.request.Request(f'https://api.telegram.org/bot{tok}/{method}', data=data)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            return _fail(method, f'HTTP {e.code} {_tg_desc(e)}')
        except Exception as e:
            return _fail(method, f'{type(e).__name__}: {e}')
    import uuid
    boundary = uuid.uuid4().hex
    body = b''
    for k, v in payload.items():
        body += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    body += (f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; '
             f'filename="shot.png"\r\nContent-Type: image/png\r\n\r\n').encode() + photo + f'\r\n--{boundary}--\r\n'.encode()
    req = urllib.request.Request(f'https://api.telegram.org/bot{tok}/{method}', data=body,
                                 headers={'Content-Type': f'multipart/form-data; boundary={boundary}'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return _fail(method, f'HTTP {e.code} {_tg_desc(e)}')
    except Exception as e:
        return _fail(method, f'{type(e).__name__}: {e}')


def api(path):
    with urllib.request.urlopen(API + path, timeout=25) as r:
        return json.load(r)['data']


def shot(url, out, wait_ms=12000, width=1366, height=900):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True, args=['--no-sandbox'])
        pg = b.new_page(viewport={'width': width, 'height': height})
        pg.goto(url, wait_until='domcontentloaded', timeout=45000)
        pg.wait_for_timeout(wait_ms)
        pg.screenshot(path=out, full_page=True)
        b.close()
    with open(out, 'rb') as f:
        return f.read()


def fmt(x, dec=2):
    try:
        return f'{float(x):,.{dec}f}'
    except (TypeError, ValueError):
        return '—'


def state():
    p = os.path.join(BASE, 'data', 'tg_state.json')
    try:
        return json.load(open(p))
    except Exception:
        return {}


def save_state(s):
    p = os.path.join(BASE, 'data', 'tg_state.json')
    json.dump(s, open(p, 'w'), indent=1)


def log_alert(rec):
    """Append one sent alert to the permanent append-only archive (JSONL)."""
    try:
        now = datetime.now(IST)
        rec.setdefault('date', now.date().isoformat())
        rec.setdefault('ts_ist', now.isoformat(timespec='seconds'))
        rec.setdefault('source', 'live')
        with open(ARCHIVE, 'a') as f:
            f.write(json.dumps(rec) + '\n')
    except Exception as e:
        print(f'archive log failed: {e}')


def rebuild_page():
    """Regenerate frontend/alerts.html from the archive (best effort)."""
    try:
        subprocess.run(['/usr/bin/python3', ALERTS_PAGE], timeout=90, check=False)
    except Exception as e:
        print(f'alerts page rebuild failed: {e}')


def ctx_from(d, t):
    ex = d.get('explanation') or {}
    cpr = d.get('cpr') or {}
    return {
        'direction': (t.get('direction') or '').upper() or '\u2014',
        'trigger': fmt(t.get('entry')),
        'invalidation': fmt(t.get('stop')),
        'target': fmt(t.get('target')),
        'structure': ex.get('structure') or d.get('structure') or '\u2014',
        'strategy': spread_name(t.get('direction')),
        'session': d.get('session'),
        'cpr_type': cpr.get('cpr_type'),
        'price_position': cpr.get('price_position'),
        'market_bias': d.get('market_bias'),
        'quote_timestamp': d.get('quote_timestamp'),
        'vwap_relation': d.get('vwap_relation'),
        'volatility_state': d.get('volatility_state'),
    }


def explanation_from(d, t, phase):
    """Factual, engine-sourced explanation stored with the record."""
    ex = d.get('explanation') or {}
    bits = []
    if phase == 'signal':
        bits.append('Engine classified the session as %s (bias %s, engine %s).'
                    % (d.get('decision') or '\u2014', d.get('market_bias') or '\u2014',
                       d.get('engine_state') or d.get('state') or '\u2014'))
    else:
        bits.append('Session context at the exit check: %s, engine %s.'
                    % (d.get('session') or '\u2014',
                       d.get('engine_state') or d.get('state') or '\u2014'))
    for label, key in (('Structure', 'structure'), ('Confirmation', 'confirmation'),
                       ('Entry zone', 'entry'), ('Reference trigger', 'trigger'),
                       ('Reference invalidation', 'invalidation'),
                       ('Reference target', 'target')):
        v = ex.get(key)
        if v and str(v).strip().lower() not in ('data unavailable', 'none', ''):
            bits.append('%s: %s' % (label, v))
    cpr = d.get('cpr') or {}
    if cpr.get('available') and 'CPR' not in str(ex.get('structure') or ''):
        bits.append('CPR %s\u2013%s (%s), price position %s.'
                    % (fmt(cpr.get('bc')), fmt(cpr.get('tc')),
                       cpr.get('cpr_type') or '\u2014', cpr.get('price_position') or '\u2014'))
    if d.get('quote_timestamp'):
        bits.append('Quote timestamp: %s.' % d.get('quote_timestamp'))
    reasons = d.get('engine_reasons') or d.get('reason_codes')
    if reasons:
        bits.append('Engine reasons: %s'
                    % (', '.join(str(r) for r in reasons) if isinstance(reasons, list) else reasons))
    return ' '.join(bits)


def do_test():
    r = tg('sendMessage', {'chat_id': CHANNEL, 'reply_markup': NAV_MARKUP,
                           'text': '🔧 TradingAI model alerts online. Morning model levels, intraday model signals and EOD model recaps will land here. Automated, standardized model output. Not personalised investment advice. Educational research only.'})
    if r.get('ok'):
        log_alert({'type': 'test', 'inst': 'channel',
                   'explanation': 'Connectivity check confirming the alerting path is live.'})
    print('test sent:', r.get('ok'))


def levels_block(sym, dec):
    c = (dec.get('cpr') or {}) if isinstance(dec, dict) else {}
    lines = [
        f"{sym} (prev close {fmt(dec.get('prev_close'))}):",
        f"TC {fmt(c.get('tc'))} | PIVOT {fmt(c.get('pivot'))} | BC {fmt(c.get('bc'))}",
    ]
    return '\n'.join(lines)


def do_morning():
    now = datetime.now(IST)
    n = api('/api/decision/nifty')
    b = api('/api/decision/banknifty')
    v = api('/api/decision/india_vix')
    sess = (n.get('session') or '')
    closed = sess in ('WEEKEND', 'MARKET_CLOSED', 'HOLIDAY')
    head = f"📊 TRADINGAI MODEL LEVELS | {now.strftime('%a %d %b').upper()}"
    if closed:
        head += f'\nMarket {sess.lower()} — levels below are the last session refs.'
    text = (head + '\n\n' + levels_block('NIFTY', n) + '\n' + levels_block('BANKNIFTY', b)
            + f"\nVIX {fmt((v.get('price')), 2)} (context)"
            + '\nLive model signals from 09:15 → https://tradingai.in'
            + '\nAutomated, standardized model output. Not personalised investment advice. Educational research only.')
    img = shot('https://tradingai.in/index.html', '/tmp/tg_morning.png')
    r = tg('sendPhoto', {'chat_id': CHANNEL, 'caption': text[:1024], 'reply_markup': NAV_MARKUP}, photo=img)
    if r.get('ok'):
        log_alert({'type': 'morning', 'inst': 'NIFTY + BANKNIFTY',
                   'ctx': {'session': sess, 'cpr_type': (n.get('cpr') or {}).get('cpr_type')},
                   'explanation': 'Reference levels (TC, pivot, BC) and context published '
                                  'before the session; these are derived from the previous '
                                  'session, not live prices.'})
        rebuild_page()
    print('morning sent:', r.get('ok'))


def spread_name(direction):
    """Credit-spread expression of the call (matches options engine mapping)."""
    return 'Bear Call Spread' if direction == 'BEAR' else 'Bull Put Spread'


EOD_HH, EOD_MM = 15, 15


def past_eod(now):
    """True once the session boundary (15:15 IST) has been reached."""
    return now.hour > EOD_HH or (now.hour == EOD_HH and now.minute >= EOD_MM)


def sl_breached(direction, stop, price):
    """True when the last reference price is through the invalidation level."""
    try:
        stop, price = float(stop), float(price)
    except (TypeError, ValueError):
        return False
    return price >= stop if (direction == 'BEAR') else price <= stop


def resolve_reason(direction, entry, stop, target, price, now):
    """Infer how a fired trade resolved. Pure function (no I/O)."""
    try:
        entry, stop, target, price = float(entry), float(stop), float(target), float(price)
    except (TypeError, ValueError):
        return 'FLAT'
    if past_eod(now):
        return 'EOD EXIT'
    # while the market is open the stop is checked first: a record that is
    # through its invalidation level is an adverse outcome, not a target hit
    if sl_breached(direction, stop, price):
        return 'STOP'
    try:
        target = float(target)
    except (TypeError, ValueError):
        return 'FLAT'
    return 'TARGET' if ((price >= target) if (direction != 'BEAR') else (price <= target)) else 'FLAT'


def do_watch():
    st = state()
    today = datetime.now(IST).date().isoformat()
    for sym, inst in (('nifty', 'NIFTY'), ('banknifty', 'BANKNIFTY')):
        try:
            d = api(f'/api/decision/{sym}')
        except Exception as e:
            print(f'{sym} poll failed: {e}');
            continue
        if d.get('decision') != 'TRADE' or not d.get('trade'):
            continue
        t = d['trade']
        key = f"{today}|{inst}|{t.get('direction')}|{t.get('entry')}"
        if key in st.get('fired', []):
            continue
        bull = (t.get('direction') != 'BEAR')
        emoji = '🟢' if bull else '🔴'
        sig_at = datetime.now(IST).strftime('%H:%M')
        try:
            _sd = api(f"/api/paper/spread/today?instrument={inst}")
            _tr = ((_sd or {}).get('trigger')) or {}
            _sp = ((_sd or {}).get('spread')) or {}
        except Exception:
            _tr, _sp = {}, {}
        _lvl = _tr.get('level') or t.get('level') or '—'
        _exp = _sp.get('expiry') or t.get('expiry') or '—'
        _strat = _sp.get('strategy') or spread_name(t.get('direction'))
        try:
            _dp = str(_tr.get('date') or today).split('-')
            _months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
            _datetxt = f"{_dp[2]} {_months[int(_dp[1])-1]} {_dp[0]}" if len(_dp) == 3 else today
        except Exception:
            _datetxt = today
        try:
            _hm = str(_tr.get('entry_time') or _tr.get('signal_time') or t.get('entry_time') or t.get('signal_time') or '')[11:16]
            _hh, _mm = _hm.split(':')
            _H = int(_hh); _ap = 'PM' if _H >= 12 else 'AM'
            _h12 = _H % 12 or 12
            _sigtxt = f"{_h12}:{_mm} {_ap}"
        except Exception:
            _sigtxt = sig_at
        text = (f"{inst}\n{_datetxt}\n"
                f"Direction: {(t.get('direction') or '').upper() or '—'}\n"
                f"Level: {_lvl}\n"
                f"Entry (ref): {fmt(t.get('entry'))}\n"
                f"SL: {fmt(t.get('stop'))}\n"
                f"{_strat} \u00b7 Exp {_exp} \u00b7 Signal {_sigtxt}")
        r = tg('sendMessage', {'chat_id': CHANNEL, 'text': text})
        if r.get('ok'):
            st.setdefault('fired', []).append(key)
            st.setdefault('open', {})[key] = {'inst': inst, 'sym': sym,
                                              'direction': t.get('direction'), 'entry': t.get('entry'),
                                              'stop': t.get('stop'), 'target': t.get('target'),
                                              'strategy': spread_name(t.get('direction')), 'fired_at': sig_at,
                                              'date': today}
            log_alert({'type': 'signal', 'inst': inst, 'sym': sym, 'key': key,
                       'direction': (t.get('direction') or '').upper() or '\u2014',
                       'ctx': ctx_from(d, t), 'explanation': explanation_from(d, t, 'signal')})
            save_state(st)
            print(f'signal sent for {key}')
        else:
            print(f'signal FAILED for {key}: {str(r)[:150]}')
    # exit sweep: previously fired trades no longer in the same TRADE
    now = datetime.now(IST)
    for key, o in list(st.get('open', {}).items()):
        if o.get('date') != today:
            st['open'].pop(key, None)
            continue
        try:
            d = api(f"/api/decision/{o['sym']}")
        except Exception as e:
            print(f"exit poll {key} failed: {e}")
            continue
        t2 = d.get('trade') if d.get('decision') == 'TRADE' else None
        same = bool(t2 and t2.get('direction') == o.get('direction')
                    and str(t2.get('entry')) == str(o.get('entry')))
        price = d.get('price')
        if not past_eod(now) and sl_breached(o.get('direction'), o.get('stop'), price):
            # 1) invalidation level reached intraday -> immediate stop-loss alert
            reason = 'STOP'
        elif past_eod(now):
            # 2) session boundary: close even if the engine still reports ACTIVE
            reason = 'EOD EXIT'
        elif not same:
            # 3) engine closed the record on its own
            reason = resolve_reason(o.get('direction'), o.get('entry'), o.get('stop'),
                                    o.get('target'), price, now)
        else:
            continue
        try:
            _entry_f = float(o.get('entry'))
            _exit_f = float((d or {}).get('price'))
            _pts = (_exit_f - _entry_f) if (o.get('direction') != 'BEAR') else (_entry_f - _exit_f)
            _pts_txt = f"{_pts:+,.2f} pts"
        except (TypeError, ValueError):
            _pts_txt = '—'
        try:
            _dp = str(today).split('-')
            _months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
            _datetxt = f"{_dp[2]} {_months[int(_dp[1])-1]} {_dp[0]}" if len(_dp) == 3 else today
        except Exception:
            _datetxt = today
        text = (f"{o['inst']}\n{_datetxt}\n"
                f"Direction: {(o.get('direction') or '').upper() or '—'}\n"
                f"Entry (ref): {fmt(o.get('entry'))}\n"
                f"Exit (ref): {fmt((d or {}).get('price'))}\n"
                f"Result: {reason} ({_pts_txt})\n"
                f"{o.get('strategy') or '—'}")
        r = tg('sendMessage', {'chat_id': CHANNEL, 'text': text})
        st['open'].pop(key, None)
        try:
            _exit_f = float((d or {}).get('price'))
            _entry_f = float(o.get('entry'))
            _cpts = (_exit_f - _entry_f) if (o.get('direction') != 'BEAR') else (_entry_f - _exit_f)
        except (TypeError, ValueError):
            _exit_f, _cpts = None, None
        st.setdefault('closed', []).append({'inst': o.get('inst'), 'sym': o.get('sym'),
                                            'direction': o.get('direction'), 'entry': o.get('entry'),
                                            'exit': _exit_f, 'reason': reason, 'points': _cpts,
                                            'strategy': o.get('strategy'), 'date': today})
        save_state(st)
        if r.get('ok'):
            log_alert({'type': 'update', 'inst': o.get('inst'), 'sym': o.get('sym'), 'key': key,
                       'outcome': {'reason': reason,
                                   'exit': fmt((d or {}).get('price')),
                                   'points_text': _pts_txt},
                       'explanation': explanation_from(d, None, 'exit')
                                      + ' Recorded exit reference: %s (%s).'
                                      % (reason, _pts_txt)})
            rebuild_page()
        print(f"exit sent for {key}: {reason} ok={r.get('ok')}")


def _fmt_pts(v):
    try:
        return f"{float(v):+,.2f} pts"
    except (TypeError, ValueError):
        return '—'


def do_eod():
    now = datetime.now(IST)
    today = now.date().isoformat()
    st = state()
    recs = [c for c in st.get('closed', []) if c.get('date') == today]
    for key, o in list(st.get('open', {}).items()):
        if o.get('date') == today and not any(r.get('inst') == o.get('inst') for r in recs):
            recs.append({'inst': o.get('inst'), 'direction': o.get('direction'),
                         'entry': o.get('entry'), 'exit': None, 'reason': 'OPEN',
                         'points': None, 'strategy': o.get('strategy')})
    if not recs:
        recs = [{'inst': 'NO MODEL TRADE today', 'direction': '—',
                 'entry': None, 'exit': None, 'reason': '', 'points': None, 'strategy': ''}]
    try:
        _dp = str(today).split('-')
        _months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
        _datetxt = f"{_dp[2]} {_months[int(_dp[1])-1]} {_dp[0]}" if len(_dp) == 3 else today
    except Exception:
        _datetxt = today
    crisp = []
    for c in recs:
        crisp.append(f"{c.get('inst')}\nDirection: {(c.get('direction') or '').upper() or '—'}\n"
                     f"Entry (ref): {fmt(c.get('entry'))}\n"
                     f"Exit (ref): {fmt(c.get('exit'))}\n"
                     f"Result: {c.get('reason')} ({_fmt_pts(c.get('points'))})\n"
                     f"{c.get('strategy') or '—'}")
    if not crisp:
        crisp = ['NO MODEL TRADE today']
    text = (f"EOD\n{_datetxt}\n\n" + "\n\n".join(crisp))
    r = tg('sendMessage', {'chat_id': CHANNEL, 'text': text})
    if r.get('ok'):
        log_alert({'type': 'eod', 'inst': 'NIFTY + BANKNIFTY',
                   'explanation': 'Daily recap of every model record closed in the session '
                                  'ledger, published win or lose.'})
        rebuild_page()
    print('eod sent:', r.get('ok'))


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else '--test'
    {'--test': do_test, '--morning': do_morning, '--watch': do_watch, '--eod': do_eod}[mode]()
