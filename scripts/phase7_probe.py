#!/usr/bin/env python3
import sys
sys.path.insert(0, '/opt/tradingai_new')
from app.core.db import get_conn
from app.core.qualification import QualificationEngine
from app.scenarios.engine import ScenarioEngine

conn = get_conn()
q = QualificationEngine()
se = ScenarioEngine()
a = se.get_active_scenario('NIFTY')
print('ACTIVE:', a['candidate']['scenario_type'], a['candidate']['created_at'][:16],
      a['match']['match_state'] if a['match'] else None)
for day in ['2026-08-05', '2026-08-12', '2026-09-18']:
    candles = [dict(c) for c in conn.execute(
        "SELECT * FROM market_candles_5m WHERE instrument_id='NIFTY' AND substr(timestamp,1,10)=? ORDER BY timestamp",
        (day,)).fetchall()]
    print(f'--- {day} first 6 candles ---')
    q.reset_research_locks()
    for c in candles[:6]:
        ms = {'trend': 'BULLISH', 'vwap_relation': 'ABOVE', 'momentum': 'POSITIVE',
              'volatility': 'NORMAL', 'price': c['close']}
        res = q.qualify('NIFTY', ms, options_valid=True, research=True, trade_date=c['timestamp'][:10])
        print(' ', c['timestamp'][11:16], res['decision'], res.get('reasons'))
conn.close()
