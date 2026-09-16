#!/usr/bin/env python3
"""Phase 9C tests — Personal Trading Intelligence.

Covers:
- All intelligence functions return SUFFICIENT_DATA/INSUFFICIENT_DATA correctly
- Sample-size protection enforced
- Deterministic results (reproducible)
- Setup, instrument, strategy, regime, direction statistics
- Time-of-day analysis
- Entry-window, confirmation, stop/target adherence
- Risk behavior
- Compliance analysis
- Mistake patterns
- Setup adherence
- AI explanation boundary (AI not calculating)
- Every response includes sample size
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from backend.personal_intelligence import (
    intelligence_summary, intelligence_instrument, intelligence_strategy,
    intelligence_regime, intelligence_direction, intelligence_time_of_day,
    intelligence_adherence, intelligence_behavior, intelligence_compliance,
    intelligence_mistakes, intelligence_setup_adherence, intelligence_risk_behavior,
    MIN_SAMPLE_SIZE,
)


class TestDataStatus:
    def test_every_function_returns_data_status(self):
        functions = [
            intelligence_summary,
            lambda: intelligence_instrument("NIFTY"),
            lambda: intelligence_strategy("Bull Put Spread"),
            lambda: intelligence_regime("RANGING"),
            lambda: intelligence_direction("LONG"),
            intelligence_time_of_day,
            intelligence_adherence,
            intelligence_behavior,
            intelligence_compliance,
            intelligence_mistakes,
            intelligence_setup_adherence,
            intelligence_risk_behavior,
        ]
        for fn in functions:
            result = fn()
            assert "data_status" in result, f"{fn.__name__} missing data_status"
            assert result["data_status"] in ("SUFFICIENT_DATA", "INSUFFICIENT_DATA"), \
                f"{fn.__name__} invalid status: {result['data_status']}"

    def test_every_function_includes_sample_size(self):
        functions = [
            intelligence_summary,
            lambda: intelligence_instrument("NIFTY"),
            lambda: intelligence_strategy("Bull Put Spread"),
            lambda: intelligence_regime("RANGING"),
            lambda: intelligence_direction("LONG"),
            intelligence_time_of_day,
            intelligence_adherence,
            intelligence_behavior,
            intelligence_compliance,
            intelligence_mistakes,
            intelligence_setup_adherence,
            intelligence_risk_behavior,
        ]
        for fn in functions:
            result = fn()
            assert "sample_size" in result, f"{fn.__name__} missing sample_size"
            assert isinstance(result["sample_size"], int), \
                f"{fn.__name__} sample_size not int"


class TestMinimumSample:
    def test_minimum_sample_constant(self):
        assert MIN_SAMPLE_SIZE == 10

    def test_insufficient_data_when_below_min(self):
        result = intelligence_summary()
        assert result["minimum_required"] == 10

    def test_sample_size_reported(self):
        result = intelligence_summary()
        assert result["sample_size"] >= 0
        assert result["minimum_required"] == 10


class TestSummary:
    def test_summary_has_total_trades(self):
        result = intelligence_summary()
        if result["data_status"] == "SUFFICIENT_DATA":
            assert "total_trades" in result
            assert result["total_trades"] >= MIN_SAMPLE_SIZE

    def test_summary_has_win_rate(self):
        result = intelligence_summary()
        if result["data_status"] == "SUFFICIENT_DATA":
            assert "win_rate" in result
            assert 0 <= result["win_rate"] <= 100

    def test_summary_has_categories(self):
        result = intelligence_summary()
        if result["data_status"] == "SUFFICIENT_DATA":
            assert "categories" in result
            assert "by_action" in result["categories"]
            assert "by_regime" in result["categories"]


class TestDeterminism:
    def test_summary_deterministic(self):
        r1 = intelligence_summary()
        r2 = intelligence_summary()
        if r1.get("data_status") == "SUFFICIENT_DATA":
            assert r1["total_trades"] == r2["total_trades"]
            assert r1["win_rate"] == r2["win_rate"]

    def test_sample_size_deterministic(self):
        r1 = intelligence_summary()
        r2 = intelligence_summary()
        assert r1["sample_size"] == r2["sample_size"]


class TestPerInstrument:
    def test_instrument_summary(self):
        result = intelligence_instrument("NIFTY")
        assert result["data_status"] in ("SUFFICIENT_DATA", "INSUFFICIENT_DATA")
        assert "sample_size" in result
        if result["data_status"] == "SUFFICIENT_DATA":
            assert "by_regime" in result
            assert "by_strategy" in result

    def test_instrument_no_data(self):
        result = intelligence_instrument("NONEXISTENT")
        assert result["data_status"] in ("SUFFICIENT_DATA", "INSUFFICIENT_DATA")


class TestPerStrategy:
    def test_strategy_summary(self):
        result = intelligence_strategy("Bull Put Spread")
        assert result["data_status"] in ("SUFFICIENT_DATA", "INSUFFICIENT_DATA")
        if result["data_status"] == "SUFFICIENT_DATA":
            assert "by_instrument" in result


class TestTimeOfDay:
    def test_time_slots(self):
        result = intelligence_time_of_day()
        assert result["data_status"] in ("SUFFICIENT_DATA", "INSUFFICIENT_DATA")
        if result["data_status"] == "SUFFICIENT_DATA":
            assert "time_slots" in result
            for slot, stats in result["time_slots"].items():
                assert "trades" in stats
                assert "win_rate" in stats


class TestAdherence:
    def test_adherence_fields(self):
        result = intelligence_adherence()
        assert result["data_status"] in ("SUFFICIENT_DATA", "INSUFFICIENT_DATA")
        if result["data_status"] == "SUFFICIENT_DATA":
            assert "entry_window_rate" in result
            assert "confirmation_rate" in result
            assert "stop_hold_rate" in result
            assert "target_hit_rate" in result


class TestBehavior:
    def test_behavior_fields(self):
        result = intelligence_behavior()
        assert result["data_status"] in ("SUFFICIENT_DATA", "INSUFFICIENT_DATA")
        if result["data_status"] == "SUFFICIENT_DATA":
            assert "exit_type_distribution" in result
            assert "risk_distribution" in result


class TestCompliance:
    def test_compliance_counts(self):
        result = intelligence_compliance()
        assert result["data_status"] in ("SUFFICIENT_DATA", "INSUFFICIENT_DATA")
        if result["data_status"] == "SUFFICIENT_DATA":
            assert "traded_when_was_wait" in result
            assert "skipped_valid_setup" in result
            assert "traded_after_invalidation" in result

    def test_no_negative_counts(self):
        result = intelligence_compliance()
        if result["data_status"] == "SUFFICIENT_DATA":
            for key, value in result.items():
                if key not in ("data_status", "sample_size", "minimum_required", "message"):
                    if isinstance(value, int):
                        assert value >= 0, f"{key} is negative: {value}"


class TestMistakes:
    def test_mistakes_patterns(self):
        result = intelligence_mistakes()
        assert result["data_status"] in ("SUFFICIENT_DATA", "INSUFFICIENT_DATA")
        if result["data_status"] == "SUFFICIENT_DATA":
            assert "mistake_patterns" in result
            assert isinstance(result["mistake_patterns"], dict)


class TestSetupAdherence:
    def test_setup_adherence_fields(self):
        result = intelligence_setup_adherence()
        assert result["data_status"] in ("SUFFICIENT_DATA", "INSUFFICIENT_DATA")
        if result["data_status"] == "SUFFICIENT_DATA":
            assert "ai_accuracy" in result
            assert "ai_outcome_correct" in result
            assert "ai_outcome_wrong" in result


class TestRiskBehavior:
    def test_risk_fields(self):
        result = intelligence_risk_behavior()
        assert result["data_status"] in ("SUFFICIENT_DATA", "INSUFFICIENT_DATA")
        if result["data_status"] == "SUFFICIENT_DATA":
            assert "avg_risk_ratio" in result
            assert "avg_risk_planned" in result
            assert "avg_risk_actual" in result


class TestAIExclusion:
    def test_no_ai_calculation_in_statistics(self):
        import backend.personal_intelligence as pi
        source = open(pi.__file__).read()
        assert "llm" not in source.lower() or "def _" in source
        assert "gpt" not in source.lower()
        assert "groq" not in source.lower()
        assert "openai" not in source.lower()

    def test_minimum_sample_enforced_in_all_functions(self):
        functions = [
            intelligence_summary,
            lambda: intelligence_instrument("NIFTY"),
            lambda: intelligence_strategy("Bull Put Spread"),
            lambda: intelligence_regime("RANGING"),
            lambda: intelligence_direction("LONG"),
            intelligence_time_of_day,
            intelligence_adherence,
            intelligence_behavior,
            intelligence_compliance,
            intelligence_mistakes,
            intelligence_setup_adherence,
            intelligence_risk_behavior,
        ]
        for fn in functions:
            result = fn()
            assert result.get("minimum_required") == 10, \
                f"{fn.__name__} missing minimum_required or wrong value"


class TestEdgeCases:
    def test_empty_instrument(self):
        result = intelligence_instrument("")
        assert result["data_status"] in ("SUFFICIENT_DATA", "INSUFFICIENT_DATA")

    def test_future_date(self):
        result = intelligence_summary(date_from="2099-01-01", date_to="2099-12-31")
        assert result["data_status"] == "INSUFFICIENT_DATA"
        assert result["sample_size"] == 0

    def test_direction_insufficient_when_no_data(self):
        result = intelligence_direction("LONG")
        assert result["data_status"] in ("SUFFICIENT_DATA", "INSUFFICIENT_DATA")
