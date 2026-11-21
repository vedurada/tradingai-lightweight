"""Cadence and identity checks for the isolated sma9_5min scanner."""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts/sma9_5min_scanner/app/live_sma9_5min_scanner.py"


@pytest.fixture
def scanner_module():
    """Import the runner with its own `app` package, without touching the DB."""
    saved_app = {
        name: module for name, module in sys.modules.items()
        if name == "app" or name.startswith("app.")
    }
    saved_path = list(sys.path)

    sys.path[:] = [p for p in sys.path if not str(p).startswith(str(ROOT))]
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]

    name = "live_sma9_5min_scanner_timing"
    spec = importlib.util.spec_from_file_location(name, RUNNER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(name, None)

    for key in list(sys.modules):
        if key == "app" or key.startswith("app."):
            del sys.modules[key]
    sys.modules.update(saved_app)
    sys.path[:] = saved_path


def test_sma9_5min_identity_and_cadence(scanner_module):
    assert scanner_module.POLL_SECONDS == 300
    assert scanner_module.POLL_OFFSET_SEC == 10
    assert scanner_module.STRATEGY_ID == "sma9_5min"
    assert scanner_module.DB_PATH.endswith("sma9_5min.db")


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2026-11-21T09:17:33+05:30", "2026-11-21T09:20:10+05:30"),
        ("2026-11-21T09:20:00+05:30", "2026-11-21T09:20:10+05:30"),
        ("2026-11-21T09:20:09+05:30", "2026-11-21T09:20:10+05:30"),
        ("2026-11-21T09:20:10+05:30", "2026-11-21T09:25:10+05:30"),
        ("2026-11-21T15:17:59+05:30", "2026-11-21T15:20:10+05:30"),
    ],
)
def test_next_poll_time_is_aligned_to_5m_boundary(scanner_module, value, expected):
    assert scanner_module.next_poll_time(datetime.fromisoformat(value)) == (
        datetime.fromisoformat(expected))


def test_status_exposes_poll_alignment(scanner_module, monkeypatch):
    monkeypatch.setattr(scanner_module, "today_stats", lambda _date: {})
    runner = scanner_module.Sma9LiveScanner(None)
    status = runner._status(
        datetime.fromisoformat("2026-11-21T09:20:10+05:30"), {})
    assert status["poll_seconds"] == 300
    assert status["poll_alignment"] == "5m_boundary_plus_10s"
