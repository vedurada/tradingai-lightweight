"""Every standalone SMA scanner must refuse to trade on NSE holidays.

Regression: 2026-11-24 (Guru Nanak Jayanti) is a weekday holiday that the
runners' weekday-only check treated as a session. Stale broker quotes were
then used to build quote-derived 5m bars and five scanners opened paper
positions at the last traded price.
"""
import importlib.util
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
IST = ZoneInfo("Asia/Kolkata")

SCANNERS = (
    ("sma9", "SMA9_DB_PATH"),
    ("sma9_live", "SMA9_LIVE_DB_PATH"),
    ("sma9_5min", "SMA9_5MIN_DB_PATH"),
    ("sma9_atr", "SMA9_ATR_DB_PATH"),
    ("sma9_trail", "SMA9_TRAIL_DB_PATH"),
    ("sma9_adx", "SMA9_ADX_DB_PATH"),
    ("sma9_high", "SMA9_HIGH_DB_PATH"),
)


@pytest.fixture
def load_runner(tmp_path, monkeypatch):
    saved_path = list(sys.path)

    def _load(key, env_key):
        sys.path[:] = [p for p in sys.path if not str(p).startswith(str(ROOT))]
        for name in list(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]
        monkeypatch.setenv(env_key, str(tmp_path / (key + ".db")))
        path = ROOT / "scripts" / (key + "_scanner") / "app" / ("live_" + key + "_scanner.py")
        name = "holiday_" + key
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod

    yield _load

    sys.path[:] = saved_path
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]


@pytest.mark.parametrize("key,env_key", SCANNERS)
def test_nse_holidays_are_not_sessions(key, env_key, load_runner):
    mod = load_runner(key, env_key)
    holiday = datetime(2026, 11, 24, 10, 0, tzinfo=IST)  # Guru Nanak Jayanti
    assert mod.is_weekday(holiday) is False
    assert mod.market_is_open(holiday) is False
    assert mod.entry_window_is_open(holiday) is False


@pytest.mark.parametrize("key,env_key", SCANNERS)
def test_normal_sessions_still_allowed(key, env_key, load_runner):
    mod = load_runner(key, env_key)
    trading_day = datetime(2026, 11, 23, 10, 0, tzinfo=IST)  # Monday
    assert mod.is_weekday(trading_day) is True
    assert mod.market_is_open(trading_day) is True
    assert mod.entry_window_is_open(trading_day) is True
    muhurat = datetime(2026, 11, 8, 15, 0, tzinfo=IST)  # special session override
    assert mod.is_weekday(muhurat) is True
    weekend = datetime(2026, 11, 21, 10, 0, tzinfo=IST)  # Saturday
    assert mod.is_weekday(weekend) is False
