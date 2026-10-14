#!/usr/bin/env python3
"""Per-signal research story generator (past backfill + nightly for new signals).

For every SIGNAL row in paper_align (per instrument x variant) it reads that
session's stored 5m candles and writes a unique, fact-grounded narrative note to
reports/signals/<variant>/YYYY-MM-DD_<INST>_<dir>_<level>.md plus a hub index.

Additive read-only: never edits DB, engine, or page generator. Writes only:
  reports/signals/<variant>/*.md and reports/signals/index.md
  frontend/signals.html and frontend/signals/<variant>/*.html (site archive)

Run modes:
  python3 scripts/signal_articles.py                      # backfill everything
  python3 scripts/signal_articles.py --date 2026-10-12    # one day (nightly cron)
  python3 scripts/signal_articles.py --variant plain      # pick a book
  python3 scripts/signal_articles.py --llm                # LLM narration (needs a key)

LLM narration: uses Groq by default (settings.json ai.*); override with
LLM_BASE_URL/LLM_MODEL/LLM_API_KEY, or put a key in config/llm_key (mode 600).
Falls back to the deterministic template per-signal if the key is missing or
the API call fails, so the daily run always produces a note.

Articles are auto-drafted research notes and carry a review marker; they are
not investment advice.
"""
import argparse
import hashlib
import json
import os
import random
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, '/opt/tradingai')
sys.path.insert(0, '/opt/tradingai/scripts')
from app.core.db import get_conn
from app.research.cpr_trigger_engine import prev_session_ohlc, day_levels, monday_of
from app.research.cpr_strategy_engine import calculate_cpr, classify_cpr
import loss_memory as lm

IST = ZoneInfo('Asia/Kolkata')
BASE = '/opt/tradingai'
CANDLE = 'market_candles_5m'
VARIANTS = ('plain',)
INSTS = ('NIFTY', 'BANKNIFTY', 'INDIA_VIX')
DIRS = {'BULL': 'bullish', 'BEAR': 'bearish', 'LONG': 'bullish', 'SHORT': 'bearish'}


def vix_read(drift):
    """Factual volatility-backdrop words for a VIX session move (direction-agnostic).

    Based on this book's history: VIX direction alone carried no directional edge for
    NIFTY/BANKNIFTY; flat VIX and intraday VIX reversals correlated with weak
    follow-through. Returns (move_word, tone, context_sentence)."""
    if drift is None:
        return 'flat', 'data unavailable', 'VIX data unavailable for this session.'
    if drift > 0.25:
        return ('rising', 'volatility expanding',
                'Rising VIX reflects fear building in the options market. In this book, '
                'VIX-rising windows printed the widest follow-through; flat or reversing '
                'VIX preceded the weakest outcomes. No equity-side direction is implied.')
    if drift < -0.25:
        return ('falling', 'volatility contracting',
                'Falling VIX reflects fear easing. In this book, VIX-falling windows '
                'were quieter and follow-through depended on CPR/VWAP location rather '
                'than VIX alone. No equity-side direction is implied.')
    return ('flat', 'volatility flat',
            'VIX was essentially unchanged on the session. In this book, flat-VIX '
            'sessions produced limited follow-through and the weakest outcomes &mdash; '
            'a range-bound caution flag, not a direction signal.')


def is_vix(inst):
    return inst == 'INDIA_VIX'


def pick(seed, options):
    r = random.Random(seed)
    return options[r.randrange(len(options))]


def api_key():
    k = os.environ.get('LLM_API_KEY') or os.environ.get('GROQ_API_KEY')
    if not k:
        try:
            k = open(f'{BASE}/config/llm_key').read().strip() or None
        except OSError:
            k = None
    return k


def llm_meta():
    base = os.environ.get('LLM_API_URL') or os.environ.get('LLM_BASE_URL')
    model = os.environ.get('LLM_MODEL')
    if base:
        if not model and 'mistral.ai' in base:
            model = 'mistral-small-latest'
        return base, model or 'mistral-small-latest'
    try:
        import json as _j
        ai = _j.load(open(f'{BASE}/config/settings.json'))['ai']
        prov, mdl = ai.get('provider', 'groq'), (ai.get('model') or 'mixtral')
    except Exception:
        prov, mdl = 'groq', 'mixtral'
    base = 'https://api.groq.com/openai/v1/chat/completions'
    model = {'mixtral': 'qwen/qwen3.8-27b'}.get(mdl, mdl)
    return base, model


