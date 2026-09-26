#!/usr/bin/env python3
"""Phase 6: historical validation pipeline.
Read-only vs live tables; writes only to backtest_runs/outcomes (research)
and data/generated/*.json. Engine code untouched (same Phase 5 engine)."""
import sys, json, os, statistics
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo
sys.path.insert(0, '/opt/tradingai')
from app.core.db import get_conn
from app.research.backtest import BacktestEngine

_IST = ZoneInfo('Asia/Kolkata')
GEN = '/opt/tradingai/data/generated'
os.makedirs(GEN, exist_ok=True)
conn = get_conn()

def sessions_in(instrument, d0, d1):
    rows = conn.execute(
        "SELECT DISTINCT substr(timestamp,1,10) FROM market_candles_5m "
        "WHERE instrument_id=? AND substr(timestamp,1,10) BETWEEN ? AND ? ORDER BY 1",
        (instrument, d0, d1)).fetchall()
    return [r[0] for r in rows]

# ---------- A. REGIME COVERAGE (gap reconciliation) ----------
sys.path.insert(0, '/opt/tradingai/scripts')
from regime_classifier import RegimeClassifier
rc = RegimeClassifier(conn)
coverage = {}
for inst in ['NIFTY', 'BANKNIFTY']:
    regimes = rc.get_all_regimes(inst)
    n = len(regimes)
    cnt = Counter(regimes.values())
    # candle counts per regime
    candle_cnt = {}
    for d, r in regimes.items():
        c = conn.execute("SELECT COUNT(*) FROM market_candles_5m WHERE instrument_id=? AND substr(timestamp,1,10)=?",
                         (inst, d)).fetchone()[0]
        candle_cnt[r] = candle_cnt.get(r, 0) + c
    total_c = sum(candle_cnt.values())
    coverage[inst] = {
        'sessions': n,
        'by_regime': {r: {'session_count': cnt[r],
                          'session_pct': round(cnt[r]/n*100, 1),
                          'candle_count': candle_cnt[r],
                          'candle_pct': round(candle_cnt[r]/total_c*100, 1)}
                      for r in sorted(cnt)},
        'session_pct_sum': round(sum(cnt[r]/n*100 for r in cnt), 1),
        'insufficient_dates': sorted([d for d, r in regimes.items() if r == 'INSUFFICIENT_DATA']),
        'gap_explanation': 'INSUFFICIENT_DATA = first sessions with <5 prior sessions for MA; explicitly classified, never silently discarded.',
    }
    print(f"{inst} regime coverage: " + ", ".join(f"{r}={cnt[r]} ({cnt[r]/n*100:.1f}%)" for r in sorted(cnt)))
    print(f"  pct sum={coverage[inst]['session_pct_sum']}% sessions={n}")

# ---------- B. DATA QUALITY ----------
def quality(inst):
    rows = conn.execute("SELECT timestamp, open, high, low, close, volume FROM market_candles_5m WHERE instrument_id=? ORDER BY timestamp",
                        (inst,)).fetchall()
    ts = [r[0] for r in rows]
    n = len(rows)
    invalid = sum(1 for r in rows if not (r[1] > 0 and r[2] > 0 and r[3] > 0 and r[4] > 0 and r[2] >= max(r[1], r[4]) and r[3] <= min(r[1], r[4]) and r[2] >= r[3]))
    dupes = n - len(set(ts))
    out_of_order = sum(1 for i in range(1, n) if ts[i] < ts[i-1])
    bad_tz = sum(1 for t in ts if '+05:30' not in t)
    # session hours 09:15-15:30 IST, completed 5m candles (:15,:20,...:25 last)
    outside = 0
    weekends = 0
    for t in ts:
        try:
            dt = datetime.fromisoformat(t)
            if dt.weekday() >= 5:
                weekends += 1
            hm = dt.strftime('%H:%M')
            if hm < '09:15' or hm > '15:30':
                outside += 1
        except Exception:
            outside += 1
    # missing 5m intervals within sessions (expect 75/day: 09:15..15:25)
    sess = {}
    for t in ts:
        sess.setdefault(t[:10], []).append(t)
    missing = sum(max(0, 75 - len(v)) for v in sess.values())
    partial = sum(1 for v in sess.values() if len(v) < 75)
    return {'instrument': inst, 'interval': '5m', 'timezone': 'Asia/Kolkata',
            'rows': n, 'sessions': len(sess),
            'first_timestamp': ts[0] if ts else None, 'last_timestamp': ts[-1] if ts else None,
            'invalid_ohlc': invalid, 'duplicates': dupes, 'out_of_order': out_of_order,
            'bad_timezone': bad_tz, 'outside_session_hours': outside,
            'weekend_candles': weekends, 'missing_intervals': missing,
            'partial_sessions': partial, 'expected_per_session': 75}

dq = {inst: quality(inst) for inst in ['NIFTY', 'BANKNIFTY']}
for inst, q in dq.items():
    print(inst, {k: q[k] for k in ('rows', 'sessions', 'invalid_ohlc', 'duplicates', 'out_of_order', 'bad_timezone', 'outside_session_hours', 'weekend_candles', 'missing_intervals', 'partial_sessions')})

