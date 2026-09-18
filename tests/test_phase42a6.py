from __future__ import annotations
import json, os, sys, tempfile, sqlite3, time
from datetime import datetime, timezone, timedelta
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
from db_schema import init_database
from scenario_activation_engine import ScenarioActivationEngine, ScenarioState, _detect_late_activation
from expected_movement_engine import ExpectedMovementEngine, ExpectedMovementResult, MIN_SAMPLE_SIZE, _get_volatility_regime, _get_positioning_state, _compute_percentile, _median, _get_time_of_day, _price_vs_vwap
from data_quality import DATA_QUALITY_LIVE, DATA_QUALITY_UNAVAILABLE
TEST_DB = os.path.join(tempfile.gettempdir(), f"t42a6_{int(time.time())}.db")
PH21 = '?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?'
PH_RO = '?,?,?,?,?,?,?,?,?,?'

def setup_module():
    if os.path.exists(TEST_DB): os.remove(TEST_DB)
    init_database(TEST_DB)
    conn = sqlite3.connect(TEST_DB)
    now = datetime.now(timezone.utc)
    now_ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    count = conn.execute("SELECT COUNT(*) FROM pre_market_scenarios").fetchone()[0]
    if count == 0:
        for i, (st, d, trig, conf, inv, em, hz) in enumerate([
            ("BULLISH_BREAKOUT", "LONG", 23200.0, json.dumps({"trigger": 23200.0}), json.dumps({"trigger_level": 23100.0}), 0.5, (23258.0, 23342.0)),
            ("BEARISH_BREAKOUT", "SHORT", 23000.0, json.dumps({"trigger": 23000.0}), json.dumps({"trigger_level": 23100.0}), 0.3, (None, None)),
        ]):
            sid = f"SCEN-{i:03d}"
            vals = (sid, "NIFTY", now.strftime("%Y-%m-%d"), st, d, trig, conf, inv, em, 60, hz[0], hz[1], "LIVE", 0, None, "ARMED", "[]", now_ts, None, None, None, None, None, 0, None, now_ts, None)
            conn.execute("INSERT INTO pre_market_scenarios VALUES (" + PH21 + ")", vals)
        vals2 = ("SCEN-002", "NIFTY", "2026-09-21", "BULLISH_BREAKOUT", "LONG", 23300.0, json.dumps({}), json.dumps({"trigger_level": 23200.0}), 0.8, 90, None, None, "LIVE", 0, None, "ACTIVATED", json.dumps([{"from": "ARMED", "to": "PRE_TRIGGER", "timestamp": now_ts, "price": 23295.0}, {"from": "PRE_TRIGGER", "to": "ACTIVATED", "timestamp": now_ts, "price": 23305.0}]), now_ts, None, None, None, None, None, 0, None, now_ts, None)
        conn.execute("INSERT INTO pre_market_scenarios VALUES (" + PH21 + ")", vals2)
        conn.commit()
    conn.close()

def teardown_module():
    if os.path.exists(TEST_DB): os.remove(TEST_DB)


class TestSchema:
    def test_states(self):
        assert all(s in [x.value for x in ScenarioState] for s in ["ARMED", "PRE_TRIGGER", "ACTIVATED", "CONFIRMED", "INVALIDATED", "EXPIRED", "COMPLETED"])
    def test_engine_init(self):
        assert ScenarioActivationEngine(TEST_DB).db_path == TEST_DB


