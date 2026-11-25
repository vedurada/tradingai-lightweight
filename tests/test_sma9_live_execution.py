"""Tests for the isolated sma9_live dry-run execution scaffold.

These assert that real orders stay hard-disabled by default and that the risk
guards cannot be bypassed. No credentials or broker calls are involved.
"""
import importlib.util
import os
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
    assert limits.max_orders_per_day == 4  # scaffold default; VM sets 0
    assert limits.lot_size == 0  # resolve from mStock instrument master
    assert limits.collar_pct == 0.0  # price collar removed by operator
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
        {"max_orders_per_day": -1},
        {"lot_size": -1},
        {"collar_pct": -1},
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
    assert execution.price_collar_breached(101.0, 100.0, 1.0) is False
    assert execution.price_collar_breached(101.1, 100.0, 1.0) is True
    assert execution.price_collar_breached(102.0, None, 1.0) is False


def test_price_collar_can_be_disabled(execution):
    assert execution.RiskLimits.from_env(
        {"SMA9_LIVE_PRICE_COLLAR_PCT": "0"}).collar_pct == 0.0
    assert execution.apply_price_collar(100, "BUY", 0) == 100.0
    assert execution.price_collar_breached(500.0, 100.0, 0) is False
    assert execution.RiskLimits(collar_pct=5.0).validate() is None


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


def test_zero_daily_cap_means_unlimited(execution, tmp_path):
    limits = execution.RiskLimits(
        max_orders_per_day=0, kill_file=str(tmp_path / "missing.KILL"))
    assert execution.RiskLimits.from_env(
        {"SMA9_LIVE_MAX_ORDERS_PER_DAY": "0"}).max_orders_per_day == 0
    assert execution.entry_allowed([], 999, limits, {}) == (True, "OK")


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


class FakeMstockFeed:
    """Minimal feed that reports the lot size mStock exposes for NIFTY options."""

    def find_contract(self, strike, expiry, option_type):
        return {
            "lot_size": 65,
            "tradingsymbol": "NIFTY26SEP200CE",
            "instrument_token": 12345,
            "strike": strike,
            "expiry": expiry,
        }


