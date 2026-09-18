from __future__ import annotations

import os
import sys
import json
import tempfile
import sqlite3
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from pre_market_scenario_engine import (
    PreMarketScenarioEngine,
    DataReadinessGate,
    KeyLevelAnalyzer,
    generate_scenarios,
    REQUIRED_SCENARIO_FIELDS,
    SCENARIO_STATE_MACHINE,
    SCENARIO_TYPES,
    MAX_SCENARIOS_PER_INSTRUMENT,
)

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "database",
    "tradingai.db",
)


class TestDataReadinessGate:
    def setup_method(self):
        self.gate = DataReadinessGate(DB_PATH)

    def test_gate_returns_dict(self):
        result = self.gate.check("NIFTY")
        assert isinstance(result, dict)
        assert "instrument" in result
        assert "sources" in result
        assert "overall" in result
        assert "issues" in result

    def test_gate_indicators_available(self):
        result = self.gate.check("NIFTY")
        assert result["sources"]["indicators"]["available"] is True

    def test_gate_regime_available(self):
        result = self.gate.check("NIFTY")
        assert result["sources"]["market_regime"]["available"] is True

    def test_gate_price_available(self):
        result = self.gate.check("NIFTY")
        assert result["sources"]["price_5m"]["available"] is True

    def test_gate_volume_flag(self):
        result = self.gate.check("NIFTY")
        has_volume = result["sources"]["price_5m"].get("has_volume", False)
        assert not has_volume, "Index volume should be 0/unavailable"
        assert "VOLUME_UNAVAILABLE" in result["issues"]

    def test_gate_banknifty(self):
        result = self.gate.check("BANKNIFTY")
        assert result["sources"]["indicators"]["available"] is True

    def test_gate_unknown_symbol(self):
        result = self.gate.check("XXXUNKNOWN")
        assert result["sources"]["indicators"]["available"] is False
        assert "NO_INDICATORS" in result["issues"]
        assert result["overall"] in ("UNAVAILABLE", "PARTIAL")

    def test_gate_overall_classification(self):
        result = self.gate.check("NIFTY")
        assert result["overall"] in ("LIVE", "PARTIAL", "UNAVAILABLE")


class TestKeyLevelAnalyzer:
    def setup_method(self):
        self.analyzer = KeyLevelAnalyzer(DB_PATH)

    def test_analyzer_returns_dict(self):
        result = self.analyzer.analyze("NIFTY", {})
        assert isinstance(result, dict)
        assert "available" in result

    def test_analyzer_has_levels(self):
        result = self.analyzer.analyze("NIFTY", {})
        assert result["available"] is True
        assert "support_levels" in result
        assert "resistance_levels" in result

    def test_support_levels_filtered(self):
        result = self.analyzer.analyze("NIFTY", {})
        for level in result.get("support_levels", []):
            assert level > 0, f"Support level should be positive, got {level}"

    def test_resistance_levels_filtered(self):
        result = self.analyzer.analyze("NIFTY", {})
        for level in result.get("resistance_levels", []):
            assert level > 0, f"Resistance level should be positive, got {level}"

    def test_levels_sorted(self):
        result = self.analyzer.analyze("NIFTY", {})
        sup = result.get("support_levels", [])
        assert sup == sorted(sup, reverse=True), "Support should be high-to-low"
        res = result.get("resistance_levels", [])
        assert res == sorted(res), "Resistance should be low-to-high"

    def test_analyzer_banknifty(self):
        result = self.analyzer.analyze("BANKNIFTY", {})
        assert result["available"] is True
        assert "current_price" in result

    def test_analyzer_nothing(self):
        result = self.analyzer.analyze("XXXNOTHING", {})
        assert result["available"] is False


