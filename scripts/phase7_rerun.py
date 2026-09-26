#!/usr/bin/env python3
"""Phase 7: rerun 7D/30D/90D/FULL on CORRECTED engine; emit phase7 JSONs.
Official corrected results + diagnostics (distribution, outliers, risk)."""
import sys, json, os, statistics
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo
sys.path.insert(0, '/opt/tradingai_new')
from app.core.db import get_conn
from app.research.backtest import BacktestEngine

_IST = ZoneInfo('Asia/Kolkata')
GEN = '/opt/tradingai_new/data/generated'
conn = get_conn()
eng = BacktestEngine()

def sessions(inst, d0, d1):
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT substr(timestamp,1,10) FROM market_candles_5m WHERE instrument_id=? "
        "AND substr(timestamp,1,10) BETWEEN ? AND ? ORDER BY 1", (inst, d0, d1)).fetchall()]

all_sess = sessions('NIFTY', '2026-01-01', '2026-12-31')
periods = {'7D': (all_sess[-7], all_sess[-1]), '30D': (all_sess[-30], all_sess[-1]),
           '90D': ('2026-06-21', '2026-09-19'), 'FULL': ('2026-07-27', '2026-09-19')}
Q = ('2026-07-27', '2026-09-18')

def pct(xs, p):
    xs = sorted(xs)
    if not xs: return 0.0
    k = (len(xs) - 1) * p / 100
    f, c = int(k), min(int(k) + 1, len(xs) - 1)
    return round(xs[f] + (xs[c] - xs[f]) * (k - f), 4)

def summarize(trades, decisions, sess_list):
    n = len(trades)
    w = sum(1 for t in trades if t['paper_pnl'] > 0)
    l = sum(1 for t in trades if t['paper_pnl'] < 0)
    ex = Counter(t['exit_reason'] for t in trades)
    R = [t['R_multiple'] for t in trades]; H = [t['holding_minutes'] for t in trades]
    MFE = [t['MFE'] for t in trades]; MAE = [t['MAE'] for t in trades]
    risks = [abs(t['entry_price'] - t['stop_price']) for t in trades]
    per_day = Counter(t['trade_date'] for t in trades)
    return {
        'sessions': len(sess_list), 'qualification_attempts': len(decisions),
        'qualified_trades': n, 'completed_trades': n, 'wins': w, 'losses': l, 'breakeven': n - w - l,
        'win_rate': round(w / n, 4) if n else 0.0,
        'exits': {k: ex.get(k, 0) for k in ('EOD', 'TARGET', 'STOP', 'AMBIGUOUS_INTRABAR', 'SCENARIO_INVALIDATION')},
        'avg_R': round(statistics.mean(R), 4) if R else 0.0,
        'median_R': round(statistics.median(R), 4) if R else 0.0,
        'total_R': round(sum(R), 4) if R else 0.0,
        'min_R': round(min(R), 4) if R else 0.0, 'max_R': round(max(R), 4) if R else 0.0,
        'p10_R': pct(R, 10), 'p25_R': pct(R, 25), 'p75_R': pct(R, 75), 'p90_R': pct(R, 90),
        'stdev_R': round(statistics.stdev(R), 4) if len(R) > 1 else 0.0,
        'pos_R': sum(1 for x in R if x > 0), 'neg_R': sum(1 for x in R if x < 0), 'zero_R': sum(1 for x in R if x == 0),
        'avg_holding_min': round(statistics.mean(H), 1) if H else 0.0,
        'median_holding_min': round(statistics.median(H), 1) if H else 0.0,
        'min_holding_min': min(H) if H else 0.0, 'max_holding_min': max(H) if H else 0.0,
        'avg_MFE': round(statistics.mean(MFE), 2) if MFE else 0.0,
        'avg_MAE': round(statistics.mean(MAE), 2) if MAE else 0.0,
        'risk_pts': {'min': round(min(risks), 2), 'max': round(max(risks), 2),
                     'median': round(statistics.median(risks), 2), 'avg': round(statistics.mean(risks), 2)} if risks else {},
        'trades_per_session': round(n / len(sess_list), 3) if sess_list else 0.0,
        'max_trades_one_day': max(per_day.values()) if per_day else 0,
        'lookahead_violations': sum(1 for d in decisions if d.get('lookahead_check') != 'PASS')}