def _position(**overrides):
    base = dict(
        trade_id="S9L-TESTTRADE",
        option_type="CE",
        tradingsymbol="NIFTY26SEP200CE",
        token=12345,
        strike=20000.0,
        expiry="2026-09-24",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _full_position(mod, **overrides):
    """A real engine Position, usable by the DB-backed entry path."""
    now = mod.now_ist()
    base = dict(
        option_type="CE",
        trade_id="S9L-FULLPOS",
        strike=25750.0,
        expiry="2026-12-01",
        token=47837,
        tradingsymbol="NIFTY26D0125750CE",
        entry_timestamp=now,
        entry_candle_start=now,
        entry_candle_end=now,
        entry_price=220.45,
        sma9=126.93,
        prev_close=222.95,
        current_open=220.45,
        condition_a=True,
        condition_b=True,
        ltp_at_entry=220.45,
    )
    base.update(overrides)
    return mod.Position(**base)


def test_order_ledger_is_idempotent_and_uses_broker_lot_size(
        live_runner, execution):
    mod = live_runner
    scanner = mod.Sma9LiveScanner(feed=FakeMstockFeed())
    pos = _position()

    first = scanner._place_order(pos, "BUY", 100.0, "SMA9_ENTRY")
    assert first is not None
    assert first.status == execution.STATUS_DRY_RUN
    assert first.quantity == 65
    # A repeated call at a different price must not create a second order.
    assert scanner._place_order(pos, "BUY", 101.0, "SMA9_ENTRY") is None
    today = mod.now_ist().date().isoformat()
    assert mod.orders_today(today) == 1
    assert mod.order_exists(execution.make_client_order_id(
        "S9L-TESTTRADE", "BUY"))

    sell = scanner._place_order(pos, "SELL", 95.0, "TRAIL_STOP_EXIT")
    assert sell is not None
    assert sell.side == "SELL"
    # No price collar means the audit reference equals the intended price.
    assert sell.limit_price == sell.intended_price
    assert mod.orders_today(today) == 2

    row = mod.order_status_for("S9L-TESTTRADE", "BUY")
    assert row["dry_run"] == 1
    assert row["status"] == execution.STATUS_DRY_RUN


def test_disabled_collar_does_not_block_large_buy_jump(
        live_runner, execution, monkeypatch):
    mod = live_runner
    monkeypatch.setattr(mod, "LIMITS", execution.RiskLimits(collar_pct=0.0))
    scanner = mod.Sma9LiveScanner(feed=FakeMstockFeed())
    scanner._last_ltp["CE"] = 100.0
    pos = _position(trade_id="S9L-NO-COLLAR")

    order = scanner._place_order(pos, "BUY", 500.0, "SMA9_ENTRY")
    assert order is not None
    assert scanner.last_order_block is None
    assert mod.order_status_for(pos.trade_id, "BUY") is not None


def test_pre_submit_block_does_not_leave_phantom_position(live_runner, monkeypatch):
    mod = live_runner
    scanner = mod.Sma9LiveScanner(feed=None)
    pos = _full_position(mod, trade_id="S9L-PHANTOM-CE")

    def blocked(*args, **kwargs):
        scanner.last_order_block = "PRICE_COLLAR_BREACH"
        return None

    monkeypatch.setattr(scanner, "_place_order", blocked)

    assert scanner._start_entry("CE", pos) is False
    assert mod.load_open_positions().get("CE") is None
    assert scanner.last_order_block == "PRICE_COLLAR_BREACH"
    assert mod.order_status_for(pos.trade_id, "BUY") is None


def test_ambiguous_submit_still_keeps_unconfirmed_position(live_runner, monkeypatch):
    mod = live_runner
    scanner = mod.Sma9LiveScanner(feed=None)
    pos = _full_position(mod, trade_id="S9L-AMBIG-CE")

    def ambiguous(*args, **kwargs):
        scanner.last_order_block = "SUBMIT_EXCEPTION"
        return None

    monkeypatch.setattr(scanner, "_place_order", ambiguous)

    assert scanner._start_entry("CE", pos) is False
    saved = mod.load_open_positions().get("CE")
    assert saved is not None
    assert saved.lifecycle_state == mod.LIFECYCLE_ENTRY_UNCONFIRMED
    assert scanner.last_order_block == "ENTRY_UNCONFIRMED"


def test_recovery_never_creates_an_exit(live_runner, monkeypatch):
    mod = live_runner
    scanner = mod.Sma9LiveScanner(feed=None)
    pos = _full_position(mod, trade_id="S9L-RECOVER-CE")
    monkeypatch.setattr(mod, "load_open_positions", lambda: {"CE": pos})
    calls = []
    monkeypatch.setattr(scanner, "_place_order", lambda *a, **k: calls.append((a, k)))

    scanner.recover_open_positions()

    assert calls == []
    assert scanner.states["CE"].position.trade_id == pos.trade_id
    assert mod.order_status_for(pos.trade_id, "SELL") is None


def test_only_stop_loss_and_trail_can_request_exit(live_runner, monkeypatch):
    mod = live_runner
    scanner = mod.Sma9LiveScanner(feed=None)
    pos = _full_position(mod, trade_id="S9L-EXIT-GUARD")
    scanner.states["CE"].restore(pos)
    calls = []
    monkeypatch.setattr(scanner, "_place_order", lambda *a, **k: calls.append((a, k)))

    assert scanner._request_exit(
        scanner.states["CE"], pos, 100.0, "SAME_CANDLE_EXIT") is None
    assert calls == []
    assert pos.lifecycle_state == mod.LIFECYCLE_ACTIVE
    assert mod.order_status_for(pos.trade_id, "SELL") is None

    with pytest.raises(ValueError):
        scanner.states["CE"].close(mod.now_ist(), 100.0, "SAME_CANDLE_EXIT")

    assert scanner._request_exit(
        scanner.states["CE"], pos, 100.0, "TRAIL_STOP_EXIT") is None  # no order result
    assert len(calls) == 1
    assert calls[0][0][3] == "TRAIL_STOP_EXIT"


def test_simple_five_percent_trailing_stop(live_runner):
    mod = live_runner
    pos = _full_position(
        mod, trade_id="S9L-TRAIL", entry_price=100.0, hwm=100.0)
    state = mod.OptionStateMachine("CE")
    state.restore(pos)

    assert state.update_trail(110.0) is None
    assert pos.hwm == 110.0
    assert pos.stop == 104.5
    assert pos.be_locked is False

    assert state.update_trail(105.0) is None
    assert state.update_trail(104.5) == 104.5


def test_trailing_stop_has_no_activation_or_breakeven_lock(live_runner):
    mod = live_runner
    pos = _full_position(
        mod, trade_id="S9L-TRAIL-SIMPLE", entry_price=100.0, hwm=100.0)
    state = mod.OptionStateMachine("CE")
    state.restore(pos)

    assert state.update_trail(103.0) is None
    assert pos.stop == 97.85  # HWM * 0.95, below entry
    assert pos.be_locked is False
    assert state.update_trail(98.0) is None  # no profitable stop yet
    assert state.check_stop_loss(95.0) == 95.0  # fixed 5% SL still active


def test_trailing_stop_only_ratchets_up(live_runner):
    mod = live_runner
    pos = _full_position(
        mod, trade_id="S9L-TRAIL-RATCHET", entry_price=100.0, hwm=100.0)
    state = mod.OptionStateMachine("CE")
    state.restore(pos)

    assert state.update_trail(120.0) is None
    first_stop = pos.stop
    assert first_stop == 114.0
    assert state.update_trail(115.0) is None
    assert pos.stop == first_stop
    assert pos.hwm == 120.0


def test_missing_lot_size_refuses_order(live_runner):
    mod = live_runner
    scanner = mod.Sma9LiveScanner(feed=None)
    pos = _position(trade_id="S9L-NOLOT")

    assert scanner._place_order(pos, "BUY", 100.0, "SMA9_ENTRY") is None
    assert scanner.last_order_block == "LOT_SIZE_UNAVAILABLE"
    assert mod.order_status_for(pos.trade_id, "BUY") is None


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
    assert calls[0]["order_type"] == "MARKET"
    assert calls[0]["price"] == 0
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


# --- real-trade lifecycle reconciliation ---------------------------------
class FakeStatusExecutor:
    """Read-only fake broker: exposes order_status but no place method."""

    name = "mstock"

    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.polled = []

    def order_status(self, record):
        self.polled.append(record.client_order_id)
        return self.statuses.pop(0) if self.statuses else execution.STATUS_ACCEPTED


def _reconcile_position(mod, trade_id, side_status, lifecycle, **overrides):
    """Persist an ACCEPTED real order plus its matching open position."""
    ts = mod.now_ist()
    base = dict(
        option_type="CE", trade_id=trade_id, strike=20000.0,
        expiry="2026-09-24", token=12345, tradingsymbol="NIFTY26SEP20000CE",
        entry_timestamp=ts, entry_candle_start=ts, entry_candle_end=ts,
        entry_price=100.0, sma9=99.0, prev_close=99.0, current_open=100.0,
        condition_a=True, condition_b=True, ltp_at_entry=100.0,
        hwm=100.0, stop=None, be_locked=False, lifecycle_state=lifecycle,
    )
    base.update(overrides)
    pos = mod.Position(**base)
    mod.save_open_position(pos)
    scanner = mod.Sma9LiveScanner(feed=None)
    scanner.states["CE"].restore(pos)
    return scanner, pos


def _accepted_order(execution, trade_id, side, **overrides):
    base = dict(
        client_order_id=execution.make_client_order_id(trade_id, side),
        trade_id=trade_id, option_type="CE", side=side,
        symbol="NFO:NIFTY26SEP20000CE", token=12345, quantity=65,
        intended_price=105.0, limit_price=106.0, collar_pct=1.0,
        reason="SMA9_ENTRY" if side == "BUY" else "TRAIL_STOP_EXIT",
        dry_run=False, status=execution.STATUS_ACCEPTED,
        broker_order_id=f"BROKER-{side}",
    )
    base.update(overrides)
    return execution.OrderRecord(**base)


def test_buy_fill_confirmation_activates_position(
        live_runner, execution, monkeypatch):
    mod = live_runner
    trade_id = "S9L-RECON-BUY"
    scanner, _ = _reconcile_position(
        mod, trade_id, "BUY", mod.LIFECYCLE_PENDING)
    mod.save_order_record(_accepted_order(execution, trade_id, "BUY"))
    fake = FakeStatusExecutor([execution.STATUS_ACCEPTED, execution.STATUS_FILLED])
    monkeypatch.setattr(mod, "EXECUTOR", fake)

    # First pass leaves it pending; the next consumes the FILLED status.
    assert scanner.reconcile_orders()["pending"] == 1
    assert scanner.reconcile_orders()["filled"] == 1
    assert fake.polled == [execution.make_client_order_id(trade_id, "BUY")] * 2
    row = mod.order_status_for(trade_id, "BUY")
    assert row["status"] == execution.STATUS_FILLED
    assert row["broker_status"] == execution.STATUS_FILLED
    assert scanner.states["CE"].position.lifecycle_state == mod.LIFECYCLE_ACTIVE
    assert mod.load_open_positions()["CE"].lifecycle_state == mod.LIFECYCLE_ACTIVE
    assert not mod.pending_order_rows()


def test_buy_rejection_removes_phantom_position(
        live_runner, execution, monkeypatch):
    mod = live_runner
    trade_id = "S9L-RECON-PHANTOM"
    scanner, _ = _reconcile_position(
        mod, trade_id, "BUY", mod.LIFECYCLE_PENDING)
    mod.save_order_record(_accepted_order(execution, trade_id, "BUY"))
    monkeypatch.setattr(mod, "EXECUTOR",
                        FakeStatusExecutor([execution.STATUS_REJECTED]))

    assert scanner.reconcile_orders()["rejected"] == 1
    assert mod.load_open_positions().get("CE") is None
    assert scanner.states["CE"].position is None
    assert mod.order_status_for(trade_id, "BUY")["status"] == (
        execution.STATUS_REJECTED)


def test_sell_fill_confirmation_closes_trade_once(
        live_runner, execution, monkeypatch):
    mod = live_runner
    trade_id = "S9L-RECON-EXIT"
    scanner, _ = _reconcile_position(
        mod, trade_id, "SELL", mod.LIFECYCLE_EXIT_PENDING)
    mod.save_order_record(_accepted_order(execution, trade_id, "SELL"))
    monkeypatch.setattr(mod, "EXECUTOR",
                        FakeStatusExecutor([execution.STATUS_FILLED]))

    assert scanner.reconcile_orders()["filled"] == 1
    assert mod.load_open_positions().get("CE") is None
    assert scanner.states["CE"].position is None
    trades = mod.today_stats(mod.now_ist().date().isoformat())
    assert trades["trades"] == 1
    assert trades["pnl_points"] == 5.0  # 105 exit - 100 entry
    # A second pass must not close or duplicate the trade.
    assert scanner.reconcile_orders()["checked"] == 0
    assert mod.today_stats(mod.now_ist().date().isoformat())["trades"] == 1


def test_sell_cancellation_keeps_position_and_does_not_retry(
        live_runner, execution, monkeypatch):
    mod = live_runner
    trade_id = "S9L-RECON-CANCEL"
    scanner, _ = _reconcile_position(
        mod, trade_id, "SELL", mod.LIFECYCLE_EXIT_PENDING)
    mod.save_order_record(_accepted_order(execution, trade_id, "SELL"))
    monkeypatch.setattr(mod, "EXECUTOR",
                        FakeStatusExecutor([execution.STATUS_CANCELLED]))

    assert scanner.reconcile_orders()["rejected"] == 1
    assert mod.load_open_positions()["CE"].lifecycle_state == (
        mod.LIFECYCLE_EXIT_FAILED)
    assert scanner.states["CE"].position.lifecycle_state == (
        mod.LIFECYCLE_EXIT_FAILED)
    assert mod.today_stats(mod.now_ist().date().isoformat())["trades"] == 0
    # No blind resubmission: the ledger still has exactly one SELL and it is
    # now terminal (CANCELLED), so it is no longer polled.
    with mod.db_conn() as conn:
        sells = conn.execute(
            "SELECT status FROM sma9_live_orders WHERE trade_id = ? "
            "AND side = 'SELL'", (trade_id,)).fetchall()
    assert [r["status"] for r in sells] == [execution.STATUS_CANCELLED]
    assert not mod.pending_order_rows()
    assert not hasattr(mod.EXECUTOR, "place")


def test_slippage_signs_and_missing_fill(execution):
    # BUY: paying more than the signal is adverse (positive).
    assert execution.measure_slippage("BUY", 100, 101.5, 65) == (1.5, 1.5, 97.5)
    # SELL: receiving less than the signal is also adverse.
    pts, pct, value = execution.measure_slippage("SELL", 105, 103, 65)
    assert pts == 2.0
    assert pct == pytest.approx(1.9048, abs=1e-4)
    assert value == 130.0
    # A favourable SELL fill is negative: it improves on the signal.
    assert execution.measure_slippage("SELL", 105, 106, 65)[0] == -1.0
    for missing in (None, "", 0, -1, "not-a-price"):
        assert execution.measure_slippage("BUY", 100, missing, 65) == (
            None, None, None)


def test_estimated_cost_defaults_and_env_overrides(execution):
    assert execution.estimated_order_cost("BUY", 65, {}) == 20.0
    env = {
        "SMA9_LIVE_COST_BROKERAGE_PER_ORDER": "20",
        "SMA9_LIVE_COST_OTHER_PER_ORDER": "10",
        "SMA9_LIVE_COST_SELL_EXTRA_PER_ORDER": "5",
        "SMA9_LIVE_COST_PER_UNIT": "0.5",
    }
    assert execution.estimated_order_cost("BUY", 65, env) == 62.5
    assert execution.estimated_order_cost("SELL", 65, env) == 67.5
    # Bad/negative values cannot create a negative cost estimate.
    assert execution.estimated_order_cost(
        "BUY", 65, {"SMA9_LIVE_COST_OTHER_PER_ORDER": "-5"}) == 0.0


def test_mstock_executor_order_details_captures_fill(execution):
    responses = [
        {
            "status": "complete", "raw_status": "COMPLETE",
            "status_message": "filled", "fill_price": "101.25",
        },
        {"status": "OPEN", "fill_price": "0"},
    ]
    ex = execution.MStockOrderExecutor(caller=lambda *a, **k: responses.pop(0))
    record = _order(execution, broker_order_id="MOCK-ORDER-1")
    details = ex.order_details(record)
    assert details.status == execution.STATUS_FILLED
    assert details.fill_price == 101.25
    assert details.raw_status == "COMPLETE"
    assert details.status_message == "filled"
    # The string wrapper still works and a zero price is not a fill.
    assert ex.order_status(record) == execution.STATUS_ACCEPTED


def test_reconcile_logs_fill_quality_once_per_leg(
        live_runner, execution, monkeypatch):
    mod = live_runner
    trade_id = "S9L-QUALITY"
    scanner, _ = _reconcile_position(
        mod, trade_id, "BUY", mod.LIFECYCLE_PENDING)
    record = _accepted_order(execution, trade_id, "BUY",
                             intended_price=100.0, quantity=65)
    mod.save_order_record(record)

    class DetailsExecutor:
        name = "mstock"

        def __init__(self, details):
            self.details = details
            self.calls = 0

        def order_details(self, received):
            self.calls += 1
            return self.details

    fake = DetailsExecutor(execution.OrderDetails(
        status=execution.STATUS_FILLED, fill_price=101.0,
        raw_status="COMPLETE"))
    monkeypatch.setattr(mod, "EXECUTOR", fake)

    assert scanner.reconcile_orders()["filled"] == 1
    with mod.db_conn() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM sma9_live_execution_quality")]
    assert len(rows) == 1
    row = rows[0]
    assert row["client_order_id"] == record.client_order_id
    assert row["signal_price"] == 100.0
    assert row["fill_price"] == 101.0
    assert row["slippage_points"] == 1.0
    assert row["slippage_value"] == 65.0
    assert row["cost_estimate"] == 20.0
    assert row["broker_status"] == execution.STATUS_FILLED
    assert row["raw_status"] == "COMPLETE"

    # A later status poll without a fill must not duplicate the row or erase
    # the already-known fill price.
    fake.details = execution.OrderDetails(status=execution.STATUS_FILLED)
    mod.record_execution_quality(record, fake.details)
    with mod.db_conn() as conn:
        again = [dict(r) for r in conn.execute(
            "SELECT * FROM sma9_live_execution_quality")]
    assert len(again) == 1
    assert again[0]["fill_price"] == 101.0
    assert again[0]["slippage_points"] == 1.0


def test_missing_broker_fill_never_guesses_slippage(live_runner, execution):
    mod = live_runner
    record = _accepted_order(execution, "S9L-QUALITY-NOFILL", "BUY",
                             intended_price=100.0)
    mod.save_order_record(record)
    mod.record_execution_quality(
        record, execution.OrderDetails(status=execution.STATUS_ACCEPTED))
    with mod.db_conn() as conn:
        row = dict(conn.execute(
            "SELECT * FROM sma9_live_execution_quality").fetchone())
    assert row["fill_price"] is None
    assert row["slippage_points"] is None
    assert row["slippage_pct"] is None
    assert row["slippage_value"] is None
    assert row["cost_estimate"] == 20.0


def test_reconciliation_audits_events_and_ignores_dry_run(
        live_runner, execution, monkeypatch):
    mod = live_runner
    trade_id = "S9L-RECON-EVENT"
    scanner, _ = _reconcile_position(
        mod, trade_id, "BUY", mod.LIFECYCLE_PENDING)
    mod.save_order_record(_accepted_order(execution, trade_id, "BUY"))
    dry = _order(execution, client_order_id="S9L-BUY-DRY",
                 trade_id="S9L-DRY", broker_order_id="DRY-1")
    mod.save_order_record(dry)
    scanner._apply_submit_result(_accepted_order(execution, trade_id, "BUY"))
    fake = FakeStatusExecutor([execution.STATUS_FILLED])
    monkeypatch.setattr(mod, "EXECUTOR", fake)

    scanner.reconcile_orders()
    assert fake.polled == [execution.make_client_order_id(trade_id, "BUY")]
    with mod.db_conn() as conn:
        events = [dict(r) for r in conn.execute(
            "SELECT event FROM sma9_live_lifecycle_events ORDER BY id")]
    assert [e["event"] for e in events] == ["ORDER_SUBMITTED", "BUY_FILL_CONFIRMED"]


# --- Stage 1 tag lookup and Stage 2 bounded retries -----------------------
class FakeTagExecutor:
    """Read-only fake broker for the order-book tag lookup."""

    name = "mstock"

    def __init__(self, lookup):
        self.lookup = lookup
        self.tags = []

    def order_by_tag(self, record):
        self.tags.append(record.client_order_id)
        return self.lookup


class FakePlaceExecutor:
    """Fake broker that accepts one re-placement and records its attempt tag."""

    name = "mstock"

    def __init__(self):
        self.placed = []

    def place(self, record):
        self.placed.append(record)
        record.dry_run = False
        record.status = "ACCEPTED"
        record.place_status = "SUBMITTED"
        record.broker_order_id = f"RETRY-BROKER-{len(self.placed)}"
        return record


class FakeDetailsExecutor:
    """Fake broker that returns one fixed read-only status/fill snapshot."""

    name = "mstock"

    def __init__(self, details):
        self.details = details

    def order_details(self, record):
        return self.details


class ChangingLotFeed(FakeMstockFeed):
    """Feed that returns a different instrument-master lot on each lookup."""

    def __init__(self, lot_size):
        self.lot_size = lot_size
        self.calls = 0

    def find_contract(self, strike, expiry, option_type):
        self.calls += 1
        contract = super().find_contract(strike, expiry, option_type)
        contract["lot_size"] = self.lot_size
        return contract


def _arm_real_orders(monkeypatch):
    monkeypatch.setenv("SMA9_LIVE_ORDERS_ENABLED", "true")
    monkeypatch.setenv("SMA9_LIVE_ARM_REAL_ORDERS", "ARMED")


def _retry_settings(mod, execution, monkeypatch, *, attempts=1,
                    ambiguous=False):
    monkeypatch.setattr(mod, "RETRY_ENABLED", True)
    monkeypatch.setattr(mod, "RETRY_MAX_ATTEMPTS", attempts)
    monkeypatch.setattr(mod, "RETRY_AMBIGUOUS", ambiguous)
    monkeypatch.setattr(mod, "RETRY_BASE_DELAY_SEC", 0)
    monkeypatch.setattr(mod, "RETRY_MAX_AGE_SEC", 300)
    monkeypatch.setattr(mod, "RETRY_SIDES",
                        frozenset({execution.BUY, execution.SELL}))
    monkeypatch.setattr(mod, "TAG_LOOKUP_MAX_ATTEMPTS", 1)


def _order_row(mod, client_order_id):
    with mod.db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM sma9_live_orders WHERE client_order_id = ?",
            (client_order_id,)).fetchone()
    assert row is not None, client_order_id
    return dict(row)


