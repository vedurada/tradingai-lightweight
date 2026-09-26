#!/usr/bin/env python3
"""Phase 8 summary: old-vs-new FULL diagnostics + 30D/7D windows + isolation.

- OLD = pre-Phase-8 global-latest qualification path (as_of=None), mirroring
  the Phase 7 engine, run over the same candles for before/after diagnostics.
- NEW = point-in-time path (batch backtest + sequential replay).
- Writes data/generated/phase8_point_in_time_summary.json (spec section 19).
- Phase 7 official artifacts are never modified; results are compared only.
"""
import sys, json, uuid, statistics
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo
sys.path.insert(0, '/opt/tradingai_new')
from app.core.db import get_conn
from app.research.backtest import BacktestEngine, IntradayExitEngine
from app.research.replay import SequentialReplay
from app.core.qualification import QualificationEngine

_IST = ZoneInfo('Asia/Kolkata')
GEN = '/opt/tradingai_new/data/generated'
FULL_START, FULL_END = '2026-07-27', '2026-09-19'  # end bound is exclusive-ish (lexicographic BETWEEN)


def sessions():
    conn = get_conn()
    days = [r[0] for r in conn.execute(
        'SELECT DISTINCT substr(timestamp,1,10) FROM market_candles_5m ORDER BY 1').fetchall()]
    conn.close()
    return days


def old_global_latest_run(instrument, start, end):
    """Faithful replica of the pre-Phase-8 path: qualify() with no as_of."""
    conn = get_conn()
    q = QualificationEngine()
    q.reset_research_locks()
    candles = [dict(c) for c in conn.execute(
        'SELECT * FROM market_candles_5m WHERE instrument_id=? AND timestamp BETWEEN ? AND ? ORDER BY timestamp',
        (instrument, start, end)).fetchall()]
    ex = IntradayExitEngine()
    trades = []
    for i, candle in enumerate(candles):
        day = candle['timestamp'][:10]
        ms = {'trend': 'BULLISH', 'vwap_relation': 'ABOVE', 'momentum': 'POSITIVE',
              'volatility': 'NORMAL', 'price': candle['close']}
        d = q.qualify(instrument, ms, options_valid=True, research=True, trade_date=day)
        if d['decision'] != 'QUALIFIED_TRADE':
            continue
        td = d['trade'] or {}
        entry, stop, target = round(td.get('entry', candle['close']), 2), round(td.get('stop', 0), 2), round(td.get('target', 0), 2)
        after = [c for c in candles[i + 1:] if c['timestamp'][:10] == day]
        xt, xp, reason, mfe, mae = ex.find_exit(
            {'entry_price': entry, 'stop_price': stop, 'target_price': target,
             'direction': 'LONG', 'entry_time': candle['timestamp']}, after)
        risk = abs(entry - stop) or 1
        trades.append({'trade_date': day, 'entry_time': candle['timestamp'], 'entry_price': entry,
                       'stop_price': stop, 'target_price': target, 'exit_time': xt,
                       'exit_price': round(xp, 2), 'exit_reason': reason,
                       'R_multiple': round((xp - entry) / risk, 2), 'paper_pnl': round((xp - entry) * 50, 2)})
    conn.close()
    return trades


def stats(trades):
    R = [t['R_multiple'] for t in trades]
    n = len(trades)
    return {'trades': n, 'wins': sum(1 for t in trades if t['paper_pnl'] > 0),
            'losses': sum(1 for t in trades if t['paper_pnl'] < 0),
            'win_rate': round(sum(1 for t in trades if t['paper_pnl'] > 0) / n, 4) if n else 0,
            'avg_R': round(sum(R) / n, 4) if n else 0,
            'median_R': round(statistics.median(R), 4) if n else 0,
            'total_R': round(sum(R), 4) if n else 0,
            'min_R': min(R) if n else 0, 'max_R': max(R) if n else 0,
            'exits': dict(Counter(t['exit_reason'] for t in trades))}


DAYS = sessions()
WINDOWS = {'FULL': DAYS, '30D': DAYS[-30:], '7D': DAYS[-7:]}
print('sessions:', len(DAYS), DAYS[0], '->', DAYS[-1], '| 90D: only', len(DAYS), 'sessions available, not fabricated')

conn = get_conn()
live_before = [tuple(conn.execute(
    'SELECT (SELECT COUNT(*) FROM qualified_trades),(SELECT COUNT(*) FROM paper_trades),(SELECT COUNT(*) FROM daily_trade_locks)').fetchone())]
conn.close()

out = {'generated_at': datetime.now(_IST).isoformat(),
       'data_period': {'sessions': len(DAYS), 'start': DAYS[0], 'end': DAYS[-1],
                       'note_90D': 'dataset spans 39 sessions only; no 90D window fabricated'},
       'windows': {}, 'before_after': {}, 'isolation': {}}

for inst in ('NIFTY', 'BANKNIFTY'):
    out['windows'][inst] = {}
    for w, days in WINDOWS.items():
        b = BacktestEngine().run(inst, days[0], days[-1] + 'T23:59:59+05:30')
        r = SequentialReplay().run(inst, days[0], days[-1] + 'T23:59:59+05:30')
        keys = ('trade_date', 'scenario', 'direction', 'entry_time', 'entry_price', 'stop_price',
                'target_price', 'exit_time', 'exit_price', 'exit_reason', 'R_multiple')
        parity = ([tuple(t[k] for k in keys) for t in b['trades']] ==
                  [tuple(t[k] for k in keys) for t in r['trades']])
        out['windows'][inst][w] = {'period': [days[0], days[-1]], 'sessions': len(days),
                                   'batch_replay_parity': 'IDENTICAL' if parity else 'MISMATCH',
                                   'stats': stats(r['trades'])}
        print(inst, w, 'parity:', 'IDENTICAL' if parity else 'MISMATCH', out['windows'][inst][w]['stats'])
    # before/after FULL diagnostics
    old = old_global_latest_run(inst, FULL_START, FULL_END)
    new = SequentialReplay().run(inst, FULL_START, FULL_END)['trades']
    old_keys = {(t['trade_date'], t['entry_time']) for t in old}
    new_keys = {(t['trade_date'], t['entry_time']) for t in new}
    out['before_after'][inst] = {
        'old_global_latest': stats(old), 'new_point_in_time': stats(new),
        'trades_only_in_old': sorted(old_keys - new_keys),
        'trades_only_in_new': sorted(new_keys - old_keys),
        'n_common': len(old_keys & new_keys)}
    print(inst, 'OLD:', stats(old))
    print(inst, 'NEW:', stats(new))

conn = get_conn()
live_after = tuple(conn.execute(
    'SELECT (SELECT COUNT(*) FROM qualified_trades),(SELECT COUNT(*) FROM paper_trades),(SELECT COUNT(*) FROM daily_trade_locks)').fetchone())
conn.close()
out['isolation'] = {'live_counts_before': list(live_before[0]), 'live_counts_after': list(live_after),
                    'verdict': 'PASS' if live_before[0] == live_after == (0, 0, 0) else 'FAIL'}
print('isolation:', out['isolation'])
json.dump(out, open(f'{GEN}/phase8_point_in_time_summary.json', 'w'), indent=1)
print('wrote phase8_point_in_time_summary.json')
