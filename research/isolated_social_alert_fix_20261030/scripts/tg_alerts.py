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
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
import urllib.parse
import hashlib
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


def init_notification_schema(conn):
    """Additive notification_events ledger. No existing tables modified."""
    conn.execute("""CREATE TABLE IF NOT EXISTS notification_events (
        event_id TEXT PRIMARY KEY,
        signal_id TEXT,
        instrument_id TEXT NOT NULL,
        channel TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT PENDING,
        message_id TEXT,
        error TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE (signal_id, channel)
    )""")
    conn.commit()


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
    prev_close = (dec.get('prev_close') if isinstance(dec, dict) else None) or c.get('prev_close')
    lines = [
        f"{sym} (prev close {fmt(prev_close)}):",
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
    try:
        img = shot('https://tradingai.in/index.html', '/tmp/tg_morning.png')
    except Exception as e:
        print(f'morning screenshot failed: {e}; sending text only')
        img = None
    try:
        if img:
            fb_post(text, photo=img)
        else:
            fb_post(text)
    except Exception as e:
        print(f'FB hook (morning) skipped: {e}')
    if img:
        r = tg('sendPhoto', {'chat_id': CHANNEL, 'caption': text[:1024], 'reply_markup': NAV_MARKUP}, photo=img)
    else:
        r = tg('sendMessage', {'chat_id': CHANNEL, 'text': text, 'reply_markup': NAV_MARKUP})
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


def open_scalp_trade(inst, today):
    """Open SCALP_HLC paper trade for (inst, today) from the paper ledger."""
    db = os.environ.get('TRADINGAI_DB_PATH') or os.path.join(BASE, 'database', 'tradingai.db')
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            'SELECT trade_id, direction, entry, stop, target, entry_time, status '
            'FROM paper_trades WHERE instrument_id=? AND scenario=? AND substr(entry_time,1,10)=? '
            'AND status IN ("ACTIVE","OPEN") ORDER BY created_at DESC',
            (inst, 'SCALP_HLC', today)).fetchall()
        return dict(rows[0]) if rows else None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def closed_trade_by_id(trade_id):
    """Resolve an already-CLOSED scalp trade by deterministic id (exit sweep)."""
    import sqlite3
    db = os.environ.get('TRADINGAI_DB_PATH') or os.path.join(BASE, 'database', 'tradingai.db')
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            'SELECT trade_id, direction, entry, stop, target, exit_price, exit_reason, '
            'status, entry_time, exit_time FROM paper_trades WHERE trade_id=?',
            (trade_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        if str(d.get('status')) != 'CLOSED' or d.get('exit_price') is None:
            return None
        return {'trade_id': d['trade_id'], 'direction': d.get('direction'),
                'entry': d.get('entry'), 'stop': d.get('stop'), 'target': d.get('target'),
                'exit_price': d.get('exit_price'), 'exit_reason': d.get('exit_reason'),
                'entry_time': d.get('entry_time'), 'exit_time': d.get('exit_time'),
                'filled': True, 'status': 'CLOSED'}
    finally:
        try:
            conn.close()
        except Exception:
            pass


def latest_price(inst):
    db = os.environ.get('TRADINGAI_DB_PATH') or os.path.join(BASE, 'database', 'tradingai.db')
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        r = conn.execute('SELECT price FROM market_snapshots WHERE instrument_id=? ORDER BY timestamp DESC LIMIT 1', (inst,)).fetchone()
        return float(r[0]) if r else None
    finally:
        try:
            conn.close()
        except Exception:
            pass


STALE_ENTRY_MIN = 20
LAST_ENTRY_CUTOFF = (15, 25)


def _fresh_entry(ts, now=None, max_min=STALE_ENTRY_MIN):
    """Live alerts/paper only act on a signal whose entry bar is recent.

    The look-ahead entry itself is intentional; this guard only prevents a
    restart from presenting an hours-old entry as a new trade."""
    if not ts:
        return False
    now = now or datetime.now(IST)
    try:
        dt = datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return (now - dt.astimezone(IST)).total_seconds() <= max_min * 60
    except (TypeError, ValueError):
        return False


def _entry_window_open(now=None):
    now = now or datetime.now(IST)
    return (now.hour, now.minute) <= LAST_ENTRY_CUTOFF


def _scalp_key(today, inst, sig):
    return (f"{today}|{inst}|{sig.get('direction')}|"
            f"{sig.get('signal_time') or sig.get('entry')}")

def _is_delivered(signal_id, db_path):
    """Check if a signal already has a DELIVERED notification_events record."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT status FROM notification_events WHERE signal_id=? AND channel=telegram",
                (signal_id,)).fetchone()
        finally:
            try:
                conn.close()
            except Exception:
                pass
        return row is not None and row[0] == DELIVERED
    except Exception:
        return False


def _scalp_link(today, inst, sig):
    return (f"scalp|{inst}|{today}|{sig.get('direction')}|"
            f"{sig.get('signal_time') or sig.get('entry_time')}")


def do_watch(lock_path='/tmp/tg_watch.lock'):
    import atexit
    from app.core.db import get_conn
    try:
        _cn = get_conn()
        init_notification_schema(_cn)
        _cn.close()
    except Exception as e:
        print(f'notification schema init failed: {e}')
    import time
    lock_p = lock_path
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
    now = datetime.now(IST)
    today = now.date().isoformat()
    allow_new = _entry_window_open(now)
    for sym, inst in (('nifty', 'NIFTY'), ('banknifty', 'BANKNIFTY')):
        _t_poll = time.perf_counter()
        try:
            sd = api_retry(f'/api/strategy/scalp?instrument={inst}')
        except Exception as e:
            print(f'{sym} poll failed: {e}')
            continue
        _ms_poll = (time.perf_counter() - _t_poll) * 1000
        _ms_create = 0.0
        _ms_alert = 0.0
        try:
            dec = api_retry(f'/api/decision/{sym}')
        except Exception as e:
            print(f'{sym} context poll failed: {e}')
            dec = {}
        signals = (sd or {}).get('signals') or []
        if not signals and str((sd or {}).get('state') or '') == 'SIGNAL' and (sd or {}).get('entry') is not None:
            signals = [sd]
        for sdata in signals:
            if str(sdata.get('state') or '') != 'SIGNAL':
                continue
            entry_time = sdata.get('entry_time') or sdata.get('signal_time')
            sig_time = sdata.get('signal_time') or entry_time
            key = _scalp_key(today, inst, sdata)
            _sig_ts = sdata.get('signal_time') or sdata.get('entry_time') or ''
            _sig_dir = sdata.get('direction') or ''
            _sig_lvl = sdata.get('level') or ''
            _sig_raw = f"{inst}|{_sig_ts}|{_sig_dir}|{_sig_lvl}"
            signal_id = 'SS-' + hashlib.sha1(_sig_raw.encode()).hexdigest()[:12].upper()
            db_path = os.environ.get('TRADINGAI_DB_PATH') or os.path.join(BASE, 'database', 'tradingai.db')
            if _is_delivered(signal_id, db_path): continue
            _pt_id = None
            if not allow_new:
                print(f'{inst} signal {sig_time} skipped: after entry cutoff')
                continue
            if not _fresh_entry(entry_time, now):
                print(f'{inst} signal {sig_time} skipped: stale entry {entry_time}')
                continue
            t = {
                'instrument': inst,
                'instrument_id': inst,
                'scenario': 'SCALP_HLC',
                'direction': sdata.get('direction'),
                'level': sdata.get('level'),
                'signal_time': sig_time,
                'entry': sdata.get('entry'),
                'entry_time': entry_time,
                'stop': sdata.get('stop'),
                'target': sdata.get('target'),
                'strategy': 'Scalp HLC 3-bar',
            }
            link = _scalp_link(today, inst, sdata)
            sig_at = now.strftime('%H:%M')
            try:
                _dp = today.split('-')
                _months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
                _datetxt = f"{_dp[2]} {_months[int(_dp[1])-1]} {_dp[0]}"
            except Exception:
                _datetxt = today
            try:
                _hm = str(entry_time or sig_time or '')[11:16]
                _hh, _mm = _hm.split(':')
                _H = int(_hh); _ap = 'PM' if _H >= 12 else 'AM'
                _h12 = _H % 12 or 12
                _sigtxt = f"{_h12}:{_mm} {_ap}"
            except Exception:
                _sigtxt = sig_at
            text = (f"{inst}\n{_datetxt}\n"
                    f"Direction: {(t.get('direction') or '').upper() or '—'}\n"
                    f"Entry (ref): {fmt(t.get('entry'))}\n"
                    f"SL: {fmt(t.get('stop'))}\n"
                    f"Target (ref): {fmt(t.get('target'))}\n"
                    f"Signal Entry {_sigtxt}")
            ctx = ctx_from(dec, t, t.get('level'), None, _sigtxt)
            ctx['strategy'] = 'Scalp HLC 3-bar'
            ctx['level'] = t.get('level') or ''
            explanation = (f"Scalp HLC 3-bar {(t.get('direction') or '').upper()} alignment "
                           f"confirmed on the {str(sig_time)[11:16]} candle; entry at the next "
                           f"5-minute open {str(entry_time)[11:16]} ({fmt(t.get('entry'))}), "
                           f"invalidation {fmt(t.get('stop'))}, target {fmt(t.get('target'))}.")
            _t_alert = time.perf_counter()
            # Persist PENDING notification event before dispatch

            r = tg('sendMessage', {'chat_id': CHANNEL, 'text': text})
            _ms_alert = (time.perf_counter() - _t_alert) * 1000
            if r.get('ok'):
                st.setdefault('fired', []).append(key)
                # Update notification_events to DELIVERED
                st.setdefault('open', {})[key] = {'inst': inst, 'sym': sym,
                                                  'trade_id': _pt_id,
                                                  'direction': t.get('direction'), 'entry': t.get('entry'),
                                                  'stop': t.get('stop'), 'target': t.get('target'),
                                                  'strategy': 'Scalp HLC 3-bar', 'fired_at': sig_at,
                                                  'date': today, 'signal_time': sig_time}
                log_alert({'type': 'signal', 'inst': inst, 'sym': sym, 'key': key, 'tg_text': text,
                           'direction': (t.get('direction') or '').upper() or '\u2014',
                           'ctx': ctx, 'explanation': explanation},
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

                # Record failure in notification_events for retry
                _nconn4 = sqlite3.connect(f"file:{db_path}?mode=rw", uri=True)
                try:
                    init_notification_schema(_nconn4)
                    _nconn4.execute(
                        "WHERE signal_id=? AND channel=telegram",
                        (str(r)[:500], now.isoformat(), signal_id))
                    _nconn4.commit()
                except Exception as e:
                    print(f'notification_events failure record failed: {e}')
                finally:
                    try:
                        _nconn4.close()
                    except Exception:
                        pass
                        "UPDATE notification_events SET status=FAILED, error=?, updated_at=? "
        print(f'[latency] inst={inst} poll_ms={_ms_poll:.1f} '
              f'create_ms={_ms_create:.1f} alert_ms={_ms_alert:.1f}')
    # exit sweep: previously fired trades no longer in the same TRADE
    now = datetime.now(IST)
    for key, o in list(st.get('open', {}).items()):
        if o.get('date') != today:
            # Stale opens belong to --reconcile (daily 09:10), which resolves
            # them from the paper ledger with explicit missed-labelling.
            # Never pop silently here: that path dropped Oct-13 exits.
            continue
        _xinst = o.get('inst')
        import hashlib as _hl
        _xid = o.get('trade_id')
        if not _xid:
            _xid = 'PT-' + _hl.sha1(f'scalp|{_xinst}|{today}'.encode()).hexdigest()[:10].upper()
        _m = None
        try:
            from app.paper_trade.engine import PaperTradeEngine
            _mons = PaperTradeEngine().monitor(_xinst)
            _m = next((x for x in _mons if str(x.get('trade_id') or '') == str(_xid)), None)
        except Exception as e:
            print(f"exit engine monitor {key} failed: {e}")
        if _m is None:
            _m = closed_trade_by_id(_xid)
        if not _m or not _m.get('filled'):
            continue
        _xp = _m.get('exit_price')
        reason = _m.get('exit_reason') or 'EOD EXIT'
        try:
            _entry_f = float(o.get('entry'))
            _exit_f = float(_xp if _xp is not None else float(o.get('entry') or 0))
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
                f"Exit (ref): {fmt(_xp if _xp is not None else float(o.get('entry') or 0))}\n"
                f"Result: {reason} ({_pts_txt})")
        r = tg('sendMessage', {'chat_id': CHANNEL, 'text': text})
        if not r.get('ok'):
            # Atomicity: a failed send must retry next minute, never vanish
            # silently (Oct-13 exits were lost by committing before checking).
            print(f"exit send FAILED for {key}: {reason} — will retry; {str(r)[:150]}")
            continue
        st['open'].pop(key, None)
        try:
            _exit_f = float(_xp if _xp is not None else float(o.get('entry') or 0))
            _entry_f = float(o.get('entry'))
            _cpts = (_exit_f - _entry_f) if (o.get('direction') != 'BEAR') else (_entry_f - _exit_f)
        except (TypeError, ValueError):
            _exit_f, _cpts = None, None
        st.setdefault('closed', []).append({'inst': o.get('inst'), 'sym': o.get('sym'),
                                            'direction': o.get('direction'), 'entry': o.get('entry'),
                                            'exit': _exit_f, 'reason': reason, 'points': _cpts,
                                            'strategy': o.get('strategy'), 'date': today,
                                            'key': key, 'trade_id': _xid})
        save_state(st)
        log_alert({'type': 'update', 'inst': o.get('inst'), 'sym': o.get('sym'), 'key': key, 'tg_text': text,
                   'outcome': {'reason': reason,
                                'exit': fmt(_xp if _xp is not None else float(o.get('entry') or 0)),
                               'points_text': _pts_txt},
                   'explanation': explanation_from({'decision': reason}, None, 'exit')
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
    # strategy exit (scalp spec: stop / 1.5R target) has been reached since entry. Runs
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
        if isinstance(v, str):
            v = v.replace('pts', '').replace(',', '').strip()
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
    """Morning repair for alerts dropped by failed watcher runs.

    Scalp alerts are reconciled from paper_trades (per-signal watch_key), not
    the legacy one-row-per-day paper_align table. Legacy CPR keys still fall
    back to paper_align. Never sends Telegram for past dates; idempotent.
    """
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
    paper = []
    try:
        for r in conn.execute(
                "SELECT trade_id, instrument_id, direction, entry, stop, target,"
                " entry_time, exit_time, exit_price, exit_reason, paper_pnl,"
                " status, qualification_evidence FROM paper_trades"
                " WHERE scenario='SCALP_HLC' OR qualification_evidence LIKE '%SCALP_HLC%'"):
            try:
                ev = json.loads(r[12] or '{}')
            except Exception:
                ev = {}
            paper.append({
                'trade_id': r[0], 'inst': r[1], 'direction': r[2],
                'entry': r[3], 'stop': r[4], 'target': r[5],
                'entry_time': r[6], 'exit_time': r[7], 'exit': r[8],
                'exit_reason': r[9], 'pnl': r[10], 'status': r[11],
                'level': ev.get('level'), 'signal_time': ev.get('signal_time'),
                'watch_key': ev.get('watch_key'),
                'date': (r[6] or ev.get('signal_time') or '')[:10],
            })
    except Exception as e:
        print(f'reconcile: paper_trades read failed: {e}')
    legacy = {}
    try:
        for r in conn.execute(
                "SELECT session_date, instrument_id, direction, level,"
                " entry_price, exit_time, exit_price, exit_reason,"
                " r_multiple, result FROM paper_align"
                " WHERE variant='plain' AND state='SIGNAL'"):
            legacy[(r[0], r[1], (r[2] or '').upper())] = r[3:]
    except Exception:
        pass
    conn.close()
    closed = st.setdefault('closed', [])
    opens = st.setdefault('open', {})
    by_id = {p['trade_id']: p for p in paper}

    def closed_tids():
        return {c.get('trade_id') for c in closed if c.get('trade_id')}

    def is_closed(key, date, inst, direction, entry):
        if any(c.get('key') == key for c in closed):
            return True
        return any(c.get('date') == date and c.get('inst') == inst
                   and (c.get('direction') or '').upper() == (direction or '').upper()
                   and str(c.get('entry')) == str(entry) for c in closed)

    def match_paper(key, o=None):
        try:
            date, inst, direction, fourth = key.split('|', 3)
        except ValueError:
            return None
        if o and o.get('trade_id') and o['trade_id'] in by_id:
            return by_id[o['trade_id']]
        cands = [p for p in paper
                 if p.get('date') == date and p.get('inst') == inst
                 and (p.get('direction') or '').upper() == (direction or '').upper()]
        if not cands:
            return None
        if len(cands) == 1:
            return cands[0]
        if 'T' in str(fourth):
            exact = [p for p in cands if p.get('signal_time') == fourth]
            if exact:
                return exact[0]
        exact = [p for p in cands if str(p.get('entry')) == str(fourth)]
        return exact[0] if exact else None

    def add_closed(p, key):
        if str(p.get('status') or '').upper() != 'CLOSED' or p.get('exit') is None:
            return 0
        if p['trade_id'] in closed_tids() or any(c.get('key') == key for c in closed):
            opens.pop(key, None)
            return 0
        try:
            entry_px = float(p.get('entry'))
            exit_px = float(p.get('exit'))
        except (TypeError, ValueError):
            return 0
        direction = (p.get('direction') or '').upper()
        pts = (exit_px - entry_px) if direction != 'BEAR' else (entry_px - exit_px)
        reason = {'EOD-1520': 'EOD EXIT', 'EOD': 'EOD EXIT'}.get(
            (p.get('exit_reason') or '').upper(), p.get('exit_reason') or 'EOD EXIT')
        closed.append({'inst': p['inst'], 'direction': p.get('direction'),
                       'entry': entry_px, 'exit': exit_px, 'reason': reason,
                       'points': round(pts, 2), 'strategy': 'Scalp HLC 3-bar',
                       'date': p.get('date'), 'trade_id': p['trade_id'],
                       'key': key, 'reconciled': True})
        opens.pop(key, None)
        log_alert({'type': 'update', 'inst': p['inst'], 'key': key,
                   'date': p.get('date'), 'source': 'ledger-backfill',
                   'sent': False, 'missed': True,
                   'outcome': {'reason': reason, 'exit': fmt(exit_px),
                               'points_text': _fmt_pts(pts)},
                   'explanation': ('Backfilled by --reconcile from paper_trades: '
                                   'no live exit alert is on record for this trade. '
                                   'Entry %s, exit %s, %s (%s).')
                                  % (fmt(entry_px), fmt(exit_px), reason, _fmt_pts(pts))},
                  delivered=False)
        arch_keys.add(('update', key))
        return 1

    def backfill_signal(key, p):
        if ('signal', key) in arch_keys:
            return 0
        log_alert({'type': 'signal', 'inst': p['inst'],
                   'sym': {'NIFTY': 'nifty', 'BANKNIFTY': 'banknifty'}.get(p['inst'], ''),
                   'key': key, 'direction': (p.get('direction') or '').upper(),
                   'date': p.get('date'), 'source': 'ledger-backfill', 'sent': True,
                   'ctx': {'direction': p.get('direction'), 'trigger': p.get('entry'),
                           'invalidation': p.get('stop'), 'target': p.get('target'),
                           'strategy': 'Scalp HLC 3-bar', 'level': p.get('level') or ''},
                   'explanation': ('Backfilled by --reconcile: the entry Telegram for '
                                   'this scalp signal was sent live, but archiving failed '
                                   'at the time. Details reconstructed from paper_trades '
                                   '(level %s, entry ref %s, signal %s).')
                                  % (p.get('level') or '—', fmt(p.get('entry')),
                                     p.get('signal_time') or '—')},
                  delivered=True)
        arch_keys.add(('signal', key))
        return 1

    n_sig = n_upd = 0
    handled = set()
    # 1) Stale open alerts: exact trade_id from the alert state.
    for key, o in list(opens.items()):
        if (o.get('date') or today) >= today:
            continue
        p = match_paper(key, o)
        if not p:
            continue
        if ('signal', key) not in arch_keys:
            n_sig += backfill_signal(key, p)
        if add_closed(p, key):
            n_upd += 1
            handled.add(key)
    # 2) Any other fired key with a matching closed paper trade.
    for key in st.get('fired', []):
        try:
            date, inst, direction, fourth = key.split('|', 3)
        except ValueError:
            print(f'reconcile: skipping malformed key {key!r}')
            continue
        if date >= today:
            continue
        if is_closed(key, date, inst, direction, fourth):
            continue
        p = match_paper(key, opens.get(key))
        if p:
            if ('signal', key) not in arch_keys:
                n_sig += backfill_signal(key, p)
            if add_closed(p, key):
                n_upd += 1
                handled.add(key)
            continue
        # 3) Legacy CPR/SMA20 keys still resolve from paper_align.
        pro = legacy.get((date, inst, (direction or '').upper()))
        if not pro:
            print(f'reconcile: no paper row for {key}; left untouched')
            continue
        level, entry_px, _xt, exit_px, exit_reason, _r, _res = pro
        if exit_px is None or is_closed(key, date, inst, direction, fourth):
            continue
        try:
            e_f, x_f = float(entry_px), float(exit_px)
            pts = (x_f - e_f) if (direction or '').upper() != 'BEAR' else (e_f - x_f)
        except (TypeError, ValueError):
            pts = None
        if ('signal', key) not in arch_keys:
            log_alert({'type': 'signal', 'inst': inst,
                       'sym': {'NIFTY': 'nifty', 'BANKNIFTY': 'banknifty'}.get(inst, ''),
                       'key': key, 'direction': (direction or '').upper(),
                       'date': date, 'source': 'ledger-backfill', 'sent': True,
                       'ctx': {'direction': direction, 'trigger': entry_px,
                               'strategy': spread_name(direction)},
                       'explanation': ('Backfilled by --reconcile: the entry Telegram for '
                                       'this legacy record was sent live, but archiving failed '
                                       'at the time. Details reconstructed from paper_align '
                                       '(level %s, entry ref %s).') % (level, entry_px)},
                      delivered=True)
            arch_keys.add(('signal', key))
            n_sig += 1
        reason = {'EOD-1520': 'EOD EXIT', 'EOD': 'EOD EXIT'}.get(
            (exit_reason or '').upper(), (exit_reason or 'EOD EXIT'))
        closed.append({'inst': inst, 'direction': direction, 'entry': entry_px,
                       'exit': float(exit_px), 'reason': reason,
                       'points': round(pts, 2) if pts is not None else None,
                       'strategy': spread_name(direction), 'date': date,
                       'key': key, 'reconciled': True})
        opens.pop(key, None)
        log_alert({'type': 'update', 'inst': inst, 'key': key, 'date': date,
                   'source': 'ledger-backfill', 'sent': False, 'missed': True,
                   'outcome': {'reason': reason, 'exit': fmt(exit_px),
                               'points_text': _fmt_pts(pts)},
                   'explanation': ('Backfilled by --reconcile: no live exit alert is '
                                   'on record for this legacy trade (watcher runs failed '
                                   'that day). Outcome reconstructed from paper_align '
                                   '(level %s, entry ref %s).') % (level, entry_px)},
                  delivered=False)
        arch_keys.add(('update', key))
        n_upd += 1
        handled.add(key)
    if n_sig or n_upd:
        save_state(st)
        rebuild_page()
    print(f'reconcile done: backfilled_signals={n_sig} backfilled_exits={n_upd}')

if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else '--test'
    {'--test': do_test, '--morning': do_morning, '--watch': do_watch,
     '--eod': do_eod, '--reconcile': do_reconcile}[mode]()
