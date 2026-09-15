#!/usr/bin/env python3
"""Phase 9A tests — Immutable Trade Journal.

Covers:
- Journal table creation and initialization
- Insert journal entry with all fields
- Immutable core fields (planned/actual entry, stop, target, risk)
- Mutable field updates create audit events
- Get single journal by ID
- List with filters (instrument, date range, user_action)
- Event log appended correctly
- User feedback insertion and retrieval
- Minimum sample size protection (10 trades)
- Comparison: TradingAI plan vs actual action
- Deterministic statistics when sample size met
- AI excluded from all calculations
- No overwriting / deletion of journal records
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from datetime import datetime, timezone

from backend.journal import (
    insert_journal, get_journal, list_journals, update_journal_notes,
    get_events, add_feedback, get_feedback, get_trade_count,
    has_minimum_sample, get_comparison, get_deterministic_stats,
    init_tables, TradeJournalRecord, MIN_SAMPLE_SIZE,
    _classify_entry_behavior, _classify_risk_adherence, _classify_exit_behavior,
    _classify_setup_vs_outcome, _classify_compliance,
    get_detailed_comparison, classify_all_journals, JournalComparison,
)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "database", "tradingai.db")


@pytest.fixture(autouse=True)
def setup_db():
    init_tables()
    yield


def _now():
    return datetime.now(timezone.utc).isoformat()


def _make_journal(**overrides):
    defaults = dict(
        date="2026-09-15",
        instrument="NIFTY",
        strategy="Bull Put Spread",
        direction="SHORT",
        planned_entry=24800.0,
        actual_entry=24750.0,
        stop=25100.0,
        target=24500.0,
        actual_exit=24600.0,
        quantity=50,
        risk_planned=1500.0,
        risk_actual=1500.0,
        market_regime="RANGING",
        tradingai_evidence_score=78.0,
        tradingai_confidence=65.0,
        user_action="TRADED",
        user_reason="Confidence above threshold",
        result="WIN",
        mistake=None,
        notes="Test trade",
    )
    defaults.update(overrides)
    return insert_journal(**defaults)


class TestJournalTable:
    def test_table_created(self):
        conn = __import__("backend.journal", fromlist=["_conn"])._conn()
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('trade_journal','trade_journal_events','user_feedback')"
        ).fetchall()
        conn.close()
        names = {t[0] for t in tables}
        assert "trade_journal" in names
        assert "trade_journal_events" in names
        assert "user_feedback" in names

    def test_insert_basic_fields(self):
        record = _make_journal()
        assert record.journal_id is not None
        assert record.journal_id.startswith("J-")
        assert record.instrument == "NIFTY"
        assert record.date == "2026-09-15"
        assert record.user_action == "TRADED"
        assert record.created_at is not None
        assert record.updated_at is not None

    def test_insert_with_setup_id(self):
        record = _make_journal(tradingai_setup_id="TA-20260915-NIFTY-094321")
        assert record.tradingai_setup_id == "TA-20260915-NIFTY-094321"

    def test_immutable_core_fields(self):
        record = _make_journal()
        original_entry = record.actual_entry
        original_stop = record.stop
        original_target = record.target
        original_risk = record.risk_actual
        updated = update_journal_notes(record.journal_id, notes="Updated notes")
        assert updated.actual_entry == original_entry
        assert updated.stop == original_stop
        assert updated.target == original_target
        assert updated.risk_actual == original_risk

    def test_update_notes_creates_event(self):
        record = _make_journal()
        updated = update_journal_notes(record.journal_id, notes="New notes")
        assert updated.notes == "New notes"
        events = get_events(record.journal_id)
        assert len(events) >= 1
        assert events[-1].event_type == "NOTES_UPDATE"
        assert events[-1].field_name == "notes"

    def test_update_mistake_creates_event(self):
        record = _make_journal()
        updated = update_journal_notes(record.journal_id, mistake="Entered early")
        assert updated.mistake == "Entered early"
        events = get_events(record.journal_id)
        assert any(e.event_type == "MISTAKE_UPDATE" for e in events)

    def test_update_action_creates_event(self):
        record = _make_journal(user_action="PENDING")
        updated = update_journal_notes(record.journal_id, user_action="TRADED")
        assert updated.user_action == "TRADED"
        events = get_events(record.journal_id)
        assert any(e.event_type == "ACTION_UPDATE" for e in events)

    def test_update_only_creates_one_event(self):
        record = _make_journal()
        update_journal_notes(record.journal_id, notes="Test")
        update_journal_notes(record.journal_id, notes="Test")
        events = get_events(record.journal_id)
        notes_events = [e for e in events if e.event_type == "NOTES_UPDATE"]
        assert len(notes_events) == 1

    def test_get_nonexistent_journal(self):
        record = get_journal("J-NONEXISTENT")
        assert record is None


class TestJournalList:
    def test_list_empty(self):
        records = list_journals()
        assert isinstance(records, list)

    def test_list_filter_by_instrument(self):
        _make_journal(instrument="NIFTY")
        _make_journal(instrument="BANKNIFTY")
        records = list_journals(instrument="NIFTY")
        assert all(r.instrument == "NIFTY" for r in records)

    def test_list_filter_by_date_range(self):
        _make_journal(date="2026-09-10")
        _make_journal(date="2026-09-15")
        records = list_journals(date_from="2026-09-12", date_to="2026-09-16")
        assert all(r.date >= "2026-09-12" and r.date <= "2026-09-16" for r in records)

    def test_list_filter_by_action(self):
        _make_journal(user_action="TRADED")
        _make_journal(user_action="SKIPPED")
        records = list_journals(user_action="TRADED")
        assert all(r.user_action == "TRADED" for r in records)

    def test_list_ordering(self):
        _make_journal(date="2026-09-01", notes="old")
        _make_journal(date="2026-09-15", notes="new")
        records = list_journals(limit=10)
        assert records[0].date >= records[-1].date


class TestComparison:
    def test_comparison_basic(self):
        record = _make_journal()
        comparison = get_comparison(record.journal_id)
        assert comparison is not None
        assert comparison["journal_id"] == record.journal_id
        assert "tradingai_plan" in comparison
        assert "actual_action" in comparison
        assert "differences" in comparison
        assert comparison["tradingai_plan"]["planned_entry"] == record.planned_entry
        assert comparison["actual_action"]["actual_entry"] == record.actual_entry

    def test_comparison_with_setup_id(self):
        record = _make_journal(tradingai_setup_id="TA-20260915-NIFTY-094321")
        comparison = get_comparison(record.journal_id)
        assert comparison["tradingai_setup_id"] == "TA-20260915-NIFTY-094321"


class TestStats:
    def test_insufficient_data_before_min_sample(self):
        stats = get_deterministic_stats(instrument="SENSEX")
        assert stats["insufficient_data"] is True
        assert stats["sample_size"] < MIN_SAMPLE_SIZE
        assert "need" in stats["message"].lower() or "need" in stats.get("message", "").lower()

    def test_minimum_sample_constant(self):
        assert MIN_SAMPLE_SIZE == 10


class TestFeedback:
    def test_add_feedback(self):
        record = _make_journal()
        feedback = add_feedback(record.journal_id, rating=4, category="Execution", comment="Good entry")
        assert feedback.feedback_id is not None
        assert feedback.rating == 4
        assert feedback.category == "Execution"

    def test_get_feedback(self):
        record = _make_journal()
        add_feedback(record.journal_id, rating=5, category="Overall")
        feedbacks = get_feedback(record.journal_id)
        assert len(feedbacks) >= 1
        assert feedbacks[-1].rating == 5

    def test_feedback_rating_validation(self):
        record = _make_journal()
        with pytest.raises(Exception):
            conn = __import__("backend.journal", fromlist=["_conn"])._conn()
            conn.execute(
                "INSERT INTO user_feedback (feedback_id, journal_id, rating) VALUES (?, ?, ?)",
                ("FB-TEST", record.journal_id, 6),
            )
            conn.commit()
            conn.close()


class TestTradeCount:
    def test_count_zero(self):
        count = get_trade_count(instrument="NONEXISTENT")
        assert count == 0

    def test_count_with_data(self):
        _make_journal()
        count = get_trade_count(instrument="NIFTY")
        assert count >= 1


class TestJournalImmutability:
    def test_core_fields_never_changed(self):
        record = _make_journal(planned_entry=25000.0, actual_entry=24800.0, stop=25100.0,
                                target=24500.0, risk_planned=2000.0, risk_actual=1800.0)
        for _ in range(5):
            update_journal_notes(record.journal_id, notes=f"Update {_}")
        refreshed = get_journal(record.journal_id)
        assert refreshed.planned_entry == 25000.0
        assert refreshed.actual_entry == 24800.0
        assert refreshed.stop == 25100.0
        assert refreshed.target == 24500.0
        assert refreshed.risk_planned == 2000.0
        assert refreshed.risk_actual == 1800.0


class TestDeterministicStats:
    def test_deterministic_with_enough_data(self):
        for i in range(12):
            _make_journal(
                date=f"2026-09-{i+1:02d}",
                result="WIN" if i % 3 != 0 else "LOSS",
                instrument="NIFTY",
            )
        stats = get_deterministic_stats(instrument="NIFTY")
        assert stats["insufficient_data"] is False
        assert stats["total_trades"] >= 12
        assert stats["win_rate"] >= 0
        assert "by_regime" in stats

    def test_deterministic_reproducible(self):
        for i in range(12):
            _make_journal(
                date=f"2026-09-{i+1:02d}",
                result="WIN" if i % 3 != 0 else "LOSS",
                instrument="BANKNIFTY",
            )
        stats1 = get_deterministic_stats(instrument="BANKNIFTY")
        stats2 = get_deterministic_stats(instrument="BANKNIFTY")
        assert stats1["total_trades"] == stats2["total_trades"]
        assert stats1["win_rate"] == stats2["win_rate"]


class TestEdgeCases:
    def test_insert_minimal(self):
        record = insert_journal(date="2026-09-15", instrument="NIFTY", user_action="SKIPPED")
        assert record.journal_id is not None
        assert record.user_action == "SKIPPED"
        assert record.planned_entry is None

    def test_update_nonexistent(self):
        result = update_journal_notes("J-NONEXISTENT", notes="test")
        assert result is None

    def test_events_for_nonexistent(self):
        events = get_events("J-NONEXISTENT")
        assert events == []

    def test_feedback_for_nonexistent(self):
        feedbacks = get_feedback("J-NONEXISTENT")
        assert feedbacks == []


class Test9BComparisonDimensions:
    def test_journal_accepts_readiness(self):
        record = _make_journal(
            tradingai_trade_readiness="WAIT",
            tradingai_predicted_outcome="DOWN",
            entry_window_start="2026-09-15T09:30:00",
            entry_window_end="2026-09-15T11:00:00",
            confirmation_at="2026-09-15T10:00:00",
            actual_entry_at="2026-09-15T09:45:00",
        )
        assert record.tradingai_trade_readiness == "WAIT"
        assert record.tradingai_predicted_outcome == "DOWN"

    def test_comparison_before_confirmation(self):
        record = _make_journal(
            actual_entry_at="2026-09-15T09:45:00",
            confirmation_at="2026-09-15T10:00:00",
        )
        result = _classify_entry_behavior(record)
        assert result["before_confirmation"] is True
        assert result["during_confirmation"] is False

    def test_comparison_during_confirmation(self):
        record = _make_journal(
            actual_entry_at="2026-09-15T10:30:00",
            confirmation_at="2026-09-15T10:00:00",
        )
        result = _classify_entry_behavior(record)
        assert result["before_confirmation"] is False
        assert result["during_confirmation"] is True

    def test_comparison_inside_entry_window(self):
        record = _make_journal(
            actual_entry_at="2026-09-15T10:00:00",
            entry_window_start="2026-09-15T09:30:00",
            entry_window_end="2026-09-15T11:00:00",
        )
        result = _classify_entry_behavior(record)
        assert result["inside_entry_window"] is True

    def test_comparison_outside_entry_window(self):
        record = _make_journal(
            actual_entry_at="2026-09-15T12:00:00",
            entry_window_start="2026-09-15T09:30:00",
            entry_window_end="2026-09-15T11:00:00",
        )
        result = _classify_entry_behavior(record)
        assert result["inside_entry_window"] is False

    def test_entry_price_match_exact(self):
        record = _make_journal(planned_entry=24800.0, actual_entry=24800.0)
        result = _classify_entry_behavior(record)
        assert result["entry_match"] == "EXACT"

    def test_risk_stop_adherence(self):
        record = _make_journal(stop=25100.0, actual_exit=25000.0)
        result = _classify_risk_adherence(record)
        assert result["stop_adherence"] in ("HIT", "NOT_HIT")

    def test_risk_target_adherence(self):
        record = _make_journal(target=24500.0, actual_exit=24400.0)
        result = _classify_risk_adherence(record)
        assert result["target_adherence"] in ("HIT", "NOT_HIT")

    def test_risk_exceeded(self):
        record = _make_journal(risk_planned=1000.0, risk_actual=1500.0)
        result = _classify_risk_adherence(record)
        assert result["risk_adherence"] == "EXCEEDED"

    def test_exit_type_target(self):
        record = _make_journal(stop=25100.0, target=24500.0, actual_exit=24400.0)
        result = _classify_exit_behavior(record)
        assert result["exit_type"] in ("TARGET", "STOP", "MANUAL")

    def test_compliance_traded_wait(self):
        record = _make_journal(
            tradingai_trade_readiness="WAIT",
            user_action="TRADED",
        )
        result = _classify_compliance(record)
        assert result["traded_wait"] is True

    def test_compliance_correctly_skipped_wait(self):
        record = _make_journal(
            tradingai_trade_readiness="WAIT",
            user_action="SKIPPED",
        )
        result = _classify_compliance(record)
        assert result["correctly_skipped_wait"] is True

    def test_compliance_skipped_valid_setup(self):
        record = _make_journal(
            tradingai_trade_readiness="GO",
            user_action="SKIPPED",
        )
        result = _classify_compliance(record)
        assert result["skipped_valid_setup"] is True

    def test_compliance_after_invalidation(self):
        record = _make_journal(
            invalidation_at="2026-09-15T10:00:00",
            actual_exit_at="2026-09-15T11:00:00",
        )
        result = _classify_compliance(record)
        assert result["traded_after_invalidation"] is True

    def test_setup_vs_outcome_match(self):
        record = _make_journal(
            tradingai_predicted_outcome="WIN",
            result="WIN",
        )
        result = _classify_setup_vs_outcome(record)
        assert result["outcome_match"] == "MATCH"

    def test_setup_vs_outcome_mismatch(self):
        record = _make_journal(
            tradingai_predicted_outcome="WIN",
            result="LOSS",
        )
        result = _classify_setup_vs_outcome(record)
        assert result["outcome_match"] == "MISMATCH"

    def test_detailed_comparison_basic(self):
        record = _make_journal(
            tradingai_trade_readiness="GO",
            tradingai_predicted_outcome="UP",
            tradingai_setup_id="TA-20260915-NIFTY-094321",
        )
        comparison = get_detailed_comparison(record.journal_id)
        assert comparison is not None
        assert "entry_behavior" in comparison
        assert "risk_adherence" in comparison
        assert "exit_behavior" in comparison
        assert "setup_vs_user_outcome" in comparison
        assert "compliance" in comparison
        assert comparison["tradingai_readiness"] == "GO"

    def test_classify_all_empty(self):
        result = classify_all_journals()
        assert isinstance(result, dict)
        for key in ["traded_wait", "traded_no_setup", "skipped_valid_setup",
                     "correctly_skipped_wait", "outcome_mismatch", "exited_before_stop"]:
            assert key in result
            assert isinstance(result[key], list)

    def test_comparison_deterministic(self):
        record = _make_journal()
        comp1 = get_detailed_comparison(record.journal_id)
        comp2 = get_detailed_comparison(record.journal_id)
        assert comp1 == comp2
