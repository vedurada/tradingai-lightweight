"""Isolated tests for the P0.14 scalp alert event pipeline.

Uses only temporary storage and mock providers. No network, no production DB,
no Telegram messages. Run with:

    /usr/bin/python3 -m pytest tests/test_scalp_alert_events.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.research.scalp_alert_events import (  # noqa: E402
    EVENT_DELIVERY_FAILED,
    EVENT_DELIVERY_SUCCEEDED,
    EVENT_PAPER_TRADE_CREATED,
    EVENT_SIGNAL_CONFIRMED,
    DELIVERY_DRY_RUN,
    DELIVERY_FAILED,
    DELIVERY_NOT_CONFIGURED,
    DELIVERY_OK,
    AlertPipeline,
    InMemoryEventStore,
    MockProvider,
    SQLiteEventStore,
    TelegramProvider,
    event_id_for,
)


def _types(store):
    return sorted(r["event_type"] for r in store.all())


def _signal(sid="SIG-1"):
    return {
        "signal_id": sid,
        "instrument": "NIFTY",
        "direction": "BULL",
        "signal_time": "2026-10-28T10:15:00+05:30",
    }


def test_one_confirmed_signal_creates_one_logical_event():
    store = InMemoryEventStore()
    p = AlertPipeline(store, MockProvider())
    first = p.signal_confirmed("SIG-1", instrument="NIFTY")
    second = p.signal_confirmed("SIG-1", instrument="NIFTY")
    assert first is not None
    assert second is None
    rows = [r for r in store.all() if r["event_type"] == EVENT_SIGNAL_CONFIRMED]
    assert len(rows) == 1
    assert rows[0]["signal_id"] == "SIG-1"


def test_repeated_processing_no_duplicate_logical_events():
    store = InMemoryEventStore()
    p = AlertPipeline(store, MockProvider())
    calls = {"n": 0}

    def creator(sig):
        calls["n"] += 1
        return "PT-ABC"

    r1 = p.process_signal(_signal(), creator)
    r2 = p.process_signal(_signal(), creator)
    assert r1["note"] == "created"
    assert r2["note"] == "already processed"
    assert calls["n"] == 1
    assert _types(store).count(EVENT_SIGNAL_CONFIRMED) == 1
    assert _types(store).count(EVENT_PAPER_TRADE_CREATED) == 1


def test_trade_creation_failure_no_trade_created_event():
    store = InMemoryEventStore()
    p = AlertPipeline(store, MockProvider())
    r = p.process_signal(_signal(), lambda sig: None)
    assert r["trade_event"] is None
    assert EVENT_PAPER_TRADE_CREATED not in _types(store)
    assert EVENT_SIGNAL_CONFIRMED in _types(store)

    def boom(sig):
        raise RuntimeError("engine down")

    store2 = InMemoryEventStore()
    p2 = AlertPipeline(store2, MockProvider())
    r2 = p2.process_signal(_signal("SIG-2"), boom)
    assert r2["trade_event"] is None
    assert EVENT_PAPER_TRADE_CREATED not in _types(store2)
    assert "raised" in r2["note"]


def test_provider_exception_logged_and_represented_as_failure():
    store = InMemoryEventStore()
    p = AlertPipeline(store, MockProvider(exc=TimeoutError("timed out")))
    ev = p.signal_confirmed("SIG-1", instrument="NIFTY")
    result = p.deliver(ev)
    assert result.status == DELIVERY_FAILED
    assert not result.ok
    assert EVENT_DELIVERY_SUCCEEDED not in _types(store)
    failed = [r for r in store.all() if r["event_type"] == EVENT_DELIVERY_FAILED]
    assert len(failed) == 1
    assert failed[0]["signal_id"] == "SIG-1"
    assert "TimeoutError" in failed[0]["payload"]["detail"]


def test_missing_configuration_produces_not_configured():
    store = InMemoryEventStore()
    p = AlertPipeline(store, MockProvider(configured=False))
    ev = p.signal_confirmed("SIG-1", instrument="NIFTY")
    result = p.deliver(ev)
    assert result.status == DELIVERY_NOT_CONFIGURED
    assert not result.ok
    assert EVENT_DELIVERY_SUCCEEDED not in _types(store)


def test_telegram_provider_real_config_is_dry_run(tmp_path):
    fake = tmp_path / "tg_env"
    fake.write_text("dummy-token-value\n")
    prov = TelegramProvider(env_path=str(fake))
    assert prov.configured() is True
    ev = AlertPipeline(InMemoryEventStore(), prov).signal_confirmed("S", instrument="NIFTY")
    res = prov.send(ev)
    assert res.status == DELIVERY_DRY_RUN
    assert not res.ok

    absent = TelegramProvider(env_path=str(tmp_path / "missing"))
    assert absent.configured() is False
    assert absent.send(ev).status == DELIVERY_NOT_CONFIGURED


def test_recovery_does_not_create_duplicate_paper_trades():
    store = InMemoryEventStore()
    p = AlertPipeline(store, MockProvider())
    created = []

    def creator(sig):
        created.append(sig["signal_id"])
        return "PT-" + sig["signal_id"]

    # first pass creates; simulated restart reprocesses the same signal
    p.process_signal(_signal("SIG-9"), creator)
    p.process_signal(_signal("SIG-9"), creator)
    assert created == ["SIG-9"]
    assert len([r for r in store.all() if r["event_type"] == EVENT_PAPER_TRADE_CREATED]) == 1


def test_event_records_retain_signal_id_and_timestamps():
    store = InMemoryEventStore()
    p = AlertPipeline(store, MockProvider(), clock=lambda: "2026-10-28T04:45:00+00:00")
    r = p.process_signal(_signal("SIG-TS"), lambda s: "PT-TS")
    assert r["trade_id"] == "PT-TS"
    rows = store.all()
    assert rows, "expected events"
    for row in rows:
        assert row["signal_id"] == "SIG-TS"
        assert row["created_at"] == "2026-10-28T04:45:00+00:00"
    trade = [x for x in rows if x["event_type"] == EVENT_PAPER_TRADE_CREATED][0]
    assert trade["payload"]["trade_id"] == "PT-TS"


def test_sqlite_store_is_idempotent_and_redacts(tmp_path):
    db = str(tmp_path / "alerts.sqlite")
    store = SQLiteEventStore(db)
    p = AlertPipeline(store, MockProvider())
    p.signal_confirmed("SIG-R", instrument="NIFTY",
                       bot_token="SHOULD_NOT_LEAK", chat_id="12345")
    p.signal_confirmed("SIG-R", instrument="NIFTY")
    rows = [r for r in store.all() if r["event_type"] == EVENT_SIGNAL_CONFIRMED]
    assert len(rows) == 1
    assert rows[0]["payload"]["bot_token"] == "***REDACTED***"
    assert rows[0]["payload"]["chat_id"] == "***REDACTED***"


def test_delivery_success_recorded_once():
    store = InMemoryEventStore()
    prov = MockProvider()
    p = AlertPipeline(store, prov)
    ev = p.signal_confirmed("SIG-OK", instrument="NIFTY")
    r1 = p.deliver(ev)
    r2 = p.deliver(ev)
    assert r1.status == DELIVERY_OK and r2.status == DELIVERY_OK
    assert len([x for x in store.all() if x["event_type"] == EVENT_DELIVERY_SUCCEEDED]) == 1
    # provider is called twice (no exactly-once guarantee), but event is deduped
    assert len(prov.sent) == 2


def test_event_id_is_stable():
    assert event_id_for("SIG-1", EVENT_SIGNAL_CONFIRMED) == event_id_for("SIG-1", EVENT_SIGNAL_CONFIRMED)
    assert event_id_for("SIG-1", EVENT_PAPER_TRADE_CREATED) != event_id_for("SIG-1", EVENT_SIGNAL_CONFIRMED)