def _event_names(mod):
    with mod.db_conn() as conn:
        return [r["event"] for r in conn.execute(
            "SELECT event FROM sma9_live_lifecycle_events ORDER BY id")]


def _stage_ambiguous_submit(mod, execution, trade_id, side, lifecycle):
    """Persist a rejected submit with no broker id (post-POST may be pending)."""
    record = _accepted_order(
        execution, trade_id, side, status=execution.STATUS_REJECTED,
        broker_order_id=None, place_status=execution.PLACE_AMBIGUOUS,
        created_at=mod.now_ist().isoformat())
    mod.save_order_record(record)
    scanner, _ = _reconcile_position(mod, trade_id, side, lifecycle)
    scanner.feed = FakeMstockFeed()
    return scanner, record.client_order_id


def _stage_confirmed_failure(mod, execution, monkeypatch, trade_id, side,
                             lifecycle, status, details=None):
    """Persist an accepted real order and drive it to a broker-confirmed loss."""
    scanner, _ = _reconcile_position(mod, trade_id, side, lifecycle)
    scanner.feed = FakeMstockFeed()
    record = _accepted_order(execution, trade_id, side)
    mod.save_order_record(record)
    fake = (FakeDetailsExecutor(details) if details is not None
            else FakeStatusExecutor([status]))
    monkeypatch.setattr(mod, "EXECUTOR", fake)
    assert scanner.reconcile_orders()["rejected"] == 1
    return scanner, record.client_order_id


