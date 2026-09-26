#!/usr/bin/env python3
"""Fix FULL-period boundary: use end='2026-09-19' so timestamp BETWEEN
includes all of 2026-09-18. Sessions unchanged (39). Updates all phase6 JSONs."""
import sys, json, statistics
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo
sys.path.insert(0, '/opt/tradingai_new')
sys.path.insert(0, '/opt/tradingai_new/scripts')
from app.core.db import get_conn
from app.research.backtest import BacktestEngine
from regime_classifier import RegimeClassifier

_IST = ZoneInfo('Asia/Kolkata')
GEN = '/opt/tradingai_new/data/generated'
conn = get_conn()
rc = RegimeClassifier(conn)
eng = BacktestEngine()

def sessions_in(inst, d0, d1):
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT substr(timestamp,1,10) FROM market_candles_5m WHERE instrument_id=? "
        "AND substr(timestamp,1,10) BETWEEN ? AND ? ORDER BY 1", (inst, d0, d1)).fetchall()]

def summarize(trades, decisions, sess_list):
    n = len(trades)
    w = sum(1 for t in trades if t['paper_pnl'] > 0)
    l = sum(1 for t in trades if t['paper_pnl'] < 0)
    ex = Counter(t['exit_reason'] for t in trades)
    R = [t['R_multiple'] for t in trades]; H = [t['holding_minutes'] for t in trades]
    MFE = [t['MFE'] for t in trades]; MAE = [t['MAE'] for t in trades]
    per_day = Counter(t['trade_date'] for t in trades)
    return {'sessions': len(sess_list), 'qualification_attempts': len(decisions),
        'qualified_trades': n, 'completed_trades': n, 'wins': w, 'losses': l, 'breakeven': n-w-l,
        'win_rate': round(w/n, 4) if n else 0.0,
        'exits': {'EOD': ex.get('EOD',0), 'TARGET': ex.get('TARGET',0), 'STOP': ex.get('STOP',0),
                  'AMBIGUOUS_INTRABAR': ex.get('AMBIGUOUS_INTRABAR',0), 'SCENARIO_INVALIDATION': ex.get('SCENARIO_INVALIDATION',0)},
        'avg_R': round(statistics.mean(R),2) if R else 0.0, 'median_R': round(statistics.median(R),2) if R else 0.0,
        'total_R': round(sum(R),2) if R else 0.0,
        'avg_holding_min': round(statistics.mean(H),1) if H else 0.0, 'median_holding_min': round(statistics.median(H),1) if H else 0.0,
        'avg_MFE': round(statistics.mean(MFE),2) if MFE else 0.0, 'avg_MAE': round(statistics.mean(MAE),2) if MAE else 0.0,
        'trades_per_session': round(n/len(sess_list),3) if sess_list else 0.0,
        'max_trades_one_day': max(per_day.values()) if per_day else 0,
        'lookahead_violations': sum(1 for d in decisions if d.get('lookahead_check') != 'PASS')}

d0, d1 = '2026-07-27', '2026-09-19'
s = json.load(open(f'{GEN}/phase6_summary.json'))
for inst in ['NIFTY', 'BANKNIFTY']:
    sess = sessions_in(inst, '2026-07-27', '2026-09-18')
    r = eng.run(inst, d0, d1)
    sm = summarize(r['trades'], r['decisions'], sess)
    sm['period'] = {'name': 'FULL', 'start': '2026-07-27', 'end': '2026-09-18', 'query_end': d1,
                    'note': 'query_end +1 day so BETWEEN includes all of end date'}
    sm['run_id'] = r['run_id']
    s['results'][inst]['FULL'] = sm
    # regime-by-regime refresh
    regimes = rc.get_all_regimes(inst)
    by_reg = {}
    for t in r['trades']:
        by_reg.setdefault(regimes.get(t['trade_date'], 'UNKNOWN'), []).append(t)
    ra = {}
    for reg, ts in sorted(by_reg.items()):
        R = [t['R_multiple'] for t in ts]; H = [t['holding_minutes'] for t in ts]
        MFE = [t['MFE'] for t in ts]; MAE = [t['MAE'] for t in ts]
        w = sum(1 for t in ts if t['paper_pnl'] > 0); ntr = len(ts)
        ra[reg] = {'sessions': sum(1 for d, g in regimes.items() if g == reg),
            'qualified_trades': ntr, 'completed_trades': ntr, 'wins': w,
            'losses': sum(1 for t in ts if t['paper_pnl'] < 0),
            'win_rate': round(w/ntr, 4) if ntr else 0.0,
            'avg_R': round(statistics.mean(R),2) if R else 0.0,
            'median_R': round(statistics.median(R),2) if R else 0.0,
            'total_R': round(sum(R),2) if R else 0.0,
            'avg_holding_min': round(statistics.mean(H),1) if H else 0.0,
            'avg_MFE': round(statistics.mean(MFE),2) if MFE else 0.0,
            'avg_MAE': round(statistics.mean(MAE),2) if MAE else 0.0,
            'sample': 'adequate' if ntr >= 20 else ('limited' if ntr >= 5 else 'very limited')}
    for reg in sorted(set(regimes.values())):
        ra.setdefault(reg, {'sessions': sum(1 for d, g in regimes.items() if g == reg),
            'qualified_trades': 0, 'note': 'observed, no qualified trades'})
    s['regime_analysis'][inst] = ra
    print(inst, 'FULL fixed:', sm['qualified_trades'], 'trades, W=', sm['wins'], 'L=', sm['losses'], 'wr=', sm['win_rate'])
s['generated_at'] = datetime.now(_IST).isoformat()
json.dump(s, open(f'{GEN}/phase6_summary.json', 'w'), indent=1)
for inst, fn in [('NIFTY', 'phase6_nifty.json'), ('BANKNIFTY', 'phase6_banknifty.json')]:
    json.dump({'instrument': inst, 'periods': s['results'][inst], 'regime': s['regime_analysis'][inst]},
              open(f'{GEN}/{fn}', 'w'), indent=1)
json.dump(s['regime_analysis'], open(f'{GEN}/phase6_regime_analysis.json', 'w'), indent=1)
live = {'qualified_trades': conn.execute('SELECT COUNT(*) FROM qualified_trades').fetchone()[0],
        'paper_trades': conn.execute('SELECT COUNT(*) FROM paper_trades').fetchone()[0],
        'daily_trade_locks': conn.execute('SELECT COUNT(*) FROM daily_trade_locks').fetchone()[0]}
print('isolation:', live)
conn.close()