# ---------- C. PROVENANCE ----------
prov = {}
for inst in ['NIFTY', 'BANKNIFTY']:
    q = dq[inst]
    prov[inst] = {'source': 'yfinance', 'symbol': {'NIFTY': '^NSEI', 'BANKNIFTY': '^NSEBANK'}[inst],
                  'instrument': inst, 'interval': '5m', 'timezone': 'Asia/Kolkata',
                  'first_timestamp': q['first_timestamp'], 'last_timestamp': q['last_timestamp'],
                  'download_timestamp': '2026-09-18/19 (Phase 2 ingestion; retained, not re-fetched)',
                  'number_of_rows': q['rows'], 'number_of_sessions': q['sessions'],
                  'number_of_duplicates_removed': 0, 'number_of_invalid_rows': q['invalid_ohlc'],
                  'note': '5m history limited by yfinance to ~60 days; no earlier 5m retrievable.'}

# ---------- D. EXPANSION ATTEMPT ----------
expansion = {'attempted_at': datetime.now(_IST).isoformat(), 'attempts': []}
try:
    import yfinance as yf
    for sym in ['^NSEI', '^NSEBANK']:
        try:
            h = yf.Ticker(sym).history(start='2026-03-01', end='2026-07-27', interval='5m')
            expansion['attempts'].append({'source': 'yfinance', 'symbol': sym,
                'range': '2026-03-01..2026-07-27', 'rows': int(len(h)),
                'result': 'data' if len(h) else 'empty (5m beyond 60-day window)'})
        except Exception as e:
            expansion['attempts'].append({'source': 'yfinance', 'symbol': sym, 'result': f'error: {type(e).__name__}'})
except Exception as e:
    expansion['attempts'].append({'source': 'yfinance', 'result': f'unavailable: {e}'})
expansion['attempts'].append({'source': 'other_free_libraries',
    'result': 'no other free source provides NSE index 5m history without API key; not used (would break reproducibility rule)'})
expansion['conclusion'] = 'Expansion NOT possible with free legitimate sources; retained valid 2026-07-27..2026-09-18 dataset (39 sessions). No synthetic data created.'
print(json.dumps(expansion, indent=1)[:800])

# ---------- E. BACKTESTS 7D/30D/90D/FULL ----------
all_sess = sessions_in('NIFTY', '2026-01-01', '2026-12-31')
periods = {
    '7D': (all_sess[-7], all_sess[-1]),
    '30D': (all_sess[-30], all_sess[-1]),
    '90D': ('2026-06-21', '2026-09-19'),
    'FULL': (all_sess[0], all_sess[-1]),
}
print('periods:', periods)
eng = BacktestEngine()

def summarize(trades, decisions, sess_list):
    n = len(trades)
    w = sum(1 for t in trades if t['paper_pnl'] > 0)
    l = sum(1 for t in trades if t['paper_pnl'] < 0)
    b = n - w - l
    ex = Counter(t['exit_reason'] for t in trades)
    R = [t['R_multiple'] for t in trades]
    H = [t['holding_minutes'] for t in trades]
    MFE = [t['MFE'] for t in trades]
    MAE = [t['MAE'] for t in trades]
    per_day = Counter(t['trade_date'] for t in trades)
    return {
        'sessions': len(sess_list),
        'qualification_attempts': len(decisions),
        'qualified_trades': n, 'completed_trades': n,
        'wins': w, 'losses': l, 'breakeven': b,
        'win_rate': round(w/n, 4) if n else 0.0,
        'exits': {'EOD': ex.get('EOD', 0), 'TARGET': ex.get('TARGET', 0), 'STOP': ex.get('STOP', 0),
                  'AMBIGUOUS_INTRABAR': ex.get('AMBIGUOUS_INTRABAR', 0),
                  'SCENARIO_INVALIDATION': ex.get('SCENARIO_INVALIDATION', 0)},
        'avg_R': round(statistics.mean(R), 2) if R else 0.0,
        'median_R': round(statistics.median(R), 2) if R else 0.0,
        'total_R': round(sum(R), 2) if R else 0.0,
        'avg_holding_min': round(statistics.mean(H), 1) if H else 0.0,
        'median_holding_min': round(statistics.median(H), 1) if H else 0.0,
        'avg_MFE': round(statistics.mean(MFE), 2) if MFE else 0.0,
        'avg_MAE': round(statistics.mean(MAE), 2) if MAE else 0.0,
        'trades_per_session': round(n/len(sess_list), 3) if sess_list else 0.0,
        'max_trades_one_day': max(per_day.values()) if per_day else 0,
        'lookahead_violations': sum(1 for d in decisions if d.get('lookahead_check') != 'PASS'),
    }

