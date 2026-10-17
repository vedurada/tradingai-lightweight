#!/usr/bin/env python3
"""Engine walk-forward self-evaluation (READ-ONLY).

Question it answers: does the shipped build (base CPR book + BREAKOUT add-on)
hold up out-of-sample, or is it an in-sample artifact?

Method (strictly no lookahead): split the available sessions into K contiguous
blocks. For every block run run_opens_range over ONLY that block's dates, for
each engine configuration in turn:

  BASE     NO_CHASE_BEAR=False, BREAKOUT_ADDON=False   (plain CPR book)
  REANCHOR NO_CHASE_BEAR=True,  BREAKOUT_ADDON=False   (directional re-anchor)
  SHIPPED  NO_CHASE_BEAR=False, BREAKOUT_ADDON=True    (the build under test)

Each block's totals are a genuine out-of-sample step (no cross-block leakage;
levels are always rebuilt from the previous session). The flags are toggled
in-process only — the DB, engine file and live path are never touched.

Read-only. Writes one markdown report.

  python3 scripts/engine_walkforward.py                 # 8 blocks
  python3 scripts/engine_walkforward.py --blocks 12
  python3 scripts/engine_walkforward.py --days 180
"""
import argparse
import os
import sys
from collections import OrderedDict
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, '/opt/tradingai')

from app.core.db import get_conn
from app.research import cpr_trigger_engine as eng

BASE = '/opt/tradingai'
IST = ZoneInfo('Asia/Kolkata')

CONFIGS = OrderedDict([
    ('BASE',   (False, False)),
    ('REANCHOR', (True,  False)),
    ('SHIPPED', (False, True)),
])


def session_dates(conn, inst, start, end):
    return [r[0] for r in conn.execute(
        'SELECT DISTINCT substr(timestamp,1,10) FROM market_candles_5m '
        'WHERE instrument_id=? AND substr(timestamp,1,10) BETWEEN ? AND ? ORDER BY 1',
        (inst, start, end)).fetchall()]


def blocks(dates, k):
    """Contiguous, near-equal chunks of the session list."""
    if not dates or k <= 0:
        return []
    size = max(1, len(dates) // k)
    out, i = [], 0
    while i < len(dates):
        out.append((dates[i], dates[min(i + size, len(dates)) - 1]))
        i += size
    return out


def run_block(inst, d0, d1, nc_bear, brk):
    old_nc, old_brk = eng.NO_CHASE_BEAR, eng.BREAKOUT_ADDON
    eng.NO_CHASE_BEAR, eng.BREAKOUT_ADDON = nc_bear, brk
    try:
        return eng.run_opens_range(inst, d0, d1, 'plain')
    finally:
        eng.NO_CHASE_BEAR, eng.BREAKOUT_ADDON = old_nc, old_brk


def block_line(r):
    n = r.get('signals', 0)
    wins = r.get('wins', 0)
    wr = (wins / n * 100) if n else 0.0
    adds = sum(1 for t in r.get('trades', []) if t.get('level', '').startswith('BRK_'))
    return n, wr, r.get('total_R', 0.0), r.get('net_R', 0.0), adds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=0,
                    help='only the last N sessions (default: all)')
    ap.add_argument('--blocks', type=int, default=8)
    ap.add_argument('--out', default='')
    a = ap.parse_args()

    insts = ['NIFTY', 'BANKNIFTY']
    conn = get_conn()
    all_dates = session_dates(conn, insts[0], '2000-01-01', '2100-01-01')
    if a.days:
        all_dates = all_dates[-a.days:]
    d0, d1 = all_dates[0], all_dates[-1]
    blks = blocks(all_dates, a.blocks)
    conn.close()

    now = datetime.now(IST).strftime('%Y-%m-%d')
    out = a.out or os.path.join(BASE, 'reports', 'engine_walkforward_%s.md' % now)

    L = []
    L.append('# Engine walk-forward self-evaluation')
    L.append('')
    L.append('Generated %s IST (read-only).' % datetime.now(IST).strftime('%Y-%m-%d %H:%M'))
    L.append('')
    L.append('Window **%s .. %s** (%d sessions), split into **%d contiguous blocks**.' %
             (d0, d1, len(all_dates), len(blks)))
    L.append('')
    L.append('Each block is an out-of-sample step: levels are rebuilt from the '
             'previous session, and only that block\'s dates are replayed.')
    L.append('')
    L.append('| config | NO_CHASE_BEAR | BREAKOUT_ADDON |')
    L.append('| --- | --- | --- |')
    for name, (nc, brk) in CONFIGS.items():
        L.append('| %s | %s | %s |' % (name, nc, brk))
    L.append('')

    for inst in insts:
        L.append('## %s' % inst)
        L.append('')
        L.append('| block | %s | REANCHOR | SHIPPED |' % 'BASE')
        L.append('| --- | --- | --- | --- |')
        tot = {c: {'n': 0, 'wins': 0, 'R': 0.0, 'adds': 0} for c in CONFIGS}
        for bi, (b0, b1) in enumerate(blks, 1):
            cells = []
            for name, (nc, brk) in CONFIGS.items():
                r = run_block(inst, b0, b1, nc, brk)
                n, wr, R, net, adds = block_line(r)
                tot[name]['n'] += n
                tot[name]['wins'] += r.get('wins', 0)
                tot[name]['R'] += R
                tot[name]['adds'] += adds
                cells.append('n=%d WR=%.0f%% %.1fR' % (n, wr, R))
            L.append('| %d | %s | %s | %s |' % (bi, cells[0], cells[1], cells[2]))
        L.append('')
        L.append('**%s totals**' % inst)
        L.append('')
        L.append('| config | trades | WR | total_R | breakout adds |')
        L.append('| --- | --- | --- | --- | --- |')
        for name in CONFIGS:
            t = tot[name]
            wr = (t['wins'] / t['n'] * 100) if t['n'] else 0.0
            L.append('| %s | %d | %.1f%% | %.2f | %d |' %
                     (name, t['n'], wr, t['R'], t['adds']))
        L.append('')
        win = max(CONFIGS, key=lambda c: tot[c]['R'])
        L.append('**Best total_R: %s (%.2fR)** over this window.' % (win, tot[win]['R']))
        L.append('')

    L.append('## Reading this')
    L.append('')
    L.append('- *BASE* is the plain CPR book (SHORT_ONLY, next-open entries).')
    L.append('- *REANCHOR* is the directional no-chase re-anchor (gated OFF in the build).')
    L.append('- *SHIPPED* is the build under test: BASE plus the BREAKOUT add-on '
             '(a fresh close-cross on a base-flat session; a Friday BULL upside-'
             'breakout may fire).')
    L.append('- The breakout add-on is a small, thin add-on (~6 trades/instrument '
             'over this window, mostly Friday BULL). Re-validate on live paper '
             'data before trusting the increment in production.')
    L.append('')

    with open(out, 'w') as f:
        f.write('\n'.join(L) + '\n')
    print('wrote %s' % out)


if __name__ == '__main__':
    main()
