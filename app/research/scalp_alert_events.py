"""Provider-neutral, idempotent alert event pipeline for scalp signals.

Phase P0.14. This module is intentionally NOT wired into any live runtime yet.
It provides the smallest testable abstraction for the three logical events:

    * signal_confirmed
    * paper_trade_created
    * delivery_succeeded / delivery_failed

Deduplication is per logical event id derived deterministically from
(signal_id, event_type). Within a single EventStore this gives at-most-once
*logical event emission*. It does NOT guarantee exactly-once external
delivery: a provider call can succeed and then the process can die before
delivery_succeeded is persisted, or a retry can deliver twice. Do not claim
exactly-once delivery.

Production persistence of events requires a new table / schema migration,
which is out of scope for this phase and must be approved first. The default
store is in-memory; SQLiteEventStore is provided only for temporary/isolated
tests.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Protocol

EVENT_SIGNAL_CONFIRMED = "signal_confirmed"
EVENT_PAPER_TRADE_CREATED = "paper_trade_created"
EVENT_DELIVERY_SUCCEEDED = "delivery_succeeded"
EVENT_DELIVERY_FAILED = "delivery_failed"

DELIVERY_OK = "delivered"
DELIVERY_FAILED = "failed"
DELIVERY_NOT_CONFIGURED = "NOT_CONFIGURED"
DELIVERY_DRY_RUN = "NOT_SENT_DRY_RUN"

_REDACT_KEYS = (
    "token", "chat_id", "chat", "secret", "password", "api_key", "authorization",
)


def _redact(value: Any) -> Any:
    """Recursively redact credential-shaped keys. Values are never logged."""
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for k, v in value.items():
            if any(s in str(k).lower() for s in _REDACT_KEYS):
                out[k] = "***REDACTED***"
            else:
                out[k] = _redact(v)
        return out
    if isinstance(value, (list, tuple)):
        return [_redact(v) for v in value]
    return value


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def event_id_for(signal_id: str, event_type: str) -> str:
    return hashlib.sha1(f"{event_type}|{signal_id}".encode()).hexdigest()[:16]


@dataclass(frozen=True)
class AlertEvent:
    event_id: str
    signal_id: str
    event_type: str
    created_at: str
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "signal_id": self.signal_id,
            "event_type": self.event_type,
            "created_at": self.created_at,
            "payload": _redact(self.payload),
        }


@dataclass(frozen=True)
class DeliveryResult:
    status: str
    detail: str = ""
    message_id: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status == DELIVERY_OK


class EventStore(Protocol):
    def has(self, event_id: str) -> bool: ...
    def put(self, event: AlertEvent, delivery: Optional[DeliveryResult] = None) -> None: ...
    def all(self) -> List[Dict[str, Any]]: ...


class AlertProvider(Protocol):
    name: str
    def configured(self) -> bool: ...
    def send(self, event: AlertEvent) -> DeliveryResult: ...


class InMemoryEventStore:
    """Default store. Per-process only; suitable for tests and dry-run."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: Dict[str, Dict[str, Any]] = {}

    def has(self, event_id: str) -> bool:
        with self._lock:
            return event_id in self._rows

    def put(self, event: AlertEvent, delivery: Optional[DeliveryResult] = None) -> None:
        with self._lock:
            row = event.to_dict()
            row["delivery"] = None if delivery is None else {
                "status": delivery.status,
                "detail": delivery.detail,
                "message_id": delivery.message_id,
            }
            self._rows[event.event_id] = row

    def all(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(v) for v in self._rows.values()]