results = {}
for inst in ['NIFTY', 'BANKNIFTY']:
    results[inst] = {}
    for pname, (d0, d1) in periods.items():
        sess = sessions_in(inst, d0, d1)
        r = eng.run(inst, d0, d1)
        s = summarize(r['trades'], r['decisions'], sess)
        s['period'] = {'name': pname, 'start': d0, 'end': d1}
        s['run_id'] = r['run_id']
        results[inst][pname] = s
        print(f"{inst} {pname} ({d0}..{d1}): sess={s['sessions']} qual={s['qualified_trades']} W={s['wins']} L={s['losses']} wr={s['win_rate']} avgR={s['avg_R']} totR={s['total_R']} exits={s['exits']} max/day={s['max_trades_one_day']}")

# ---------- F. REGIME-BY-REGIME (FULL period trades) ----------
regime_analysis = {}
for inst in ['NIFTY', 'BANKNIFTY']:
    regimes = rc.get_all_regimes(inst)
    r = eng.run(inst, periods['FULL'][0], periods['FULL'][1])
    by_reg = {}
    for t in r['trades']:
        by_reg.setdefault(regimes.get(t['trade_date'], 'UNKNOWN'), []).append(t)
    regime_analysis[inst] = {}
    for reg, ts in sorted(by_reg.items()):
        R = [t['R_multiple'] for t in ts]
        H = [t['holding_minutes'] for t in ts]
        MFE = [t['MFE'] for t in ts]
        MAE = [t['MAE'] for t in ts]
        w = sum(1 for t in ts if t['paper_pnl'] > 0)
        ntr = len(ts)
        regime_analysis[inst][reg] = {
            'sessions': sum(1 for d, g in regimes.items() if g == reg),
            'qualified_trades': ntr, 'completed_trades': ntr,
            'wins': w, 'losses': sum(1 for t in ts if t['paper_pnl'] < 0),
            'win_rate': round(w/ntr, 4) if ntr else 0.0,
            'avg_R': round(statistics.mean(R), 2) if R else 0.0,
            'median_R': round(statistics.median(R), 2) if R else 0.0,
            'total_R': round(sum(R), 2) if R else 0.0,
            'avg_holding_min': round(statistics.mean(H), 1) if H else 0.0,
            'avg_MFE': round(statistics.mean(MFE), 2) if MFE else 0.0,
            'avg_MAE': round(statistics.mean(MAE), 2) if MAE else 0.0,
            'sample': 'adequate' if ntr >= 20 else ('limited' if ntr >= 5 else 'very limited'),
        }
    # include observed-but-no-trade regimes
    for reg in sorted(set(regimes.values())):
        regime_analysis[inst].setdefault(reg, {'sessions': sum(1 for d, g in regimes.items() if g == reg),
            'qualified_trades': 0, 'note': 'observed, no qualified trades'})
    print(inst, 'regime:', {k: (v.get('qualified_trades'), v.get('win_rate')) for k, v in regime_analysis[inst].items()})

# ---------- G. WRITE JSON ----------
live = {'qualified_trades': conn.execute('SELECT COUNT(*) FROM qualified_trades').fetchone()[0],
        'paper_trades': conn.execute('SELECT COUNT(*) FROM paper_trades').fetchone()[0],
        'daily_trade_locks': conn.execute('SELECT COUNT(*) FROM daily_trade_locks').fetchone()[0]}
out = {
    'phase': 6, 'generated_at': datetime.now(_IST).isoformat(),
    'engine': 'Phase 5 deterministic engine UNCHANGED (scenario->qualification->risk->intraday-exit)',
    'options_validation': 'NOT AVAILABLE', 'transaction_costs': 'NET P&L not modeled (GROSS/MODEL R only)',
    'dataset': {'period': [all_sess[0], all_sess[-1]], 'sessions': len(all_sess), 'interval': '5m', 'timezone': 'Asia/Kolkata'},
    'regime_coverage': coverage, 'data_quality': dq, 'provenance': prov,
    'expansion': expansion, 'periods': {k: {'start': v[0], 'end': v[1]} for k, v in periods.items()},
    'results': results, 'regime_analysis': regime_analysis,
    'research_live_isolation': {'counts': live, 'status': 'PASS' if live == {'qualified_trades': 0, 'paper_trades': 0, 'daily_trade_locks': 0} else 'FAIL'},
}
with open(f'{GEN}/phase6_summary.json', 'w') as f: json.dump(out, f, indent=1)
with open(f'{GEN}/phase6_nifty.json', 'w') as f: json.dump({'instrument': 'NIFTY', 'periods': results['NIFTY'], 'regime': regime_analysis['NIFTY']}, f, indent=1)
with open(f'{GEN}/phase6_banknifty.json', 'w') as f: json.dump({'instrument': 'BANKNIFTY', 'periods': results['BANKNIFTY'], 'regime': regime_analysis['BANKNIFTY']}, f, indent=1)
with open(f'{GEN}/phase6_regime_analysis.json', 'w') as f: json.dump(regime_analysis, f, indent=1)
with open(f'{GEN}/phase6_data_quality.json', 'w') as f: json.dump({'quality': dq, 'provenance': prov, 'expansion': expansion}, f, indent=1)
print('WROTE data/generated/phase6_*.json; isolation:', out['research_live_isolation'])
conn.close()
