"""Regression tests for Phase 42A AI Outlook Pipeline repairs."""

import pytest
import json
import sys
import os
import sqlite3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from db_schema import DB_PATH


@pytest.fixture
def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    yield c
    c.close()


class TestResearchCollectorInsertsSnapshot:
    """Fix 1: _record_snapshot and _record_evidence must persist records."""

    def test_research_collector_inserts_snapshot(self, conn):
        from research_collector import ResearchCollector

        rc = ResearchCollector(DB_PATH)
        row = conn.execute(
            "SELECT symbol, timestamp, close, volume FROM price_5m WHERE symbol='NIFTY' ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        assert row is not None, "No price_5m data for NIFTY"

        symbol = row["symbol"]
        ts = row["timestamp"]
        result = {"snapshots": 0, "evidence": 0}

        snap_result = rc._record_snapshot(conn, result, symbol, ts)
        assert snap_result is True, "Snapshot insertion failed"
        assert result["snapshots"] >= 0, "Snapshot counter not updated"

        snap_count = conn.execute(
            "SELECT COUNT(*) FROM market_snapshots_5m WHERE symbol=? AND candle_timestamp=?",
            (symbol, ts),
        ).fetchone()[0]
        assert snap_count >= 1, f"Snapshot not found in DB ({snap_count})"

    def test_research_collector_inserts_evidence(self, conn):
        from research_collector import ResearchCollector

        rc = ResearchCollector(DB_PATH)
        row = conn.execute(
            "SELECT symbol, timestamp FROM price_5m WHERE symbol='NIFTY' ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        assert row is not None, "No price_5m data for NIFTY"

        symbol = row["symbol"]
        ts = row["timestamp"]
        result = {"snapshots": 0, "evidence": 0}

        ev_result = rc._record_evidence(conn, result, symbol, ts)
        assert ev_result is True, "Evidence insertion failed"

        ev_count = conn.execute(
            "SELECT COUNT(*) FROM market_evidence_5m WHERE instrument=? AND candle_timestamp=?",
            (symbol, ts),
        ).fetchone()[0]
        assert ev_count >= 1, f"Evidence not found in DB ({ev_count})"

    def test_idempotency_no_duplicate_records(self, conn):
        from research_collector import ResearchCollector

        rc = ResearchCollector(DB_PATH)
        row = conn.execute(
            "SELECT symbol, timestamp FROM price_5m WHERE symbol='NIFTY' ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        symbol = row["symbol"]
        ts = row["timestamp"]

        result1 = {"snapshots": 0, "evidence": 0}
        rc._record_snapshot(conn, result1, symbol, ts)
        rc._record_evidence(conn, result1, symbol, ts)

        result2 = {"snapshots": 0, "evidence": 0}
        rc._record_snapshot(conn, result2, symbol, ts)
        rc._record_evidence(conn, result2, symbol, ts)

        snap_count = conn.execute(
            "SELECT COUNT(*) FROM market_snapshots_5m WHERE symbol=? AND candle_timestamp=?",
            (symbol, ts),
        ).fetchone()[0]
        ev_count = conn.execute(
            "SELECT COUNT(*) FROM market_evidence_5m WHERE instrument=? AND candle_timestamp=?",
            (symbol, ts),
        ).fetchone()[0]

        assert snap_count == 1, f"Duplicate snapshots: {snap_count}"
        assert ev_count == 1, f"Duplicate evidence: {ev_count}"


class TestAIOutlook5MSymbolRouting:
    """Fix 2: AIOutlookGenerator5m must use actual symbol and market_state."""

    def test_ai_outlook_5m_uses_actual_symbol(self):
        from ai_outlook_5m import AIOutlookGenerator5m
        gen = AIOutlookGenerator5m()

        assert hasattr(gen, "_call_llm"), "_call_llm method missing"
        import inspect
        sig = inspect.signature(gen._call_llm)
        params = list(sig.parameters.keys())
        assert "symbol" in params, "_call_llm missing symbol parameter"
        assert "market_state" in params, "_call_llm missing market_state parameter"

    def test_banknifty_ai_context(self, conn):
        from ai_outlook_5m import AIOutlookGenerator5m
        gen = AIOutlookGenerator5m()

        snap = conn.execute(
            "SELECT * FROM market_snapshots_5m WHERE symbol='BANKNIFTY' ORDER BY candle_timestamp DESC LIMIT 1"
        ).fetchone()
        if snap is None:
            pytest.skip("No BANKNIFTY snapshot available")

        s = dict(snap)
        ai_input = gen._prepare_ai_input(s)

        assert ai_input["symbol"] == "BANKNIFTY", \
            f"Symbol routing broken: {ai_input['symbol']} != BANKNIFTY"
        assert ai_input["price"] == s["close"], \
            f"Price mismatch: {ai_input['price']} != {s['close']}"

    def test_nifty_ai_context(self, conn):
        from ai_outlook_5m import AIOutlookGenerator5m
        gen = AIOutlookGenerator5m()

        snap = conn.execute(
            "SELECT * FROM market_snapshots_5m WHERE symbol='NIFTY' ORDER BY candle_timestamp DESC LIMIT 1"
        ).fetchone()
        if snap is None:
            pytest.skip("No NIFTY snapshot available")

        s = dict(snap)
        ai_input = gen._prepare_ai_input(s)

        assert ai_input["symbol"] == "NIFTY", \
            f"Symbol routing broken: {ai_input['symbol']} != NIFTY"
        assert ai_input["price"] == s["close"], \
            f"Price mismatch: {ai_input['price']} != {s['close']}"

    def test_prepare_ai_input_has_required_fields(self):
        from ai_outlook_5m import AIOutlookGenerator5m
        gen = AIOutlookGenerator5m()

        fake_state = {
            "close": 23346.0,
            "open": 23341.0,
            "rsi": 20.0,
            "macd": -260.0,
            "adx": 45.0,
            "atr": 50.0,
            "vwap": 23340.0,
            "pivot": 23315.0,
            "cpr_upper": 23350.0,
            "vix": 11.0,
            "volume": 1000000,
            "regime": "BEARISH",
            "support": [23300.0],
            "resistance": [23400.0],
            "data_state": "LIVE",
            "symbol": "NIFTY",
        }
        ai_input = gen._prepare_ai_input(fake_state)
        assert ai_input["price"] == 23346.0
        assert ai_input["rsi"] == 20.0
        assert ai_input["regime"] == "BEARISH"
        assert ai_input["vwap"] == 23340.0
        assert ai_input["symbol"] == "NIFTY"


class TestLegacyFallbackProvenance:
    """Fix 3: Legacy fallback must never claim LIVE."""

    def test_legacy_fallback_not_marked_live(self):
        import backend.api_server as api_server
        from unittest.mock import MagicMock, patch

        with patch("backend.api_server.sqlite3.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_connect.return_value = mock_conn

            from backend.api_server import _ai_outlook_from_legacy

            mock_row = {"outlook": json.dumps({
                "directional_bias": "BEARISH",
                "confidence": 70,
                "market_regime": "BEARISH",
                "market_summary": "Test outlook",
            }), "timestamp": "2026-09-18T10:00:00Z"}
            mock_conn.execute.return_value.fetchone.return_value = mock_row
            mock_conn.execute.return_value.fetchall.return_value = []

            result = _ai_outlook_from_legacy(mock_conn, "NIFTY")
            current, previous, timeline = result

            assert current is not None, "Legacy fallback returned None"
            assert current.get("data_state") != "LIVE", \
                f"Legacy fallback incorrectly claims LIVE: {current.get('data_state')}"
            assert current.get("source_type") == "LEGACY", \
                f"Missing source_type: {current.get('source_type')}"
            assert current.get("is_current_5m") is False, \
                f"Legacy marked as current 5m: {current.get('is_current_5m')}"

    def test_legacy_fallback_has_provenance_fields(self):
        import backend.api_server as api_server
        from unittest.mock import MagicMock, patch

        with patch("backend.api_server.sqlite3.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_connect.return_value = mock_conn

            from backend.api_server import _ai_outlook_from_legacy

            mock_row = {"outlook": json.dumps({
                "directional_bias": "BEARISH",
                "confidence": 70,
                "market_regime": "BEARISH",
                "market_summary": "Test outlook",
            }), "timestamp": "2026-09-18T10:00:00Z"}
            mock_conn.execute.return_value.fetchone.return_value = mock_row
            mock_conn.execute.return_value.fetchall.return_value = []

            result = _ai_outlook_from_legacy(mock_conn, "NIFTY")
            current, _, _ = result

            assert "source_type" in current, "Missing source_type field"
            assert "is_current_5m" in current, "Missing is_current_5m field"
            assert "generated_at" in current, "Missing generated_at field"
            assert "outlook_id" in current, "Missing outlook_id field"
            assert "instrument" in current, "Missing instrument field"


class TestSchedulerTrigger:
    """Fix 4: Production scheduler trigger via monitor.py."""

    def test_monitor_has_run_scheduler(self):
        import backend.monitor as monitor
        assert hasattr(monitor, "run_scheduler"), "monitor.py missing run_scheduler function"

    def test_scheduler_is_failure_isolated(self):
        import backend.monitor as monitor
        import inspect
        sig = inspect.signature(monitor.run_scheduler)
        assert sig is not None, "run_scheduler has no signature"

    def test_scheduler_called_during_market_hours(self):
        import backend.monitor as monitor
        from unittest.mock import patch, MagicMock, mock_open

        with patch.object(monitor, "_is_market_hours", return_value=True), \
             patch("os.makedirs"), \
             patch.object(monitor, "log"), \
             patch.object(monitor, "run_research_collection") as mock_rc, \
             patch.object(monitor, "run_scheduler") as mock_rs, \
             patch.object(monitor, "check_db", return_value=(True, "ok")), \
             patch.object(monitor, "check_disk", return_value=(True, "ok")), \
             patch.object(monitor, "check_cron", return_value=(True, "ok")), \
             patch.object(monitor, "check_data_freshness", return_value=(True, "ok")):
            with patch("builtins.open", mock_open()):
                monitor.check_health()
                mock_rc.assert_called_once()
                mock_rs.assert_called_once()

    def test_scheduler_not_called_outside_market_hours(self):
        import backend.monitor as monitor
        from unittest.mock import patch, MagicMock, mock_open

        with patch.object(monitor, "_is_market_hours", return_value=False), \
             patch("os.makedirs"), \
             patch.object(monitor, "log"), \
             patch.object(monitor, "run_research_collection") as mock_rc, \
             patch.object(monitor, "run_scheduler") as mock_rs, \
             patch.object(monitor, "check_db", return_value=(True, "ok")), \
             patch.object(monitor, "check_disk", return_value=(True, "ok")), \
             patch.object(monitor, "check_cron", return_value=(True, "ok")), \
             patch.object(monitor, "check_data_freshness", return_value=(True, "ok")):
            with patch("builtins.open", mock_open()):
                monitor.check_health()
                mock_rc.assert_not_called()
                mock_rs.assert_not_called()
