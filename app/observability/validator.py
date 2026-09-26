"""Live validation: PIT integrity, market data, decision state validation.

Verifies the production pipeline during live sessions:
- PIT integrity: scenario.created_at <= T, match.timestamp <= T, candle <= T
- Market data: candles arrive, completed only, no future, no duplicates
- Decision states: correct behavior for each state encountered
"""
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

_IST = ZoneInfo('Asia/Kolkata')


def validate_pit_integrity(scenario_engine, instrument: str, timestamp: str) -> dict:
    """Verify PIT integrity for a sampled decision timestamp.
    Returns {valid: bool, violations: [], details: {}}
    """
    result = scenario_engine.get_scenario_for_timestamp(instrument, timestamp)
    violations = []
    details = {'timestamp': timestamp, 'scenario_found': result is not None}

    if result and result.get('candidate'):
        cand = result['candidate']
        cand_created = cand.get('created_at', '')
        if cand_created > timestamp:
            violations.append(f"SCENARIO_FUTURE: {cand_created} > {timestamp}")
        details['scenario_created_at'] = cand_created

    if result and result.get('match'):
        match_ts = result['match'].get('timestamp', '')
        if match_ts > timestamp:
            violations.append(f"MATCH_FUTURE: {match_ts} > {timestamp}")
        details['match_timestamp'] = match_ts

    return {
        'valid': len(violations) == 0,
        'violations': violations,
        'details': details,
    }


def validate_market_data(candles: list, completed_ts: str) -> dict:
    """Validate live candle data integrity.
    Returns {valid: bool, issues: [], first_candle, last_candle, completed_count, missing_intervals, duplicates, stale}
    """
    issues = []
    if not candles:
        return {'valid': False, 'issues': ['NO_CANDLES'], 'completed_count': 0}

    seen = set()
    duplicates = []
    missing_intervals = []
    stale = []
    timestamps = []

    for c in candles:
        ts = c.get('timestamp', '')
        timestamps.append(ts)
        if ts in seen:
            issues.append(f'DUPLICATE_CANDLE:{ts}')
            duplicates.append(ts)
        seen.add(ts)
        try:
            dt = datetime.fromisoformat(ts)
            if dt > datetime.fromisoformat(completed_ts):
                issues.append(f'FUTURE_CANDLE:{ts}')
                stale.append(ts)
        except (ValueError, TypeError):
            issues.append(f'INVALID_TIMESTAMP:{ts}')
        try:
            o, h, l, cl = (float(c['open']), float(c['high']),
                           float(c['low']), float(c['close']))
            if not (o > 0 and h > 0 and l > 0 and cl > 0):
                issues.append(f'NON_POSITIVE_PRICE:{ts}')
            if h < l:
                issues.append(f'HIGH_BELOW_LOW:{ts}')
            if not (l - 1e-9 <= o <= h + 1e-9 and l - 1e-9 <= cl <= h + 1e-9):
                issues.append(f'OHLC_RANGE_VIOLATION:{ts}')
        except (KeyError, TypeError, ValueError):
            issues.append(f'NON_NUMERIC_OHLC:{ts}')

    timestamps.sort()
    # Filter out future candles (beyond completed_ts) for interval check
    valid_ts = [ts for ts in timestamps if ts <= completed_ts]
    if len(valid_ts) > 1:
        expected = set()
        first = valid_ts[0]
        current = first
        max_iterations = 10000
        iterations = 0
        while current <= valid_ts[-1] and iterations < max_iterations:
            expected.add(current[:19] if len(current) > 19 else current)
            dt = datetime.fromisoformat(current)
            dt += timedelta(minutes=5)
            current = dt.isoformat()
            iterations += 1
        for exp in expected:
            if exp not in set(valid_ts):
                missing_intervals.append(exp)

    return {
        'valid': len(issues) == 0 and len(stale) == 0,
        'issues': issues,
        'first_candle': timestamps[0] if timestamps else None,
        'last_candle': timestamps[-1] if timestamps else None,
        'completed_count': len(timestamps),
        'missing_intervals': missing_intervals,
        'duplicates': duplicates,
        'stale': stale,
    }


def validate_decision_state(state: str) -> dict:
    """Validate that a decision state is a recognized canonical state.
    Returns {valid: bool, is_tradeable: bool, requires_reason: bool}
    """
    from app.core.decision_state import DecisionState
    canonical = DecisionState.canonical_states()
    return {
        'valid': state in canonical,
        'is_tradeable': DecisionState.is_tradeable(state),
        'requires_reason': not DecisionState.is_tradeable(state),
    }


def check_future_rows(conn, instrument: str, timestamp: str) -> list:
    """Check that no future rows affect a decision at `timestamp`.
    Scans scenario_candidates and scenario_matches for future rows.
    """
    violations = []
    future_scenarios = conn.execute(
        "SELECT candidate_id, created_at FROM scenario_candidates WHERE instrument_id=? AND created_at > ?",
        (instrument, timestamp)
    ).fetchall()
    for fs in future_scenarios:
        violations.append(f"FUTURE_SCENARIO:{fs['candidate_id']} created_at={fs['created_at']}")

    future_matches = conn.execute(
        "SELECT match_id, timestamp FROM scenario_matches WHERE instrument_id=? AND timestamp > ?",
        (instrument, timestamp)
    ).fetchall()
    for fm in future_matches:
        violations.append(f"FUTURE_MATCH:{fm['match_id']} timestamp={fm['timestamp']}")

    return violations