def _facts(conn, s):
    inst, day, variant = s['instrument_id'], s['session_date'], s['variant']
    cs = candles(conn, inst, day)
    prev = prev_session_ohlc(conn, inst, day)
    if not prev:
        return None
    z = day_levels(prev['high'], prev['low'], prev['close'])
    pclose = float(prev['close'])
    width = (float(prev['high']) - float(prev['low'])) / pclose * 100
    regime = classify_cpr(width) or 'NORMAL'
    last = cs[-1]['close'] if cs else s['exit_price']
    o = cs[0]['open'] if cs else s['entry_price']
    day_hi = max(c['high'] for c in cs) if cs else pclose
    day_lo = min(c['low'] for c in cs) if cs else pclose
    drift = (last - pclose) / pclose * 100
    ent = fmt(s['entry_time'])[11:16]
    slot = 'open-drive' if ent == '09:20' else 'intraday'
    xo, xt, xl, lt = excursions(
        cs, 'T'.join(s['entry_time'].split()) if s['entry_time'] else None,
        'T'.join(s['exit_time'].split())[:16] if s['exit_time'] else None)
    d = DIRS.get(s['direction'], s['direction'].lower())
    fav, fav_t = (xl, lt) if s['direction'] in ('BEAR', 'SHORT') else (xo, xt)
    adv, adv_t = (xo, xt) if s['direction'] in ('BEAR', 'SHORT') else (xl, lt)
    fav_gap = abs((fav - s['entry_price']) / s['entry_price']) * 100 if fav else 0
    adv_gap = abs((adv - s['entry_price']) / s['entry_price']) * 100 if adv else 0
    levels = {k.upper(): round(float(z[k]), 2) for k in ('pp', 'r1', 'r2', 'r3', 's1', 's2', 's3') if z.get(k)}
    return {'inst': inst, 'day': day, 'variant': variant, 'direction': d,
            'signal_side': s['direction'], 'level': s['level'], 'result': s['result'],
            'r': float(s['r_multiple'] or 0), 'prev_close': round(pclose, 2),
            'levels': levels, 'width_pct': round(width, 2), 'regime': regime,
            'open': round(o, 2), 'day_hi': round(day_hi, 2), 'day_lo': round(day_lo, 2),
            'drift_pct': round(drift, 2), 'slot': slot,
            'entry': fmt(s['entry_time']), 'entry_price': round(float(s['entry_price'] or 0), 2),
            'exit': fmt(s['exit_time']), 'exit_price': round(float(s['exit_price'] or 0), 2),
            'exit_reason': s['exit_reason'], 'stop_price': round(float(s['stop_price'] or 0), 2),
            'fav': f'{fav_gap:.2f}%' + (f' at {fmt(fav_t)}' if fav_t else ''),
            'adv': f'{adv_gap:.2f}%' + (f' at {fmt(adv_t)}' if adv_t else ''),
            'gate': 'none (plain)' if variant == 'plain' else 'weekly CPR gate cleared',
            'engine_rules': ('plain CPR book — first trigger of the session; entry at the '
                             'next 5m candle open in [09:20, 15:20); 0.5% stop / 2% target at '
                             'subsequent opens (stop first); flat at 15:20'
                             if variant == 'plain' else
                             'weekly CPR gate then first trigger; entry at the next 5m open; '
                             '0.5% stop / 2% target at opens (stop first); flat at 15:20')}


PROMPT = ("You write concise research notes for an NSE index trading-log. Use ONLY the "
          "facts given below. Never invent, extend, or project any price, level, time, "
          "percentage or outcome beyond what is listed. No predictions or advice. "
          "Be precise and professional, lightly narrative. Write Markdown: start with a "
          "heading line `# `, then sections `## The setup`, `## The session`, "
          "`## What this notes`. 180-260 words total.")


def llm_narrate(facts):
    base, model = llm_meta()
    key = api_key()
    if not key:
        return None
    payload = {'model': model, 'temperature': 0.9, 'max_tokens': 1000,
               'messages': [{'role': 'system', 'content': PROMPT},
                            {'role': 'user', 'content': json.dumps(facts, indent=1)}]}
    ua = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                        '(KHTML, like Gecko) Chrome/120 Safari/537.36',
          'Accept': 'application/json, text/plain, */*'}
    deadline = time.time() + 180
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        req = urllib.request.Request(base, data=json.dumps(payload).encode(),
                                     headers={'Authorization': f'Bearer {key}',
                                              'Content-Type': 'application/json', **ua})
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                out = json.load(r)
            txt = (out.get('choices') or [{}])[0].get('message', {}).get('content') or ''
            if txt:
                return txt.strip()
            print(f'llm_empty model={model} attempt={attempt}', flush=True)
            return None
        except urllib.error.HTTPError as e:
            s = e.code
            if s in (429, 500, 502, 503, 529):
                print(f'llm_rate_limited model={model} code={s} attempt={attempt}', flush=True)
                time.sleep(min(30, max(5, attempt * attempt)))
                continue
            print(f'llm_fail model={model} code={s} attempt={attempt}', flush=True)
            return None
        except (urllib.error.URLError, OSError, KeyError, ValueError,
                json.JSONDecodeError) as e:
            print(f'llm_fail model={model} {type(e).__name__} attempt={attempt}', flush=True)
            return None
    print(f'llm_quota_exhausted model={model}', flush=True)
    return None


def wrap_llm(facts, body):
    lines = body.splitlines()
    title = None
    if lines and lines[0].lstrip().startswith('# '):
        title = lines[0].lstrip()[2:].strip()
        lines = lines[1:]
    if not title:
        title = (f"{facts['inst']} {facts['day']}: {facts['direction']} "
                 f"{facts['level']} setup ({facts['result']} {facts['r']:+.2f}R)")
    body = '\n'.join(l.rstrip() for l in lines).strip()
    L = []
    A = L.append
    A(f'# {title}')
    A('')
    A(f'> **Index:** {facts["inst"]} · **Session:** {facts["day"]} · '
      f'**Signal:** {facts["direction"].split()[0].upper()} at {facts["level"]} · '
      f'**Result:** {facts["result"]} ({facts["r"]:+.2f}R) · '
      f'**Note:** auto-drafted by LLM — curate and review before republishing')
    A('')
    A(body)
    A('')
    A('<sub>Generated by scripts/signal_articles.py (LLM narration on stored candles and the '
      'paper_align book). Hypothetical; no recommendation.</sub>')
    A('')
    return '\n'.join(L)


