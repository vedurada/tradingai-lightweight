#!/usr/bin/env python3
"""Phase 8 future-mutation battery (A-D). All mutations reverted afterwards."""
import sys, json, uuid
from datetime import datetime
from zoneinfo import ZoneInfo
sys.path.insert(0, '/opt/tradingai_new')
from app.core.db import get_conn
from app.research.replay import SequentialReplay
from app.scenarios.engine import ScenarioEngine

_IST = ZoneInfo('Asia/Kolkata')
GEN = '/opt/tradingai_new/data/generated'
conn = get_conn()
res = {'run_at': datetime.now(_IST).isoformat(), 'mutations': {}}

def day_trace(inst, day):
    # NOTE: end bound must exceed the day's timestamps (BETWEEN is lexicographic)
    r = SequentialReplay().run(inst, day, day + 'T23:59:59+05:30')
    r['traces'] = [t for t in r['traces'] if t['trade_date'] == day]
    r['trades'] = [t for t in r['trades'] if t['trade_date'] == day]
    r['daily'] = [d for d in r['daily'] if d['trade_date'] == day]
    return r

# baseline
base = day_trace('NIFTY', '2026-09-16')
base_trades = [(t['entry_time'], t['entry_price'], t['stop_price'], t['target_price'], t['scenario']) for t in base['trades']]
base_dec = [(t['timestamp'], t['qualification']) for t in base['traces']]
print('baseline 09-16:', base_trades, 'n_traces:', len(base_dec))
assert base_trades, 'need a traded day for mutations'

# --- Mutation A: change candles strictly AFTER the signal/entry ---
sig_ts = base_trades[0][0]
orig = [dict(c) for c in conn.execute(
    "SELECT timestamp,open,high,low,close,volume FROM market_candles_5m WHERE instrument_id='NIFTY' AND substr(timestamp,1,10)='2026-09-16' AND timestamp>?",
    (sig_ts,)).fetchall()]
try:
    conn.execute("UPDATE market_candles_5m SET high=high*1.05, low=low*1.05, close=close*1.05, open=open*1.05 WHERE instrument_id='NIFTY' AND substr(timestamp,1,10)='2026-09-16' AND timestamp>?",
                 (sig_ts,))
    conn.commit()
    m = day_trace('NIFTY', '2026-09-16')
    mt = [(t['entry_time'], t['entry_price'], t['stop_price'], t['target_price'], t['scenario']) for t in m['trades']]
    md = [(t['timestamp'], t['qualification']) for t in m['traces'] if t['timestamp'] <= sig_ts]
    bd = [(t['timestamp'], t['qualification']) for t in base['traces'] if t['timestamp'] <= sig_ts]
    res['mutations']['A_future_candles'] = {
        'decisions_at_or_before_signal_unchanged': md == bd,
        'levels_unchanged': mt == base_trades,
        'exit_changed_ok': True, 'verdict': 'PASS' if (md == bd and mt == base_trades) else 'FAIL'}
finally:
    for c in orig:
        conn.execute("UPDATE market_candles_5m SET open=?,high=?,low=?,close=?,volume=? WHERE instrument_id='NIFTY' AND timestamp=?",
                     (c['open'], c['high'], c['low'], c['close'], c['volume'], c['timestamp']))
    conn.commit()
print('A:', res['mutations']['A_future_candles']['verdict'])

# --- Mutation B: insert future candidate+match after T ---
cid, mid = 'SC-MUTB-' + uuid.uuid4().hex[:8], ''
mid = 'SM-' + cid
fts = '2026-09-18T10:00:00+05:30'
try:
    conn.execute("INSERT INTO scenario_candidates (candidate_id, instrument_id, session_id, scenario_type, historical_context, required_conditions, confirmation_conditions, invalidation_conditions, status, confidence, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                 (cid, 'NIFTY', 'SESS-MUT', 'BREAKOUT', '{}', '{}', '{}', '{}', 'CONFIRMED', 1.0, fts, fts))
    conn.execute("INSERT INTO scenario_matches (match_id, candidate_id, instrument_id, timestamp, match_state, evidence, confidence, confirmation_evidence, invalidation_evidence, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                 (mid, cid, 'NIFTY', fts, 'CONFIRMED', '[]', 1.0, '[]', '[]', fts))
    conn.commit()
    m = day_trace('NIFTY', '2026-09-16')
    mt = [(t['entry_time'], t['entry_price'], t['stop_price'], t['target_price']) for t in m['trades']]
    res['mutations']['B_future_candidate'] = {
        'decision_unchanged': mt == [b[:4] for b in base_trades], 'verdict': 'PASS' if mt == [b[:4] for b in base_trades] else 'FAIL'}
finally:
    conn.execute("DELETE FROM scenario_matches WHERE match_id=?", (mid,))
    conn.execute("DELETE FROM scenario_candidates WHERE candidate_id=?", (cid,))
    conn.commit()
print('B:', res['mutations']['B_future_candidate']['verdict'])

# --- Mutation C: change future scenario metadata ---
row = conn.execute("SELECT candidate_id, confidence FROM scenario_candidates WHERE instrument_id='NIFTY' AND created_at>'2026-09-17T15:30:00+05:30' LIMIT 1").fetchone()
try:
    conn.execute("UPDATE scenario_candidates SET confidence=0.01 WHERE candidate_id=?", (row[0],))
    conn.commit()
    m = day_trace('NIFTY', '2026-09-16')
    mt = [(t['entry_time'], t['entry_price']) for t in m['trades']]
    res['mutations']['C_future_metadata'] = {
        'decision_unchanged': mt == [(b[0], b[1]) for b in base_trades], 'verdict': 'PASS' if mt == [(b[0], b[1]) for b in base_trades] else 'FAIL'}
finally:
    conn.execute("UPDATE scenario_candidates SET confidence=? WHERE candidate_id=?", (row[1], row[0]))
    conn.commit()
print('C:', res['mutations']['C_future_metadata']['verdict'])

# --- Mutation D: later qualifying signal cannot replace first ---
r = day_trace('NIFTY', '2026-09-16')
first = r['trades'][0]['entry_time'] if r['trades'] else None
later = [t for t in r['traces'] if t['qualification'] == 'QUALIFIED_TRADE']
res['mutations']['D_first_signal_wins'] = {
    'first_entry': first,
    'qualified_count_day': len([t for t in r['trades'] if t['trade_date'] == '2026-09-16']),
    'verdict': 'PASS' if first and all(t['entry_time'] == first for t in r['trades'] if t['trade_date'] == '2026-09-16') else 'FAIL'}
print('D:', res['mutations']['D_first_signal_wins'])

json.dump(res, open(f'{GEN}/phase8_future_mutation_results.json', 'w'), indent=1)
# verify no residue
left = conn.execute("SELECT COUNT(*) FROM scenario_candidates WHERE candidate_id LIKE 'SC-MUT%'").fetchone()[0]
print('mutation residue:', left)
conn.close()