class TestActivation:
    def setup_method(self): setup_module()
    def teardown_method(self): teardown_module(); setup_module()
    def test_active_scenarios(self):
        e = ScenarioActivationEngine(TEST_DB)
        c = {"timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "close": 23205.0, "volume": 500000}
        ms = {"vwap": 23150.0, "trend_state": "BULLISH", "market_regime": "BULLISH", "rsi": 55.0, "close": 23205.0}
        r = e.evaluate_activation("NIFTY", c, ms, session_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"), db_path=TEST_DB)
        assert len(r["results"]) >= 1 and all("new_state" in x for x in r["results"])
    def test_no_scenarios(self):
        e = ScenarioActivationEngine(TEST_DB)
        r = e.evaluate_activation("NOPE", {"close": 23205.0}, {"vwap": 23150.0}, session_date="2026-09-20", db_path=TEST_DB)
        assert r["scenarios_evaluated"] == 0 and r["data_quality"] == DATA_QUALITY_UNAVAILABLE
    def test_missing_close(self):
        e = ScenarioActivationEngine(TEST_DB)
        r = e.evaluate_activation("NIFTY", {"timestamp": "2026-09-20T10:00:00Z"}, {"vwap": 23150.0}, session_date="2026-09-20", db_path=TEST_DB)
        assert all(x.get("action") == "SKIPPED" for x in r["results"])
    def test_pre_trigger(self):
        e = ScenarioActivationEngine(TEST_DB)
        c = {"timestamp": "2026-09-20T10:00:00Z", "open": 23190.0, "high": 23210.0, "low": 23185.0, "close": 23199.0, "volume": 500000}
        ms = {"vwap": 23150.0, "trend_state": "BULLISH", "market_regime": "BULLISH", "rsi": 55.0, "close": 23199.0}
        r = e.evaluate_activation("NIFTY", c, ms, session_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"), db_path=TEST_DB)
        for x in r["results"]:
            if x["scenario_id"] == "SCEN-000": assert x["new_state"] in ("PRE_TRIGGER", "ACTIVATED", "CONFIRMED")
    def test_bullish_activation(self):
        e = ScenarioActivationEngine(TEST_DB)
        c = {"timestamp": "2026-09-20T10:00:00Z", "open": 23180.0, "high": 23250.0, "low": 23170.0, "close": 23260.0, "volume": 500000}
        ms = {"vwap": 23150.0, "trend_state": "BULLISH", "market_regime": "BULLISH", "rsi": 55.0, "close": 23260.0}
        r = e.evaluate_activation("NIFTY", c, ms, session_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"), db_path=TEST_DB)
        for x in r["results"]:
            if x["scenario_id"] == "SCEN-000": assert x["new_state"] in ("ACTIVATED", "PRE_TRIGGER", "CONFIRMED", "ARMED")
    def test_late_activation(self):
        e = ScenarioActivationEngine(TEST_DB)
        c = {"timestamp": "2026-09-20T10:00:00Z", "open": 23180.0, "high": 23400.0, "low": 23170.0, "close": 23380.0, "volume": 500000}
        ms = {"vwap": 23150.0, "trend_state": "BULLISH", "market_regime": "BULLISH", "rsi": 65.0, "close": 23380.0}
        r = e.evaluate_activation("NIFTY", c, ms, session_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"), db_path=TEST_DB)
        for x in r["results"]:
            if x["scenario_id"] == "SCEN-000": assert isinstance(x.get("late_activation_flag"), bool)
    def test_get_state(self):
        e = ScenarioActivationEngine(TEST_DB)
        s = e.get_scenario_state("SCEN-000", db_path=TEST_DB)
        assert s is not None and s["scenario_id"] == "SCEN-000"
    def test_update_state(self):
        e = ScenarioActivationEngine(TEST_DB)
        assert e.update_scenario_state("SCEN-000", ScenarioState.CONFIRMED.value, db_path=TEST_DB)
        assert e.get_scenario_state("SCEN-000", db_path=TEST_DB)["status"] == ScenarioState.CONFIRMED.value
    def test_no_future_data(self):
        e = ScenarioActivationEngine(TEST_DB)
        ct = "2026-09-20T10:00:00Z"
        c = {"timestamp": ct, "close": 23205.0, "high": 23210.0, "volume": 500000}
        ms = {"vwap": 23150.0, "trend_state": "BULLISH", "market_regime": "BULLISH", "close": 23205.0}
        r = e.evaluate_activation("NIFTY", c, ms, session_date="2026-09-20", db_path=TEST_DB)
        for x in r["results"]:
            if x.get("evidence_snapshot"):
                assert x["evidence_snapshot"].get("no_lookahead") is True
                assert x["evidence_snapshot"].get("data_used_timestamp") == ct


class TestMovement:
    def setup_method(self): setup_module()
    def teardown_method(self): teardown_module(); setup_module()
    def test_insufficient(self):
        e = ExpectedMovementEngine(TEST_DB)
        r = e.compute_expected_movement("NIFTY", "BULLISH_BREAKOUT", "2026-09-20", db_path=TEST_DB)
        assert r["data_status"] == "INSUFFICIENT_SAMPLE" and r["sample_size"] == 0
    def test_dimensions(self):
        e = ExpectedMovementEngine(TEST_DB)
        r = e.compute_expected_movement("NIFTY", "BULLISH_BREAKOUT", "2026-09-20", {"close": 23200.0, "vwap": 23150.0, "atr": 80.0, "market_regime": "BULLISH"}, db_path=TEST_DB)
        assert r["direction"] == "LONG" and r["volatility_regime"] in ("HIGH", "NORMAL", "LOW", "UNKNOWN")
        assert all(k in r for k in ["distance_from_vwap", "liquidity_event", "comparable_scenarios", "time_of_day"])
    def test_sufficient_data(self):
        conn = sqlite3.connect(TEST_DB)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for i in range(12):
            ts = f"2026-09-20T{9+i}:00:00Z"
            conn.execute("INSERT INTO research_outcome_tracking (outlook_id,instrument,candle_timestamp,outcome_5m,outcome_5m_return_pct,outcome_15m,outcome_15m_return_pct,outcome_30m,outcome_30m_return_pct,outcome_60m_return_pct) VALUES (" + PH_RO + ")", (f"OUT{i:03d}", "NIFTY", ts, "WIN", round(0.3 + i * 0.05, 4), "WIN", round(0.5 + i * 0.03, 4), "WIN", round(0.7 + i * 0.02, 4), round(1.0 + i * 0.01, 4)))
        conn.commit(); conn.close()
        e = ExpectedMovementEngine(TEST_DB)
        ms = {"close": 23200.0, "vwap": 23150.0, "atr": 80.0, "market_regime": "BULLISH"}
        r = e.compute_expected_movement("NIFTY", "BULLISH_BREAKOUT", "2026-09-20", ms, db_path=TEST_DB)
        assert r["data_status"] == "SUFFICIENT_DATA" and r["sample_size"] >= MIN_SAMPLE_SIZE
        assert r["median_favorable_move"] is not None and r["target_zone_low"] and r["target_zone_high"]
        assert r["target_zone_low"] < r["target_zone_high"] and r["expected_horizon_minutes"] == 60
    def test_percentiles(self):
        conn = sqlite3.connect(TEST_DB)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for i in range(15):
            ts = f"2026-09-20T{9+i}:00:00Z"
            conn.execute("INSERT INTO research_outcome_tracking (outlook_id,instrument,candle_timestamp,outcome_5m,outcome_5m_return_pct,outcome_15m,outcome_15m_return_pct,outcome_30m,outcome_30m_return_pct,outcome_60m_return_pct) VALUES (" + PH_RO + ")", (f"CP{i:03d}", "NIFTY", ts, "WIN", round(0.2 + (i % 5) * 0.1, 4), "WIN", round(0.4 + (i % 5) * 0.1, 4), "WIN", round(0.6 + (i % 5) * 0.1, 4), round(0.9 + (i % 5) * 0.1, 4)))
        conn.commit(); conn.close()
        e = ExpectedMovementEngine(TEST_DB)
        ms = {"close": 23200.0, "vwap": 23150.0, "atr": 80.0, "market_regime": "BULLISH"}
        r = e.compute_expected_movement("NIFTY", "BULLISH_BREAKOUT", "2026-09-20", ms, db_path=TEST_DB)
        assert r["median_favorable_move"] is not None and r["p25_favorable_move"] is not None and r["p75_favorable_move"] is not None
        assert r["p25_favorable_move"] <= r["median_favorable_move"] <= r["p75_favorable_move"]
    def test_bearish(self):
        e = ExpectedMovementEngine(TEST_DB)
        r = e.compute_expected_movement("NIFTY", "BEARISH_BREAKOUT", "2026-09-20", {"close": 23200.0, "vwap": 23150.0}, db_path=TEST_DB)
        assert r["direction"] == "SHORT"
    def test_record(self):
        e = ExpectedMovementEngine(TEST_DB)
        assert e.record_scenario_outcome("TO-001", "NIFTY", "2026-09-20", outcome_5m="WIN", outcome_5m_return_pct=0.5, outcome_15m="WIN", outcome_15m_return_pct=0.8, mfe_pct=0.9, mae_pct=0.2, target_reached=True, db_path=TEST_DB)
    def test_calibration_insufficient(self):
        assert ExpectedMovementEngine(TEST_DB).get_calibration_summary("NIFTY", db_path=TEST_DB)["data_status"] == "INSUFFICIENT_DATA"
    def test_fields(self):
        r = ExpectedMovementResult(symbol="N", scenario_type="BB", session_date="2026-09-20", direction="LONG", market_regime="BULLISH", volatility_regime="NORMAL", time_of_day="0930-1100", distance_from_vwap="ABOVE_VWAP", positioning_state="ABOVE_VWAP", liquidity_event="NORMAL", data_status="INSUFFICIENT_SAMPLE", sample_size=0, minimum_required=10, median_favorable_move=None, p25_favorable_move=None, p75_favorable_move=None, median_adverse_move=None, p25_adverse_move=None, p75_adverse_move=None, mfe=None, mae=None, target_hit_rate=None, time_to_target=None, time_to_invalidation=None, target_zone_low=None, target_zone_high=None, expected_horizon_minutes=None, comparable_scenarios=[], data_quality="DATA UNAVAILABLE", message="t").to_dict()
        assert r["data_status"] == "INSUFFICIENT_SAMPLE"
    def test_volatility(self):
        assert _get_volatility_regime(100.0, 23200.0) == "LOW" and _get_volatility_regime(200.0, 23200.0) == "NORMAL" and _get_volatility_regime(500.0, 23200.0) == "HIGH" and _get_volatility_regime(None, 23200.0) == "UNKNOWN"
    def test_positioning(self):
        assert _get_positioning_state({"close": 23300.0, "vwap": 23100.0}) == "ABOVE_VWAP_STRONG"
        assert _get_positioning_state({"close": 23180.0, "vwap": 23100.0}) == "ABOVE_VWAP"
        assert _get_positioning_state({"close": 23105.0, "vwap": 23100.0}) == "AT_VWAP"
        assert _get_positioning_state({"close": 23020.0, "vwap": 23100.0}) == "BELOW_VWAP"
        assert _get_positioning_state({"close": 22900.0, "vwap": 23100.0}) == "BELOW_VWAP_STRONG"
        assert _get_positioning_state({}) == "UNKNOWN"
    def test_vwap(self):
        assert _price_vs_vwap(23250.0, 23150.0) == "ABOVE_VWAP"
        assert _price_vs_vwap(23000.0, 23100.0) == "BELOW_VWAP"
        assert _price_vs_vwap(23150.0, 23150.0) == "AT_VWAP"
        assert _price_vs_vwap(23150.0, None) == "UNKNOWN"


class TestLate:
    def test_true(self):
        f, d = _detect_late_activation(23300.0, 23400.0, 0.3, 23200.0, "2026-09-20T10:00:00Z", "2026-09-20T10:30:00Z")
        assert f is True and d is not None
    def test_false(self):
        f, d = _detect_late_activation(23300.0, 23350.0, 1.0, 23200.0, "2026-09-20T10:00:00Z", "2026-09-20T10:30:00Z")
        assert f is False
    def test_insufficient(self):
        f, d = _detect_late_activation(None, 23400.0, 0.5, 23200.0, "2026-09-20T10:00:00Z", "2026-09-20T10:30:00Z")
        assert f is False and d is None
    def test_zero(self):
        f, d = _detect_late_activation(23300.0, 23400.0, 0, 23200.0, "2026-09-20T10:00:00Z", "2026-09-20T10:30:00Z")
        assert f is False


class TestMath:
    def test_percentile(self):
        v = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert _median(v) == 3.0 and _compute_percentile(v, 25) == 2.0 and _compute_percentile(v, 50) == 3.0 and _compute_percentile(v, 75) == 4.0
    def test_empty(self):
        assert _median([]) is None and _compute_percentile([], 50) is None
    def test_tod(self):
        assert _get_time_of_day("") == "UNKNOWN" and _get_time_of_day(None) == "UNKNOWN"
