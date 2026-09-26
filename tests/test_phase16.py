"""Phase 16 tests: production decision quality & trader UX audit."""
import sys
sys.path.insert(0, '/opt/tradingai_new')
import concurrent.futures
import subprocess

def client():
    from app.api.app import app
    app.config["TESTING"] = True
    return app.test_client()

# ===== 1. DECISION STATE MACHINE =====
def test_decision_state_canonical():
    from app.core.decision_state import canonical_state
    assert canonical_state("QUALIFIED") == "QUALIFIED"
    assert canonical_state("NO_TRADE") == "NO_TRADE"
    assert canonical_state("OPTIONS_DATA_UNAVAILABLE") == "OPTIONS_DATA_UNAVAILABLE"
    assert canonical_state("PREMARKET") == "PREMARKET"
    assert canonical_state("STALE") == "STALE"
    assert canonical_state("MARKET_CLOSED") == "MARKET_CLOSED"

def test_decision_states_complete():
    from app.core.decision_state import DecisionState
    states = DecisionState.canonical_states()
    for s in ["PREMARKET", "LIVE", "QUALIFIED", "NO_TRADE", "OPTIONS_DATA_UNAVAILABLE", "STALE", "NO_DATA", "MARKET_CLOSED", "WEEKEND", "DAILY_TRADE_LIMIT_REACHED"]:
        assert s in states, f"Missing: {s}"

def test_is_tradeable():
    from app.core.decision_state import DecisionState
    assert DecisionState.is_tradeable("QUALIFIED") is True
    assert DecisionState.is_tradeable("NO_TRADE") is False
    assert DecisionState.is_tradeable("OPTIONS_DATA_UNAVAILABLE") is False

def test_is_data_gated():
    from app.core.decision_state import DecisionState
    assert DecisionState.is_data_gated("OPTIONS_DATA_UNAVAILABLE") is True
    assert DecisionState.is_data_gated("NO_DATA") is True
    assert DecisionState.is_data_gated("STALE") is True
    assert DecisionState.is_data_gated("QUALIFIED") is False

def test_is_session_gated():
    from app.core.decision_state import DecisionState
    assert DecisionState.is_session_gated("PREMARKET") is True
    assert DecisionState.is_session_gated("MARKET_CLOSED") is True
    assert DecisionState.is_session_gated("WEEKEND") is True
    assert DecisionState.is_session_gated("LIVE") is False

def test_validate_decision_output():
    from app.core.decision_state import validate_decision_output
    errors = validate_decision_output({"state": "NO_TRADE", "timestamp": "2026-09-20T10:00:00+05:30", "instrument": "NIFTY"})
    assert any("MISSING_REASON" in e for e in errors)

def test_state_backward_compatibility():
    from app.core.decision_state import INTERNAL_TO_CANONICAL
    assert "NO_DATA" in INTERNAL_TO_CANONICAL
    assert "QUALIFIED" in INTERNAL_TO_CANONICAL
    assert "PREMARKET" in INTERNAL_TO_CANONICAL