def candles(conn, inst, day):
    rows = conn.execute(
        f"SELECT timestamp, open, high, low, close FROM {CANDLE} "
        "WHERE instrument_id=? AND substr(timestamp,1,10)=? ORDER BY timestamp",
        (inst, day)).fetchall()
    out = []
    for r in rows:
        ts = (r['timestamp'] or '').replace(' ', 'T')[:16]
        out.append({'ts': ts, 'open': float(r['open']), 'high': float(r['high']),
                    'low': float(r['low']), 'close': float(r['close'])})
    return out


def excursions(cs, entry, exit_ts):
    hi = lo = None
    hi_t = lo_t = None
    for c in cs:
        if c['ts'] < entry:
            continue
        if exit_ts and c['ts'] > exit_ts:
            break
        if hi is None or c['high'] > hi:
            hi, hi_t = c['high'], c['ts']
        if lo is None or c['low'] < lo:
            lo, lo_t = c['low'], c['ts']
    return hi, hi_t, lo, lo_t


def fmt(ts):
    return (ts or '')[:16].replace('T', ' ')


def article(conn, s):
    inst, day, variant = s['instrument_id'], s['session_date'], s['variant']
    cs = candles(conn, inst, day)
    prev = prev_session_ohlc(conn, inst, day)
    if not prev:
        return None, 'no prev session'
    z = day_levels(prev['high'], prev['low'], prev['close'])
    pclose = float(prev['close'])
    width = (float(prev['high']) - float(prev['low'])) / pclose * 100
    regime = classify_cpr(width) or 'NORMAL'
    last = cs[-1]['close'] if cs else s['exit_price']
    o = cs[0]['open'] if cs else s['entry_price']
    day_hi = max(c['high'] for c in cs) if cs else pclose
    day_lo = min(c['low'] for c in cs) if cs else pclose
    move_down = (o - day_lo) / o * 100
    move_up = (day_hi - o) / o * 100
    drift = (last - pclose) / pclose * 100
    ent = fmt(s['entry_time'])[11:16]
    slot = 'open-drive' if ent == '09:20' else 'intraday'
    xo, xt, xl, lt = excursions(cs, 'T'.join(s['entry_time'].split()) if s['entry_time'] else None,
                                'T'.join(s['exit_time'].split())[:16] if s['exit_time'] else None)
    d = DIRS.get(s['direction'], s['direction'].lower())
    fav, fav_t = (xl, lt) if s['direction'] in ('BEAR', 'SHORT') else (xo, xt)
    adv, adv_t = (xo, xt) if s['direction'] in ('BEAR', 'SHORT') else (xl, lt)
    fav_gap = abs((fav - s['entry_price']) / s['entry_price']) * 100 if fav else 0
    adv_gap = abs((adv - s['entry_price']) / s['entry_price']) * 100 if adv else 0

    seed = f"{day}|{inst}|{variant}"
    title = f"{inst} {day}: a {d} {s['level']} setup that {'paid +%.2fR' % float(s['r_multiple']) if s['result'] == 'WIN' else 'hit its stop at -%.2fR' % -float(s['r_multiple']) if s['result'] == 'LOSS' else 'closed flat'}"
    bonus = float(s['r_multiple'] or 0)

    L = []
    A = L.append
    A(f'# {title}')
    A('')
    A(f'> **Index:** {inst} · **Session:** {day} · **Variant:** {variant} '
      f'({"all sessions" if variant == "plain" else "weekly CPR gate"}) · '
      f'**Signal:** {s["direction"]} at {s["level"]} · **Result:** {s["result"]} '
      f'({bonus:+.2f}R)')
    A('')
    A('<sub>Auto-drafted research note — curate and review before republishing. Not investment advice.</sub>')
    A('')
    A('## The setup')
    A('')
    A(pick(seed + '|setup1', [
        f'{inst} closed the prior session near {pclose:,.2f} after a {regime}-width day '
        f'({width:.2f}% swing), and the overnight tape framed the entry zone cleanly.',
        f'Coming in off the prior close of {pclose:,.2f}, the {regime} regime '
        f'({width:.2f}% range) left the reference levels tightly packed near the action.',
        f'A {regime} prior session closed {inst} at {pclose:,.2f}, and the levels that '
        f'mattered most were the {s["level"]} marker in play.',
    ]))
    A('')
    A(f'- Previous close: {pclose:,.2f}')
    line = ['- Day levels:']
    for k in ('pp', 'r1', 'r2', 'r3', 's1', 's2', 's3'):
        if z.get(k):
            line.append(f'{k.upper()} {z[k]:,.2f}')
    A(' '.join(line))
    A(f'- Prior range: {width:.2f}% (regime: {regime})')
    if variant == 'aligned':
        A(f'- Weekly gate: cleared (signal admitted under the aligned book).')
    else:
        A('- Weekly gate: none applied (plain book).')
    A('')
    A('## The session')
    A('')
    A(pick(seed + '|sess1', [
        f'Price opened at {o:,.2f} and the {d} thesis triggered at {fmt(s["entry_time"])} '
        f'({slot} entry, {s["level"]}), with the day subsequently traveling as low as '
        f'{day_lo:,.2f} and as high as {day_hi:,.2f}.',
        f'From an open of {o:,.2f}, the reference level {s["level"]} was reached in the '
        f'{slot} window; the session then ranged {day_lo:,.2f}–{day_hi:,.2f} before resolving.',
        f'The first move carried {inst} from {o:,.2f} toward {s["level"]}; that {d}-side '
        f'read was honored at {fmt(s["entry_time"])}, and the tape traded '
        f'{day_lo:,.2f}–{day_hi:,.2f} through the day.',
    ]))
    A('')
    if fmt(s["entry_time"]) != fmt(s["exit_time"]):
        A(f'- Entry: {fmt(s["entry_time"])} at {s["entry_price"]:,.2f} ({slot}, level {s["level"]})')
        A(f'- Unfavorable excursion: {adv_gap:+.2f}%'
          + (f' (to {adv:,.2f} at {fmt(adv_t)})' if adv else ''))
        A(f'- Favorable excursion: {fav_gap:+.2f}%'
          + (f' (to {fav:,.2f} at {fmt(fav_t)})' if fav else ''))
        A(f'- Exit: {fmt(s["exit_time"])} at {s["exit_price"]:,.2f} ({s["exit_reason"]})')
    A(f'- Day span: {day_lo:,.2f}–{day_hi:,.2f} · open-to-close drift from prior close: {drift:+.2f}%')
    A('')
    if s['exit_reason'] == 'TARGET':
        A(pick(seed + '|res1', [
            f'Risk ran {adv_gap:+.2f}% adverse before the target filled at '
            f'{s["exit_price"]:,.2f} — the move returned {bonus:+.2f}R without trailing much premium.',
            f'The target was booked at {s["exit_price"]:,.2f} for {bonus:+.2f}R; '
            f'intraday drift against the position peaked around {adv_gap:+.2f}%.',
            f'Target hit at {s["exit_price"]:,.2f}: {bonus:+.2f}R on a position that '
            f'dipped only {adv_gap:+.2f}% adverse first.',
        ]))
    elif s['exit_reason'] == 'STOP':
        A(pick(seed + '|res2', [
            f'The stop at {s["stop_price"]:,.2f} took the position out for {bonus:+.2f}R; '
            f'the favorable leg {fav_gap:+.2f}% did trigger but gave back before resolution.',
            f'{inst} never honored the {s["level"]} premise far enough — the stop filled '
            f'at {s["stop_price"]:,.2f} ({bonus:+.2f}R) after {fav_gap:+.2f}% of early wind.',
            f'An early {fav_gap:+.2f}% tail drew in the direction of the setup, but '
            f'rejection came quickly and the {s["exit_price"]:,.2f} stop closed it '
            f'at {bonus:+.2f}R.',
        ]))
    else:
        A(pick(seed + '|res3', [
            f'Carried to the flat open at {s["exit_price"]:,.2f}, the book booked '
            f'{bonus:+.2f}R without a stop fill; the favorable excursion reached '
            f'{fav_gap:+.2f}%.',
            f'No stop was tagged; the position drifted to the {s["exit_reason"]} mark at '
            f'{s["exit_price"]:,.2f} for {bonus:+.2f}R, with {fav_gap:+.2f}% of '
            f'daylight in its favor.',
            f'The trade closed at the day exit ({s["exit_price"]:,.2f}, {bonus:+.2f}R) '
            f'after the setup never made a clean target run.',
        ]))
    A('')
    A('## What this notes')
    A('')
    A(pick(seed + '|take1', [
        f'A {d} read at {s["level"]} inside a {regime} regime is that rare setup whose '
        f'edge shows in slip rather than speed: {bonus:+.2f}R for the session.',
        f'On {day}, the {s["level"]} trigger gave {inst} traders a definable '
        f'risk line; whether it pays is a matter of honoring the stop and the '
        f'day time window — this one landed at {bonus:+.2f}R.',
        f'The takeaway from {inst} on {day}: the {slot} reference {s["level"]} setup '
        f'produced {bonus:+.2f}R, this being useful only as an observation of a '
        f'rule in a single fixture.',
    ]))
    A('')
    A('<sub>Generated by scripts/signal_articles.py from stored candles and the paper_align book. '
      'Hypothetical; no recommendation.</sub>')
    A('')
    return '\n'.join(L), None