class TestScenarioGeneration:
    def setup_method(self):
        self.engine = PreMarketScenarioEngine(DB_PATH)

    def test_generate_returns_dict(self):
        result = self.engine.generate_scenarios("NIFTY")
        assert isinstance(result, dict)
        assert "scenarios" in result
        assert "scenario_count" in result
        assert "data_readiness" in result
        assert "key_levels" in result

    def test_scenario_count_max(self):
        result = self.engine.generate_scenarios("NIFTY", max_scenarios=3)
        assert result["scenario_count"] <= MAX_SCENARIOS_PER_INSTRUMENT

    def test_scenario_count_min(self):
        result = self.engine.generate_scenarios("NIFTY")
        assert result["scenario_count"] >= 1

    def test_scenario_count_with_limit(self):
        result = self.engine.generate_scenarios("NIFTY", max_scenarios=1)
        assert result["scenario_count"] == 1

    def test_scenario_types_valid(self):
        result = self.engine.generate_scenarios("NIFTY")
        for s in result["scenarios"]:
            assert s["scenario_type"] in SCENARIO_TYPES, (
                f"Unknown scenario type: {s['scenario_type']}"
            )

    def test_all_scenario_types_exist(self):
        assert len(SCENARIO_TYPES) == 9
        expected = {
            "BULLISH_BREAKOUT", "BEARISH_BREAKDOWN",
            "BULLISH_CONTINUATION", "BEARISH_CONTINUATION",
            "BULLISH_REVERSAL", "BEARISH_REVERSAL",
            "RANGE_ROTATION", "VOLATILITY_EXPANSION", "VOLATILITY_COMPRESSION",
        }
        assert set(SCENARIO_TYPES) == expected


class TestScenarioCompleteness:
    def setup_method(self):
        self.engine = PreMarketScenarioEngine(DB_PATH)

    def test_all_required_fields_present(self):
        result = self.engine.generate_scenarios("NIFTY")
        for scenario in result["scenarios"]:
            for field in REQUIRED_SCENARIO_FIELDS:
                assert field in scenario, (
                    f"Scenario {scenario.get('scenario_id', '?')} missing field: {field}"
                )

    def test_historical_probability_null_when_unavailable(self):
        result = self.engine.generate_scenarios("NIFTY")
        for scenario in result["scenarios"]:
            assert scenario["historical_probability"] is None, (
                "Should be None when no historical data"
            )

    def test_status_is_armed(self):
        result = self.engine.generate_scenarios("NIFTY")
        for scenario in result["scenarios"]:
            assert scenario["status"] == "ARMED", (
                f"Expected ARMED, got {scenario['status']}"
            )

    def test_direction_consistent_with_type(self):
        direction_map = {
            "BULLISH_BREAKOUT": "LONG",
            "BEARISH_BREAKDOWN": "SHORT",
            "BULLISH_CONTINUATION": "LONG",
            "BEARISH_CONTINUATION": "SHORT",
            "BULLISH_REVERSAL": "LONG",
            "BEARISH_REVERSAL": "SHORT",
            "RANGE_ROTATION": None,
            "VOLATILITY_EXPANSION": None,
            "VOLATILITY_COMPRESSION": None,
        }
        result = self.engine.generate_scenarios("NIFTY")
        for scenario in result["scenarios"]:
            expected_dir = direction_map.get(scenario["scenario_type"])
            assert scenario["direction"] == expected_dir, (
                f"{scenario['scenario_type']}: expected {expected_dir}, "
                f"got {scenario['direction']}"
            )

    def test_horizon_set(self):
        result = self.engine.generate_scenarios("NIFTY")
        for scenario in result["scenarios"]:
            assert scenario["expected_horizon"], (
                f"{scenario['scenario_type']} missing horizon"
            )
            assert isinstance(scenario["expected_horizon"], str)


