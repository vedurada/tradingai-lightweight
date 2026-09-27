#!/usr/bin/env python3
"""Weekly learning review (READ-ONLY analysis, never touches live logic).

Reads paper_align (aligned book) + stored candles, writes one markdown
report to reports/weekly_review_YYYY-MM-DD.md. Run: python3 scripts/weekly_review.py
Suggested cron (not installed): 30 8 * * 0 cd /opt/tradingai && python3 scripts/weekly_review.py
"""
import sqlite3, os
from datetime import datetime
from zoneinfo import ZoneInfo
from collections import defaultdict

BASE = '/opt/tradingai'
IST = ZoneInfo('Asia/Kolkata')
import sys
sys.path.insert(0, BASE)
from app.core.db import get_conn
from app.research.cpr_strategy_engine import calculate_cpr, classify_cpr

INSTS = ('NIFTY', 'BANKNIFTY')


def width_of(conn, inst, day):
    r = conn.execute(
        'SELECT MAX(high) h, MIN(low) l FROM market_candles_5m WHERE instrument_id=? '
        'AND substr(timestamp,1,10)=(SELECT MAX(substr(timestamp,1,10)) FROM market_candles_5m '
        'WHERE instrument_id=? AND substr(timestamp,1,10)<?)', (inst, inst, day)).fetchone()
    if not r or r['h'] is None:
        return None, None
    last = conn.execute(
        'SELECT close FROM market_candles_5m WHERE instrument_id=? AND substr(timestamp,1,10)='
        '(SELECT MAX(substr(timestamp,1,10)) FROM market_candles_5m WHERE instrument_id=? '
        'AND substr(timestamp,1,10)<?) ORDER BY timestamp DESC LIMIT 1', (inst, inst, day)).fetchone()
    cpr = calculate_cpr(float(r['h']), float(r['l']), float(last['close']))
    return cpr['width_pct'], cpr['bc']


def main():
    conn = get_conn()
    rows = conn.execute(
        "SELECT session_date, instrument_id, direction, level, entry_price, exit_price,"
        " entry_time, exit_reason, r_multiple, result FROM paper_align"
        " WHERE variant='aligned' AND state='SIGNAL' AND instrument_id IN ('NIFTY','BANKNIFTY')"
        " ORDER BY session_date").fetchall()
    recs = [dict(r) for r in rows]
    for t in recs:
        w, bc = width_of(conn, t['instrument_id'], t['session_date'])
        t['width'] = w
        t['regime'] = classify_cpr(w) if w is not None else 'UNKNOWN'
        try:
            t['dist_bc'] = (float(t['entry_price']) - bc) / bc * 100
        except (TypeError, ValueError):
            t['dist_bc'] = None
        t['slot'] = 'OPEN-DRIVE' if str(t.get('entry_time') or '')[11:16] == '09:20' else 'INTRADAY'
        t['dow'] = datetime.strptime(t['session_date'], '%Y-%m-%d').strftime('%a')
    conn.close()

    L = []
    A = lambda s: L.append(s)
    today = datetime.now(IST).strftime('%Y-%m-%d')
    A(f'# Weekly learning review — {today}')
    A('_Aligned CPR book, NIFTY+BANKNIFTY. Read-only; suggestions need owner approval._\n')

    def summ(ts, name):
        n = len(ts)
        w = sum(1 for t in ts if t['result'] == 'WIN')
        l = sum(1 for t in ts if t['result'] == 'LOSS')
        r = round(sum(float(t['r_multiple'] or 0) for t in ts), 2)
        wr = round(100 * w / n, 1) if n else 0.0
        return f'| {name} | {n} | {w} | {l} | {wr}% | {r:+.2f}R |'

    A('| Scope | n | W | L | Win% | R |')
    A('|---|---|---|---|---|---|')
    A(summ(recs, 'ALL'))
    for inst in INSTS:
        A(summ([t for t in recs if t['instrument_id'] == inst], inst))
    A('')
    A('| Slice | n | W | L | Win% | R |')
    A('|---|---|---|---|---|---|')
    for key in ('direction', 'level', 'regime', 'slot', 'dow'):
        groups = defaultdict(list)
        for t in recs:
            groups[t[key]].append(t)
        for g in sorted(groups, key=str):
            A(summ(groups[g], f'{key}={g}'))
    A('')
    stops = sum(1 for t in recs if t['result'] == 'LOSS' and t['exit_reason'] == 'STOP')
    eods = sum(1 for t in recs if t['result'] == 'LOSS' and t['exit_reason'] != 'STOP')
    dec = sum(1 for t in recs if t['result'] == 'WIN' and float(t['r_multiple'] or 0) < 0)
    A(f'Loss anatomy: STOP={stops} EOD-drift={eods}; decay-booked wins (raw-negative): {dec}.')
    # current streak
    streak, last = 0, None
    for t in reversed(recs):
        r = 'W' if t['result'] == 'WIN' else 'L'
        if last is None:
            last, streak = r, 1
        elif r == last:
            streak += 1
        else:
            break
    A(f'Current streak: {streak}x {last}.')
    A('')
    A('## Candidate improvements (suggestions only — no auto-apply)')
    base_wr = sum(1 for t in recs if t['result'] == 'WIN') / max(len(recs), 1)
    cands = [
        ('BELOW_CPR + NARROW regime', [t for t in recs if t['level'] == 'BELOW_CPR' and t['regime'] == 'NARROW']),
        ('BELOW_CPR OPEN-DRIVE entries', [t for t in recs if t['level'] == 'BELOW_CPR' and t['slot'] == 'OPEN-DRIVE']),
        ('ABOVE_CPR OPEN-DRIVE entries', [t for t in recs if t['level'] == 'ABOVE_CPR' and t['slot'] == 'OPEN-DRIVE']),
        ('R1/R2/PDH touch bears', [t for t in recs if t['direction'] == 'BEAR' and t['level'] in ('R1', 'R2', 'PDH')]),
        ('WIDE-regime trades', [t for t in recs if t['regime'] == 'WIDE']),
    ]
    for name, ts in cands:
        n = len(ts)
        if n < 5:
            A(f'- {name}: n={n} (too small — watch, no action).')
            continue
        w = sum(1 for t in ts if t['result'] == 'WIN')
        wr = 100 * w / n
        flag = 'UNDERPERFORMS' if wr < base_wr * 100 - 5 else ('OUTPERFORMS' if wr > base_wr * 100 + 5 else 'in line')
        A(f'- {name}: {w}W/{n - w}L ({wr:.0f}%) vs book {base_wr * 100:.0f}% — {flag}.')
    A('')
    A('_Generated by scripts/weekly_review.py. Thresholds fixed; this file only observes._')
    os.makedirs(f'{BASE}/reports', exist_ok=True)
    out = f"{BASE}/reports/weekly_review_{today}.md"
    open(out, 'w').write('\n'.join(L) + '\n')
    print('\n'.join(L[:14]))
    print(f'... wrote {out}')


if __name__ == '__main__':
    main()
