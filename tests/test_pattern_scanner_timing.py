"""Timing guards for the pattern scanner's 09:00 warm-up.

The live runner starts at 09:00 so the Kite feed and status heartbeat are warm
before the exchange opens at 09:15. These tests pin the guards that keep the
warm-up harmless:

  * CandleBuffer ignores ticks before 09:15, so no synthetic pre-open candle
    can become the first signal candle.
  * _manage_positions_tick ignores pre-open quotes, so no premium ATR stop can
    fire before 09:15.
  * Premium exits are managed only on the position's own option tick; spot
    ticks and other option symbols never manage an open position.

Pure in-memory tests: a dummy sqlite connection stands in for the live DB.
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.research.pattern_scanner import (  # noqa: E402
    CandleBuffer,
    FIRST_CANDLE_START,
    MARKET_OPEN,
    PatternScanner,
)

from datetime import datetime, timedelta, timezone  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
DAY = datetime(2026, 11, 19, tzinfo=IST)


def at(h, m, s=0):
    return DAY.replace(hour=h, minute=m, second=s)


def dummy_conn():
    """Schema-free connection; the scanner's schema helpers swallow errors."""
    return sqlite3.connect(":memory:")


class FakePosition:
    """Records premium ATR trail updates without the full position model."""

    def __init__(self, instrument="TEST_CE_OLD"):
        self.instrument = instrument
        self.entry_ts = (DAY - timedelta(days=1)).isoformat()
        self.stop_loss = 100.0
        self.mfe_points = 0.0
        self.mae_points = 0.0
        self.calls = []

    def update_mfe_mae(self, premium_high, premium_low):
        self.mfe_points = max(self.mfe_points, premium_high)
        self.mae_points = min(self.mae_points, premium_low)

    def update_trail(self, ltp, ts_iso):
        self.calls.append((ltp, ts_iso))
        return None

    def check_stop_loss(self, ltp):
        return None


def make_scanner():
    scanner = PatternScanner(dummy_conn)
    scanner.positions = {"sentinel:TEST_CE_OLD": FakePosition()}
    return scanner


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


def test_exit_management_ignores_pre_open_ticks():
    scanner = make_scanner()
    pos = next(iter(scanner.positions.values()))

    scanner._manage_positions_tick(pos.instrument, 120.0, at(9, 10))
    assert pos.calls == [], "pre-open tick must not manage exits"

    scanner._manage_positions_tick(pos.instrument, 120.0, at(9, 15, 1))
    assert len(pos.calls) == 1, "09:15 option tick must manage exits"
    assert pos.calls[0][0] == 120.0


def test_spot_ticks_never_manage_premium_exits():
    scanner = make_scanner()
    pos = next(iter(scanner.positions.values()))
    scanner._manage_positions_tick("NIFTY_SPOT", 24000.0, at(10, 0))
    assert pos.calls == [], "spot ticks must not manage premium exits"


def test_other_option_ticks_do_not_manage_positions():
    scanner = make_scanner()
    pos = next(iter(scanner.positions.values()))
    scanner._manage_positions_tick("NIFTY26NOV25000PE", 120.0, at(10, 0))
    assert pos.calls == [], "only the position's own option tick may manage it"


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