class TestScenarioTriggers:
    def setup_method(self):
        self.engine = PreMarketScenarioEngine(DB_PATH)

    def test_trigger_based_on_actual_levels(self):
        result = self.engine.generate_scenarios("NIFTY")
        key_levels = result["key_levels"]
        current_price = key_levels.get("current_price")
        for scenario in result["scenarios"]:
            trigger = scenario["trigger"]
            assert isinstance(trigger, str) and len(trigger) > 5, (
                f"{scenario['scenario_type']}: trigger too short"
            )
            if "support" in trigger.lower() or "resistance" in trigger.lower():
                assert current_price is not None, "Current price should be set"

    def test_invalidation_based_on_actual_levels(self):
        result = self.engine.generate_scenarios("NIFTY")
        for scenario in result["scenarios"]:
            inv = scenario["invalidation"]
            assert isinstance(inv, str) and len(inv) > 5, (
                f"{scenario['scenario_type']}: invalidation too short"
            )

    def test_target_zone_set(self):
        result = self.engine.generate_scenarios("NIFTY")
        for scenario in result["scenarios"]:
            assert scenario["target_zone"], (
                f"{scenario['scenario_type']}: missing target zone"
            )

    def test_confirmation_conditions_set(self):
        result = self.engine.generate_scenarios("NIFTY")
        for scenario in result["scenarios"]:
            assert scenario["confirmation_conditions"], (
                f"{scenario['scenario_type']}: missing confirmation"
            )

    def test_bullish_breakout_trigger_above_current(self):
        result = self.engine.generate_scenarios("NIFTY")
        key_levels = result["key_levels"]
        current_price = key_levels.get("current_price") or 0
        for scenario in result["scenarios"]:
            if scenario["scenario_type"] == "BULLISH_BREAKOUT":
                res_levels = key_levels.get("resistance_levels", [])
                if res_levels:
                    nearest_above = min(r for r in res_levels if r > current_price) if any(r > current_price for r in res_levels) else res_levels[0]
                    assert nearest_above >= current_price, (
                        f"Breakout trigger should be above current price: "
                        f"{nearest_above} vs {current_price}"
                    )


class TestScenarioContextFields:
    def setup_method(self):
        self.engine = PreMarketScenarioEngine(DB_PATH)

    def test_positioning_context(self):
        result = self.engine.generate_scenarios("NIFTY")
        for scenario in result["scenarios"]:
            ctx = scenario["positioning_context"]
            assert isinstance(ctx, dict)
            assert "positioning_source" in ctx
            assert "recommended_bias" in ctx

    def test_liquidity_context(self):
        result = self.engine.generate_scenarios("NIFTY")
        for scenario in result["scenarios"]:
            ctx = scenario["liquidity_context"]
            assert isinstance(ctx, dict)
            assert "primary_liquidity_zones" in ctx
            assert "institutional_order_flow" in ctx

    def test_market_intent_context(self):
        result = self.engine.generate_scenarios("NIFTY")
        for scenario in result["scenarios"]:
            ctx = scenario["market_intent_context"]
            assert isinstance(ctx, dict)
            assert "intent_summary" in ctx
            assert "market_structure_read" in ctx

    def test_supporting_evidence(self):
        result = self.engine.generate_scenarios("NIFTY")
        for scenario in result["scenarios"]:
            assert isinstance(scenario["supporting_evidence"], list)
            assert len(scenario["supporting_evidence"]) >= 1

    def test_contradictory_evidence(self):
        result = self.engine.generate_scenarios("NIFTY")
        for scenario in result["scenarios"]:
            assert isinstance(scenario["contradictory_evidence"], list)


class TestDataQualityFlags:
    def setup_method(self):
        self.engine = PreMarketScenarioEngine(DB_PATH)

    def test_data_quality_not_empty(self):
        result = self.engine.generate_scenarios("NIFTY")
        for scenario in result["scenarios"]:
            assert scenario["data_quality"], (
                f"{scenario['scenario_type']}: data_quality is empty"
            )
            assert isinstance(scenario["data_quality"], str)

    def test_volume_unavailable_reflected(self):
        result = self.engine.generate_scenarios("NIFTY")
        gate = DataReadinessGate(DB_PATH)
        readiness = gate.check("NIFTY")
        for scenario in result["scenarios"]:
            if "VOLUME_UNAVAILABLE" in readiness.get("issues", []):
                assert "VOLUME_UNAVAILABLE" in scenario["data_quality"], (
                    f"{scenario['scenario_type']}: data_quality should mention VOLUME_UNAVAILABLE"
                )

    def test_historical_sample_size_integer(self):
        result = self.engine.generate_scenarios("NIFTY")
        for scenario in result["scenarios"]:
            assert isinstance(scenario["historical_sample_size"], int)


class TestScenarioValidation:
    def setup_method(self):
        self.engine = PreMarketScenarioEngine(DB_PATH)

    def test_validate_valid_scenario(self):
        result = self.engine.generate_scenarios("NIFTY")
        for scenario in result["scenarios"]:
            valid, missing = self.engine.validate_scenario(scenario)
            assert valid, f"{scenario['scenario_id']}: {missing}"

    def test_validate_missing_field(self):
        bad_scenario = {"scenario_id": "TEST"}
        valid, missing = self.engine.validate_scenario(bad_scenario)
        assert not valid
        assert len(missing) > 0

    def test_validate_all_scenarios(self):
        result = self.engine.generate_scenarios("NIFTY")
        report = self.engine.validate_all_scenarios(result["scenarios"])
        assert report["invalid"] == 0, f"Invalid scenarios: {report['errors']}"


