"""Pattern scanner must never report RUNNING on a data-less mock feed.

A failed Kite/gateway connection used to fall back to MockFeed (no option
prices, possibly stale spot from the DB) while the status file still said
RUNNING. Operators read that status to decide whether quotes are trustworthy.
"""
from __future__ import annotations

from scripts.pattern_scanner_live import MockFeed, PatternScannerLive


class _FakePS:
    def __init__(self, status="RUNNING"):
        self.status = status

    def get_status(self):
        return {"status": self.status, "scanner": "pattern_scanner"}


def _scanner(live_ok, available):
    scanner = PatternScannerLive.__new__(PatternScannerLive)
    scanner.ps = _FakePS()
    scanner.live_feed_ok = live_ok
    feed = MockFeed()
    feed.available = available
    scanner.feed = feed
    return scanner


def test_mock_feed_reports_no_live_feed():
    scanner = _scanner(live_ok=False, available=True)
    status = scanner._status_snapshot()
    assert status["status"] == "NO_LIVE_FEED"
    assert status["data_available"] is False
    assert status["feed"] == "mock"
    assert status["poll_interval_sec"] == 300
    assert status["poll_alignment"] == "5m_boundary_plus_10s"
    assert status["exit_data"] == "completed_5m_option_ohlc"
    assert any("no live broker feed" in e for e in status["errors"])


def test_live_feed_keeps_running_status():
    scanner = _scanner(live_ok=True, available=True)
    status = scanner._status_snapshot()
    assert status["status"] == "RUNNING"
    assert status["data_available"] is True
    assert status["feed"] == "live"
    assert status["errors"] == []


def test_live_feed_that_lost_availability_is_not_running():
    scanner = _scanner(live_ok=True, available=False)
    status = scanner._status_snapshot()
    assert status["status"] == "NO_LIVE_FEED"
    assert status["data_available"] is False