def test_tag_lookup_resolves_ambiguous_submit_without_placing(
        live_runner, execution, monkeypatch):
    mod = live_runner
    trade_id = "S9L-TAG-RESOLVED"
    scanner, client_id = _stage_ambiguous_submit(
        mod, execution, trade_id, execution.BUY, mod.LIFECYCLE_ENTRY_UNCONFIRMED)
    fake = FakeTagExecutor(execution.OrderLookup(
        found=True, broker_order_id="MOCK-TAG-1", status=execution.STATUS_FILLED,
        fill_price=102.0, filled_quantity=65))
    monkeypatch.setattr(mod, "EXECUTOR", fake)

    summary = scanner.resolve_unknown_submits()

    assert summary["resolved"] == 1
    assert fake.tags == [client_id]
    row = _order_row(mod, client_id)
    assert row["broker_order_id"] == "MOCK-TAG-1"
    assert row["status"] == execution.STATUS_FILLED
    assert row["place_status"] == execution.PLACE_RESOLVED
    assert row["filled_quantity"] == 65
    assert scanner.states["CE"].position.lifecycle_state == mod.LIFECYCLE_ACTIVE
    events = _event_names(mod)
    assert "TAG_LOOKUP_RESOLVED" in events
    assert "BUY_FILL_CONFIRMED" in events


