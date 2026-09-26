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
import sys
import urllib.request
import urllib.parse
from datetime import datetime
from zoneinfo import ZoneInfo

BASE = '/opt/tradingai'
IST = ZoneInfo('Asia/Kolkata')
API = 'http://127.0.0.1:8000'
CHANNEL = '@tradingai_cpr'


def token():
    with open(os.path.join(BASE, '.tg_env')) as f:
        return f.read().strip()


def tg(method, payload, photo=None, timeout=30):
    tok = token()
    if photo is None:
        data = urllib.parse.urlencode(payload).encode()
        req = urllib.request.Request(f'https://api.telegram.org/bot{tok}/{method}', data=data)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    import uuid
    boundary = uuid.uuid4().hex
    body = b''
    for k, v in payload.items():
        body += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    body += (f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; '
             f'filename="shot.png"\r\nContent-Type: image/png\r\n\r\n').encode() + photo + f'\r\n--{boundary}--\r\n'.encode()
    req = urllib.request.Request(f'https://api.telegram.org/bot{tok}/{method}', data=body,
                                 headers={'Content-Type': f'multipart/form-data; boundary={boundary}'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


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


def do_test():
    r = tg('sendMessage', {'chat_id': CHANNEL,
                           'text': '🔧 TradingAI alerts online. Morning levels, intraday TRADE signals and EOD recaps will land here. (Educational research only — not financial advice.)'})
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
    head = f"📊 CPR LEVELS | {now.strftime('%a %d %b').upper()}"
    if closed:
        head += f'\nMarket {sess.lower()} — levels below are the last session refs.'
    text = (head + '\n\n' + levels_block('NIFTY', n) + '\n' + levels_block('BANKNIFTY', b)
            + f"\nVIX {fmt((v.get('price')), 2)} (context)"
            + '\nLive decisions from 09:15 → https://tradingai.in'
            + '\nEducational research only — not financial advice.')
    img = shot('https://tradingai.in/index.html', '/tmp/tg_morning.png')
    r = tg('sendPhoto', {'chat_id': CHANNEL, 'caption': text[:1024]}, photo=img)
    print('morning sent:', r.get('ok'))


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
        text = (f"{emoji} TRADE SIGNAL — {inst} ({t.get('direction') or ''})\n"
                f"Entry {fmt(t.get('entry'))} | Stop {fmt(t.get('stop'))} | Target {fmt(t.get('target'))}\n"
                f"Strategy: {t.get('strategy') or '—'}\n"
                f"Full levels: https://tradingai.in/indices/{sym}.html\n"
                f"Educational research only — not financial advice.")
        img = shot(f'https://tradingai.in/indices/{sym}.html', f'/tmp/tg_sig_{sym}.png')
        r = tg('sendPhoto', {'chat_id': CHANNEL, 'caption': text[:1024]}, photo=img)
        if r.get('ok'):
            st.setdefault('fired', []).append(key)
            save_state(st)
            print(f'signal sent for {key}')
        else:
            print(f'signal FAILED for {key}: {str(r)[:150]}')


def do_eod():
    now = datetime.now(IST)
    parts = []
    for sym, inst in (('nifty', 'NIFTY'), ('banknifty', 'BANKNIFTY')):
        try:
            d = api(f'/api/decision/{sym}')
            parts.append(f"{inst}: {d.get('decision') or '—'} ({d.get('session') or ''})")
        except Exception as e:
            parts.append(f'{inst}: feed unreachable')
    text = (f"🔔 EOD {now.strftime('%a %d %b').upper()}\n" + '\n'.join(parts)
            + '\nFull ledger → https://tradingai.in/paper.html'
            + '\nPosted win or lose. Educational research only — not financial advice.')
    r = tg('sendMessage', {'chat_id': CHANNEL, 'text': text})
    print('eod sent:', r.get('ok'))


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else '--test'
    {'--test': do_test, '--morning': do_morning, '--watch': do_watch, '--eod': do_eod}[mode]()
