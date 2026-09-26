"""Decision observation recorder.

Lightweight, production-safe logging of every decision evaluation.
One row per evaluation with all required fields.
No internal implementation details exposed.
No excessive logging — one row per evaluation, no per-request noise.
"""
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.db import get_conn, DB_PATH

_IST = ZoneInfo('Asia/Kolkata')

OBS_TABLE = 'live_observations'

CREATE_TABLE = f"""
CREATE TABLE IF NOT EXISTS {OBS_TABLE} (
    observation_id TEXT PRIMARY KEY,
    instrument TEXT NOT NULL,
    market_timestamp TEXT NOT NULL,
    completed_candle_timestamp TEXT,
    decision_as_of TEXT NOT NULL,
    index_price REAL,
    scenario TEXT,
    scenario_timestamp TEXT,
    index_signal TEXT,
    options_data_state TEXT,
    strategy_qualification TEXT,
    final_decision_state TEXT NOT NULL,
    rejection_reason TEXT,
    data_age_minutes REAL,
    provider_state TEXT,
    quote_age_seconds REAL,
    completed_age_minutes REAL,
    session_state TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(instrument, decision_as_of)
)
"""

CLEANUP_SQL = f"""
DELETE FROM {OBS_TABLE}
WHERE session_state NOT IN ('PREMARKET', 'LIVE', 'MARKET_CLOSED', 'WEEKEND', 'HOLIDAY')
   OR created_at < datetime('now', '-7 days')
"""


def ensure_table():
    conn = get_conn()
    conn.execute(CREATE_TABLE)
    conn.commit()
    conn.close()


def record_observation(observation: dict) -> str:
    """Record a single decision observation. Returns observation_id."""
    ensure_table()
    obs_id = observation.get('observation_id') or f"OBV-{datetime.now(_IST).strftime('%Y%m%d%H%M%S%f')}"
    conn = get_conn()
    conn.execute(
        f"""INSERT OR REPLACE INTO {OBS_TABLE}
        (observation_id, instrument, market_timestamp, completed_candle_timestamp,
         decision_as_of, index_price, scenario, scenario_timestamp, index_signal,
         options_data_state, strategy_qualification, final_decision_state,
         rejection_reason, data_age_minutes, provider_state, quote_age_seconds,
         completed_age_minutes, session_state, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            obs_id,
            observation.get('instrument'),
            observation.get('market_timestamp'),
            observation.get('completed_candle_timestamp'),
            observation.get('decision_as_of'),
            observation.get('index_price'),
            observation.get('scenario'),
            observation.get('scenario_timestamp'),
            observation.get('index_signal'),
            observation.get('options_data_state'),
            observation.get('strategy_qualification'),
            observation.get('final_decision_state'),
            observation.get('rejection_reason'),
            observation.get('data_age_minutes'),
            observation.get('provider_state'),
            observation.get('quote_age_seconds'),
            observation.get('completed_age_minutes'),
            observation.get('session_state'),
            datetime.now(_IST).isoformat(),
        )
    )
    conn.commit()
    conn.close()
    cleanup()
    return obs_id


def cleanup():
    """Remove stale observations to keep DB small."""
    conn = get_conn()
    conn.execute(CLEANUP_SQL)
    conn.commit()
    conn.close()


def get_observations(instrument=None, since=None, limit=100):
    """Query observations. All read-only, no side effects."""
    conn = get_conn()
    query = f"SELECT * FROM {OBS_TABLE}"
    params = []
    conditions = []
    if instrument:
        conditions.append("instrument = ?")
        params.append(instrument)
    if since:
        conditions.append("created_at >= ?")
        params.append(since)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_session_summary(instrument=None):
    """Summary of observations for a session."""
    conn = get_conn()
    if instrument:
        rows = conn.execute(
            f"SELECT final_decision_state, COUNT(*) as count FROM {OBS_TABLE} WHERE instrument=? GROUP BY final_decision_state",
            (instrument,)
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT final_decision_state, COUNT(*) as count FROM {OBS_TABLE} GROUP BY final_decision_state"
        ).fetchall()
    conn.close()
    return {r['final_decision_state']: r['count'] for r in rows}


def record_observations_from_evaluation(instrument: str, evaluation: dict, options_state: str = None) -> str:
    """Convert a LiveEngine evaluation to an observation and record it.
    Lightweight: extracts only the required fields, no deep inspection.
    """
    trade = evaluation.get('trade') or {}
    qualification = evaluation.get('qualification') or {}
    obs_id = f"OBV-{instrument}-{evaluation.get('now_ist', datetime.now(_IST).isoformat())[:19]}"
    observation = {
        'observation_id': obs_id,
        'instrument': instrument,
        'market_timestamp': evaluation.get('now_ist'),
        'completed_candle_timestamp': evaluation.get('completed_candle'),
        'decision_as_of': evaluation.get('decision_timestamp') or evaluation.get('completed_candle'),
        'index_price': evaluation.get('live_price') or evaluation.get('decision_price'),
        'scenario': (trade or {}).get('scenario'),
        'scenario_timestamp': evaluation.get('scenario_timestamp') if isinstance(evaluation.get('scenario_timestamp'), str) else None,
        'index_signal': (evaluation.get('market_state') or {}).get('trend'),
        'options_data_state': options_state,
        'strategy_qualification': qualification.get('decision'),
        'final_decision_state': evaluation.get('state'),
        'rejection_reason': '; '.join(evaluation.get('reasons', [])),
        'data_age_minutes': evaluation.get('completed_age_minutes'),
        'provider_state': evaluation.get('quote_state'),
        'quote_age_seconds': evaluation.get('quote_age_seconds'),
        'completed_age_minutes': evaluation.get('completed_age_minutes'),
        'session_state': evaluation.get('session'),
    }
    return record_observation(observation)