def test_tag_lookup_multiple_orders_requires_manual(
        live_runner, execution, monkeypatch):
    mod = live_runner
    trade_id = "S9L-TAG-MULTIPLE"
    scanner, client_id = _stage_ambiguous_submit(
        mod, execution, trade_id, execution.BUY, mod.LIFECYCLE_ENTRY_UNCONFIRMED)
    fake = FakeTagExecutor(execution.OrderLookup(
        found=True, multiple=True, error_code="MULTIPLE_ORDERS"))
    monkeypatch.setattr(mod, "EXECUTOR", fake)

    summary = scanner.resolve_unknown_submits()

    assert summary["manual"] == 1
    row = _order_row(mod, client_id)
    assert row["place_status"] == execution.PLACE_MANUAL_REQUIRED
    assert row["last_error_code"] == "MULTIPLE_ORDERS"
    assert "TAG_LOOKUP_MULTIPLE" in _event_names(mod)


def test_tag_lookup_unresolved_is_manual_by_default(
        live_runner, execution, monkeypatch):
    mod = live_runner
    trade_id = "S9L-TAG-UNRESOLVED"
    scanner, client_id = _stage_ambiguous_submit(
        mod, execution, trade_id, execution.BUY, mod.LIFECYCLE_ENTRY_UNCONFIRMED)
    monkeypatch.setattr(mod, "TAG_LOOKUP_MAX_ATTEMPTS", 1)
    fake = FakeTagExecutor(execution.OrderLookup())
    monkeypatch.setattr(mod, "EXECUTOR", fake)

    summary = scanner.resolve_unknown_submits()

    assert summary["manual"] == 1
    assert summary["retry_scheduled"] == 0
    row = _order_row(mod, client_id)
    assert row["place_status"] == execution.PLACE_MANUAL_REQUIRED
    assert row["last_error_code"] == "AMBIGUOUS_UNRESOLVED"
    assert mod.retry_due_rows() == []