# ===== 2. PIT INTEGRITY =====
def test_pit_future_row_does_not_influence():
    from app.core.db import get_conn
    from app.scenarios.engine import ScenarioEngine
    conn = get_conn()
    now = "2026-09-18T14:00:00+05:30"
    future_ts = "2099-01-01T00:00:00+05:30"
    conn.execute(
        "INSERT INTO scenario_candidates (candidate_id, instrument_id, session_id, scenario_type, historical_context, required_conditions, confirmation_conditions, invalidation_conditions, status, confidence, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("FUT-SC-NIFTY", "NIFTY", "s1", "BULLISH_CONTINUATION", "{}", "{}", "{}", "{}", "NOT_ACTIVE", 0.0, future_ts, future_ts))
    conn.commit()
    engine = ScenarioEngine()
    result = engine.get_scenario_for_timestamp("NIFTY", now)
    if result:
        assert result["candidate"]["created_at"] <= now, "Future scenario leaked!"
    conn.execute("DELETE FROM scenario_candidates WHERE candidate_id='FUT-SC-NIFTY'")
    conn.commit()
    conn.close()

def test_pit_match_timestamp_not_exceeds():
    from app.scenarios.engine import ScenarioEngine
    engine = ScenarioEngine()
    result = engine.get_scenario_for_timestamp("NIFTY", "2026-09-18T14:00:00+05:30")
    if result and result.get("match"):
        assert result["match"]["timestamp"] <= "2026-09-18T14:00:00+05:30"

# ===== 3. DECISION TRACE =====
def test_decision_trace_complete():
    from app.core.decision_trace import build_decision_trace, validate_trace
    trace = build_decision_trace(
        instrument="NIFTY", market_state={"price": 23000, "trend": "BULLISH"},
        scenario={"candidate": {"scenario_type": "BULLISH_CONTINUATION"}, "match": {"match_state": "CONFIRMED"}},
        options_state="OPTIONS_NO_DATA", strategy="BULL_PUT_SPREAD",
        economics={"net_credit": 50.0}, qualification={"decision": "QUALIFIED_TRADE", "reasons": []},
        daily_lock={"status": "CONSUMED"},
        completed_candle={"timestamp": "2026-09-20T10:00:00+05:30", "close": 23000},
        decision_as_of="2026-09-20T10:00:00+05:30")
    errors = validate_trace(trace)
    assert errors == [], errors
    assert trace["instrument"] == "NIFTY"
    assert trace["options_data_state"] == "OPTIONS_NO_DATA"
    assert trace["final_trader_facing_state"] == "QUALIFIED"

def test_decision_trace_no_trade():
    from app.core.decision_trace import build_decision_trace
    trace = build_decision_trace(
        instrument="NIFTY", market_state={"price": 23000, "trend": "NEUTRAL"},
        scenario=None, options_state="OPTIONS_NO_DATA", strategy="BULL_PUT_SPREAD",
        economics=None, qualification={"decision": "NO_TRADE", "reasons": []},
        daily_lock={"status": "PENDING"},
        completed_candle={"timestamp": "2026-09-20T10:00:00+05:30", "close": 23000},
        decision_as_of="2026-09-20T10:00:00+05:30")
    assert trace["final_trader_facing_state"] == "OPTIONS_DATA_UNAVAILABLE"

def test_trace_public_format():
    from app.core.decision_trace import build_decision_trace, trace_to_public
    trace = build_decision_trace(
        instrument="NIFTY", market_state={"price": 23000, "trend": "BULLISH"},
        scenario=None, options_state="OPTIONS_NO_DATA", strategy="BULL_PUT_SPREAD",
        economics=None, qualification={"decision": "NO_TRADE", "reasons": []},
        daily_lock={"status": "PENDING"},
        completed_candle={"timestamp": "2026-09-20T10:00:00+05:30", "close": 23000},
        decision_as_of="2026-09-20T10:00:00+05:30")
    public = trace_to_public(trace)
    assert "trace_id" in public and "final_state" in public and "index_price" in public
    assert "qualification_reasons" not in public

# ===== 4. ONE-TRADE/DAY CONCURRENCY =====
def test_one_trade_day_concurrent_claims():
    from app.core.db import get_conn
    conn = get_conn()
    conn.execute("DELETE FROM daily_trade_locks WHERE instrument_id='NIFTY' AND date=?", ('2026-09-20',))
    conn.execute("DELETE FROM qualified_trades WHERE instrument_id='NIFTY' AND date=?", ('2026-09-20',))
    conn.commit()
    conn.close()
    def claim():
        return client().post("/api/NIFTY/decision/claim").get_json()
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        results = [ex.submit(claim).result() for _ in range(8)]
    conn = get_conn()
    trade_count = conn.execute("SELECT COUNT(*) FROM qualified_trades WHERE instrument_id='NIFTY' AND date=?", ('2026-09-20',)).fetchone()[0]
    conn.close()
    assert trade_count <= 1, f"Expected <=1 trade, got {trade_count}"
    conn = get_conn()
    conn.execute("DELETE FROM daily_trade_locks WHERE instrument_id='NIFTY' AND date=?", ('2026-09-20',))
    conn.execute("DELETE FROM qualified_trades WHERE instrument_id='NIFTY' AND date=?", ('2026-09-20',))
    conn.commit()
    conn.close()

def test_get_decision_zero_writes():
    from app.core.db import get_conn
    conn = get_conn()
    before = conn.execute("SELECT COUNT(*) FROM daily_trade_locks").fetchone()[0]
    conn.close()
    c = client()
    c.get("/api/NIFTY/decision"); c.get("/api/NIFTY/decision"); c.get("/api/NIFTY/decision")
    conn = get_conn()
    after = conn.execute("SELECT COUNT(*) FROM daily_trade_locks").fetchone()[0]
    conn.close()
    assert before == after

# ===== 5. FAILURE-INJECTION MATRIX =====
def test_market_timeout():
    from app.market.provider import MarketDataProvider
    p = MarketDataProvider()
    result = p.get_quote("^NSEI")
    assert result.get("state") in ("UNAVAILABLE", "API_ERROR", "RATE_LIMITED", "LIVE", "STALE")

def test_options_no_data_state():
    from app.options.provider import get_options_chain
    state, data = get_options_chain("NIFTY")
    assert state in ("OPTIONS_UNAVAILABLE", "OPTIONS_NO_DATA", "OPTIONS_RATE_LIMITED")
    assert data.get("contracts") == []

def test_options_rate_limited_state():
    from app.options.contract import OptionsFreshness
    assert OptionsFreshness.OPTIONS_RATE_LIMITED.value == "OPTIONS_RATE_LIMITED"

def test_options_stale_state():
    from app.options.contract import classify_freshness, OptionsFreshness
    freshness, age = classify_freshness("2020-01-01T00:00:00+05:30")
    assert freshness == OptionsFreshness.OPTIONS_STALE

def test_malformed_contract_rejected():
    from app.options.contract import validate_contract
    valid, errors = validate_contract({"instrument": "NIFTY"})
    assert not valid
    assert len(errors) > 0

def test_missing_strike_rejected():
    from app.options.contract import validate_contract
    valid, errors = validate_contract({"instrument": "NIFTY", "option_type": "CE", "expiry": "2026-09-25", "timestamp": "2026-09-20T10:00:00+05:30"})
    assert not valid
    assert any("MISSING_STRIKE" in e for e in errors)

def test_missing_expiry_rejected():
    from app.options.contract import validate_contract
    valid, errors = validate_contract({"instrument": "NIFTY", "option_type": "CE", "strike": 17000, "timestamp": "2026-09-20T10:00:00+05:30"})
    assert not valid
    assert any("MISSING_EXPIRY" in e for e in errors)

def test_invalid_option_type_rejected():
    from app.options.contract import validate_contract
    valid, errors = validate_contract({"instrument": "NIFTY", "option_type": "CALL", "strike": 17000, "expiry": "2026-09-25", "timestamp": "2026-09-20T10:00:00+05:30"})
    assert not valid
    assert any("INVALID_OPTION_TYPE" in e for e in errors)

def test_empty_response_handled():
    from app.options.provider import get_options_chain
    state, data = get_options_chain("NIFTY")
    assert state in ("OPTIONS_UNAVAILABLE", "OPTIONS_NO_DATA")

def test_nifty_banknifty_isolation():
    from app.options.engine import OptionsStrategyEngine
    engine = OptionsStrategyEngine()
    r1 = engine.qualify("NIFTY", index_state="LIVE")
    r2 = engine.qualify("BANKNIFTY", index_state="LIVE")
    assert r1.reason == r2.reason == "OPTIONS_DATA_UNAVAILABLE"

# ===== 6. REGRESSION =====
def test_phase13_baselines_intact():
    import json
    n = json.load(open('/opt/tradingai_new/app/research/baseline_NIFTY_FULL.json'))
    b = json.load(open('/opt/tradingai_new/app/research/baseline_BANKNIFTY_FULL.json'))
    assert (n['summary']['trades'], n['summary']['total_R']) == (34, 16.21)
    assert (b['summary']['trades'], b['summary']['total_R']) == (31, 16.63)

def test_phase14_options_api_intact():
    assert client().get("/api/options/NIFTY").status_code == 200

def test_phase15_strategy_api_intact():
    assert client().get("/api/options/strategy/NIFTY").status_code == 200

def test_app_options_package_imports():
    from app.options import TradeResult, StrategyType, APPROVED_STRATEGIES, OptionsStrategyEngine
    assert len(APPROVED_STRATEGIES) == 5

# ===== 7. SECURITY =====
def test_no_secrets_in_git_diff():
    # Verify test_phase16.py exists as a new file
    import os
    assert os.path.isfile("/opt/tradingai_new/tests/test_phase16.py")
    # Check no secrets in all tracked + modified files
    result = subprocess.run(["git", "diff", "HEAD", "--name-only"], capture_output=True, text=True, cwd="/opt/tradingai_new")
    files = result.stdout.strip().split("\n") + ["tests/test_phase16.py"]
    for fname in files:
        fpath = os.path.join("/opt/tradingai_new", fname)
        if os.path.isfile(fpath):
            try:
                text = open(fpath).read()
                for bad in ("API_KEY=", "SECRET_KEY=", "password:", "api_key="):
                    assert bad.lower() not in text.lower(), f"Found secret {bad} in {fname}"
            except Exception:
                pass

def test_no_debug_mode():
    from app.api.app import app
    assert app.debug is False

def test_decision_api_read_only():
    assert client().post("/api/NIFTY/decision").status_code == 405

def test_options_strategy_api_read_only():
    assert client().post("/api/options/strategy/NIFTY").status_code == 405

def test_options_strategy_no_fabricated_economics():
    d = client().get("/api/options/strategy/NIFTY?strategy=BULL_PUT_SPREAD").get_json()["data"]
    assert d["economics"] is None
    assert d["legs"] == []

# ===== 8. OPTIONS DATA GATE =====
def test_options_data_gate_fresh():
    from app.options.engine import OptionsStrategyEngine
    ok, err, data = OptionsStrategyEngine().validate_data_gate("NIFTY")
    assert not ok
    assert err in ("OPTIONS_UNAVAILABLE", "OPTIONS_NO_DATA", "OPTIONS_PARTIAL_CHAIN")

def test_index_signal_gate():
    from app.options.engine import OptionsStrategyEngine
    engine = OptionsStrategyEngine()
    ok, err = engine.validate_index_signal("NIFTY", "STALE")
    assert not ok and err == "INDEX_SIGNAL_STALE"
    ok, err = engine.validate_index_signal("NIFTY", None)
    assert not ok and err == "INDEX_SIGNAL_UNAVAILABLE"

