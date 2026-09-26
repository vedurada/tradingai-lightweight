#!/usr/bin/env python3
"""Phase 9 live dry-run (non-trading): fetch market data, build completed-5m
state, evaluate qualification gates, expose state. dry_run=True throughout:
zero DB writes, no broker, no credentials. Logs captured, not committed."""
import sys, json
from datetime import datetime
from zoneinfo import ZoneInfo
sys.path.insert(0, '/opt/tradingai_new')
from app.live.engine import LiveEngine
from app.core.db import get_conn

_IST = ZoneInfo('Asia/Kolkata')
out = {'run_at_ist': datetime.now(_IST).isoformat(), 'mode': 'dry_run_no_writes',
       'instruments': {}}

conn = get_conn()
before = tuple(conn.execute(
    'SELECT (SELECT COUNT(*) FROM qualified_trades),(SELECT COUNT(*) FROM paper_trades),'
    '(SELECT COUNT(*) FROM daily_trade_locks)').fetchone())
conn.close()

eng = LiveEngine()
for inst in ('NIFTY', 'BANKNIFTY'):
    try:
        st = eng.evaluate(inst, dry_run=True)
    except Exception as e:  # noqa - dry-run must record, never raise
        st = {'instrument': inst, 'state': 'DRYRUN_ERROR', 'reasons': [str(e)]}
    out['instruments'][inst] = st
    print(f"{inst}: state={st.get('state')} session={st.get('session')} "
          f"completed={st.get('completed_candle')} reasons={st.get('reasons')}")

conn = get_conn()
after = tuple(conn.execute(
    'SELECT (SELECT COUNT(*) FROM qualified_trades),(SELECT COUNT(*) FROM paper_trades),'
    '(SELECT COUNT(*) FROM daily_trade_locks)').fetchone())
conn.close()
out['live_counts_before'] = list(before)
out['live_counts_after'] = list(after)
out['writes'] = 'NONE' if before == after else 'UNEXPECTED_WRITES'
print('live tables before/after:', before, after)
json.dump(out, open('/opt/tradingai_new/data/generated/phase9_dryrun.json', 'w'), indent=1)
print('wrote data/generated/phase9_dryrun.json')
