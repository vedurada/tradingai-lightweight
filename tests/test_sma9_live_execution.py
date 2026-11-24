"""Tests for the isolated sma9_live dry-run execution scaffold.

These assert that real orders stay hard-disabled by default and that the risk
guards cannot be bypassed. No credentials or broker calls are involved.
"""
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "scripts" / "sma9_live_scanner" / "app"


@pytest.fixture(scope="module")
def execution():
    name = "sma9_live_execution_under_test"
    spec = importlib.util.spec_from_file_location(name, APP / "live_execution.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_defaults_are_dry_run_and_disarmed(execution):
    limits = execution.RiskLimits.from_env({})
    assert limits.max_orders_per_day == 4
    assert limits.lot_size == 75
    assert limits.collar_pct == 1.0
    assert execution.build_executor({}).name == "dry_run"
    assert execution.real_orders_armed({}) is False
    # The real executor is wired, but it fails closed until both flags are set.
    with pytest.raises(PermissionError):
        execution.MStockOrderExecutor().place(object())


@pytest.mark.parametrize(
    "env,expected",
    [
        ({}, False),
        ({"SMA9_LIVE_ORDERS_ENABLED": "true"}, False),
        ({"SMA9_LIVE_ARM_REAL_ORDERS": "ARMED"}, False),
        (
            {"SMA9_LIVE_ORDERS_ENABLED": "true",
             "SMA9_LIVE_ARM_REAL_ORDERS": "ARMED"},
            True,
        ),
    ],
)
def test_real_orders_require_both_flags(execution, env, expected):
    assert execution.real_orders_armed(env) is expected


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_orders_per_day": 0},
        {"lot_size": 0},
        {"collar_pct": 0},
        {"collar_pct": 6},
        {"kill_file": ""},
    ],
)
def test_invalid_limits_are_rejected(execution, kwargs):
    with pytest.raises(ValueError):
        execution.RiskLimits(**kwargs).validate()


def test_client_order_ids_are_stable_and_side_specific(execution):
    a = execution.make_client_order_id("S9L-ABC", "BUY")
    b = execution.make_client_order_id("S9L-ABC", "BUY")
    sell = execution.make_client_order_id("S9L-ABC", "SELL")
    assert a == b
    assert a.startswith("S9L-BUY-")
    assert sell.startswith("S9L-SELL-")
    assert a != sell


def test_price_collar_direction(execution):
    assert execution.apply_price_collar(100, "BUY", 1.0) == 101.0
    assert execution.apply_price_collar(100, "SELL", 1.0) == 99.0


def test_kill_switch_env_and_file(execution, tmp_path):
    limits = execution.RiskLimits(kill_file=str(tmp_path / "missing.KILL"))
    assert execution.kill_switch_active(limits, {}) is False
    assert execution.kill_switch_active(limits, {"SMA9_LIVE_KILLED": "true"}) is True
    (tmp_path / "missing.KILL").write_text("stop")
    assert execution.kill_switch_active(limits, {}) is True


def test_entry_allowed_guards(execution, tmp_path):
    limits = execution.RiskLimits(max_orders_per_day=2,
                                  kill_file=str(tmp_path / "missing.KILL"))
    assert execution.entry_allowed([], 0, limits, {}) == (True, "OK")
    assert execution.entry_allowed([], 2, limits, {}) == (False, "DAILY_ORDER_CAP")
    assert execution.entry_allowed([object(), object()], 0, limits, {}) == (
        False, "MAX_TWO_OPEN_LEGS")
    assert execution.entry_allowed([], 0, limits,
                                   {"SMA9_LIVE_KILLED": "1"}) == (
        False, "KILL_SWITCH_ACTIVE")


def test_dry_run_executor_never_touches_a_broker(execution):
    record = execution.OrderRecord(
        client_order_id="S9L-BUY-TEST",
        trade_id="S9L-TRADE",
        option_type="CE",
        side="BUY",
        symbol="NFO:TEST",
        token=1,
        quantity=75,
        intended_price=100.0,
        limit_price=101.0,
        collar_pct=1.0,
        reason="SMA9_ENTRY",
    )
    result = execution.DryRunOrderExecutor().place(record)
    assert result.status == execution.STATUS_DRY_RUN
    assert result.dry_run is True
    assert result.broker_order_id.startswith("DRY-")


def test_order_record_validation(execution):
    base = dict(
        client_order_id="S9L-X", trade_id="T", option_type="CE", side="BUY",
        symbol="NFO:X", token=1, quantity=75, intended_price=100,
        limit_price=101, collar_pct=1.0, reason="SMA9_ENTRY",
    )
    with pytest.raises(ValueError):
        execution.OrderRecord(**{**base, "side": "HOLD"})
    with pytest.raises(ValueError):
        execution.OrderRecord(**{**base, "quantity": 0})


