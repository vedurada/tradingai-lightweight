"""TradingAI.in Facebook Page auto-post (mirrors Telegram signals).

Posts every signal + exit/update from data/tg_alerts_archive.jsonl to a
Facebook **Page** (Meta Graph API cannot auto-post to personal Profiles).

Secrets: /opt/tradingai/.fb_env (0600, gitignored), format:
  FB_PAGE_ID=1234567890
  FB_PAGE_TOKEN=EAA... (Page access token, long-lived)
State: data/fb_state.json {posted_keys: [...]} — once-per-record dedupe.
Source: data/tg_alerts_archive.jsonl — same records Telegram sends.

Modes:
  --dry-run  print what would post (no token needed, no writes to FB)
  --sync     post all unposted signal/update records (marks posted only on success)
  --test     post a test message (requires token)

Cron (enable AFTER token is stored):
  */5 9-15 * * 1-5 cd /opt/tradingai && python3 scripts/fb_post.py --sync >> logs/fb.log 2>&1

Message format mirrors Telegram entry/exit text + educational disclaimer + link.
Failures never mark posted (retry next run).
"""
import json
import os
import sys
import urllib.parse
import urllib.request
import urllib.error

BASE = '/opt/tradingai'
FB_ENV = os.path.join(BASE, '.fb_env')
ARCHIVE = os.path.join(BASE, 'data', 'tg_alerts_archive.jsonl')
STATE = os.path.join(BASE, 'data', 'fb_state.json')
SITE = 'https://tradingai.in'
ARCHIVE_URL = 'https://tradingai.in/alerts.html'
GRAPH = 'https://graph.facebook.com/v21.0'
DISCLAIMER = ('Automated, rule-based, hypothetical output for study. '
              'Not investment advice. Educational research only.')


def load_secrets():
    cfg = {}
    with open(FB_ENV) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            cfg[k.strip()] = v.strip()
    page = cfg.get('FB_PAGE_ID', '').strip()
    tok = cfg.get('FB_PAGE_TOKEN', '').strip()
    if not page or not tok:
        raise SystemExit('Missing FB_PAGE_ID / FB_PAGE_TOKEN in .fb_env (0600, gitignored).')
    return page, tok


def load_state():
    try:
        with open(STATE) as f:
            st = json.load(f)
    except (FileNotFoundError, ValueError):
        st = {}
    st.setdefault('posted_keys', [])
    return st


def save_state(st):
    tmp = STATE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(st, f)
    os.replace(tmp, STATE)


def rec_key(r, i):
    return r.get('key') or '%s|%s|%s|%d' % (
        r.get('date', ''), r.get('inst', ''), r.get('type', ''), i)


def build_signal_index(records):
    idx = {}
    for _, r in records:
        if r.get('type') == 'signal' and r.get('key'):
            idx[r['key']] = r
    return idx


def fb_format(r, sig_idx=None):
    """Mirror Telegram signal/update text, plus disclaimer + archive link."""
    t = r.get('type')
    inst = r.get('inst', '')
    ctx = r.get('ctx') or {}
    date = r.get('date', '')
    try:
        dp = str(date).split('-')
        months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        datetxt = '%s %s %s' % (dp[2], months[int(dp[1]) - 1], dp[0]) if len(dp) == 3 else date
    except Exception:
        datetxt = date
    if t == 'update' and sig_idx:
        sig = sig_idx.get(r.get('key') or '')
        if sig:
            sget = (sig.get('ctx') or {})
            ctx = dict(sget)
            r = dict(r)
            r.setdefault('direction', sig.get('direction'))
            r.setdefault('strategy', sget.get('strategy'))
            r['ctx'] = ctx
    if t == 'signal':
        lines = [
            '%s' % inst,
            '%s' % datetxt,
            'Direction: %s' % (ctx.get('direction') or '—'),
        ]
        if ctx.get('level'):
            lines.append('Level: %s' % ctx['level'])
        lines += [
            'Entry (ref): %s' % (ctx.get('trigger') or '—'),
            'SL: %s' % (ctx.get('invalidation') or '—'),
        ]
        strat = ctx.get('strategy') or '—'
        tail = strat
        if ctx.get('expiry'):
            tail += ' · Exp %s' % ctx['expiry']
        if ctx.get('signal_time'):
            tail += ' · Signal %s' % ctx['signal_time']
        lines.append(tail)
    elif t == 'update':
        oc = r.get('outcome') or {}
        lines = [
            '%s' % inst,
            '%s' % datetxt,
            'Direction: %s' % ((r.get('direction') or ctx.get('direction')) or '—'),
            'Entry (ref): %s' % (ctx.get('trigger') or r.get('entry') or '—'),
            'Exit (ref): %s' % (oc.get('exit') or '—'),
            'Result: %s (%s)' % (oc.get('reason') or '—', oc.get('points_text') or '—'),
            '%s' % (ctx.get('strategy') or r.get('strategy') or '—'),
        ]
    else:
        return None
    lines += [DISCLAIMER, 'Full archive: %s' % ARCHIVE_URL]
    return '\n'.join(lines)


def fb_post(page, token, message, link=ARCHIVE_URL):
    data = urllib.parse.urlencode(
        {'message': message, 'link': link, 'access_token': token}).encode()
    req = urllib.request.Request('%s/%s/feed' % (GRAPH, page), data=data)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return {'ok': True, 'resp': json.load(resp)}
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode()[:300]
        except Exception:
            detail = str(e)
        return {'ok': False, 'error': 'HTTP %s %s' % (e.code, detail)}
    except Exception as e:
        return {'ok': False, 'error': '%s: %s' % (type(e).__name__, e)}


def iter_records():
    try:
        f = open(ARCHIVE)
    except FileNotFoundError:
        return
    with f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get('type') in ('signal', 'update'):
                yield i, r


def main(argv):
    mode = argv[1] if len(argv) > 1 else '--dry-run'
    if mode == '--test':
        page, tok = load_secrets()
        msg = ('TradingAI.in Facebook wiring test.\n%s\n%s'
               % (DISCLAIMER, ARCHIVE_URL))
        print(fb_post(page, tok, msg, link=SITE))
        return
    records = [(i, r) for i, r in iter_records()]
    sig_idx = build_signal_index(records)
    st = load_state()
    posted = set(st.get('posted_keys', []))
    pending = [(i, r) for i, r in records if rec_key(r, i) not in posted]
    if mode == '--dry-run':
        print('%d records total, %d already posted, %d would post'
              % (len(records), len(posted), len(pending)))
        for i, r in pending[-5:]:
            print('--- %s ---' % rec_key(r, i))
            print(fb_format(r, sig_idx))
        return
    if mode != '--sync':
        raise SystemExit('usage: fb_post.py [--dry-run|--sync|--test]')
    page, tok = load_secrets()
    sent = 0
    for i, r in pending:
        msg = fb_format(r, sig_idx)
        if not msg:
            continue
        res = fb_post(page, tok, msg)
        if not res.get('ok'):
            print('FAILED %s: %s — will retry next run'
                  % (rec_key(r, i), str(res.get('error'))[:200]))
            continue
        st['posted_keys'].append(rec_key(r, i))
        save_state(st)
        sent += 1
        print('posted %s -> %s' % (rec_key(r, i), res.get('resp')))
    print('done: posted %d/%d pending' % (sent, len(pending)))


if __name__ == '__main__':
    main(sys.argv)