class TestStateMachine:
    def setup_method(self):
        self.engine = PreMarketScenarioEngine(DB_PATH)

    def test_state_machine_has_all_states(self):
        assert len(SCENARIO_STATE_MACHINE) == 9
        assert SCENARIO_STATE_MACHINE[0] == "DRAFT"
        assert SCENARIO_STATE_MACHINE[-1] == "COMPLETED"
        assert "ARMED" in SCENARIO_STATE_MACHINE

    def test_valid_forward_transition(self):
        result = self.engine.get_state_transition("DRAFT", "ARMED")
        assert result["valid"] is True

    def test_valid_chain(self):
        for i in range(len(SCENARIO_STATE_MACHINE) - 1):
            frm = SCENARIO_STATE_MACHINE[i]
            to = SCENARIO_STATE_MACHINE[i + 1]
            result = self.engine.get_state_transition(frm, to)
            assert result["valid"] is True, f"{frm} → {to} should be valid"

    def test_invalid_backward_transition(self):
        result = self.engine.get_state_transition("ARMED", "DRAFT")
        assert result["valid"] is False

    def test_get_all_transitions(self):
        transitions = self.engine.get_all_state_transitions()
        assert len(transitions) == len(SCENARIO_STATE_MACHINE) - 1

    def test_scenarios_start_at_armed(self):
        result = self.engine.generate_scenarios("NIFTY")
        for scenario in result["scenarios"]:
            assert scenario["status"] == "ARMED"


class TestJSONSerialization:
    def setup_method(self):
        self.engine = PreMarketScenarioEngine(DB_PATH)

    def test_result_json_serializable(self):
        result = self.engine.generate_scenarios("NIFTY")
        serialized = json.dumps(result, default=str)
        assert isinstance(serialized, str)
        loaded = json.loads(serialized)
        assert "scenarios" in loaded

    def test_scenario_json_serializable(self):
        result = self.engine.generate_scenarios("NIFTY")
        for scenario in result["scenarios"]:
            serialized = json.dumps(scenario, default=str)
            loaded = json.loads(serialized)
            for field in REQUIRED_SCENARIO_FIELDS:
                assert field in loaded, f"{field} not in serialized scenario"


class TestModuleFunction:
    def test_generate_scenarios_function(self):
        result = generate_scenarios("NIFTY", db_path=DB_PATH)
        assert isinstance(result, dict)
        assert "scenarios" in result

    def test_module_scenario_types_constant(self):
        assert isinstance(SCENARIO_TYPES, list)
        assert len(SCENARIO_TYPES) == 9

    def test_module_max_scenarios_constant(self):
        assert MAX_SCENARIOS_PER_INSTRUMENT == 3


class TestInstrumentVariations:
    def setup_method(self):
        self.engine = PreMarketScenarioEngine(DB_PATH)

    def test_nifty_generates_scenarios(self):
        result = self.engine.generate_scenarios("NIFTY")
        assert result["scenario_count"] >= 1

    def test_banknifty_generates_scenarios(self):
        result = self.engine.generate_scenarios("BANKNIFTY")
        assert result["scenario_count"] >= 1

    def test_banknifty_fields_complete(self):
        result = self.engine.generate_scenarios("BANKNIFTY")
        for scenario in result["scenarios"]:
            valid, missing = self.engine.validate_scenario(scenario)
            assert valid, f"BANKNIFTY {scenario['scenario_type']}: {missing}"

    def test_scenario_ids_unique(self):
        result = self.engine.generate_scenarios("NIFTY")
        ids = [s["scenario_id"] for s in result["scenarios"]]
        assert len(ids) == len(set(ids)), "Scenario IDs should be unique"

    def test_session_date_in_scenarios(self):
        result = self.engine.generate_scenarios("NIFTY", session_date="2026-09-18")
        for scenario in result["scenarios"]:
            assert scenario["session_date"] == "2026-09-18"
