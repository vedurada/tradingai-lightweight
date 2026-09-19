#!/usr/bin/env python3
import sys, os, json, sqlite3
sys.path.insert(0, '/opt/tradingai_new')
from datetime import datetime
from zoneinfo import ZoneInfo
from app.core.db import get_conn

_IST = ZoneInfo('Asia/Kolkata')

def populate_matches():
    conn = get_conn()
    candidates = conn.execute("SELECT * FROM scenario_candidates WHERE status='CONFIRMED'").fetchall()
    print(f"Found {len(candidates)} confirmed candidates")

    for c in candidates:
        match_id = f"SM-{c['candidate_id']}"
        match_state = 'CONFIRMED'
        evidence = ['Confirmed by deterministic rules']
        try:
            conn.execute('''INSERT OR IGNORE INTO scenario_matches
                (match_id, candidate_id, instrument_id, timestamp, match_state, evidence, confidence, confirmation_evidence, invalidation_evidence, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)''',
                (match_id, c['candidate_id'], c['instrument_id'], c['created_at'],
                 match_state, json.dumps(evidence), 1.0,
                 json.dumps(evidence), json.dumps([]), c['created_at']))
        except sqlite3.IntegrityError:
            pass
    conn.commit()
    match_count = conn.execute("SELECT COUNT(*) FROM scenario_matches").fetchone()[0]
    print(f"Created {match_count} scenario matches")
    conn.close()

if __name__ == '__main__':
    populate_matches()
