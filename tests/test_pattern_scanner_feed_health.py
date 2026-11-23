"""Pattern scanner must never report RUNNING on a data-less mock feed.

A failed Kite/gateway connection used to fall back to MockFeed (no option
prices, possibly stale spot from the DB) while the status file still said
RUNNING. Operators read that status to decide whether quotes are trustworthy.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.pattern_scanner_live import MockFeed, PatternScannerLive

IST = timezone(timedelta(hours=5, minutes=30))


def at(h, m, s=0):
    return datetime(2026, 11, 18, h, m, s, tzinfo=IST)


class _FakePS:
    def __init__(self, status="RUNNING"):
        self.status = status
        self.positions = {}

    def get_status(self):
        return {"status": self.status, "scanner": "pattern_scanner"}


def _scanner(live_ok, available):
    scanner = PatternScannerLive.__new__(PatternScannerLive)
    scanner.ps = _FakePS()
    scanner.live_feed_ok = live_ok
    feed = MockFeed()
    feed.available = available
    scanner.feed = feed
    scanner._failed_bar_symbols = set()
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


def test_live_feed_with_failed_option_bar_is_not_running():
    scanner = _scanner(live_ok=True, available=True)
    scanner._failed_bar_symbols = {"NIFTY26NOV24000CE"}
    status = scanner._status_snapshot()
    assert status["status"] == "NO_OPTION_DATA"
    assert status["data_available"] is True
    assert status["exit_data_available"] is False
    assert any("option bar unavailable" in e for e in status["errors"])


def test_mock_feed_keeps_no_live_feed_even_with_failed_bars():
    scanner = _scanner(live_ok=False, available=True)
    scanner._failed_bar_symbols = {"NIFTY26NOV24000CE"}
    status = scanner._status_snapshot()
    assert status["status"] == "NO_LIVE_FEED"
    assert status["exit_data_available"] is False


def test_failed_completed_bar_is_retried_before_the_next_bar():
    scanner = _scanner(live_ok=True, available=True)
    scanner._pending_bars = {}
    applied = []

    class FlakyFeed:
        available = True

        def __init__(self):
            self.fail_once = at(9, 20)

        def completed_5m_bar(self, sym, start):
            if start == self.fail_once:
                self.fail_once = None
                return None
            return {"start": start, "open": 100.0, "high": 100.0,
                    "low": 100.0, "close": 100.0}

    scanner.feed = FlakyFeed()
    scanner.ps.positions = {"TEST_CE": object()}
    scanner.ps.on_option_bar = lambda sym, bar, now: applied.append(bar["start"])

    # 09:25 poll -> previous completed bar is 09:20; its fetch fails.
    scanner._fetch_completed_bars(["TEST_CE"], at(9, 25, 10))
    assert applied == []
    assert scanner._pending_bars == {"TEST_CE": at(9, 20)}
    assert scanner._failed_bar_symbols == {"TEST_CE"}

    # 09:30 poll -> retry 09:20 first, then the new 09:25 bar.
    scanner._failed_bar_symbols.clear()
    scanner._fetch_completed_bars(["TEST_CE"], at(9, 30, 10))
    assert applied == [at(9, 20), at(9, 25)]
    assert scanner._pending_bars == {}
    assert scanner._failed_bar_symbols == set()


def test_missing_bar_for_unheld_atm_does_not_block_entries():
    scanner = _scanner(live_ok=True, available=True)
    scanner._pending_bars = {}

    class NoBarFeed:
        available = True

        def completed_5m_bar(self, sym, start):
            return None

    scanner.feed = NoBarFeed()
    scanner.ps.on_option_bar = lambda sym, bar, now: None

    # Current ATM changes every poll; a missing prior bar for an unheld
    # strike must not be reported as NO_OPTION_DATA or block fresh entries.
    scanner._fetch_completed_bars(["TEST_CE"], at(9, 25, 10))
    assert scanner._failed_bar_symbols == set()
    status = scanner._status_snapshot()
    assert status["status"] == "RUNNING"
    assert status["exit_data_available"] is True
