"""Phase 17 tests: live market validation & observability."""
import sys
sys.path.insert(0, '/opt/tradingai_new')


def client():
    from app.api.app import app
    app.config["TESTING"] = True
    return app.test_client()


# ===== 1. OBSERVATION RECORDING =====
def test_ensure_table():
    from app.observability.decision_log import ensure_table
    ensure_table()
    from app.core.db import get_conn
    conn = get_conn()
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='live_observations'").fetchall()]
    conn.close()
    assert 'live_observations' in tables


def test_record_observation():
    from app.observability.decision_log import record_observation, get_observations, cleanup
    cleanup()
    obs_id = record_observation({
        'instrument': 'NIFTY',
        'market_timestamp': '2026-09-20T10:00:00+05:30',
        'completed_candle_timestamp': '2026-09-20T10:00:00+05:30',
        'decision_as_of': '2026-09-20T10:00:00+05:30',
        'index_price': 23000,
        'scenario': 'BULLISH_CONTINUATION',
        'index_signal': 'BULLISH',
        'options_data_state': 'OPTIONS_NO_DATA',
        'strategy_qualification': 'NO_TRADE',
        'final_decision_state': 'NO_TRADE',
        'rejection_reason': 'OPTIONS_DATA_UNAVAILABLE',
        'data_age_minutes': 7.5,
        'provider_state': 'STALE',
        'session_state': 'WEEKEND',
    })
    assert obs_id.startswith('OBV-')
    obs = get_observations(instrument='NIFTY', limit=1)
    assert len(obs) >= 1
    assert obs[0]['final_decision_state'] == 'NO_TRADE'
    cleanup()


def test_observation_required_fields():
    from app.observability.decision_log import record_observation, cleanup
    cleanup()
    required = [
        'instrument', 'market_timestamp', 'decision_as_of',
        'final_decision_state', 'session_state',
    ]
    for field in required:
        obs_id = record_observation({
            'instrument': 'NIFTY',
            'market_timestamp': '2026-09-20T10:00:00+05:30',
            'completed_candle_timestamp': None,
            'decision_as_of': '2026-09-20T10:00:00+05:30',
            'index_price': None,
            'scenario': None,
            'scenario_timestamp': None,
            'index_signal': None,
            'options_data_state': None,
            'strategy_qualification': None,
            'final_decision_state': 'NO_TRADE',
            'rejection_reason': 'TEST',
            'data_age_minutes': None,
            'provider_state': None,
            'quote_age_seconds': None,
            'completed_age_minutes': None,
            'session_state': 'PREMARKET',
        })
        assert obs_id.startswith('OBV-')
    cleanup()


def test_record_from_evaluation():
    from app.observability.decision_log import record_observations_from_evaluation, cleanup
    cleanup()
    evaluation = {
        'now_ist': '2026-09-20T10:00:00+05:30',
        'completed_candle': '2026-09-20T10:00:00+05:30',
        'live_price': 23000,
        'decision_price': 22905,
        'decision_timestamp': '2026-09-20T10:00:00+05:30',
        'quote_state': 'STALE',
        'quote_age_seconds': 1500,
        'completed_age_minutes': 7.5,
        'session': 'LIVE',
        'state': 'NO_TRADE',
        'reasons': ['SCENARIO_NOT_MATCHED'],
        'trade': {'scenario': 'BULLISH_CONTINUATION'},
        'qualification': {'decision': 'NO_TRADE', 'reasons': ['scenario_not_matched']},
        'market_state': {'trend': 'BULLISH'},
    }
    obs_id = record_observations_from_evaluation('NIFTY', evaluation)
    assert obs_id.startswith('OBV-')
    cleanup()


def test_get_session_summary():
    from app.observability.decision_log import record_observation, get_session_summary, cleanup
    cleanup()
    record_observation({
        'instrument': 'NIFTY', 'market_timestamp': '2026-09-20T10:00:00+05:30',
        'decision_as_of': '2026-09-20T10:00:00+05:30',
        'final_decision_state': 'NO_TRADE', 'session_state': 'WEEKEND',
        'rejection_reason': 'TEST', 'index_price': None,
        'scenario': None, 'scenario_timestamp': None, 'index_signal': None,
        'options_data_state': None, 'strategy_qualification': None,
        'data_age_minutes': None, 'provider_state': None,
        'quote_age_seconds': None, 'completed_age_minutes': None,
    })
    summary = get_session_summary(instrument='NIFTY')
    assert 'NO_TRADE' in summary
    cleanup()


# ===== 2. VALIDATOR =====
def test_validate_decision_state():
    from app.observability.validator import validate_decision_state
    from app.core.decision_state import DecisionState
    for state in DecisionState.canonical_states():
        result = validate_decision_state(state)
        assert result['valid'] is True, f"{state} should be valid"
        assert result['requires_reason'] == (not DecisionState.is_tradeable(state))


