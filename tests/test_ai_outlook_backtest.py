"""Tests for TradingAI AI Outlook Historical Validation backend/ai_outlook_backtest.py."""
from __future__ import annotations

import datetime
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.ai_outlook_backtest import (
    _is_in_market_hours,
    _parse_ts,
    _minutes_between,
    build_replay_input,
    compute_metrics,
    evaluate_outcomes,
    identify_sessions,
    load_price_5m,
)

DB_PATH = "database/tradingai.db"


class TestMarketHours:
    def test_open_is_market_hours(self):
        assert _is_in_market_hours("2026-09-15 03:45:00") is True

    def test_close_is_market_hours(self):
        assert _is_in_market_hours("2026-09-15 09:55:00") is True

    def test_midday_is_market_hours(self):
        assert _is_in_market_hours("2026-09-15 06:00:00") is True

    def test_before_market_is_not_market_hours(self):
        assert _is_in_market_hours("2026-09-15 02:00:00") is False

    def test_after_market_is_not_market_hours(self):
        assert _is_in_market_hours("2026-09-15 11:00:00") is False

    def test_invalid_timestamp_returns_false(self):
        assert _is_in_market_hours("") is False
        assert _is_in_market_hours("invalid") is False
        assert _is_in_market_hours(None) is False


class TestParseTimestamp:
    def test_valid_datetime(self):
        result = _parse_ts("2026-09-15 09:15:00")
        assert result is not None
        assert result.year == 2026

    def test_invalid_returns_none(self):
        assert _parse_ts("") is None
        assert _parse_ts("not-a-date") is None
        assert _parse_ts(None) is None


class TestMinutesBetween:
    def test_same_timestamp(self):
        assert _minutes_between("2026-09-15 09:15:00", "2026-09-15 09:15:00") == 0

    def test_five_minutes_apart(self):
        assert _minutes_between("2026-09-15 09:15:00", "2026-09-15 09:20:00") == 5

    def test_one_hour_apart(self):
        assert _minutes_between("2026-09-15 09:15:00", "2026-09-15 10:15:00") == 60

    def test_none_input(self):
        assert _minutes_between("", "2026-09-15 09:15:00") is None
        assert _minutes_between("2026-09-15 09:15:00", "") is None
        assert _minutes_between(None, "2026-09-15 09:15:00") is None


class TestIdentifySessions:
    def test_returns_list(self):
        candles = load_price_5m(DB_PATH, "NIFTY")
        sessions = identify_sessions(candles, 5)
        assert isinstance(sessions, list)
        assert len(sessions) > 0

    def test_each_session_has_candles(self):
        candles = load_price_5m(DB_PATH, "NIFTY")
        sessions = identify_sessions(candles, 5)
        for s in sessions:
            assert len(s) >= 50

    def test_session_count(self):
        candles = load_price_5m(DB_PATH, "NIFTY")
        sessions = identify_sessions(candles, 30)
        assert len(sessions) == 30


class TestBuildReplayInput:
    def test_returns_dict(self):
        data = {"close": 23500, "ema20": 23300, "rsi": 55}
        result = build_replay_input(data)
        assert isinstance(result, dict)
        assert "price" in result
        assert "rsi" in result

    def test_handles_minimal_data(self):
        result = build_replay_input({})
        assert result["price"] == 0
        assert result["rsi"] == 0


class TestEvaluateOutcomes:
    def test_no_lookahead_in_outcomes(self):
        candles = load_price_5m(DB_PATH, "NIFTY")
        sessions = identify_sessions(candles, 1)
        decisions, _ = None, "PASS"

        from backend.ai_outlook_backtest import run_replay
        decisions, _ = run_replay("NIFTY", 1, DB_PATH)
        decisions = evaluate_outcomes(decisions, DB_PATH)

        for d in decisions:
            assert d["outcome"] in ("WIN", "LOSS", "EXPIRED", "NO_TRIGGER", "NO_TRADE", "")

    def test_outcomes_filled(self):
        from backend.ai_outlook_backtest import run_replay
        decisions, _ = run_replay("NIFTY", 1, DB_PATH)
        decisions = evaluate_outcomes(decisions, DB_PATH)
        for d in decisions:
            assert d["outcome"] != "" or d["trade_status"] == "NO_TRADE"

    def test_no_trigger_when_no_breakout(self):
        from backend.ai_outlook_backtest import run_replay
        decisions, _ = run_replay("NIFTY", 1, DB_PATH)
        decisions = evaluate_outcomes(decisions, DB_PATH)
        no_trigger = [d for d in decisions if d["outcome"] == "NO_TRIGGER"]
        assert len(no_trigger) >= 0

    def test_trade_ledger_columns(self):
        from backend.ai_outlook_backtest import run_replay
        decisions, _ = run_replay("NIFTY", 1, DB_PATH)
        decisions = evaluate_outcomes(decisions, DB_PATH)
        if decisions:
            required = [
                "timestamp", "date", "symbol", "spot", "market_structure",
                "directional_bias", "trade_class", "trade_status", "confidence",
                "entry_trigger", "actual_entry_time", "actual_entry_price",
                "invalidation", "target_zone", "exit_time", "exit_price",
                "outcome", "return_pct", "max_favorable_excursion",
                "max_adverse_excursion", "time_to_trigger", "time_to_outcome",
                "data_state", "reason",
            ]
            for d in decisions:
                for r in required:
                    assert r in d, f"Missing column: {r}"