def test_ambiguous_retry_requires_both_retry_and_ambiguous_flags(
        live_runner, execution, monkeypatch):
    mod = live_runner
    for index, (enabled, ambiguous) in enumerate(((False, True), (True, False))):
        trade_id = f"S9L-AMBIG-GATE-{index}"
        scanner, client_id = _stage_ambiguous_submit(
            mod, execution, trade_id, execution.BUY,
            mod.LIFECYCLE_ENTRY_UNCONFIRMED)
        monkeypatch.setattr(mod, "RETRY_ENABLED", enabled)
        monkeypatch.setattr(mod, "RETRY_MAX_ATTEMPTS", 1 if enabled else 0)
        monkeypatch.setattr(mod, "RETRY_AMBIGUOUS", ambiguous)
        monkeypatch.setattr(mod, "TAG_LOOKUP_MAX_ATTEMPTS", 1)
        monkeypatch.setattr(mod, "EXECUTOR", FakeTagExecutor(
            execution.OrderLookup()))

        summary = scanner.resolve_unknown_submits()

        assert summary["retry_scheduled"] == 0
        assert summary["manual"] == 1
        assert _order_row(mod, client_id)[
            "place_status"] == execution.PLACE_MANUAL_REQUIRED
    assert mod.retry_due_rows() == []


def test_ambiguous_opt_in_retry_uses_new_tag(
        live_runner, execution, monkeypatch):
    mod = live_runner
    trade_id = "S9L-AMBIG-RETRY"
    _retry_settings(mod, execution, monkeypatch, ambiguous=True)
    scanner, client_id = _stage_ambiguous_submit(
        mod, execution, trade_id, execution.BUY, mod.LIFECYCLE_ENTRY_UNCONFIRMED)
    monkeypatch.setattr(mod, "EXECUTOR", FakeTagExecutor(execution.OrderLookup()))

    lookup_summary = scanner.resolve_unknown_submits()
    assert lookup_summary["retry_scheduled"] == 1
    assert _order_row(mod, client_id)[
        "place_status"] == execution.PLACE_RETRY_DUE

    _arm_real_orders(monkeypatch)
    placer = FakePlaceExecutor()
    monkeypatch.setattr(mod, "EXECUTOR", placer)
    assert scanner.process_retries()["submitted"] == 1
    assert len(placer.placed) == 1
    assert placer.placed[0].client_order_id == execution.make_client_order_id(
        trade_id, execution.BUY, "r1")