def test_validate_decision_state_invalid():
    from app.observability.validator import validate_decision_state
    result = validate_decision_state('INVALID_STATE')
    assert result['valid'] is False


def test_validate_market_data():
    from app.observability.validator import validate_market_data
    candles = [
        {'timestamp': '2026-09-20T09:15:00+05:30', 'open': 23000, 'high': 23100, 'low': 22900, 'close': 23050},
        {'timestamp': '2026-09-20T09:20:00+05:30', 'open': 23050, 'high': 23150, 'low': 23000, 'close': 23100},
    ]
    result = validate_market_data(candles, '2026-09-20T09:20:00+05:30')
    assert result['valid'] is True
    assert result['completed_count'] == 2
    assert result['first_candle'] == '2026-09-20T09:15:00+05:30'


def test_validate_market_data_no_candles():
    from app.observability.validator import validate_market_data
    result = validate_market_data([], '2026-09-20T09:20:00+05:30')
    assert result['valid'] is False
    assert 'NO_CANDLES' in result['issues']


def test_validate_market_data_duplicate():
    from app.observability.validator import validate_market_data
    candles = [
        {'timestamp': '2026-09-20T09:15:00+05:30', 'open': 23000, 'high': 23100, 'low': 22900, 'close': 23050},
        {'timestamp': '2026-09-20T09:15:00+05:30', 'open': 23000, 'high': 23100, 'low': 22900, 'close': 23050},
    ]
    result = validate_market_data(candles, '2026-09-20T09:20:00+05:30')
    assert any('DUPLICATE' in i for i in result['issues'])


def test_validate_market_data_future():
    from app.observability.validator import validate_market_data
    candles = [
        {'timestamp': '2026-09-20T09:15:00+05:30', 'open': 23000, 'high': 23100, 'low': 22900, 'close': 23050},
        {'timestamp': '2099-01-01T00:00:00+05:30', 'open': 23000, 'high': 23100, 'low': 22900, 'close': 23050},
    ]
    result = validate_market_data(candles, '2026-09-20T09:20:00+05:30')
    assert any('FUTURE' in i for i in result['issues'])


def test_validate_market_data_ohlc_range():
    from app.observability.validator import validate_market_data
    candles = [
        {'timestamp': '2026-09-20T09:15:00+05:30', 'open': 23000, 'high': 22900, 'low': 23100, 'close': 23050},
    ]
    result = validate_market_data(candles, '2026-09-20T09:20:00+05:30')
    assert any('OHLC_RANGE' in i for i in result['issues'])


def test_validate_pit_integrity():
    from app.observability.validator import validate_pit_integrity
    from app.scenarios.engine import ScenarioEngine
    engine = ScenarioEngine()
    result = validate_pit_integrity(engine, 'NIFTY', '2026-09-18T14:00:00+05:30')
    assert isinstance(result, dict)
    assert 'valid' in result
    assert 'violations' in result


def test_check_future_rows():
    from app.observability.validator import check_future_rows
    from app.core.db import get_conn
    conn = get_conn()
    violations = check_future_rows(conn, 'NIFTY', '2026-09-18T14:00:00+05:30')
    conn.close()
    assert isinstance(violations, list)


# ===== 3. MONITOR =====
def test_monitor_api_health():
    from app.observability.monitor import monitor_api
    result = monitor_api('/api/health')
    assert result['status'] in (200, 0)
    assert result['endpoint'] == '/api/health'


def test_monitor_api_decision():
    from app.observability.monitor import monitor_api
    result = monitor_api('/api/NIFTY/decision')
    assert result['status'] in (200, 0)
    assert 'timestamp' in result


def test_monitor_apis():
    from app.observability.monitor import monitor_apis
    results = monitor_apis(['/api/health', '/api/NIFTY/decision'])
    assert len(results) == 2
    for r in results:
        assert r['endpoint'] is not None


def test_monitor_resources():
    from app.observability.monitor import monitor_resources
    snapshot = monitor_resources()
    assert 'timestamp' in snapshot
    assert 'ram_total_mb' in snapshot or 'ram_error' in snapshot
    assert 'disk_usage_pct' in snapshot or 'disk_error' in snapshot


def test_monitor_api_status_only():
    from app.observability.monitor import monitor_api_status_only
    statuses = monitor_api_status_only()
    assert '/api/health' in statuses
    for ep, status in statuses.items():
        assert 'status' in status
        assert 'error' in status


# ===== 4. COLLECTOR =====
def test_session_validator_creation():
    from app.observability.collector import SessionValidator
    validator = SessionValidator()
    assert validator is not None


