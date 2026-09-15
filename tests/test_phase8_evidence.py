import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from historical_evidence import (
    run_historical_evidence, SimilarityCondition,
    UnderlyingOutcome, HistoricalEvidenceResult,
)

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "database", "tradingai.db")

BROAD = SimilarityCondition('ANY', 'ANY', 'ANY', 'ANY', None, None, 'ANY', 'ANY')


def test_broad_search_finds_matches():
    result = run_historical_evidence('NIFTY', '2026-09-15', BROAD, db_path=DB_PATH)
    assert result.match_count > 0
    assert result.insufficient_data is False


def test_specific_criteria_no_matches():
    cond = SimilarityCondition('TRENDING', 'UP', 'ANY', 'ANY', None, None, 'ANY', 'ANY')
    result = run_historical_evidence('NIFTY', '2026-09-15', cond, db_path=DB_PATH)
    assert result.match_count == 0
    assert result.insufficient_data is False


def test_insufficient_data_symbol():
    result = run_historical_evidence('NOPE', '2026-09-15', BROAD, db_path=DB_PATH)
    assert result.insufficient_data is True


def test_insufficient_data_future():
    result = run_historical_evidence('NIFTY', '2027-01-01', BROAD, db_path=DB_PATH)
    assert result.insufficient_data is True


def test_coverage_reported():
    result = run_historical_evidence('NIFTY', '2026-09-15', BROAD, db_path=DB_PATH)
    cov = result.coverage
    assert cov["symbol"] == "NIFTY"
    assert "earliest" in cov
    assert "latest" in cov
    assert cov["total_days"] > 0


def test_underlying_outcomes_have_required_fields():
    result = run_historical_evidence('NIFTY', '2026-09-15', BROAD, db_path=DB_PATH)
    if result.underlying_outcomes:
        o = result.underlying_outcomes[0]
        assert hasattr(o, 'date')
        assert hasattr(o, 'subsequent_close_pct')
        assert hasattr(o, 'target_reached')
        assert hasattr(o, 'invalidation_reached')
        assert hasattr(o, 'subsequent_move_direction')


def test_options_separated():
    result = run_historical_evidence('NIFTY', '2026-09-15', BROAD, db_path=DB_PATH)
    assert result.option_data_available is False
    assert isinstance(result.options_outcomes, list)


def test_ai_excluded_from_calculation():
    result = run_historical_evidence('NIFTY', '2026-09-15', BROAD, db_path=DB_PATH)
    cond = result.conditions
    assert "ai_model" not in cond
    assert "ai_confidence" not in cond
    assert "ai_explanation" not in cond


def test_provenance_recorded():
    result = run_historical_evidence('NIFTY', '2026-09-15', BROAD, db_path=DB_PATH)
    cond = result.conditions
    assert "regime" in cond
    assert "gap_direction" in cond
    assert "price_location" in cond
    assert "rsi" in cond


def test_insufficient_data_has_coverage():
    result = run_historical_evidence('NOPE', '2026-09-15', BROAD, db_path=DB_PATH)
    assert result.insufficient_data is True
    assert result.coverage is not None


def test_deterministic_results():
    r1 = run_historical_evidence('NIFTY', '2026-09-15', BROAD, db_path=DB_PATH)
    r2 = run_historical_evidence('NIFTY', '2026-09-15', BROAD, db_path=DB_PATH)
    assert r1.match_count == r2.match_count
    assert r1.confirmed == r2.confirmed
    assert r1.failed == r2.failed
    assert r1.median_subsequent_move == r2.median_subsequent_move

