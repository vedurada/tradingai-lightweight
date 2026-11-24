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
    assert limits.max_orders_per_day == 4  # scaffold default; VM sets 0
    assert limits.lot_size == 0  # resolve from mStock instrument master
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
        {"max_orders_per_day": -1},
        {"lot_size": -1},
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
    assert execution.price_collar_breached(101.0, 100.0, 1.0) is False
    assert execution.price_collar_breached(101.1, 100.0, 1.0) is True
    assert execution.price_collar_breached(102.0, None, 1.0) is False


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
    assert sell.limit_price < sell.intended_price
    assert mod.orders_today(today) == 2

    row = mod.order_status_for("S9L-TESTTRADE", "BUY")
    assert row["dry_run"] == 1
    assert row["status"] == execution.STATUS_DRY_RUN


def test_buy_collar_breach_blocks_market_order(live_runner):
    mod = live_runner
    scanner = mod.Sma9LiveScanner(feed=FakeMstockFeed())
    scanner._last_ltp["CE"] = 100.0
    pos = _position(trade_id="S9L-COLLAR")

    assert scanner._place_order(pos, "BUY", 102.0, "SMA9_ENTRY") is None
    assert scanner.last_order_block == "PRICE_COLLAR_BREACH"
    assert mod.order_status_for(pos.trade_id, "BUY") is None


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


@pytest.fixture
def live_api(live_runner):
    """Flask test client for the read-only live API on the private DB."""
    name = "sma9_live_api_under_test"
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "app" / "api" / "sma9_live_api.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    from flask import Flask
    app = Flask(__name__)
    app.register_blueprint(mod.bp)
    yield app.test_client()
    for key in list(sys.modules):
        if key == name:
            del sys.modules[key]


def test_execution_quality_api_aggregates_without_writing(
        live_api, live_runner, execution):
    mod = live_runner
    trade_id = "S9L-QUALITY-API"
    ts = mod.now_ist().isoformat()
    with mod.db_conn() as conn:
        conn.execute(
            """INSERT INTO sma9_live_trades
               (trade_id, trade_date, option_type, strike, expiry,
                signal_timestamp, entry_timestamp, entry_price,
                exit_timestamp, exit_price, pnl_points,
                status, created_at, updated_at, dataset)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (trade_id, mod.now_ist().date().isoformat(), "CE", 20000.0,
             "2026-09-24", ts, ts, 100.0, ts, 110.0, 10.0,
             "CLOSED", ts, ts, "LIVE"),
        )
    buy = _accepted_order(execution, trade_id, "BUY", intended_price=100.0)
    sell = _accepted_order(execution, trade_id, "SELL", intended_price=110.0)
    mod.record_execution_quality(
        buy, execution.OrderDetails(status=execution.STATUS_FILLED,
                                    fill_price=101.0))
    mod.record_execution_quality(
        sell, execution.OrderDetails(status=execution.STATUS_FILLED,
                                     fill_price=109.0))

    with mod.db_conn() as conn:
        before = conn.execute(
            "SELECT COUNT(*) FROM sma9_live_execution_quality").fetchone()[0]
    response = live_api.get("/api/sma9-live/execution-quality?limit=10")
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    summary = data["summary"]
    assert summary["legs"] == 2
    assert summary["filled_legs"] == 2
    assert summary["missing_fills"] == 0
    assert summary["slippage_points"] == 2.0
    assert summary["slippage_value"] == 130.0
    assert summary["cost_estimate"] == 40.0
    assert summary["paper_pnl_points"] == 10.0
    assert summary["fill_adjusted_pnl_points"] == 8.0
    assert summary["estimated_realized_rupees"] == 480.0
    assert len(data["legs"]) == 2
    assert data["trades"][0]["trade_id"] == trade_id
    with mod.db_conn() as conn:
        after = conn.execute(
            "SELECT COUNT(*) FROM sma9_live_execution_quality").fetchone()[0]
    assert after == before


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