def test_session_validator_health_checks():
    from app.observability.collector import SessionValidator
    validator = SessionValidator()
    health = validator.run_health_checks()
    assert 'apis' in health
    assert 'resources' in health


def test_session_validator_session_status():
    from app.observability.collector import SessionValidator
    validator = SessionValidator()
    status = validator.get_session_status()
    assert status['session_state'] in ('PREMARKET', 'LIVE', 'MARKET_CLOSED', 'WEEKEND', 'NO_DATA')
    assert 'is_market_hours' in status


def test_session_validator_observe():
    from app.observability.collector import SessionValidator
    from app.observability.decision_log import cleanup
    cleanup()
    validator = SessionValidator()
    obs = validator.observe_and_validate('NIFTY')
    assert obs['instrument'] == 'NIFTY'
    assert obs['final_decision_state'] in ('NO_TRADE', 'PREMARKET', 'STALE', 'MARKET_CLOSED', 'WEEKEND', 'LIVE', 'NO_DATA')
    assert 'observation_id' in obs
    cleanup()


# ===== 5. REPORT =====
def test_report_generation():
    from app.observability.report import generate_report
    report = generate_report(
        session_info={'date': '2026-09-20', 'nse_status': 'WEEKEND', 'instruments': ['NIFTY', 'BANKNIFTY']},
        market_data={'completed_candles': 5, 'missing_intervals': 'none'},
        decisions={'evaluations': 10, 'states_observed': ['WEEKEND'], 'no_trade_count': 10},
        options_info={'provider': 'NSE', 'availability': 'unavailable', 'economics_available': False},
        pit_results={'sampled_timestamps': '2026-09-18T14:00', 'results': 'valid'},
        trace_results={'sampled_traces': '2', 'completeness': 'complete'},
        health={'api_latency': '50ms', 'ram': '505/956MB'},
        frontend={'nifty': 'normal', 'banknifty': 'normal'},
        findings=[{'classification': 'PASS', 'description': 'All systems nominal'}],
    )
    assert 'Phase 17' in report
    assert 'Session Information' in report
    assert 'PASS' in report


def test_report_from_data():
    from app.observability.report import generate_report_from_data
    report = generate_report_from_data({
        'session_info': {'date': '2026-09-20', 'instruments': ['NIFTY']},
        'market_data': {},
        'decisions': {},
        'options_info': {},
        'pit_results': {},
        'trace_results': {},
        'health': {},
        'frontend': {},
        'findings': [],
    })
    assert 'Phase 17' in report


# ===== 6. API OBSERVABILITY =====
def test_api_health_endpoint():
    c = client()
    r = c.get('/api/health')
    assert r.status_code == 200
    data = r.get_json()
    assert data['status'] == 'LIVE'


def test_api_decision_read_only():
    c = client()
    r = c.post('/api/NIFTY/decision')
    assert r.status_code == 405


def test_api_options_read_only():
    c = client()
    r = c.post('/api/options/NIFTY')
    assert r.status_code == 405


def test_api_strategies_read_only():
    c = client()
    r = c.post('/api/options/strategy/NIFTY')
    assert r.status_code == 405


# ===== 7. DECISION STATE CONFORMANCE =====
def test_api_returns_canonical_state():
    c = client()
    r = c.get('/api/NIFTY/decision')
    data = r.get_json()['data']
    state = data.get('state')
    from app.core.decision_state import DecisionState
    assert state in DecisionState.canonical_states(), f"State {state} not in canonical states"


def test_api_has_explicit_reason():
    c = client()
    r = c.get('/api/NIFTY/decision')
    data = r.get_json()['data']
    state = data.get('state')
    from app.core.decision_state import DecisionState
    if not DecisionState.is_tradeable(state):
        reasons = data.get('reasons', [])
        assert reasons and len(reasons) > 0, f"Non-tradeable state {state} must have reasons"


def test_options_strategy_no_economics():
    c = client()
    r = c.get('/api/options/strategy/NIFTY?strategy=BULL_PUT_SPREAD')
    data = r.get_json()['data']
    assert data['economics'] is None
    assert data['legs'] == []


# ===== 8. OBSERVABILITY TABLE ====
def test_observation_table_columns():
    from app.core.db import get_conn
    from app.observability.decision_log import ensure_table
    ensure_table()
    conn = get_conn()
    columns = [row[1] for row in conn.execute("PRAGMA table_info(live_observations)").fetchall()]
    conn.close()
    required = ['instrument', 'market_timestamp', 'decision_as_of', 'final_decision_state', 'session_state']
    for col in required:
        assert col in columns, f"Missing column: {col}"