@pytest.fixture
def live_runner(tmp_path, monkeypatch):
    """Load the live runner against a private DB with safe env defaults."""
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
    monkeypatch.setenv("SMA9_LIVE_DB_PATH", str(tmp_path / "sma9_live.db"))
    monkeypatch.setenv("SMA9_LIVE_EXECUTOR", "dry_run")
    for key in ("SMA9_LIVE_KILLED", "SMA9_LIVE_ORDERS_ENABLED",
                "SMA9_LIVE_ARM_REAL_ORDERS"):
        monkeypatch.delenv(key, raising=False)

    name = "sma9_live_runner_under_test"
    spec = importlib.util.spec_from_file_location(
        name, APP / "live_sma9_live_scanner.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    mod.init_db()
    yield mod
    for key in list(sys.modules):
        if key == "app" or key.startswith("app.") or key == name:
            del sys.modules[key]


def test_order_ledger_is_idempotent_and_counts_for_daily_cap(
        live_runner, execution):
    mod = live_runner
    scanner = mod.Sma9LiveScanner(feed=None)
    pos = SimpleNamespace(
        trade_id="S9L-TESTTRADE",
        option_type="CE",
        tradingsymbol="NIFTY26SEP200CE",
        token=12345,
    )

    first = scanner._place_order(pos, "BUY", 100.0, "SMA9_ENTRY")
    assert first is not None
    assert first.status == execution.STATUS_DRY_RUN
    # A repeated call at a different price must not create a second order.
    assert scanner._place_order(pos, "BUY", 101.0, "SMA9_ENTRY") is None
    today = mod.now_ist().date().isoformat()
    assert mod.orders_today(today) == 1
    assert mod.order_exists(execution.make_client_order_id(
        "S9L-TESTTRADE", "BUY"))

    sell = scanner._place_order(pos, "SELL", 95.0, "TRAIL_STOP_EXIT")
    assert sell is not None
    assert sell.side == "SELL"
    assert sell.limit_price < sell.intended_price
    assert mod.orders_today(today) == 2

    row = mod.order_status_for("S9L-TESTTRADE", "BUY")
    assert row["dry_run"] == 1
    assert row["status"] == execution.STATUS_DRY_RUN


def _order(execution, **overrides):
    base = dict(
        client_order_id="S9L-BUY-ABC", trade_id="S9L-TRADE", option_type="CE",
        side="BUY", symbol="NFO:NIFTY26NOV20000CE", token=12345, quantity=75,
        intended_price=100.0, limit_price=101.0, collar_pct=1.0,
        reason="SMA9_ENTRY", dry_run=True,
    )
    base.update(overrides)
    return execution.OrderRecord(**base)


def test_mstock_executor_requires_both_flags_and_kill_switch(execution, tmp_path):
    env = {
        "SMA9_LIVE_ORDERS_ENABLED": "true",
        "SMA9_LIVE_ARM_REAL_ORDERS": "ARMED",
        "SMA9_LIVE_KILL_FILE": str(tmp_path / "missing.KILL"),
    }
    calls = []
    def fake_call(*args, **kwargs):
        calls.append(kwargs)
        return {"order_id": "MOCK-ORDER-1"}
    ex = execution.MStockOrderExecutor(caller=fake_call, environ=env)
    record = _order(execution)
    assert ex.place(record).status == execution.STATUS_ACCEPTED
    assert len(calls) == 1
    assert calls[0]["transaction_type"] == "BUY"
    assert calls[0]["order_type"] == "LIMIT"
    assert calls[0]["product"] == "MIS"
    assert calls[0]["tag"] == "S9L-BUY-ABC"
    assert record.dry_run is False
    assert record.broker_order_id == "MOCK-ORDER-1"

    (tmp_path / "missing.KILL").write_text("stop")
    with pytest.raises(PermissionError):
        ex.place(_order(execution, client_order_id="S9L-BUY-NEW"))


def test_mstock_executor_fails_closed_on_gateway_error(execution, tmp_path):
    env = {
        "SMA9_LIVE_ORDERS_ENABLED": "true",
        "SMA9_LIVE_ARM_REAL_ORDERS": "ARMED",
        "SMA9_LIVE_KILL_FILE": str(tmp_path / "missing.KILL"),
    }
    def boom(*args, **kwargs):
        raise RuntimeError("gateway unavailable")

    ex = execution.MStockOrderExecutor(caller=boom, environ=env)
    record = _order(execution)
    with pytest.raises(RuntimeError):
        ex.place(record)
    assert record.status == execution.STATUS_REJECTED
    assert record.broker_order_id is None
    assert record.dry_run is False


def test_mstock_executor_rejects_non_nfo_symbol(execution, tmp_path):
    env = {
        "SMA9_LIVE_ORDERS_ENABLED": "true",
        "SMA9_LIVE_ARM_REAL_ORDERS": "ARMED",
        "SMA9_LIVE_KILL_FILE": str(tmp_path / "missing.KILL"),
    }
    ex = execution.MStockOrderExecutor(caller=lambda *a, **k: {}, environ=env)
    with pytest.raises(ValueError):
        ex.place(_order(execution, symbol="BSE:INFY"))


def test_mstock_executor_maps_order_status(execution):
    responses = [
        {"status": "FILLED"}, {"status": "REJECTED"}, {"status": "OPEN"},
    ]
    ex = execution.MStockOrderExecutor(caller=lambda *a, **k: responses.pop(0))
    record = _order(execution, broker_order_id="MOCK-ORDER-1")
    assert ex.order_status(record) == execution.STATUS_FILLED
    assert ex.order_status(record) == execution.STATUS_REJECTED
    assert ex.order_status(record) == execution.STATUS_ACCEPTED
