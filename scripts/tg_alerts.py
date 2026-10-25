"""TradingAI.in Telegram alerts (Path B, owner-authorized).

Modes:
  --test     send a test message
  --morning  levels snapshot: photo (homepage) + levels text
  --watch    poll decisions; alert once per new TRADE signal (+ chart photo)
  --eod      end-of-day recap text
  --reconcile  morning repair: backfill alerts dropped by failed runs
             (labeled ledger-backfill records; never sends Telegram)

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

BASE = os.environ.get('TRADINGAI_BASE', '/opt/tradingai')
import sys as _sys
if BASE not in _sys.path:
    _sys.path.insert(0, BASE)
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
        [{"text": "Join Telegram", "url": "https://telegram.me/tradingai_cpr"}]
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



FB_ENV = os.path.join(BASE, ".fb_env")
_FB_WARNED = set()

def fb_config():
    """Read (page_id, page_token) from .fb_env. Returns (None,None) if missing."""
    try:
        raw = open(FB_ENV).read().strip()
    except Exception:
        return None, None
    cfg = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        cfg[k.strip()] = v.strip()
    if cfg.get("FB_PAGE_ID") or cfg.get("FB_PAGE_TOKEN"):
        return cfg.get("FB_PAGE_ID") or None, cfg.get("FB_PAGE_TOKEN") or None
    if "|" in raw:
        pid, tok = raw.split("|", 1)
        return pid.strip() or None, tok.strip() or None
    parts = [x.strip() for x in raw.splitlines() if x.strip()]
    if len(parts) >= 2:
        return parts[0], parts[1]
    return None, None


def fb_post(message, link=None, photo=None, timeout=30):
    """Best-effort Facebook Page post. Never raises; returns Graph response dict or None."""
    pid, tok = fb_config()
    if not pid or not tok:
        key = "missing"
        if key not in _FB_WARNED:
            _FB_WARNED.add(key)
            print("FB skipped (.fb_env missing or malformed)")
        return None
    try:
        if photo is None:
            payload = {"message": message, "access_token": tok}
            if link:
                payload["link"] = link
            data = urllib.parse.urlencode(payload).encode()
            req = urllib.request.Request(f"https://graph.facebook.com/v19.0/{pid}/feed", data=data)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        import uuid
        boundary = uuid.uuid4().hex
        body = b""
        fields = {"caption": message, "access_token": tok}
        if link:
            fields["link"] = link
        for k, v in fields.items():
            body += ("--" + boundary + "\r\n" + "Content-Disposition: form-data; name=\"" + k + "\"\r\n\r\n" + v + "\r\n").encode()
        body += ("--" + boundary + "\r\n" + "Content-Disposition: form-data; name=\"source\"; filename=\"shot.png\"\r\nContent-Type: image/png\r\n\r\n").encode() + photo + ("\r\n--" + boundary + "--\r\n").encode()
        req = urllib.request.Request(f"https://graph.facebook.com/v19.0/{pid}/photos", data=body,
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode()[:200]
        except Exception:
            detail = str(e)
        print(f"FB POST FAILED: HTTP {e.code} {detail}")
        return None
    except Exception as e:
        print(f"FB POST FAILED: {type(e).__name__}: {e}")
        return None

def api(path):
    with urllib.request.urlopen(API + path, timeout=25) as r:
        return json.load(r)['data']


def api_post(path):
    req = urllib.request.Request(API + path, data=b'', method='POST')
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)['data']


def api_retry(path, tries=3, sleep_s=5):
    """GET with retries. Oct-13 exits were silently lost to a single
    'Connection reset by peer'; polls must not fail on one bad socket."""
    import time
    last = None
    for i in range(tries):
        try:
            return api(path)
        except Exception as e:
            last = e
            print(f'api retry {i + 1}/{tries} {path}: {e}')
            time.sleep(sleep_s)
    raise last


def api_post_retry(path, tries=2, sleep_s=5):
    """POST with retries. The claim endpoint is idempotent (one frozen
    trade per instrument/day), so a retry is safe."""
    import time
    last = None
    for i in range(tries):
        try:
            return api_post(path)
        except Exception as e:
            last = e
            print(f'api_post retry {i + 1}/{tries} {path}: {e}')
            time.sleep(sleep_s)
    raise last


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


def log_alert(rec, delivered=None, message_id=None):
    """Append one sent alert to the permanent append-only archive (JSONL).

    Delivery provenance (2026-10-18): `delivered`/`message_id` record whether
    Telegram actually accepted the message. Before this, the archive stored
    only what we TRIED to send, so a generated alert could not be told apart
    from a delivered one. Backfills pass delivered=False explicitly."""
    try:
        now = datetime.now(IST)
        rec.setdefault('date', now.date().isoformat())
        rec.setdefault('ts_ist', now.isoformat(timespec='seconds'))
        rec.setdefault('source', 'live')
        if delivered is not None:
            rec.setdefault('delivered', bool(delivered))
        if message_id is not None:
            rec.setdefault('message_id', message_id)
        with open(ARCHIVE, 'a') as f:
            f.write(json.dumps(rec) + '\n')
    except Exception as e:
        print(f'archive log failed: {e}')


def rebuild_page():
    """Regenerate frontend/alerts.html from the archive (best effort).

    check=False meant a non-zero exit -- the archive failing to rebuild -- was
    discarded and only the subprocess traceback reached the log. Check the exit
    status explicitly and print one actionable line so a stale archive page is
    visible in tg.log rather than discovered later.
    """
    try:
        _rr = subprocess.run(['/usr/bin/python3', os.path.join(BASE, 'scripts', 'build_rss.py')],
                             timeout=60, check=False, capture_output=True, text=True)
        if _rr.returncode != 0:
            print(f'WARNING rss rebuild failed (exit {_rr.returncode}): {((_rr.stderr or _rr.stdout or "").strip().splitlines() or [""])[-1][:160]}')
        elif (_rr.stdout or '').strip():
            print((_rr.stdout or '').strip())
    except Exception as _e:
        print(f'WARNING rss rebuild did not run: {_e}')
    try:
        r = subprocess.run(['/usr/bin/python3', ALERTS_PAGE], timeout=90,
                           check=False, capture_output=True, text=True)
    except Exception as e:
        print(f'ERROR alerts page rebuild did not run: {e}')
        return
    if r.returncode != 0:
        detail = (r.stderr or r.stdout or '').strip().splitlines()
        last = detail[-1] if detail else f'exit {r.returncode}'
        print(f'ERROR alerts page rebuild failed (exit {r.returncode}): {last}')
    elif r.stdout and r.stdout.strip():
        print(r.stdout.strip())


def ctx_from(d, t, level=None, expiry=None, signal_time=None):
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
        'level': '' if level in (None, '', '\u2014') else str(level),
        'expiry': '' if expiry in (None, '', '\u2014') else str(expiry),
        'signal_time': signal_time or '',
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
                   'explanation': 'Connectivity check confirming the alerting path is live.'},
                  delivered=True,
                  message_id=(r.get('result') or {}).get('message_id'))
    try:
        fb_post('\U0001f527 TradingAI model alerts online. Morning model levels, intraday model signals and EOD model recaps will land here. Automated, standardized model output. Not personalised investment advice. Educational research only.')
    except Exception as e:
        print(f'FB hook (test) skipped: {e}')
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
    try:
        fb_post(text, photo=img)
    except Exception as e:
        print(f'FB hook (morning) skipped: {e}')
    r = tg('sendPhoto', {'chat_id': CHANNEL, 'caption': text[:1024], 'reply_markup': NAV_MARKUP}, photo=img)
    if r.get('ok'):
        log_alert({'type': 'morning', 'inst': 'NIFTY + BANKNIFTY', 'tg_text': text,
                   'ctx': {'session': sess, 'cpr_type': (n.get('cpr') or {}).get('cpr_type')},
                   'explanation': 'Reference levels (TC, pivot, BC) and context published '
                                  'before the session; these are derived from the previous '
                                  'session, not live prices.'},
                  delivered=True,
                  message_id=(r.get('result') or {}).get('message_id'))
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


def _candle_opens(sym, inst, since_iso):
    """Completed 5m candle OPENS strictly after `since_iso` as [(ts, open)].
    Mirrors the plain backtest subsequent-opens walk (opens spec)."""
    import sqlite3
    db = os.environ.get('TRADINGAI_DB_PATH') or os.path.join(BASE, 'database', 'tradingai.db')
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT timestamp, open FROM market_candles_5m "
            "WHERE instrument_id=? AND timestamp > ? ORDER BY timestamp",
            (inst, since_iso)).fetchall()
    finally:
        conn.close()
    return [(ts, o) for ts, o in rows if o is not None]


def do_watch():
    import atexit
    lock_p = '/tmp/tg_watch.lock'
    try:
        import time as _t
        try:
            fd = os.open(lock_p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(_t.time()).encode())
            os.close(fd)
        except FileExistsError:
            try:
                age = _t.time() - float(open(lock_p).read().strip())
            except Exception:
                age = 0
            if age > 600:
                try:
                    os.remove(lock_p)
                except Exception:
                    pass
                fd = os.open(lock_p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(_t.time()).encode())
                os.close(fd)
            else:
                print('watch already running, skipping')
                return
    except Exception as e:
        print(f'watch lock failed ({e}); running unlocked')
        lock_p = None
    if lock_p:
        atexit.register(lambda: (os.remove(lock_p) if os.path.exists(lock_p) else None))
    st = state()
    today = datetime.now(IST).date().isoformat()
    for sym, inst in (('nifty', 'NIFTY'), ('banknifty', 'BANKNIFTY')):
        try:
            d = api_retry(f'/api/decision/{sym}')
        except Exception as e:
            print(f'{sym} poll failed: {e}');
            continue
        if d.get('decision') != 'TRADE' or not d.get('trade'):
            continue
        t = d['trade']
        key = f"{today}|{inst}|{t.get('direction')}|{t.get('entry')}"
        if key in st.get('fired', []):
            continue
        # First detection of a live trigger: freeze it server-side (idempotent,
        # one per instrument/day) and use the persisted entry/stop/target so
        # the alert can never drift on later stateless polls. The claim is the
        # authoritative gate: if the server does not persist a trade here, do
        # NOT alert on the stale dry-run poll (the watcher retries next minute).
        try:
            ct = ((api_post_retry(f'/api/{inst}/decision/claim')) or {}).get('trade') or None
        except Exception as e:
            print(f'{inst} claim failed: {e}; not alerting (will retry next poll)')
            continue
        if not ct:
            print(f'{inst} claim returned no trade; not alerting (server did not persist)')
            continue
        t = ct
        key = f"{today}|{inst}|{t.get('direction')}|{t.get('entry')}"
        # Automatic paper trading: persist ONE live paper trade for a
        # confirmed (frozen) signal. Idempotent per (instrument, day) — the
        # deterministic trade_id means retries and concurrent runs cannot
        # duplicate it. Only runs on a persisted claim (never fabricates a
        # signal); failures are logged and never stop the alert loop.
        try:
            from app.paper_trade.engine import PaperTradeEngine
            _pt_id = PaperTradeEngine().create_paper_trade(
                {**t, 'instrument_id': inst}, link_key=f'{inst}|{today}')
            print(f'{inst} paper trade {_pt_id} active')
        except Exception as e:
            print(f'{inst} paper-trade create failed: {e}')
        bull = (t.get('direction') != 'BEAR')
        emoji = '🟢' if bull else '🔴'
        sig_at = datetime.now(IST).strftime('%H:%M')
        try:
            _sd = api_retry(f"/api/paper/spread/today?instrument={inst}")
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
            _hm = str(t.get('entry_time') or t.get('signal_time') or _tr.get('entry_time') or _tr.get('signal_time') or '')[11:16]
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
                                              'date': today,
                                              'signal_time': t.get('signal_time') or t.get('entry_time')
                                              or f'{today}T{sig_at}:00+05:30'}
            log_alert({'type': 'signal', 'inst': inst, 'sym': sym, 'key': key, 'tg_text': text,
                       'direction': (t.get('direction') or '').upper() or '\u2014',
                       'ctx': ctx_from(d, t, _lvl, _exp, _sigtxt), 'explanation': explanation_from(d, t, 'signal')},
                      delivered=True,
                      message_id=(r.get('result') or {}).get('message_id'))
            save_state(st)
            try:
                fb_post(text)
            except Exception as e:
                print(f'FB hook (signal) skipped: {e}')
            rebuild_page()
            print(f'signal sent for {key}')
        else:
            print(f'signal FAILED for {key}: {str(r)[:150]}')
    # exit sweep: previously fired trades no longer in the same TRADE
    now = datetime.now(IST)
    for key, o in list(st.get('open', {}).items()):
        if o.get('date') != today:
            # Stale opens belong to --reconcile (daily 09:10), which resolves
            # them from the paper ledger with explicit missed-labelling.
            # Never pop silently here: that path dropped Oct-13 exits.
            continue
        try:
            d = api_retry(f"/api/decision/{o['sym']}")
        except Exception as e:
            print(f"exit poll {key} failed: {e}")
            continue
        t2 = d.get('trade') if d.get('decision') == 'TRADE' else None
        same = bool(t2 and t2.get('direction') == o.get('direction')
                    and str(t2.get('entry')) == str(o.get('entry')))
        price = d.get('price')
        # 1) plain-engine exit on subsequent completed candle OPENS
        #    (opens spec: 0.5% stop / 2% target at opens, stop first;
        #    entry bar excluded) — parity with run_opens_range(variant='plain').
        plain = None
        try:
            from app.research.cpr_trigger_engine import exits_opens, OPEN_STOP_PCT, OPEN_TARGET_PCT
            ref = o.get('signal_time') or ('%sT%s:00+05:30' % (o.get('date') or today,
                                    o.get('fired_at') or '00:00'))
            rows = _candle_opens(o.get('sym'), o.get('inst'), ref)
            if len(rows) > 1:
                plain = exits_opens(o.get('direction'), float(o.get('entry')),
                                    OPEN_STOP_PCT, OPEN_TARGET_PCT, rows[1:])
        except Exception as e:
            print(f"plain exit {key} unavailable: {e}")
        if not past_eod(now) and plain:
            _xp, reason = plain[1], plain[2]
        elif past_eod(now):
            # 2) session boundary (15:15): close even if plain rules haven't hit
            reason = 'EOD EXIT'
            _xp = price
        elif not same:
            # 3) engine closed the record on its own
            reason = resolve_reason(o.get('direction'), o.get('entry'), o.get('stop'),
                                    o.get('target'), price, now)
            _xp = price
        else:
            continue
        try:
            _entry_f = float(o.get('entry'))
            _exit_f = float(_xp if _xp is not None else (d or {}).get('price'))
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
                f"Exit (ref): {fmt(_xp if _xp is not None else (d or {}).get('price'))}\n"
                f"Result: {reason} ({_pts_txt})\n"
                f"{o.get('strategy') or '—'}")
        r = tg('sendMessage', {'chat_id': CHANNEL, 'text': text})
        if not r.get('ok'):
            # Atomicity: a failed send must retry next minute, never vanish
            # silently (Oct-13 exits were lost by committing before checking).
            print(f"exit send FAILED for {key}: {reason} — will retry; {str(r)[:150]}")
            continue
        st['open'].pop(key, None)
        try:
            _exit_f = float(_xp if _xp is not None else (d or {}).get('price'))
            _entry_f = float(o.get('entry'))
            _cpts = (_exit_f - _entry_f) if (o.get('direction') != 'BEAR') else (_entry_f - _exit_f)
        except (TypeError, ValueError):
            _exit_f, _cpts = None, None
        st.setdefault('closed', []).append({'inst': o.get('inst'), 'sym': o.get('sym'),
                                            'direction': o.get('direction'), 'entry': o.get('entry'),
                                            'exit': _exit_f, 'reason': reason, 'points': _cpts,
                                            'strategy': o.get('strategy'), 'date': today})
        save_state(st)
        log_alert({'type': 'update', 'inst': o.get('inst'), 'sym': o.get('sym'), 'key': key, 'tg_text': text,
                   'outcome': {'reason': reason,
                               'exit': fmt(_xp if _xp is not None else (d or {}).get('price')),
                               'points_text': _pts_txt},
                   'explanation': explanation_from(d, None, 'exit')
                                  + ' Recorded exit reference: %s (%s).'
                                  % (reason, _pts_txt)},
                  delivered=True,
                  message_id=(r.get('result') or {}).get('message_id'))
        rebuild_page()
        try:
            fb_post(text)
        except Exception as e:
            print(f"FB hook (exit) skipped: {e}")
        print(f"exit sent for {key}: {reason} ok=True")
    # Automatic paper-trade monitoring: close any open live paper trade whose
    # strategy exit (opens spec, 0.5%/2%) has been reached since entry. Runs
    # every watch cycle inside the single-instance scheduler process (never
    # inside a gunicorn worker). Logged; never fatal to the watch loop.
    try:
        from app.paper_trade.engine import PaperTradeEngine
        _pt = PaperTradeEngine()
        for _mi in ('NIFTY', 'BANKNIFTY'):
            try:
                _pt.monitor(_mi)
            except Exception as e:
                print(f'paper monitor {_mi} failed: {e}')
    except Exception as e:
        print(f'paper monitor unavailable: {e}')


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
    try:
        fb_post(text)
    except Exception as e:
        print(f'FB hook (eod) skipped: {e}')
    r = tg('sendMessage', {'chat_id': CHANNEL, 'text': text})
    if r.get('ok'):
        log_alert({'type': 'eod', 'inst': 'NIFTY + BANKNIFTY', 'tg_text': text,
                   'explanation': 'Daily recap of every model record closed in the session '
                                  'ledger, published win or lose.'},
                  delivered=True,
                  message_id=(r.get('result') or {}).get('message_id'))
        rebuild_page()
    print('eod sent:', r.get('ok'))


def do_reconcile():
    """Morning repair for alerts dropped by failed watcher runs (see Oct-13,
    when entries fired but API flakiness killed every later run before the
    exit sweep could record anything).

    For every fired key dated before today:
      - if no archive 'signal' line carries the key, backfill one from the
        paper ledger (source='ledger-backfill', sent=true: fired is only
        recorded when Telegram acknowledges, so the entry went out but the
        archiving failed);
      - if no 'closed' entry matches, resolve the exit from the paper ledger,
        append to closed (reconciled=true) and log an 'update' record
        (missed=true: no live exit alert is on record).
    Stale 'open' keys are resolved the same way and popped. Never sends
    Telegram for past dates. Idempotent; prints a summary for the cron log.
    Rebuilds the alerts page only if something changed.
    """
    import sqlite3
    st = state()
    today = datetime.now(IST).date().isoformat()
    arch_keys = set()
    try:
        with open(ARCHIVE) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get('type') in ('signal', 'update') and r.get('key'):
                    arch_keys.add((r['type'], r['key']))
    except FileNotFoundError:
        pass
    conn = sqlite3.connect(
        f"file:{os.path.join(BASE, 'database', 'tradingai.db')}?mode=ro",
        uri=True)
    try:
        led = {}
        for r in conn.execute(
                "SELECT session_date, instrument_id, direction, level,"
                " entry_price, exit_time, exit_price, exit_reason,"
                " r_multiple, result FROM paper_align"
                " WHERE variant='plain' AND state='SIGNAL'"):
            led[(r[0], r[1], (r[2] or '').upper())] = r[3:]
    finally:
        conn.close()
    closed = st.setdefault('closed', [])
    opens = st.setdefault('open', {})

    def is_closed(date, inst, direction, entry):
        return any(c.get('date') == date and c.get('inst') == inst
                   and (c.get('direction') or '').upper() == (direction or '').upper()
                   and str(c.get('entry')) == str(entry) for c in closed)

    def paper_exit(pro):
        level, entry_px, _xt, exit_px, exit_reason, _r, _res = pro
        reason = {'EOD-1520': 'EOD EXIT', 'EOD': 'EOD EXIT'}.get(
            (exit_reason or '').upper(), (exit_reason or 'EOD EXIT'))
        return level, entry_px, exit_px, reason

    def points_txt(direction, entry_px, exit_px):
        try:
            e_f, x_f = float(entry_px), float(exit_px)
            pts = (x_f - e_f) if (direction or '').upper() != 'BEAR' else (e_f - x_f)
            return x_f, f'{pts:+,.2f} pts'
        except (TypeError, ValueError):
            return None, '—'

    def backfill_exit(date, inst, direction, key, pro):
        level, entry_px, exit_px, reason = paper_exit(pro)
        x_f, pts_txt = points_txt(direction, entry_px, exit_px)
        closed.append({'inst': inst, 'direction': direction, 'entry': entry_px,
                       'exit': x_f, 'reason': reason, 'points': pts_txt,
                       'strategy': spread_name(direction), 'date': date,
                       'reconciled': True})
        opens.pop(key, None)
        log_alert({'type': 'update', 'inst': inst, 'key': key, 'date': date,
                   'source': 'ledger-backfill', 'sent': False, 'missed': True,
                   'outcome': {'reason': reason, 'exit': fmt(exit_px),
                               'points_text': pts_txt},
                   'explanation': ('Backfilled by --reconcile: no live exit alert is '
                                   'on record for this trade (watcher runs failed that '
                                   'day). Outcome reconstructed from the paper ledger '
                                   '(level %s, entry ref %s); nothing was sent to '
                                   'Telegram now.') % (level, entry_px)},
                  delivered=False)
        arch_keys.add(('update', key))
        return 1

    n_sig = n_upd = 0
    cands = {}  # (date, inst, direction) -> key, from fired keys then stale opens
    for key in st.get('fired', []):
        try:
            date, inst, direction, _entry = key.split('|', 3)
        except ValueError:
            print(f'reconcile: skipping malformed key {key!r}')
            continue
        if date < today:
            cands.setdefault((date, inst, (direction or '').upper()), key)
    for key, o in opens.items():
        if (o.get('date') or today) < today:
            cands.setdefault((o.get('date'), o.get('inst'),
                              (o.get('direction') or '').upper()), key)
    for (date, inst, direction), key in sorted(cands.items()):
        pro = led.get((date, inst, direction))
        if pro is None:
            print(f'reconcile: no paper row for {key}; left untouched')
            continue
        level, entry_px = pro[0], pro[1]
        if ('signal', key) not in arch_keys:
            log_alert({'type': 'signal', 'inst': inst,
                       'sym': {'NIFTY': 'nifty', 'BANKNIFTY': 'banknifty'}.get(inst, ''),
                       'key': key, 'direction': (direction or '').upper(),
                       'date': date, 'source': 'ledger-backfill', 'sent': True,
                       'ctx': {'direction': direction, 'trigger': entry_px,
                               'strategy': spread_name(direction)},
                       'explanation': ('Backfilled by --reconcile: the entry Telegram for '
                                       'this record was sent live, but archiving failed at '
                                       'the time. Details reconstructed from the paper '
                                       'ledger (level %s, entry ref %s).') % (level, entry_px)},
                      delivered=True)
            arch_keys.add(('signal', key))
            n_sig += 1
        try:
            _kd, _ki, _kdr, kentry = key.split('|', 3)
        except ValueError:
            kentry = entry_px
        if not is_closed(date, inst, direction, kentry):
            # paper entry can differ from the fired key entry (claim freezes
            # the live price); match closed rows on either.
            if not is_closed(date, inst, direction, entry_px):
                n_upd += backfill_exit(date, inst, direction, key, pro)
    if n_sig or n_upd:
        save_state(st)
        rebuild_page()
    print(f'reconcile done: backfilled_signals={n_sig} backfilled_exits={n_upd}')


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else '--test'
    {'--test': do_test, '--morning': do_morning, '--watch': do_watch,
     '--eod': do_eod, '--reconcile': do_reconcile}[mode]()
