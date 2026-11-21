"""Timing guards for the pattern scanner's aligned 5-minute cadence.

The live runner still starts at 09:00 so the Kite feed and status heartbeat are
warm before the exchange opens at 09:15. These tests pin the guards that keep
the warm-up harmless and keep exits on completed 5m option bars:

  * CandleBuffer ignores ticks before 09:15, so no synthetic pre-open candle
    can become the first signal candle.
  * _manage_positions_bar ignores forming bars and pre-open bar closes, so no
    premium ATR stop can fire before 09:15 or from a partial bar.
  * Premium exits are managed only on the position's own option bar; spot
    ticks, quotes and other option symbols never manage an open position.
  * The live loop polls at a 5m boundary plus a small publication offset.

Pure in-memory tests: a dummy sqlite connection stands in for the live DB.
"""
import importlib.util
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.research.pattern_scanner import (  # noqa: E402
    CandleBuffer,
    FIRST_CANDLE_START,
    MARKET_OPEN,
    PatternScanner,
)

IST = timezone(timedelta(hours=5, minutes=30))
DAY = datetime(2026, 11, 19, tzinfo=IST)


def at(h, m, s=0):
    return DAY.replace(hour=h, minute=m, second=s)


def option_bar(start, high=120.0, low=120.0):
    """Completed 5m option OHLC bar starting at `start`."""
    return {
        "start": start,
        "open": 120.0,
        "high": high,
        "low": low,
        "close": 120.0,
        "volume": 0,
    }


def dummy_conn():
    """Schema-free connection; the scanner's schema helpers swallow errors."""
    return sqlite3.connect(":memory:")


class FakePosition:
    """Records premium ATR bar evaluations without the full position model."""

    def __init__(self, instrument="TEST_CE_OLD"):
        self.instrument = instrument
        self.entry_ts = (DAY - timedelta(days=1)).isoformat()
        self.stop_loss = 100.0
        self.mfe_points = 0.0
        self.mae_points = 0.0
        self.calls = []

    def evaluate_bar(self, bar_high, bar_low, timestamp):
        self.calls.append((bar_high, bar_low, timestamp))
        return None


def make_scanner():
    scanner = PatternScanner(dummy_conn)
    scanner.positions = {"sentinel:TEST_CE_OLD": FakePosition()}
    return scanner


def _load_live_runner():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "scripts", "pattern_scanner_live.py")
    spec = importlib.util.spec_from_file_location("pattern_scanner_live_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_constants():
    assert str(MARKET_OPEN) == "09:00:00", MARKET_OPEN
    assert str(FIRST_CANDLE_START) == "09:15:00", FIRST_CANDLE_START


def test_buffer_ignores_pre_open_ticks():
    buf = CandleBuffer("NIFTY_SPOT", "SPOT")
    for h, m in [(9, 0), (9, 4), (9, 5), (9, 9), (9, 10), (9, 14)]:
        assert buf.on_tick(25000.0, at(h, m)) is None
    assert buf.current is None and buf.candles == []

    # 09:15 opens the first real candle; 09:20 completes it.
    assert buf.on_tick(25010.0, at(9, 15, 2)) is None
    done = buf.on_tick(25020.0, at(9, 20, 1))
    assert done is not None
    assert done["timestamp"].startswith("2026-11-19T09:15"), done


def test_exit_management_ignores_pre_open_bar_closes():
    scanner = make_scanner()
    pos = next(iter(scanner.positions.values()))

    # 09:05 poll: previous 09:00 bar closes before the exchange opens.
    scanner._manage_positions_bar(
        pos.instrument, option_bar(at(9, 0)), at(9, 5, 10))
    assert pos.calls == [], "pre-open bar close must not manage exits"

    # 09:15 poll: the 09:10 bar is still a pre-open bar; it must not manage.
    scanner._manage_positions_bar(
        pos.instrument, option_bar(at(9, 10)), at(9, 15, 10))
    assert pos.calls == [], "a bar starting before 09:15 must not manage exits"

    # 09:20 poll: the 09:15 bar closes at 09:20 and may manage the position.
    scanner._manage_positions_bar(
        pos.instrument, option_bar(at(9, 15)), at(9, 20, 10))
    assert len(pos.calls) == 1, "09:15 completed bar must manage exits"
    assert pos.calls[0][2] == at(9, 20).isoformat()


def test_forming_bar_is_not_managed():
    scanner = make_scanner()
    pos = next(iter(scanner.positions.values()))
    scanner._manage_positions_bar(
        pos.instrument, option_bar(at(9, 15)), at(9, 18, 0))
    assert pos.calls == [], "a bar whose end is in the future is still forming"


def test_spot_ticks_never_manage_premium_exits():
    scanner = make_scanner()
    pos = next(iter(scanner.positions.values()))
    scanner._manage_positions_bar(
        "NIFTY_SPOT", option_bar(at(9, 15)), at(10, 0))
    assert pos.calls == [], "spot bars must not manage premium exits"


def test_other_option_bars_do_not_manage_positions():
    scanner = make_scanner()
    pos = next(iter(scanner.positions.values()))
    scanner._manage_positions_bar(
        "NIFTY26NOV25000PE", option_bar(at(9, 15)), at(10, 0))
    assert pos.calls == [], "only the position's own option bar may manage it"


def test_aligned_poll_schedule():
    runner = _load_live_runner()
    assert runner.POLL_INTERVAL_SEC == 300
    assert runner.POLL_OFFSET_SEC == 10

    cls = runner.PatternScannerLive
    assert cls.next_poll_time(at(9, 15, 9)) == at(9, 15, 10)
    assert cls.next_poll_time(at(9, 15, 10)) == at(9, 20, 10)
    assert cls.next_poll_time(at(9, 19, 59)) == at(9, 20, 10)
    assert cls.next_poll_time(at(14, 59, 59)) == at(15, 0, 10)


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    if failures:
        raise SystemExit(1)
    print("\nAll checks passed.")