def test_confirmed_buy_failure_retries_with_new_tag_and_no_cap_charge(
        live_runner, execution, monkeypatch):
    mod = live_runner
    trade_id = "S9L-RETRY-BUY"
    _retry_settings(mod, execution, monkeypatch)
    scanner, client_id = _stage_confirmed_failure(
        mod, execution, monkeypatch, trade_id, execution.BUY,
        mod.LIFECYCLE_PENDING, execution.STATUS_REJECTED)

    assert _order_row(mod, client_id)[
        "place_status"] == execution.PLACE_RETRY_DUE
    assert scanner.states["CE"].position.lifecycle_state == (
        mod.LIFECYCLE_ENTRY_RETRY_PENDING)

    _arm_real_orders(monkeypatch)
    placer = FakePlaceExecutor()
    monkeypatch.setattr(mod, "EXECUTOR", placer)
    today = mod.now_ist().date().isoformat()
    before = mod.orders_today(today)

    assert scanner.process_retries()["submitted"] == 1
    assert len(placer.placed) == 1
    attempt = placer.placed[0]
    retry_id = execution.make_client_order_id(trade_id, execution.BUY, "r1")
    assert attempt.client_order_id == retry_id
    assert attempt.retry_of == client_id
    assert attempt.attempt_no == 1
    assert attempt.retry_count == 1
    assert attempt.counts_toward_cap is False
    assert attempt.quantity == 65
    assert _order_row(mod, retry_id)["counts_toward_cap"] == 0
    assert mod.orders_today(today) == before
    assert "RETRY_SUBMITTED" in _event_names(mod)


def test_confirmed_sell_failure_retries_without_closing_position(
        live_runner, execution, monkeypatch):
    mod = live_runner
    trade_id = "S9L-RETRY-SELL"
    _retry_settings(mod, execution, monkeypatch)
    scanner, client_id = _stage_confirmed_failure(
        mod, execution, monkeypatch, trade_id, execution.SELL,
        mod.LIFECYCLE_EXIT_PENDING, execution.STATUS_CANCELLED)

    assert _order_row(mod, client_id)[
        "place_status"] == execution.PLACE_RETRY_DUE
    assert scanner.states["CE"].position.lifecycle_state == (
        mod.LIFECYCLE_EXIT_RETRY_PENDING)

    _arm_real_orders(monkeypatch)
    placer = FakePlaceExecutor()
    monkeypatch.setattr(mod, "EXECUTOR", placer)
    assert scanner.process_retries()["submitted"] == 1
    assert placer.placed[0].client_order_id == execution.make_client_order_id(
        trade_id, execution.SELL, "r1")
    assert mod.load_open_positions()["CE"].lifecycle_state == (
        mod.LIFECYCLE_EXIT_PENDING)
    assert mod.today_stats(mod.now_ist().date().isoformat())["trades"] == 0


@pytest.mark.parametrize(
    "side,status,start_state,expected_state",
    [
        ("BUY", "REJECTED", "PENDING_FILL", "ENTRY_PARTIAL"),
        ("SELL", "CANCELLED", "EXIT_PENDING", "EXIT_PARTIAL"),
    ],
)
def test_partial_fill_never_retries_or_drops_position(
        live_runner, execution, monkeypatch, side, status, start_state,
        expected_state):
    mod = live_runner
    trade_id = f"S9L-PARTIAL-{side}"
    _retry_settings(mod, execution, monkeypatch)
    details = execution.OrderDetails(status=status, filled_quantity=5)
    scanner, client_id = _stage_confirmed_failure(
        mod, execution, monkeypatch, trade_id, side, start_state, status,
        details=details)

    row = _order_row(mod, client_id)
    assert row["place_status"] == execution.PLACE_MANUAL_REQUIRED
    assert row["last_error_code"] == "PARTIAL_FILL"
    assert scanner.states["CE"].position.lifecycle_state == expected_state
    assert mod.load_open_positions()["CE"].lifecycle_state == expected_state
    assert mod.retry_due_rows() == []
    events = _event_names(mod)
    assert "PARTIAL_FILL_MANUAL" in events
    assert "PHANTOM_POSITION_REMOVED" not in events
    assert "RETRY_SCHEDULED" not in events


def test_retry_rechecks_kill_switch_without_broker_call(
        live_runner, execution, monkeypatch, tmp_path):
    mod = live_runner
    trade_id = "S9L-RETRY-KILL"
    _retry_settings(mod, execution, monkeypatch)
    scanner, client_id = _stage_confirmed_failure(
        mod, execution, monkeypatch, trade_id, execution.BUY,
        mod.LIFECYCLE_PENDING, execution.STATUS_REJECTED)

    kill_file = tmp_path / "retry.KILL"
    kill_file.write_text("stop", encoding="utf-8")
    monkeypatch.setenv("SMA9_LIVE_KILL_FILE", str(kill_file))
    monkeypatch.setattr(mod, "LIMITS", execution.RiskLimits(
        max_orders_per_day=mod.LIMITS.max_orders_per_day,
        lot_size=mod.LIMITS.lot_size,
        collar_pct=mod.LIMITS.collar_pct,
        kill_file=str(kill_file)))
    _arm_real_orders(monkeypatch)
    calls = []

    def caller(*args, **kwargs):
        calls.append(kwargs)
        return {"order_id": "MUST-NOT-HAPPEN"}

    monkeypatch.setattr(mod, "EXECUTOR", execution.MStockOrderExecutor(
        caller=caller, environ=os.environ))

    assert scanner.process_retries()["exhausted"] == 1

    assert calls == []
    retry_id = execution.make_client_order_id(trade_id, execution.BUY, "r1")
    retry_row = _order_row(mod, retry_id)
    assert retry_row["status"] == execution.STATUS_REJECTED
    assert retry_row["place_status"] == execution.PLACE_PRE_POST_REFUSED
    assert _order_row(mod, client_id)[
        "place_status"] == execution.PLACE_RETRY_EXHAUSTED


