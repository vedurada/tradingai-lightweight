"""mStock published rate-limit guards: 1/s Data APIs, 20/s Quote APIs."""
from __future__ import annotations

import datetime as dt
import pathlib
import re

import pytest

from broker_gateway.adapters import mstock

ROOT = pathlib.Path(__file__).resolve().parents[1]
FAST_SCANNERS = (
    "sma9", "sma9_high", "sma9_trail",
    "sma9_atr", "sma9_adx",
)


def test_history_cache_key_is_one_per_token_per_5m_bar():
    start = dt.datetime(2026, 11, 23, 3, 45, tzinfo=dt.timezone.utc)
    first = dt.datetime(2026, 11, 23, 9, 20, 2, 123456, tzinfo=mstock.IST)
    same_bar = dt.datetime(2026, 11, 23, 9, 22, 57, 987654, tzinfo=mstock.IST)
    next_bar = dt.datetime(2026, 11, 23, 9, 25, 1, tzinfo=mstock.IST)

    key = mstock._history_cache_key(12345, "5minute", "sig", start, first)
    assert key == mstock._history_cache_key(12345, "5minute", "sig", start, same_bar)
    assert key != mstock._history_cache_key(12345, "5minute", "sig", start, next_bar)
    assert key != mstock._history_cache_key(99999, "5minute", "sig", start, first)


def test_data_api_calls_are_paced_to_one_per_second(monkeypatch):
    clock = [100.0]
    slept = []
    monkeypatch.setattr(mstock.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        mstock.time,
        "sleep",
        lambda seconds: (slept.append(seconds), clock.__setitem__(0, clock[0] + seconds)),
    )
    monkeypatch.setattr(mstock, "_DATA_API_LAST", 0.0)

    mstock._pace_data_api()
    assert slept == []
    mstock._pace_data_api()
    assert len(slept) == 1
    assert slept[0] == pytest.approx(mstock.DATA_API_MIN_INTERVAL)
    clock[0] += mstock.DATA_API_MIN_INTERVAL + 0.001
    mstock._pace_data_api()
    assert len(slept) == 1  # no extra wait once the interval has elapsed


def test_fast_scanners_have_distinct_poll_phases():
    offsets = {}
    for alias in FAST_SCANNERS:
        path = ROOT / "scripts" / f"{alias}_scanner" / "app" / f"live_{alias}_scanner.py"
        text = path.read_text(encoding="utf-8")
        assert re.search(r"^POLL_SECONDS = 5$", text, re.M), alias
        match = re.search(r"^POLL_OFFSET_SECONDS = ([0-9.]+)", text, re.M)
        offsets[alias] = float(match.group(1)) if match else 0.0

    assert len(set(offsets.values())) == len(FAST_SCANNERS)
    assert all(0 <= value < 5 for value in offsets.values())
