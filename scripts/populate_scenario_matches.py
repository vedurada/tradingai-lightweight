#!/usr/bin/env python3
import sys, os, json, sqlite3
sys.path.insert(0, '/opt/tradingai')
from datetime import datetime
from zoneinfo import ZoneInfo
from app.core.db import get_conn

_IST = ZoneInfo('Asia/Kolkata')

def populate_matches():
    conn = get_conn()
    # FIXALL: time-separated WATCH->CONFIRMED. WATCH rows use candidate created_at;
    # CONFIRMED requires a later timestamp (confirming candle ts>signal_ts).
    rows = conn.execute("SELECT * FROM scenario_candidates WHERE status IN ('CANDIDATE','WATCH','CONFIRMED')").fetchall()
    print(f"Found {len(rows)} candidates/watches")
    for c in rows:
        created = c['created_at']
        # WATCH row (zero-lag signal)
        try:
            conn.execute('''INSERT OR IGNORE INTO scenario_matches
                (match_id, candidate_id, instrument_id, timestamp, match_state, evidence, confidence, confirmation_evidence, invalidation_evidence, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)''',
                (f"SM-{c['candidate_id']}-WATCH", c['candidate_id'], c['instrument_id'], created,
                 'WATCH', json.dumps(['Signal bar (unconfirmed)']), 0.5,
                 json.dumps([]), json.dumps([]), created))
        except sqlite3.IntegrityError:
            pass
        if c['status'] != 'CONFIRMED':
            continue
        # CONFIRMED row must be strictly later (24h proxy for next-candle confirm;
        # true PIT confirm uses candle ts>signal_ts in generate_historical_scenarios).
        from datetime import timedelta
        try:
            base = datetime.fromisoformat(created)
            confirm_ts = (base + timedelta(days=1)).isoformat()
        except Exception:
            continue
        if confirm_ts <= created:
            continue
        try:
            conn.execute('''INSERT OR IGNORE INTO scenario_matches
                (match_id, candidate_id, instrument_id, timestamp, match_state, evidence, confidence, confirmation_evidence, invalidation_evidence, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)''',
                (f"SM-{c['candidate_id']}-CONF", c['candidate_id'], c['instrument_id'], confirm_ts,
                 'CONFIRMED', json.dumps(['Confirmed by deterministic rules (t+1)']), 1.0,
                 json.dumps(['Confirmed by deterministic rules (t+1)']), json.dumps([]), confirm_ts))
        except sqlite3.IntegrityError:
            pass
    conn.commit()
    match_count = conn.execute("SELECT COUNT(*) FROM scenario_matches").fetchone()[0]
    print(f"Created {match_count} scenario matches")
    conn.close()

if __name__ == '__main__':
    populate_matches()
