"""Build frontend/rss.xml from data/tg_alerts_archive.jsonl.

Read-only vs trading logic: presentation of the alert log as an RSS 2.0
feed for automation (Make/Zapier/Buffer -> Facebook Page). Latest 30
records, newest first. Atomic write. No DB, no trading state.
"""
import json
import os
import tempfile
from datetime import datetime
from email.utils import format_datetime
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

BASE = '/opt/tradingai'
IST = ZoneInfo('Asia/Kolkata')
ARCHIVE = os.path.join(BASE, 'data', 'tg_alerts_archive.jsonl')
OUT = os.path.join(BASE, 'frontend', 'rss.xml')
MAX_ITEMS = 30

SITE = 'https://tradingai.in'
DISCLAIMER = ('Automated model output. Not investment advice, not a research '
              'recommendation. Educational research only. https://tradingai.in/disclaimer.html')

SYM_LINK = {'nifty': f'{SITE}/indices/nifty.html',
            'banknifty': f'{SITE}/indices/banknifty.html'}


def parse_ts(rec):
    try:
        dt = datetime.fromisoformat(rec.get('ts_ist') or rec.get('date'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return dt
    except Exception:
        return datetime.now(IST)


def title_for(rec):
    t = rec.get('type', '')
    inst = rec.get('inst') or 'Model'
    direction = (rec.get('direction') or '').upper()
    date = rec.get('date') or ''
    if t == 'signal':
        trig = ((rec.get('ctx') or {}).get('trigger')) or ''
        return f'{inst} {direction} model signal {trig} | {date}'.strip()
    if t == 'update':
        out = rec.get('outcome') or {}
        reason = out.get('reason') or ''
        pts = out.get('points_text') or ''
        return f'{inst} model update: {reason} ({pts}) | {date}'.strip()
    if t == 'eod':
        return f'TradingAI EOD recap | {date}'
    if t == 'morning':
        return f'TradingAI model levels | {date}'
    return f'TradingAI model alert ({inst}) | {date}'


def desc_for(rec):
    tg = (rec.get('tg_text') or '').strip()
    if tg:
        return tg
    bits = []
    ctx = rec.get('ctx') or {}
    if rec.get('type') == 'signal':
        bits.append(f"Direction: {(rec.get('direction') or '').upper()}")
        for k in ('trigger', 'invalidation', 'target', 'strategy', 'signal_time'):
            if ctx.get(k):
                bits.append(f'{k}: {ctx[k]}')
    if rec.get('type') == 'update':
        out = rec.get('outcome') or {}
        bits.append(f"Result: {out.get('reason')} ({out.get('points_text')})")
    expl = (rec.get('explanation') or '').strip()
    if expl:
        bits.append(expl)
    bits.append(DISCLAIMER)
    return ' — '.join(b for b in bits if b)


def link_for(rec):
    sym = (rec.get('sym') or '').lower()
    return SYM_LINK.get(sym, f'{SITE}/alerts.html')


def build():
    recs = []
    try:
        with open(ARCHIVE) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    recs.append(json.loads(line))
                except Exception:
                    continue
    except FileNotFoundError:
        recs = []
    # newest first by ts_ist
    recs.sort(key=lambda r: str(r.get('ts_ist') or r.get('date') or ''), reverse=True)
    recs = recs[:MAX_ITEMS]

    items = []
    for r in recs:
        dt = parse_ts(r)
        pub = format_datetime(dt)
        title = escape(title_for(r))
        desc = escape(desc_for(r))
        link = escape(link_for(r), {'"': '&quot;'})
        guid = escape(f"{SITE}/alerts.html#{r.get('key') or r.get('ts_ist') or title}")
        items.append(
            f'<item><title>{title}</title><link>{link}</link>'
            f'<guid isPermaLink="false">{guid}</guid>'
            f'<pubDate>{pub}</pubDate><description>{desc}</description></item>')

    now = format_datetime(datetime.now(IST))
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0"><channel>'
        f'<title>TradingAI.in Model Alerts</title><link>{SITE}/alerts.html</link>'
        '<description>Automated NIFTY/BANKNIFTY model signals, updates and EOD recaps. '
        'Educational research only, not investment advice.</description>'
        '<language>en-in</language>'
        f'<lastBuildDate>{now}</lastBuildDate>'
        f'<pubDate>{now}</pubDate>'
        f'<ttl>5</ttl>'
        + ''.join(items) +
        '</channel></rss>\n')

    tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(OUT), prefix='.rss-')
    os.chmod(tmp_path, 0o644)
    try:
        with open(tmp_fd, 'w', encoding='utf-8') as f:
            f.write(xml)
        os.replace(tmp_path, OUT)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
    print(f'rss built: {len(items)} items -> {OUT}')


if __name__ == '__main__':
    build()