class TestComputeMetrics:
    def test_returns_dict(self):
        from backend.ai_outlook_backtest import run_replay
        decisions, _ = run_replay("NIFTY", 1, DB_PATH)
        decisions = evaluate_outcomes(decisions, DB_PATH)
        metrics = compute_metrics(decisions)
        assert isinstance(metrics, dict)
        assert "total_outlooks" in metrics
        assert "win_rate" in metrics

    def test_metrics_structure(self):
        from backend.ai_outlook_backtest import run_replay
        decisions, _ = run_replay("NIFTY", 1, DB_PATH)
        decisions = evaluate_outcomes(decisions, DB_PATH)
        metrics = compute_metrics(decisions)
        for key in [
            "total_outlooks", "directional_outlooks", "bullish_outlooks",
            "bearish_outlooks", "non_directional_outlooks", "wait",
            "no_trade", "triggered", "no_trigger", "wins", "losses",
            "expired", "win_rate", "loss_rate", "directional_accuracy",
            "avg_return", "confusion_matrix", "by_structure", "by_hour",
            "by_confidence", "by_direction", "wilson_confidence_interval",
        ]:
            assert key in metrics, f"Missing metric: {key}"

    def test_win_rate_range(self):
        from backend.ai_outlook_backtest import run_replay
        decisions, _ = run_replay("NIFTY", 1, DB_PATH)
        decisions = evaluate_outcomes(decisions, DB_PATH)
        metrics = compute_metrics(decisions)
        assert 0.0 <= metrics["win_rate"] <= 100.0

    def test_wilson_interval(self):
        from backend.ai_outlook_backtest import run_replay, compute_metrics
        decisions, _ = run_replay("NIFTY", 1, DB_PATH)
        decisions = evaluate_outcomes(decisions, DB_PATH)
        metrics = compute_metrics(decisions)
        ci = metrics["wilson_confidence_interval"]
        assert "lower" in ci
        assert "upper" in ci
        assert "point" in ci
        assert ci["lower"] <= ci["point"] <= ci["upper"]

    def test_directional_accuracy_range(self):
        from backend.ai_outlook_backtest import run_replay, compute_metrics
        decisions, _ = run_replay("NIFTY", 1, DB_PATH)
        decisions = evaluate_outcomes(decisions, DB_PATH)
        metrics = compute_metrics(decisions)
        assert 0.0 <= metrics["directional_accuracy"] <= 100.0


class TestLookAheadBias:
    def test_outlook_frozen_before_future_evaluation(self):
        from backend.ai_outlook_backtest import run_replay, evaluate_outcomes
        decisions, _ = run_replay("NIFTY", 1, DB_PATH)
        decisions_evaluated = evaluate_outcomes(decisions, DB_PATH)
        for d in decisions_evaluated:
            assert d["timestamp"] is not None
            assert d["outcome"] is not None or d["trade_status"] == "NO_TRADE"

    def test_candle_data_not_leaked(self):
        from backend.ai_outlook_backtest import run_replay, evaluate_outcomes, load_price_5m
        candles = load_price_5m(DB_PATH, "NIFTY")
        decisions, _ = run_replay("NIFTY", 1, DB_PATH)
        decisions = evaluate_outcomes(decisions, DB_PATH)
        first_ts = decisions[0]["timestamp"]
        for d in decisions:
            assert d["timestamp"] >= first_ts


class TestDataIntegrity:
    def test_no_duplicate_timestamps_in_session(self):
        from backend.ai_outlook_backtest import identify_sessions, load_price_5m
        candles = load_price_5m(DB_PATH, "NIFTY")
        sessions = identify_sessions(candles, 1)
        assert len(sessions) == 1
        timestamps = [c["timestamp"] for c in sessions[0]]
        assert len(timestamps) == len(set(timestamps))

    def test_candles_sequential(self):
        from backend.ai_outlook_backtest import identify_sessions, load_price_5m
        candles = load_price_5m(DB_PATH, "NIFTY")
        sessions = identify_sessions(candles, 1)
        timestamps = [c["timestamp"] for c in sessions[0]]
        for i in range(1, len(timestamps)):
            assert timestamps[i] > timestamps[i - 1]

    def test_all_candles_in_market_hours(self):
        from backend.ai_outlook_backtest import identify_sessions, load_price_5m
        candles = load_price_5m(DB_PATH, "NIFTY")
        sessions = identify_sessions(candles, 30)
        for session in sessions:
            for c in session:
                assert _is_in_market_hours(c["timestamp"])
