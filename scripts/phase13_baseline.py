#!/usr/bin/env python3
"""Phase 13: generate validated research baseline snapshots.

Runs the authoritative BacktestEngine over session-derived periods and writes
read-only product snapshots to app/research/baseline_<INST>_<PERIOD>.json
(committed app data, served by GET /api/research/baseline — no per-request
engine runs, no live-table writes, fasthttp responses).

STOPS (non-zero exit) if the validated baselines drift:
  NIFTY FULL: 34 trades / +16.21R | BANKNIFTY FULL: 31 / +16.63R
"""
import sys, json, statistics
from collections import Counter
sys.path.insert(0, '/opt/tradingai')
from app.core.db import get_conn
from app.research.backtest import BacktestEngine

OUT = '/opt/tradingai/app/research/baseline_{inst}_{period}.json'
DAY_END = 'T23:59:59+05:30'

conn = get_conn()
days = [r[0] for r in conn.execute(
    'SELECT DISTINCT substr(timestamp,1,10) FROM market_candles_5m ORDER BY 1').fetchall()]
ncandles = conn.execute('SELECT COUNT(*) FROM market_candles_5m').fetchone()[0]
PERIODS = {'FULL': days, '30D': days[-30:], '7D': days[-7:]}
print('sessions:', len(days), days[0], '->', days[-1], '| candles:', ncandles)

EXPECTED = {('NIFTY', 'FULL'): (34, 16.21), ('BANKNIFTY', 'FULL'): (31, 16.63)}
fail = False

for inst in ('NIFTY', 'BANKNIFTY'):
    for period, ds in PERIODS.items():
        eng = BacktestEngine()
        res = eng.run(inst, ds[0], ds[-1] + DAY_END)
        tr = res['trades']
        R = [t['R_multiple'] for t in tr]
        wins = [t for t in tr if t['paper_pnl'] > 0]
        losses = [t for t in tr if t['paper_pnl'] < 0]
        bes = [t for t in tr if t['paper_pnl'] == 0]
        n = len(tr)
        lim_rej = sum(1 for d in res['decisions']
                      if 'DAILY_TRADE_LIMIT_REACHED' in (d.get('reasons') or []))
        traded_days = sorted({t['trade_date'] for t in tr})
        n_cand = conn.execute(
            'SELECT COUNT(*) FROM scenario_candidates WHERE instrument_id=? '
            'AND substr(created_at,1,10) BETWEEN ? AND ?', (inst, ds[0], ds[-1])).fetchone()[0]
        n_match = conn.execute(
            'SELECT COUNT(*) FROM scenario_matches WHERE instrument_id=? '
            'AND substr(timestamp,1,10) BETWEEN ? AND ?', (inst, ds[0], ds[-1])).fetchone()[0]
        snap = {
            'instrument': inst, 'period': period,
            'dataset': {'start': ds[0], 'end': ds[-1], 'sessions': len(ds),
                        'sessions_total': len(days)},
            'summary': {
                'trades': n, 'wins': len(wins), 'losses': len(losses),
                'breakeven': len(bes),
                'win_rate': round(len(wins) / n, 4) if n else 0,
                'total_R': round(sum(R), 2) if n else 0,
                'avg_R': round(sum(R) / n, 4) if n else 0,
                'median_R': round(statistics.median(R), 4) if n else 0,
                'min_R': min(R) if n else 0, 'max_R': max(R) if n else 0,
                'avg_risk_points': round(sum(t['risk_points'] for t in tr) / n, 2) if n else 0,
                'avg_mfe': round(sum(t['MFE'] for t in tr) / n, 2) if n else 0,
                'avg_mae': round(sum(t['MAE'] for t in tr) / n, 2) if n else 0,
                'avg_holding_min': round(sum(t['holding_minutes'] for t in tr) / n, 1) if n else 0,
                'exits': dict(Counter(t['exit_reason'] for t in tr)),
            },
            'one_trade_day': {
                'max_per_day': 1, 'sessions_evaluated': len(ds),
                'sessions_with_trade': len(traded_days),
                'sessions_without_trade': len(ds) - len(traded_days),
                'limit_rejections': lim_rej,
            },
            'pipeline': {'candidates': n_cand, 'matches': n_match,
                         'qualified_trades': n},
            'trades': [dict({k: t[k] for k in (
                'trade_date', 'instrument', 'entry_time', 'scenario', 'direction',
                'entry_price', 'stop_price', 'target_price', 'exit_time',
                'exit_price', 'exit_reason', 'R_multiple', 'MFE', 'MAE',
                'holding_minutes', 'risk_points', 'reward_points')},
                result=('WIN' if t['paper_pnl'] > 0 else ('LOSS' if t['paper_pnl'] < 0 else 'BE')))
                for t in tr],
        }
        json.dump(snap, open(OUT.format(inst=inst, period=period), 'w'), indent=1)
        key = (inst, period)
        if key in EXPECTED and (n, snap['summary']['total_R']) != EXPECTED[key]:
            print(f'DRIFT {inst} {period}: got {(n, snap["summary"]["total_R"])} '
                  f'want {EXPECTED[key]}')
            fail = True
        print(inst, period, n, snap['summary']['total_R'], 'sessions', len(ds))
conn.close()
sys.exit(1 if fail else 0)