def test_retry_ignores_collar_when_disabled(
        live_runner, execution, monkeypatch):
    mod = live_runner
    trade_id = "S9L-RETRY-COLLAR"
    _retry_settings(mod, execution, monkeypatch)
    monkeypatch.setattr(mod, "LIMITS", execution.RiskLimits(collar_pct=0.0))
    scanner, client_id = _stage_confirmed_failure(
        mod, execution, monkeypatch, trade_id, execution.BUY,
        mod.LIFECYCLE_PENDING, execution.STATUS_REJECTED)
    scanner._last_ltp["CE"] = 100.0  # original intended price is 105.0

    _arm_real_orders(monkeypatch)
    placer = FakePlaceExecutor()
    monkeypatch.setattr(mod, "EXECUTOR", placer)

    assert scanner.process_retries()["submitted"] == 1

    assert len(placer.placed) == 1
    retry_id = execution.make_client_order_id(trade_id, execution.BUY, "r1")
    assert mod.order_exists(retry_id)
    original = _order_row(mod, client_id)
    assert original["place_status"] == execution.PLACE_RETRY_ATTEMPTED
    assert original["last_error_code"] != "PRICE_COLLAR_BREACH"


def test_retry_rechecks_lot_size_from_instrument_master(
        live_runner, execution, monkeypatch):
    mod = live_runner
    trade_id = "S9L-RETRY-LOT"
    _retry_settings(mod, execution, monkeypatch)
    scanner, client_id = _stage_confirmed_failure(
        mod, execution, monkeypatch, trade_id, execution.BUY,
        mod.LIFECYCLE_PENDING, execution.STATUS_REJECTED)
    assert _order_row(mod, client_id)["quantity"] == 65
    feed = ChangingLotFeed(75)
    scanner.feed = feed

    _arm_real_orders(monkeypatch)
    placer = FakePlaceExecutor()
    monkeypatch.setattr(mod, "EXECUTOR", placer)

    assert scanner.process_retries()["submitted"] == 1

    assert feed.calls == 1
    retry_id = execution.make_client_order_id(trade_id, execution.BUY, "r1")
    assert placer.placed[0].quantity == 75
    assert _order_row(mod, retry_id)["quantity"] == 75


def test_init_db_migrates_pre_retry_schema(live_runner):
    """An already-deployed DB without retry columns must migrate on startup."""
    mod = live_runner
    with mod.db_conn() as conn:
        conn.execute("DROP INDEX IF EXISTS idx_sma9_live_orders_place")
        conn.execute("DROP TABLE sma9_live_orders")
        conn.execute(
            """CREATE TABLE sma9_live_orders (
                   client_order_id TEXT PRIMARY KEY,
                   scanner TEXT NOT NULL,
                   trade_id TEXT NOT NULL,
                   option_type TEXT NOT NULL CHECK(option_type IN ('CE','PE')),
                   side TEXT NOT NULL CHECK(side IN ('BUY','SELL')),
                   symbol TEXT NOT NULL,
                   token INTEGER,
                   quantity INTEGER NOT NULL,
                   intended_price REAL NOT NULL,
                   limit_price REAL NOT NULL,
                   collar_pct REAL NOT NULL,
                   reason TEXT NOT NULL,
                   dry_run INTEGER NOT NULL,
                   status TEXT NOT NULL,
                   broker_order_id TEXT,
                   created_at TEXT NOT NULL,
                   order_date TEXT NOT NULL,
                   broker_status TEXT,
                   status_checked_at TEXT,
                   reconcile_attempts INTEGER NOT NULL DEFAULT 0,
                   last_error TEXT)""")
        conn.execute(
            """INSERT INTO sma9_live_orders
                   (client_order_id, scanner, trade_id, option_type, side,
                    symbol, token, quantity, intended_price, limit_price,
                    collar_pct, reason, dry_run, status, created_at, order_date)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("S9L-OLD", "sma9_live", "S9L-OLDTRADE", "CE", "BUY",
             "NFO:NIFTY", 12345, 65, 100.0, 101.0, 1.0, "SMA9_ENTRY",
             0, "FILLED", "2026-11-24T10:00:00+05:30", "2026-11-24"))

    # Must not raise: the retry index is created only after columns exist.
    mod.init_db()

    with mod.db_conn() as conn:
        cols = [r[1] for r in conn.execute(
            "PRAGMA table_info(sma9_live_orders)")]
        indexes = [r[1] for r in conn.execute(
            "PRAGMA index_list(sma9_live_orders)")]
        row = dict(conn.execute(
            "SELECT * FROM sma9_live_orders WHERE client_order_id = ?",
            ("S9L-OLD",)).fetchone())
    for col in ("place_status", "retry_of", "retry_count", "attempt_no",
                "counts_toward_cap", "tag_lookup_attempts", "filled_quantity",
                "last_error_code", "next_retry_at", "updated_at"):
        assert col in cols
    assert "idx_sma9_live_orders_place" in indexes
    assert row["place_status"] == "SUBMITTED"
    assert row["retry_of"] == "S9L-OLD"
    assert row["retry_count"] == 0
    assert row["counts_toward_cap"] == 1
