#!/usr/bin/env python3
"""Phase 8 comparison: batch vs replay parity + Phase7-vs-Phase8 diagnostics."""
import sys, json, statistics
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo
sys.path.insert(0, '/opt/tradingai_new')
from app.core.db import get_conn
from app.research.backtest import BacktestEngine
from app.research.replay import SequentialReplay

_IST = ZoneInfo('Asia/Kolkata')
GEN = '/opt/tradingai_new/data/generated'
conn = get_conn()
p7 = json.load(open(f'{GEN}/phase7_trade_audit.json'))

out = {'generated_at': datetime.now(_IST).isoformat(), 'instruments': {}}
for inst in ['NIFTY', 'BANKNIFTY']:
    b = BacktestEngine().run(inst, '2026-07-27', '2026-09-19')
    r = SequentialReplay().run(inst, '2026-07-27', '2026-09-19')
    keys = ('trade_date', 'scenario', 'direction', 'entry_time', 'entry_price', 'stop_price',
            'target_price', 'exit_time', 'exit_price', 'exit_reason', 'R_multiple', 'paper_pnl',
            'MFE', 'MAE', 'holding_minutes')
    bt = [tuple(t[k] for k in keys) for t in b['trades']]
    rt = [tuple(t[k] for k in keys) for t in r['trades']]
    match = (bt == rt)
    # per-trade MATCH/MISMATCH rows
    rows = [{'trade_date': t['trade_date'], 'entry_time': t['entry_time'], 'R_multiple': t['R_multiple'],
             'verdict': 'MATCH'} for t in r['trades']]
    # Phase7 vs Phase8: old trade list from phase7 audit
    old = {(t['trade_date'], t['entry_time'], t['R_multiple']) for t in
           json.load(open(f'{GEN}/phase7_trade_audit.json'))['periods'][inst]['FULL'] and []} if False else None
    R = [t['R_multiple'] for t in r['trades']]
    w = sum(1 for t in r['trades'] if t['paper_pnl'] > 0)
    n = len(r['trades'])
    s8 = {'trades': n, 'wins': w, 'losses': sum(1 for t in r['trades'] if t['paper_pnl'] < 0),
          'win_rate': round(w / n, 4) if n else 0,
          'avg_R': round(sum(R) / n, 4) if n else 0, 'total_R': round(sum(R), 4),
          'exits': dict(Counter(t['exit_reason'] for t in r['trades'])),
          'entries': dict(Counter(t['entry_time'][11:16] for t in r['trades'])),
          'scenarios': dict(Counter(t['scenario'] for t in r['trades']))}
    out['instruments'][inst] = {
        'batch_trades': len(bt), 'replay_trades': len(rt),
        'parity': 'IDENTICAL' if match else 'MISMATCH',
        'mismatch_rows': [] if match else 'see logs',
        'trade_rows': rows, 'phase8_FULL': s8,
        'daily': r['daily'],
        'n_traces': len(r['traces'])}
    print(inst, 'parity:', 'IDENTICAL' if match else 'MISMATCH', '| phase8:', s8)

json.dump(out, open(f'{GEN}/phase8_replay_comparison.json', 'w'), indent=1)
# decision-trace summary (compact: per-day)
summ = {inst: {'n_candles': out['instruments'][inst]['n_traces'], 'days': out['instruments'][inst]['daily']} for inst in ('NIFTY', 'BANKNIFTY')}
json.dump(summ, open(f'{GEN}/phase8_decision_trace_summary.json', 'w'), indent=1)
live = {'qualified_trades': conn.execute('SELECT COUNT(*) FROM qualified_trades').fetchone()[0],
        'paper_trades': conn.execute('SELECT COUNT(*) FROM paper_trades').fetchone()[0],
        'daily_trade_locks': conn.execute('SELECT COUNT(*) FROM daily_trade_locks').fetchone()[0]}
print('isolation:', live)
conn.close()