def vix_article(conn, s):
    """India VIX is not directly tradable; render it as a volatility /
    market-direction gauge rather than a position with entry, stop and R."""
    inst, day, variant = s['instrument_id'], s['session_date'], s['variant']
    cs = candles(conn, inst, day)
    prev = prev_session_ohlc(conn, inst, day)
    if not prev:
        return None, 'no prev session'
    z = day_levels(prev['high'], prev['low'], prev['close'])
    pclose = float(prev['close'])
    width = (float(prev['high']) - float(prev['low'])) / pclose * 100
    regime = classify_cpr(width) or 'NORMAL'
    o = cs[0]['open'] if cs else s['entry_price']
    last = cs[-1]['close'] if cs else pclose
    day_hi = max(c['high'] for c in cs) if cs else pclose
    day_lo = min(c['low'] for c in cs) if cs else pclose
    drift = (last - pclose) / pclose * 100
    turn, tone, ctx = vix_read(drift)
    seed = f"{day}|{inst}|{variant}"
    title = f"India VIX Log: {day} — volatility gauge, {tone}"

    L = []
    A = L.append
    A(f'# {title}')
    A('')
    A(f'> **Index:** India VIX · **Session:** {day} · **VIX move:** {drift:+.2f}% '
      f'({turn}) · **Market read:** {tone} — direction-neutral volatility backdrop. '
      f'India VIX is not a directly tradable index; it carries no equity-bias call '
      f'on its own.')
    A('')
    A('<sub>Auto-drafted research note — curate and review before republishing. Not investment advice.</sub>')
    A('')
    A('## The setup')
    A('')
    A(pick(seed + '|setup', [
        f'India VIX closed the prior session at {pclose:,.2f} after a {regime}-width day '
        f'({width:.2f}% swing). Volatility entered the {day} session around that reference, '
        f'with the pivot at {z.get("pp", pclose):,.2f}.',
        f'Coming off a prior close of {pclose:,.2f} and a {regime} range ({width:.2f}%), '
        f'India VIX opened the {day} session with its reference levels — '
        f'PP {z.get("pp", pclose):,.2f} — framing the volatility backdrop.',
    ]))
    A('')
    A(f'- Previous close: {pclose:,.2f}')
    line = ['- Day levels:']
    for k in ('pp', 'r1', 'r2', 'r3', 's1', 's2', 's3'):
        if z.get(k):
            line.append(f'{k.upper()} {z[k]:,.2f}')
    A(' '.join(line))
    A(f'- Prior range: {width:.2f}% (regime: {regime})')
    A('')
    A('## The session')
    A('')
    A(pick(seed + '|sess', [
        f'India VIX opened at {o:,.2f} and traded a {day_lo:,.2f}–{day_hi:,.2f} range, '
        f'finishing the session {turn} for a {drift:+.2f}% net move on the day.',
        f'From an open of {o:,.2f}, the volatility index ranged {day_lo:,.2f}–{day_hi:,.2f} '
        f'and closed the session {turn} ({drift:+.2f}% versus the prior close).',
    ]))
    A('')
    A(f'- Session span: {day_lo:,.2f}–{day_hi:,.2f}')
    A(f'- Net move vs prior close: {drift:+.2f}% ({turn})')
    A('')
    A('## Market direction read')
    A('')
    A(f'India VIX is an expected-volatility gauge, not a directional instrument. This '
      f'session showed a **{turn}** VIX ({drift:+.2f}%). {ctx}')
    A('')
    A(pick(seed + '|take', [
        f'Use VIX as a backdrop: expanding volatility warns of wide sessions, '
        f'contracting or flat volatility of quieter ones. Direction still comes from '
        f'price location (CPR / VWAP) and a confirmed trigger — VIX alone is not a '
        f'position.',
        f'The lesson from this book\'s history: flat VIX and intraday VIX reversals '
        f'correlate with weak follow-through; let price confirm before acting.',
    ]))
    A('')
    A('<sub>Generated by scripts/signal_articles.py from stored candles. India VIX is not '
      'tradable and is used here as a volatility backdrop only. Hypothetical; no '
      'recommendation.</sub>')
    A('')
    return '\n'.join(L), None