results, trade_audit, rdist, outliers = {}, {}, {}, {}
for inst in ['NIFTY', 'BANKNIFTY']:
    results[inst] = {}
    for pname, (d0, d1) in periods.items():
        sess = sessions(inst, d0, Q[1] if pname == 'FULL' else d1)
        r = eng.run(inst, d0, d1)
        s = summarize(r['trades'], r['decisions'], sess)
        s['period'] = {'name': pname, 'start': d0, 'end': Q[1] if pname == 'FULL' else d1}
        s['run_id'] = r['run_id']
        results[inst][pname] = s
        print(inst, pname, 'q=', s['qualified_trades'], 'W=', s['wins'], 'L=', s['losses'],
              'wr=', s['win_rate'], 'avgR=', s['avg_R'], 'totR=', s['total_R'], 'exits=', s['exits'],
              'max/day=', s['max_trades_one_day'], 'la=', s['lookahead_violations'])
    full = eng.run(inst, periods['FULL'][0], periods['FULL'][1])['trades']
    trade_audit[inst] = [{
        'trade_id': t['trade_id'], 'trade_date': t['trade_date'], 'scenario': t['scenario'],
        'direction': t['direction'], 'entry_time': t['entry_time'], 'entry_price': t['entry_price'],
        'stop_price': t['stop_price'], 'target_price': t['target_price'],
        'risk_pts': round(abs(t['entry_price'] - t['stop_price']), 2),
        'reward_pts': round(abs(t['target_price'] - t['entry_price']), 2),
        'exit_time': t['exit_time'], 'exit_price': t['exit_price'], 'exit_reason': t['exit_reason'],
        'holding_minutes': t['holding_minutes'], 'MFE_pts': t['MFE'], 'MAE_pts': t['MAE'],
        'R_multiple': t['R_multiple'], 'paper_pnl': t['paper_pnl']} for t in full]
    Rs = sorted((t['R_multiple'] for t in full), reverse=True)
    by_id = {t['trade_id']: t for t in full}
    top = sorted(full, key=lambda t: t['R_multiple'], reverse=True)[:5]
    bot = sorted(full, key=lambda t: t['R_multiple'])[:5]
    outliers[inst] = {
        'top5': [{k: t[k] for k in ('trade_id', 'trade_date', 'scenario', 'direction', 'entry_price',
                                    'stop_price', 'target_price', 'exit_price', 'exit_reason',
                                    'holding_minutes', 'MFE', 'MAE', 'R_multiple', 'paper_pnl')} for t in top],
        'bottom5': [{k: t[k] for k in ('trade_id', 'trade_date', 'scenario', 'direction', 'entry_price',
                                       'stop_price', 'target_price', 'exit_price', 'exit_reason',
                                       'holding_minutes', 'MFE', 'MAE', 'R_multiple', 'paper_pnl')} for t in bot],
        'sensitivity_NOT_A_TRADING_RESULT': {
            'all': {'n': len(Rs), 'wins': sum(1 for x in Rs if x > 0),
                    'total_R': round(sum(Rs), 4), 'avg_R': round(sum(Rs) / len(Rs), 4)},
            'ex_top1': {'total_R': round(sum(Rs[1:]), 4), 'avg_R': round(sum(Rs[1:]) / (len(Rs) - 1), 4)},
            'ex_top2': {'total_R': round(sum(Rs[2:]), 4), 'avg_R': round(sum(Rs[2:]) / (len(Rs) - 2), 4)},
            'ex_top5': {'total_R': round(sum(Rs[5:]), 4), 'avg_R': round(sum(Rs[5:]) / (len(Rs) - 5), 4)}}}
    r = results[inst]['FULL']
    rdist[inst] = {k: r[k] for k in ('min_R', 'max_R', 'p10_R', 'p25_R', 'median_R', 'p75_R', 'p90_R',
                                     'avg_R', 'stdev_R', 'total_R', 'pos_R', 'neg_R', 'zero_R')}
    print(inst, 'FULL entries:', Counter(t['entry_time'][11:16] for t in full))

