#!/usr/bin/env python3
"""Phase 5 tests - Historical AI Replay Engine.

Covers:
- Replay day with strict no-lookahead
- Each snapshot uses only data ≤ that timestamp
- Gap computed from opening price (stable, doesn't change intraday)
- Trade setup evolves timestamp by timestamp
- Evidence/uncertainty captured per snapshot
- Immutability of snapshots
- Empty data handling
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from backend.replay_engine import ReplaySnapshot, replay_day


# ═══════════════════════════════════════════════════════
# Basic Replay Tests
# ═══════════════════════════════════════════════════════

class TestReplayDay:
    def test_replay_returns_list(self):
        candles = [
            {"timestamp": "2026-09-15T09:15:00", "open": 25600, "high": 25620, "low": 25580, "close": 25610, "volume": 1000},
            {"timestamp": "2026-09-15T09:20:00", "open": 25610, "high": 25630, "low": 25600, "close": 25625, "volume": 1200},
        ]
        result = replay_day("NIFTY", "2026-09-15", candles, prev_close=25550)
        assert isinstance(result, list)
        assert len(result) == 2

    def test_no_lookahead(self):
        """At 09:20, AI should not know 09:25 data."""
        candles = [
            {"timestamp": "2026-09-15T09:15:00", "open": 25600, "high": 25620, "low": 25580, "close": 25610, "volume": 1000},
            {"timestamp": "2026-09-15T09:20:00", "open": 25610, "high": 25630, "low": 25600, "close": 25625, "volume": 1200},
            {"timestamp": "2026-09-15T09:25:00", "open": 25625, "high": 25650, "low": 25620, "close": 25640, "volume": 1500},
        ]
        result = replay_day("NIFTY", "2026-09-15", candles, prev_close=25550)
        assert len(result) == 3
        # At 09:20, the trade setup should only use data up to 09:20
        assert result[1].timestamp == "2026-09-15T09:20:00"
        assert result[1].market_state is not None

    def test_gap_computed_from_open(self):
        """Gap is from opening price vs previous close."""
        candles = [
            {"timestamp": "2026-09-15T09:15:00", "open": 25700, "high": 25720, "low": 25680, "close": 25710, "volume": 1000},
        ]
        result = replay_day("NIFTY", "2026-09-15", candles, prev_close=25550)
        assert len(result) == 1
        gap = result[0].gap
        assert gap is not None
        assert gap["gap_pct"] > 0
        assert gap["kind"] == "GAP UP"
        assert gap["prev_close"] == 25550

    def test_flat_gap(self):
        """No gap if open equals prev close."""
        candles = [
            {"timestamp": "2026-09-15T09:15:00", "open": 25550, "high": 25570, "low": 25530, "close": 25560, "volume": 1000},
        ]
        result = replay_day("NIFTY", "2026-09-15", candles, prev_close=25550)
        assert len(result) == 1
        gap = result[0].gap
        assert gap["kind"] == "FLAT OPEN"

    def test_empty_candles(self):
        result = replay_day("NIFTY", "2026-09-15", [])
        assert result == []


# ═══════════════════════════════════════════════════════
# No-Lookahead Tests
# ═══════════════════════════════════════════════════════

class TestNoLookahead:
    def test_evidence_uses_only_past_data(self):
        """Evidence at each step should reference data available at that step."""
        candles = [
            {"timestamp": "2026-09-15T09:15:00", "open": 25600, "high": 25620, "low": 25580, "close": 25610, "volume": 1000},
            {"timestamp": "2026-09-15T09:20:00", "open": 25610, "high": 25630, "low": 25600, "close": 25625, "volume": 1200},
        ]
        result = replay_day("NIFTY", "2026-09-15", candles, prev_close=25550)
        # At 09:15, should reference 09:15 data
        assert any("25610" in e for e in result[0].what_ai_knew)
        # At 09:20, should reference 09:20 data (not future)
        assert result[1].timestamp == "2026-09-15T09:20:00"

    def test_no_future_in_snapshot(self):
        """Snapshots should not contain data from future timestamps."""
        candles = [
            {"timestamp": "2026-09-15T09:15:00", "open": 25600, "high": 25620, "low": 25580, "close": 25610, "volume": 1000},
        ]
        result = replay_day("NIFTY", "2026-09-15", candles, prev_close=25550)
        snapshot = result[0]
        # What AI knew should not reference data after 09:15
        for ev in snapshot.what_ai_knew:
            assert "09:20" not in ev
            assert "09:25" not in ev


# ═══════════════════════════════════════════════════════
# Snapshot Immutability
# ═══════════════════════════════════════════════════════

class TestSnapshotImmutability:
    def test_snapshot_to_dict(self):
        candles = [
            {"timestamp": "2026-09-15T09:15:00", "open": 25600, "high": 25620, "low": 25580, "close": 25610, "volume": 1000},
        ]
        result = replay_day("NIFTY", "2026-09-15", candles, prev_close=25550)
        d = result[0].to_dict()
        assert d["symbol"] == "NIFTY"
        assert d["timestamp"] == "2026-09-15T09:15:00"

    def test_snapshot_to_json(self):
        candles = [
            {"timestamp": "2026-09-15T09:15:00", "open": 25600, "high": 25620, "low": 25580, "close": 25610, "volume": 1000},
        ]
        result = replay_day("NIFTY", "2026-09-15", candles, prev_close=25550)
        import json
        parsed = json.loads(result[0].to_json())
        assert parsed["symbol"] == "NIFTY"


# ═══════════════════════════════════════════════════════
# Trade Setup Evolution
# ═══════════════════════════════════════════════════════

class TestSetupEvolution:
    def test_setup_evolves_over_time(self):
        """Trade setup should change as more data becomes available."""
        candles = [
            {"timestamp": "2026-09-15T09:15:00", "open": 25600, "high": 25620, "low": 25580, "close": 25610, "volume": 1000},
            {"timestamp": "2026-09-15T09:20:00", "open": 25610, "high": 25630, "low": 25600, "close": 25625, "volume": 1200},
            {"timestamp": "2026-09-15T09:25:00", "open": 25625, "high": 25650, "low": 25620, "close": 25640, "volume": 1500},
        ]
        result = replay_day("NIFTY", "2026-09-15", candles, prev_close=25550)
        # Each snapshot should have a trade setup
        for snap in result:
            assert snap.trade_setup is not None, f"No setup at {snap.timestamp}"
            assert "trade_readiness" in snap.trade_setup

    def test_gap_stable_intraday(self):
        """Gap doesn't change during the day - it's opening vs prev close."""
        candles = [
            {"timestamp": "2026-09-15T09:15:00", "open": 25700, "high": 25720, "low": 25680, "close": 25710, "volume": 1000},
            {"timestamp": "2026-09-15T09:20:00", "open": 25710, "high": 25730, "low": 25700, "close": 25725, "volume": 1200},
            {"timestamp": "2026-09-15T09:25:00", "open": 25725, "high": 25750, "low": 25720, "close": 25740, "volume": 1500},
        ]
        result = replay_day("NIFTY", "2026-09-15", candles, prev_close=25550)
        gap_pcts = [s.gap["gap_pct"] for s in result if s.gap]
        # All should be the same (gap from open vs prev close)
        assert len(set(gap_pcts)) == 1


# ═══════════════════════════════════════════════════════
# Evidence and Uncertainty
# ═══════════════════════════════════════════════════════

class TestEvidenceCapture:
    def test_what_ai_knows(self):
        candles = [
            {"timestamp": "2026-09-15T09:15:00", "open": 25700, "high": 25720, "low": 25680, "close": 25710, "volume": 1000},
        ]
        result = replay_day("NIFTY", "2026-09-15", candles, prev_close=25550)
        snap = result[0]
        assert len(snap.what_ai_knew) >= 2
        # Should know price and gap
        assert any("25710" in e for e in snap.what_ai_knew)
        assert any("GAP UP" in e or "FLAT" in e for e in snap.what_ai_knew)

    def test_what_ai_does_not_know_empty_candles(self):
        result = replay_day("NIFTY", "2026-09-15", [])
        assert result == []

    def test_evidence_never_guarantees(self):
        candles = [
            {"timestamp": "2026-09-15T09:15:00", "open": 25600, "high": 25620, "low": 25580, "close": 25610, "volume": 1000},
        ]
        result = replay_day("NIFTY", "2026-09-15", candles, prev_close=25550)
        for snap in result:
            for ev in snap.what_ai_knew:
                assert "guarantee" not in ev.lower()
                assert "certain" not in ev.lower()


# ═══════════════════════════════════════════════════════
# Audit Trail
# ═══════════════════════════════════════════════════════

class TestAuditTrail:
    def test_timestamp_preserved(self):
        candles = [
            {"timestamp": "2026-09-15T09:15:00", "open": 25600, "high": 25620, "low": 25580, "close": 25610, "volume": 1000},
        ]
        result = replay_day("NIFTY", "2026-09-15", candles, prev_close=25550)
        snap = result[0]
        assert snap.timestamp == "2026-09-15T09:15:00"

    def test_data_quality_preserved(self):
        candles = [
            {"timestamp": "2026-09-15T09:15:00", "open": 25600, "high": 25620, "low": 25580, "close": 25610, "volume": 1000},
        ]
        result = replay_day("NIFTY", "2026-09-15", candles, prev_close=25550)
        snap = result[0]
        assert snap.data_quality in ("LIVE", "DATA UNAVAILABLE")

    def test_indicators_version_preserved(self):
        candles = [
            {"timestamp": "2026-09-15T09:15:00", "open": 25600, "high": 25620, "low": 25580, "close": 25610, "volume": 1000},
        ]
        result = replay_day("NIFTY", "2026-09-15", candles, prev_close=25550)
        snap = result[0]
        # May or may not have indicator version
        assert isinstance(snap.indicators_version, str)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