def learned_context(conn, s):
    """Checked facts from the loss-memory system: does this setup match a learned
    avoid-rule, and was this exact signal vetoed live? Returns an md block or None.
    Never invents a prediction — reports what the trained memory currently says."""
    inst, day, variant = s['instrument_id'], s['session_date'], s['variant']
    mem = lm.load_memory(variant)
    if not mem:
        return None
    prev = prev_session_ohlc(conn, inst, day)
    if not prev:
        return None
    pclose = float(prev['close'])
    width = (float(prev['high']) - float(prev['low'])) / pclose * 100
    regime = classify_cpr(width) or 'UNKNOWN'
    fp = {'instrument_id': inst, 'direction': s['direction'], 'level': s['level'],
          'regime': regime, 'dow': datetime.strptime(day, '%Y-%m-%d').strftime('%a'),
          'vix_dir': lm.vix_dir_for(conn, day, s.get('entry_time'))}
    matches = [r for r in lm.active_rules(mem)
               if all(fp.get(k) == v for k, v in r['keys'].items())]
    lines = []
    if matches:
        worst = min(matches, key=lambda r: r['total_r'])
        kd = ', '.join('%s=%s' % (k, v) for k, v in worst['keys'].items())
        lines.append(
            f"- Live loss-memory marks the fingerprint *{kd}*: n={worst['n']} "
            f"({worst['wins']}W/{worst['losses']}L, {worst['total_r']:+.2f}R, "
            f"{worst['reason']}) — the live guard would currently VETO this setup.")
    vl = f'{BASE}/data/mistake_veto_log.jsonl'
    if os.path.exists(vl):
        for line in open(vl, errors='ignore'):
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            tr = rec.get('trade') or {}
            if (rec.get('date') != day or rec.get('instrument') != inst
                    or tr.get('direction') != s['direction']
                    or (tr.get('scenario') or tr.get('level')) != s['level']):
                continue
            w = rec.get('verdict', {}).get('worst') or {}
            lines.append(
                f"- Live guard veto: this exact signal was vetoed live and logged "
                f"(n={w.get('n')}, {w.get('wins')}W/{w.get('losses')}L, "
                f"{w.get('total_r', 0.0):+.2f}R).")
            break
    if not lines:
        return None
    return '## Learned context\n\n' + '\n'.join(lines)