class SQLiteEventStore:
    """Temporary-file store for isolated tests. Not a production migration."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.Lock()
        with self._lock:
            c = sqlite3.connect(self.path)
            try:
                c.execute(
                    """CREATE TABLE IF NOT EXISTS scalp_alert_events (
                        event_id TEXT PRIMARY KEY,
                        signal_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        payload TEXT NOT NULL,
                        delivery_status TEXT,
                        delivery_detail TEXT,
                        delivery_message_id TEXT
                    )"""
                )
                c.commit()
            finally:
                c.close()

    def has(self, event_id: str) -> bool:
        with self._lock:
            c = sqlite3.connect(self.path)
            try:
                return c.execute(
                    "SELECT 1 FROM scalp_alert_events WHERE event_id=?", (event_id,)
                ).fetchone() is not None
            finally:
                c.close()

    def put(self, event: AlertEvent, delivery: Optional[DeliveryResult] = None) -> None:
        import json
        with self._lock:
            c = sqlite3.connect(self.path)
            try:
                c.execute(
                    "INSERT OR IGNORE INTO scalp_alert_events "
                    "(event_id, signal_id, event_type, created_at, payload, "
                    " delivery_status, delivery_detail, delivery_message_id) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (
                        event.event_id, event.signal_id, event.event_type,
                        event.created_at, json.dumps(_redact(event.payload)),
                        None if delivery is None else delivery.status,
                        None if delivery is None else delivery.detail,
                        None if delivery is None else delivery.message_id,
                    ),
                )
                c.commit()
            finally:
                c.close()

    def all(self) -> List[Dict[str, Any]]:
        import json
        with self._lock:
            c = sqlite3.connect(self.path)
            try:
                rows = c.execute(
                    "SELECT event_id, signal_id, event_type, created_at, payload, "
                    "delivery_status, delivery_detail, delivery_message_id "
                    "FROM scalp_alert_events"
                ).fetchall()
            finally:
                c.close()
        return [
            {
                "event_id": r[0], "signal_id": r[1], "event_type": r[2],
                "created_at": r[3], "payload": json.loads(r[4]),
                "delivery": None if r[5] is None else {
                    "status": r[5], "detail": r[6], "message_id": r[7],
                },
            }
            for r in rows
        ]


class MockProvider:
    """Test provider. Never touches the network."""

    name = "mock"

    def __init__(self, configured: bool = True, fail: bool = False,
                 exc: Optional[BaseException] = None) -> None:
        self._configured = configured
        self.fail = fail
        self.exc = exc
        self.sent: List[str] = []

    def configured(self) -> bool:
        return self._configured

    def send(self, event: AlertEvent) -> DeliveryResult:
        if self.exc is not None:
            raise self.exc
        if not self._configured:
            return DeliveryResult(DELIVERY_NOT_CONFIGURED)
        self.sent.append(event.event_id)
        if self.fail:
            return DeliveryResult(DELIVERY_FAILED, "simulated failure")
        return DeliveryResult(DELIVERY_OK, "mocked", message_id=f"m{len(self.sent)}")


class TelegramProvider:
    """Presence/config detection only. Never sends during P0.14.

    The token file is inspected for existence and non-empty size only; its
    contents (token) are never read into logs or returned. `send` returns
    NOT_CONFIGURED when the file is absent, and NOT_SENT_DRY_RUN otherwise,
    so a log line can never be misrepresented as delivered.
    """

    name = "telegram"

    def __init__(self, env_path: Optional[str] = None,
                 allow_send: bool = False) -> None:
        base = os.environ.get("TRADINGAI_BASE", "/opt/tradingai")
        self.env_path = env_path or os.path.join(base, ".tg_env")
        self.allow_send = allow_send

    def configured(self) -> bool:
        try:
            return os.path.isfile(self.env_path) and os.path.getsize(self.env_path) > 0
        except OSError:
            return False

    def send(self, event: AlertEvent) -> DeliveryResult:
        if not self.configured():
            return DeliveryResult(DELIVERY_NOT_CONFIGURED)
        if not self.allow_send:
            return DeliveryResult(DELIVERY_DRY_RUN, "dry-run: no message sent")
        raise RuntimeError("live Telegram send is not enabled in P0.14")


class AlertPipeline:
    """Emit logical events and optionally deliver them via a provider."""

    def __init__(self, store: EventStore, provider: AlertProvider,
                 clock: Callable[[], str] = utc_now_iso) -> None:
        self.store = store
        self.provider = provider
        self.clock = clock

    def _emit(self, signal_id: str, event_type: str,
              payload: Dict[str, Any]):
        eid = event_id_for(signal_id, event_type)
        if self.store.has(eid):
            return None
        ev = AlertEvent(eid, signal_id, event_type, self.clock(), payload)
        self.store.put(ev)
        return ev

    def signal_confirmed(self, signal_id: str, **payload: Any):
        return self._emit(signal_id, EVENT_SIGNAL_CONFIRMED, payload)

    def paper_trade_created(self, signal_id: str, trade_id: str, **payload: Any):
        if not trade_id:
            raise ValueError("paper_trade_created requires a non-empty trade_id")
        body = dict(payload)
        body["trade_id"] = trade_id
        return self._emit(signal_id, EVENT_PAPER_TRADE_CREATED, body)

    def deliver(self, event: AlertEvent) -> DeliveryResult:
        try:
            result = self.provider.send(event)
        except Exception as exc:  # provider exception => represented as failure
            result = DeliveryResult(DELIVERY_FAILED, f"{type(exc).__name__}: {exc}")
        dtype = EVENT_DELIVERY_SUCCEEDED if result.ok else EVENT_DELIVERY_FAILED
        did = event_id_for(event.signal_id, dtype)
        if not self.store.has(did):
            self.store.put(
                AlertEvent(did, event.signal_id, dtype, self.clock(), {
                    "for_event": event.event_id,
                    "status": result.status,
                    "detail": result.detail,
                    "message_id": result.message_id,
                }),
                delivery=result,
            )
        return result

    def process_signal(self, signal: Dict[str, Any],
                       trade_creator: Callable[[Dict[str, Any]], Optional[str]]) -> Dict[str, Any]:
        """Confirm a signal, then emit paper_trade_created only on success.

        `trade_creator` must return a non-empty trade id on success, or
        None / raise on failure. Repeated calls for the same signal are
        idempotent: once the trade-created event exists, trade_creator is not
        called again and no duplicate logical events are emitted.
        """
        signal_id = str(signal["signal_id"])
        payload = {k: v for k, v in signal.items() if k != "signal_id"}
        signal_event = self.signal_confirmed(signal_id, **payload)

        trade_eid = event_id_for(signal_id, EVENT_PAPER_TRADE_CREATED)
        if self.store.has(trade_eid):
            return {"signal_event": signal_event, "trade_event": None,
                    "trade_id": None, "note": "already processed"}

        try:
            trade_id = trade_creator(signal)
        except Exception as exc:
            return {"signal_event": signal_event, "trade_event": None,
                    "trade_id": None,
                    "note": f"trade creation raised: {type(exc).__name__}: {exc}"}

        if not trade_id:
            return {"signal_event": signal_event, "trade_event": None,
                    "trade_id": None, "note": "trade not created"}

        trade_event = self.paper_trade_created(signal_id, str(trade_id))
        return {"signal_event": signal_event, "trade_event": trade_event,
                "trade_id": trade_id, "note": "created"}
