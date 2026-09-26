#!/usr/bin/env python3
"""Phase 11 machine-readable diagnostics (compact, deterministic).

Writes data/generated/:
  phase11_data_reliability.json  - provider/cache/retry/session findings
  phase11_provider_failures.json - per-failure-mode expected states
  phase11_freshness_results.json - freshness probe outcomes (15m threshold)
  phase11_concurrency_results.json- concurrent-claim outcome (sentinel day, cleaned)
  phase11_session_results.json    - session/holiday/weekend matrix
  phase11_baseline_regression.json- PIT baseline numbers gate (34/31, 16.21/16.63)
Follows project conventions (git-ignored like earlier phase JSONs).
"""
import sys, json, threading
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
sys.path.insert(0, '/opt/tradingai_new')
from app.live.engine import LiveEngine
from app.market.nse_calendar import holiday_name, is_session_day, NSE_HOLIDAYS_2026
from app.core.db import get_conn
from app.research.replay import SequentialReplay

_IST = ZoneInfo('Asia/Kolkata')
GEN = '/opt/tradingai_new/data/generated'
WED = '2026-09-16'


def dump(name, obj):
    json.dump(obj, open(f'{GEN}/{name}', 'w'), indent=1)
    print('wrote', name, obj.get('verdict', ''))


conn = get_conn()
rows = [dict(c) for c in conn.execute(
    "SELECT timestamp,open,high,low,close,volume FROM market_candles_5m "
    "WHERE instrument_id='NIFTY' AND substr(timestamp,1,10)=? ORDER BY timestamp", (WED,)).fetchall()]
conn.close()
upto55 = [c for c in rows if c['timestamp'] <= f'{WED}T09:55:00+05:30']

dump('phase11_data_reliability.json', {
    'provider': 'yfinance on-demand (no collector daemon)',
    'fetch_timeout_s': 12, 'max_attempts': 2,
    'cache': {'backend': 'SQLite provider_cache (shared across workers)',
              'ttl_quote_s': 45, 'ttl_candles_s': 90,
              'timestamp_rule': 'original data_ts preserved on hits'},
    'forming_candle': 'never decision-eligible (is_complete=False + engine derivation)',
    'timestamp_convention': 'candle OPEN, Asia/Kolkata +05:30 (unchanged from Phase 9)',
})

dump('phase11_provider_failures.json', {
    'timeout': 'API_ERROR, no trade', 'dns': 'API_ERROR, no trade',
    'http_429': 'RATE_LIMITED, no trade', 'empty': 'UNAVAILABLE, no trade',
    'malformed': 'API_ERROR, no trade',
    'one_instrument_down': 'that instrument NO_DATA/STALE; other unaffected',
    'cross_substitution': 'FORBIDDEN by per-symbol feed functions',
})

# freshness + session matrix (injected deterministic feed)
eng = LiveEngine(
    quote_fn=lambda i: {'price': 1.0, 'timestamp': upto55[-1]['timestamp'],
                        'age_seconds': 9999.0, 'state': 'STALE', 'source': 'test'},
    candles_fn=lambda i, c: upto55)
fresh = {
    'dead_feed': eng.evaluate('NIFTY', now=datetime.fromisoformat(f'{WED}T10:11:00+05:30'),
                              dry_run=True)['state'],
    'threshold_min': 15,
}
dump('phase11_freshness_results.json', {
    'probes': fresh,
    'verdict': 'PASS' if fresh['dead_feed'] == 'STALE' else 'FAIL'})

eng2 = LiveEngine(quote_fn=lambda i: {}, candles_fn=lambda i, c: [])
eng_live = LiveEngine(
    quote_fn=lambda i: {'price': 1.0, 'timestamp': rows[-1]['timestamp'],
                        'age_seconds': 60.0, 'state': 'LIVE', 'source': 'test'},
    candles_fn=lambda inst, completed: [c for c in rows
                                         if c['timestamp'] <= completed.isoformat()])
sess_cases = {
    'premarket': ('2026-09-16T08:00:00+05:30', 'PREMARKET', eng2),
    'live_window': ('2026-09-16T10:00:00+05:30', None, eng_live),  # NO_TRADE or QUALIFIED
    'after_close': ('2026-09-16T16:00:00+05:30', 'MARKET_CLOSED', eng2),
    'saturday': ('2026-09-19T10:00:00+05:30', 'WEEKEND', eng2),
    'sunday': ('2026-09-20T10:00:00+05:30', 'WEEKEND', eng2),
    'holiday_ganesh': ('2026-09-14T10:00:00+05:30', 'MARKET_CLOSED', eng2),
}
sess_out, sess_ok = {}, True
for name, (ts, want, engx) in sess_cases.items():
    got = engx.evaluate('NIFTY', now=datetime.fromisoformat(ts), dry_run=True)['state']
    sess_out[name] = got
    sess_ok &= (want is None and got in ('NO_TRADE', 'QUALIFIED')) or (got == want)
dump('phase11_session_results.json', {
    'calendar_source': 'NSE circular CMTR71775 (2026), 15 weekday holidays encoded',
    'holidays_encoded': len(NSE_HOLIDAYS_2026),
    'special_sessions_note': 'Budget-Sunday / Muhurat sessions NOT modeled (limitation)',
    'cases': sess_out, 'verdict': 'PASS' if sess_ok else 'FAIL'})

# concurrency: 8 parallel claims on a sentinel day, then full cleanup
from app.core.qualification import QualificationEngine
day = '2030-01-05'
ms = {'trend': 'BULLISH', 'vwap_relation': 'ABOVE', 'momentum': 'POSITIVE',
      'volatility': 'NORMAL', 'price': 25000.0}
results, errors = [], []


def worker():
    try:
        results.append(QualificationEngine().qualify(
            'NIFTY', ms, options_valid=True, research=False,
            trade_date=day, as_of='2030-01-05T10:00:00+05:30')['decision'])
    except Exception as e:  # noqa
        errors.append(str(e)[:100])


ts = [threading.Thread(target=worker) for _ in range(8)]
[t.start() for t in ts]
[t.join(timeout=60) for t in ts]
conn = get_conn()
n_tr = conn.execute('SELECT COUNT(*) FROM qualified_trades WHERE date=?', (day,)).fetchone()[0]
n_lk = conn.execute('SELECT COUNT(*) FROM daily_trade_locks WHERE date=?', (day,)).fetchone()[0]
conn.execute('DELETE FROM qualified_trades WHERE date=?', (day,))
conn.execute('DELETE FROM daily_trade_locks WHERE date=?', (day,))
conn.commit()
conn.close()
dump('phase11_concurrency_results.json', {
    'threads': 8, 'decisions': {r: results.count(r) for r in set(results)},
    'errors': errors, 'trade_rows': n_tr, 'lock_rows': n_lk,
    'verdict': 'PASS' if (not errors and n_tr <= 1 and n_lk <= 1) else 'FAIL'})

# baseline regression gate (replay FULL, both instruments)
base = {}
for inst, exp in (('NIFTY', (34, 16.21)), ('BANKNIFTY', (31, 16.63))):
    tr = SequentialReplay().run(inst, '2026-07-27', '2026-09-19')['trades']
    total = round(sum(t['R_multiple'] for t in tr), 2)
    base[inst] = {'trades': len(tr), 'total_R': total,
                  'expected': {'trades': exp[0], 'total_R': exp[1]},
                  'match': (len(tr), total) == exp}
    print(inst, len(tr), total)
dump('phase11_baseline_regression.json', {
    'baseline': base,
    'verdict': 'PASS' if all(v['match'] for v in base.values()) else 'FAIL'})