def append_context(art, ctx):
    if not ctx:
        return art
    i = art.rfind('<sub>Generated by')
    if i == -1:
        return art.rstrip() + '\n\n' + ctx + '\n'
    return art[:i].rstrip() + '\n\n' + ctx + '\n\n' + art[i:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--variant', default='plain', help='plain|aligned|all (default plain)')
    ap.add_argument('--instrument', default=None, help='NIFTY|BANKNIFTY|INDIA_VIX (default all)')
    ap.add_argument('--date', default=None, help='YYYY-MM-DD (default all)')
    ap.add_argument('--llm', action='store_true',
                    help='narrate with an LLM (key: $LLM_API_KEY or config/llm_key); '
                         'falls back to templates when unavailable')
    ap.add_argument('--llm-delay', type=float, default=0.0,
                    help='seconds to pause after each LLM attempt (rate-limit pacing)')
    args = ap.parse_args()
    variants = list(VARIANTS) if args.variant == 'all' else [args.variant]
    insts = [args.instrument] if args.instrument else list(INSTS)
    conn = get_conn()
    rows = conn.execute(
        "SELECT session_date, instrument_id, variant, direction, level, entry_time,"
        " entry_price, stop_price, target_price, exit_time, exit_price, exit_reason,"
        " r_multiple, result FROM paper_align WHERE state='SIGNAL'"
        " ORDER BY session_date").fetchall()
    wrote = 0
    llm_n = 0
    tpl_n = 0
    for r in rows:
        if r['variant'] not in variants or r['instrument_id'] not in insts:
            continue
        if args.date and r['session_date'] != args.date:
            continue
        art = None
        err = None
        vix = is_vix(r['instrument_id'])
        if args.llm and api_key() and not vix:
            f = _facts(conn, dict(r))
            if f:
                body = llm_narrate(f)
                if body:
                    art = wrap_llm(f, body)
                    llm_n += 1
            if args.llm_delay:
                time.sleep(args.llm_delay)
        if art is None:
            art, err = (vix_article if vix else article)(conn, dict(r))
            tpl_n += 1
        if err:
            print(f"skip {r['session_date']} {r['instrument_id']}: {err}", flush=True)
            continue
        if not vix:
            art = append_context(art, learned_context(conn, dict(r)))
        d = f"{BASE}/reports/signals/{r['variant']}"
        os.makedirs(d, exist_ok=True)
        fn = f"{d}/{r['session_date']}_{r['instrument_id']}_{r['direction']}_{r['level']}.md"
        open(fn, 'w').write(art + '\n')
        wrote += 1
    conn.close()
    rebuild_index()
    n_html = build_html()
    print(f"wrote {wrote} signal articles (llm={llm_n}, template={tpl_n}, html={n_html})", flush=True)


def rebuild_index():
    hub = {}
    for v in VARIANTS:
        d = f"{BASE}/reports/signals/{v}"
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith('.md'):
                continue
            p = os.path.join(d, fn)
            first = None
            exit_reason = None
            with open(p) as f:
                for line in f:
                    if line.startswith('# ') and first is None:
                        first = line[2:].strip()
                    if 'Result:' in line and exit_reason is None:
                        exit_reason = line.strip()
            hub.setdefault(v, []).append((fn, first, exit_reason))
    L = ['# Signal research notes', '',
         'Per-session, per-index research stories over the paper_align book. '
         'Auto-drafted; curate before republication.', '']
    for v in VARIANTS:
        L.append(f'## Book: {v}')
        L.append('')
        by_inst = {}
        for fn, t, res in hub.get(v, []):
            rest = fn[11:]
            inst = 'INDIA_VIX' if rest.startswith('INDIA_VIX_') else rest.split('_', 1)[0]
            by_inst.setdefault(inst, []).append((fn, t, res))
        for inst in INSTS:
            items = by_inst.get(inst) or []
            if not items:
                continue
            L.append(f'### {inst}')
            L.append('')
            for fn, t, res in items:
                res = res.replace('·', '|') if res else ''
                L.append(f'- [{t}]({v}/{fn}) — {res}')
            L.append('')
    with open(f"{BASE}/reports/signals/index.md", 'w') as f:
        f.write('\n'.join(L) + '\n')


STYLE = """
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#f1f5f9;color:#0f172a;line-height:1.6}
.topbar{background:#0b1e3a;color:#fff;padding:.6rem 1.2rem;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:.5rem}
.brand{font-size:1.4rem;font-weight:800}.brand .dot{color:#22d3ee}
.tagline{font-size:.85rem;color:#cbd5e1;margin-left:.8rem}
nav.main{background:#0b1e3a;color:#cbd5e1;border-top:1px solid #1e3a5f;padding:.5rem 1.2rem;display:flex;gap:1.5rem;justify-content:flex-end;font-size:.9rem;flex-wrap:wrap}
nav.main a{color:#cbd5e1;text-decoration:none}nav.main a.active,nav.main a:hover{color:#fff;border-bottom:2px solid #38bdf8;padding-bottom:2px}
.wrap{max-width:960px;margin:0 auto;padding:1.2rem}
h1{font-size:1.6rem;color:#0f172a;margin-bottom:.4rem}
h2{color:#0b1e3a;margin:1.4rem 0 .6rem;font-size:1.15rem}
h3{font-size:1rem;color:#0f172a}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:.9rem;margin:1rem 0}
.card{background:#fff;padding:1rem 1.1rem;border-radius:12px;border:1px solid #e2e8f0}
.card a{color:#0f172a;text-decoration:none;font-weight:600}.card a:hover{color:#2563eb}
.columns{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1rem;margin:1rem 0;align-items:start}
.col{background:#e9eef5;border-radius:12px;padding:.7rem .7rem .25rem}
.col h3{font-size:.95rem;color:#0b1e3a;margin:0 0 .5rem;padding-bottom:.4rem;border-bottom:2px solid #cbd5e1}
.col .muted{font-weight:400}
ul.notes{list-style:none}
ul.notes li{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:.55rem .7rem;margin-bottom:.5rem}
ul.notes li a{color:#0f172a;text-decoration:none;font-weight:600;font-size:.9rem}
ul.notes li a:hover{color:#2563eb}
ul.notes li .meta{margin-top:.25rem}
@media(max-width:760px){.columns{grid-template-columns:1fr}}
.meta{font-size:.8rem;color:#64748b;margin-top:.4rem}
.note{font-size:.8rem;color:#475569;margin-top:.6rem}
.muted{font-size:.8rem;color:#64748b}
blockquote{border-left:4px solid #38bdf8;background:#eaf5fd;padding:.5rem .9rem;margin:.6rem 0;border-radius:0 8px 8px 0;font-size:.85rem;color:#334155}
.prose p{margin:.5rem 0}
.prose ul{margin:.5rem 0 .5rem 1.4rem}
.prose code{background:#eef2f7;border:1px solid #e2e8f0;border-radius:4px;padding:0 .25rem;font-size:.85em}
.pill{font-size:.72rem;font-weight:700;padding:.1rem .5rem;border-radius:999px;background:#f8fafc;color:#334155;border:1px solid #e2e8f0}
.pill.win{background:#f0fdf4;color:#15803d;border-color:#bbf7d0}
.pill.loss{background:#fef2f2;color:#b91c1c;border-color:#fecaca}
.pill.flat{background:#f1f5f9;color:#64748b;border-color:#e2e8f0}
.crumb{font-size:.8rem;color:#64748b;margin-bottom:.6rem}.crumb a{color:#2563eb;text-decoration:none}
footer{background:#0b1e3a;color:#94a3b8;text-align:center;font-size:.75rem;padding:1rem;margin-top:1.2rem}
footer nav{display:flex;gap:.9rem;justify-content:center;flex-wrap:wrap;margin-bottom:.5rem}
footer a{color:#cbd5e1;text-decoration:none;font-size:.78rem}
"""

# AdSense loader (Auto Ads). See scripts/install_adsense.py.
ADS = ('<script async src="https://pagead2.googlesyndication.com/pagead/js/'
       'adsbygoogle.js?client=ca-pub-2262405054444130" crossorigin="anonymous"></script>\n')

NAV = ('<nav class="main" aria-label="Primary"><a href="/">Home</a>'
       '<a href="/indices/nifty.html">NIFTY Outlook</a>'
       '<a href="/nifty-intraday-dashboard.html">NIFTY Intraday</a>'
       '<a href="/indices/banknifty.html">BANKNIFTY Outlook</a>'
       '<a href="/backtest.html">Historical Analysis</a><a href="/tools.html">Tools</a>'
       '<a href="/learn.html">Learn</a><a href="/methodology.html">Methodology</a>'
       '<a href="/signals.html" class="active">Signal Notes</a></nav>')

FOOT = ('<footer><nav aria-label="Footer"><a href="/methodology.html">Methodology</a>'
        '<a href="/learn.html">Learn</a><a href="/tools.html">Tools</a>'
        '<a href="/disclaimer.html">Risk Disclosure</a><a href="/terms.html">Terms of Use</a>'
        '<a href="/privacy.html">Privacy Policy</a><a href="/contact.html">About</a></nav>'
        '<div>TradingAI.in · Educational market analytics · Not investment advice</div></footer>')


def _inline(md):
    t = md.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    t = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', t)
    t = re.sub(r'`(.+?)`', r'<code>\1</code>', t)
    t = re.sub(r'(?<!\*)\*([^*\n]+)\*(?!\*)', r'<em>\1</em>', t)
    return t


def md_html(text):
    out, buf, mode = [], [], None

    def flush():
        if mode == 'ul':
            out.append('<ul>' + ''.join('<li>' + _inline(x[2:].strip()) + '</li>'
                                        for x in buf) + '</ul>')
        elif mode == 'quote':
            out.append('<blockquote>' + '<br>'.join(_inline(x[2:].strip()) for x in buf)
                       + '</blockquote>')
        elif mode == 'p':
            out.append('<p>' + _inline(' '.join(x.strip() for x in buf)) + '</p>')

    for raw in text.splitlines():
        ln = raw.rstrip()
        if not ln:
            flush(); buf = []; mode = None; continue
        if ln.startswith('# '):
            flush(); buf = []; mode = None
            out.append('<h1>' + _inline(ln[2:].strip()) + '</h1>')
        elif ln.startswith('## '):
            flush(); buf = []; mode = None
            out.append('<h2>' + _inline(ln[3:].strip()) + '</h2>')
        elif ln.startswith('### '):
            flush(); buf = []; mode = None
            out.append('<h3>' + _inline(ln[4:].strip()) + '</h3>')
        elif ln.startswith('- '):
            if mode != 'ul':
                flush(); buf = []; mode = 'ul'
            buf.append(ln)
        elif ln.startswith('> '):
            if mode != 'quote':
                flush(); buf = []; mode = 'quote'
            buf.append(ln)
        elif ln.startswith('<sub>'):
            flush(); buf = []; mode = None
            out.append('<p class="muted">' + _inline(ln[5:].rstrip('</sub>')) + '</p>')
        else:
            if mode != 'p':
                flush(); buf = []; mode = 'p'
            buf.append(ln)
    flush()
    return '\n'.join(out)


def _txt(html):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html)).strip()