live = {'qualified_trades': conn.execute('SELECT COUNT(*) FROM qualified_trades').fetchone()[0],
        'paper_trades': conn.execute('SELECT COUNT(*) FROM paper_trades').fetchone()[0],
        'daily_trade_locks': conn.execute('SELECT COUNT(*) FROM daily_trade_locks').fetchone()[0]}
summary = {'phase': 7, 'generated_at': datetime.now(_IST).isoformat(),
    'engine': 'Phase 5 engine + 4 accounting bugfixes (B1 R units, B2 target fill, B3 MFE/MAE excursions, B4 risk eps); strategy rules unchanged',
    'formulas': {
        'R_multiple': '(exit-entry)/|entry-stop| LONG; (entry-exit)/|entry-stop| SHORT (points/points)',
        'paper_pnl_rupees': '(exit-entry)*50 LONG (lot-size 50; informational only, NOT used in R)',
        'entry': 'round(signal_close*0.995,2)', 'stop': 'round(entry*0.99,2)', 'target': 'round(entry*1.02,2)',
        'theoretical_RR': '2.000 for every trade', 'win_rate': 'round(wins/completed,4)'},
    'bugs_fixed': {
        'B1': 'R divided rupee-PnL by point-risk (50x inflation). Fixed to points/points.',
        'B2': 'TARGET filled at candle extreme (favorable intrabar). Fixed to fill at target.',
        'B3': 'MFE/MAE stored price levels. Fixed to excursions in points (>=0).',
        'B4': 'risk-gate eps 1e-9 < rounding noise (~4e-5); random rejections scattered entries. Fixed to 1e-4.'},
    'phase6_vs_corrected_FULL': {
        'NIFTY': {'phase6': {'trades': 39, 'wins': 37, 'losses': 2, 'win_rate': 0.9487, 'avg_R': 24.55, 'total_R': 957.56},
                  'corrected': {k: results['NIFTY']['FULL'][k] for k in ('qualified_trades', 'wins', 'losses', 'win_rate', 'avg_R', 'total_R', 'exits')}},
        'BANKNIFTY': {'phase6': {'trades': 39, 'wins': 36, 'losses': 3, 'win_rate': 0.9231, 'avg_R': 26.9, 'total_R': 1049.18},
                      'corrected': {k: results['BANKNIFTY']['FULL'][k] for k in ('qualified_trades', 'wins', 'losses', 'win_rate', 'avg_R', 'total_R', 'exits')}}},
    'options': 'NOT AVAILABLE (underlying/index research only)',
    'costs': 'NET P&L not modeled (gross/model R only)',
    'periods': results,
    'research_live_isolation': {'counts': live,
        'status': 'PASS' if live == {'qualified_trades': 0, 'paper_trades': 0, 'daily_trade_locks': 0} else 'FAIL'}}
json.dump(summary, open(f'{GEN}/phase7_trade_audit.json', 'w'), indent=1)
json.dump(rdist, open(f'{GEN}/phase7_r_distribution.json', 'w'), indent=1)
json.dump(outliers, open(f'{GEN}/phase7_outlier_analysis.json', 'w'), indent=1)
json.dump({'NIFTY': results['NIFTY']['FULL']['risk_pts'], 'BANKNIFTY': results['BANKNIFTY']['FULL']['risk_pts'],
           'entry_rule': 'signal_close*0.995', 'stop_rule': 'entry*0.99', 'target_rule': 'entry*1.02',
           'theoretical_RR': 2.0, 'note': 'denominator healthy; no tiny-risk inflation'},
          open(f'{GEN}/phase7_risk_analysis.json', 'w'), indent=1)
print('WROTE phase7 JSONs; isolation:', summary['research_live_isolation'])
conn.close()