def page(inner, title, desc, canonical, jsonld=''):
    ld = f'<script type="application/ld+json">{jsonld}</script>\n' if jsonld else ''
    return ('<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="UTF-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
            f'<title>{title}</title>\n<meta name="description" content="{desc}">\n'
            f'<link rel="canonical" href="{canonical}">\n'
            '<meta property="og:type" content="website">\n'
            '<meta property="og:site_name" content="TradingAI.in">\n'
            f'<meta property="og:url" content="{canonical}">\n'
            f'<meta property="og:title" content="{title}">\n'
            f'<meta property="og:description" content="{desc}">\n'
            '<meta name="twitter:card" content="summary_large_image">\n'
            '<link rel="icon" type="image/svg+xml" href="/favicon.svg">\n' + ld +
            '<link rel="stylesheet" href="/tradingai-share.css?v=4">\n'
            f'<style>{STYLE}</style>\n{ADS}</head>\n<body>\n'
            '<div class="topbar"><span class="brand">Trading<span class="dot">AI</span>.in</span>'
            '<span class="tagline">Educational market analytics — not investment advice</span>'
            '</div>\n' + NAV + '\n<main class="wrap">\n' + inner + '\n</main>\n'
            + FOOT + '\n</body>\n</html>\n')


def build_html():
    """Bake every markdown note into the public site archive."""
    out_n = 0
    rows = {v: [] for v in VARIANTS}
    for v in VARIANTS:
        d, hdir = f'{BASE}/reports/signals/{v}', f'{BASE}/frontend/signals/{v}'
        os.makedirs(hdir, exist_ok=True)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith('.md'):
                continue
            md = open(os.path.join(d, fn), errors='ignore').read()
            md = md.replace(
                '<sub>Auto-drafted research note — curate and review before republishing. '
                'Not investment advice.</sub>\n', '')
            md = re.sub(r' · \*\*Note:\*\* auto-drafted[^\n]*', '', md)
            title = next((ln[2:].strip() for ln in md.splitlines()
                          if ln.startswith('# ')), fn[:-3])
            body_html = md_html(md)
            desc = _txt(body_html)[:158]
            date, stem = fn[:10], fn[:-3]
            canonical = f'https://tradingai.in/signals/{v}/{stem}.html'
            jsonld = json.dumps({
                '@context': 'https://schema.org', '@type': 'Article',
                'headline': title, 'datePublished': date, 'dateModified': date,
                'author': {'@type': 'Organization', 'name': 'TradingAI.in'},
                'mainEntityOfPage': canonical,
                'publisher': {'@type': 'Organization', 'name': 'TradingAI.in'},
                'description': desc, 'articleBody': _txt(body_html)}, ensure_ascii=False)
            inner = (f'<p class="crumb"><a href="/signals.html">Signal research notes</a> · '
                     f'{v} book · {date}</p>\n<article class="card prose">\n{body_html}\n'
                     '<p class="note">Auto-drafted from stored 5-minute candles and the '
                     'paper_align book. Historical and hypothetical — not investment advice.</p>\n'
                     '</article>\n')
            open(f'{hdir}/{stem}.html', 'w').write(
                page(inner, title + ' | TradingAI.in', desc, canonical, jsonld))
            m = re.search(r'Result:\**\s*(\w+)\s*\(([-+0-9.]+)R\)', md)
            rest = stem[11:]
            if rest.startswith('INDIA_VIX_'):
                inst, direction = 'INDIA_VIX', rest[len('INDIA_VIX_'):].split('_', 1)[0]
            else:
                inst = rest.split('_', 1)[0]
                direction = rest[len(inst) + 1:].split('_', 1)[0]
            rows[v].append({'stem': stem, 'title': title, 'date': date,
                            'inst': inst, 'vix': is_vix(inst), 'direction': direction,
                            'result': (m.group(1) if m else ''),
                            'r': (float(m.group(2)) if m else 0.0)})
            out_n += 1
    inner = ['<h1>Signal research notes</h1>',
             '<p>A per-session journal for NIFTY and BANKNIFTY as recorded in the '
             'hypothetical paper book, plus India VIX volatility notes. India VIX is '
             'not a tradable index — its notes are read only as a market-direction '
             'gauge. Notes are auto-drafted from stored 5-minute candles and the '
             'recorded signal; they are historical observations for study — not '
             'investment advice.</p>']
    for v in VARIANTS:
        tag = 'all sessions' if v == 'plain' else 'weekly CPR gate'
        inner.append(f'<h2 id="{v}">{v} book — {tag} ({len(rows[v])} notes)</h2>')
        cols = []
        for inst in INSTS:
            items = sorted((r for r in rows[v] if r['inst'] == inst),
                           key=lambda x: x['date'], reverse=True)
            lis = []
            for row in items:
                if row['vix']:
                    pills = '<span class="pill flat">market direction</span>'
                    meta = f'{row["date"]} · {pills} volatility backdrop'
                else:
                    rc = ('+' if row['r'] >= 0 else '') + f"{row['r']:.2f}R"
                    pills = (f'<span class="pill {row["result"].lower()}">{row["result"]}</span>'
                             if row['result'] else '')
                    meta = f'{row["date"]} · {pills} {rc}'
                lis.append(
                    f'<li><a href="/signals/{v}/{row["stem"]}.html">{row["title"]}</a>'
                    f'<div class="meta">{meta}</div></li>')
            if lis:
                cols.append(
                    f'<div class="col"><h3>{inst}'
                    f'<span class="muted"> · {len(lis)}</span></h3>'
                    f'<ul class="notes">{"".join(lis)}</ul></div>')
        inner.append('<div class="columns">' + ''.join(cols) + '</div>')
    inner.append('<p class="note">All sessions are back-tested observations on a hypothetical '
                 'paper book. Past results are not indicative of future performance. '
                 'Not investment advice.</p>')
    idx = page('\n'.join(inner), 'Signal Research Notes | TradingAI.in',
               'Per-session, per-index research notes for the hypothetical TradingAI paper book.',
               'https://tradingai.in/signals.html',
               json.dumps({'@context': 'https://schema.org', '@type': 'WebPage',
                           'name': 'Signal Research Notes | TradingAI.in',
                           'url': 'https://tradingai.in/signals.html'}, ensure_ascii=False))
    open(f'{BASE}/frontend/signals.html', 'w').write(idx)
    return out_n


if __name__ == '__main__':
    main()