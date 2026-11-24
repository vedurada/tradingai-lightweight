"""Risk-controlled order execution for the isolated ``sma9_live`` service.

This module is deliberately separate from the paper scanners and from the
read-only Kite-compatible gateway shim. Nothing here places a broker order by
default:

* ``SMA9_LIVE_EXECUTOR`` defaults to ``dry_run``.
* ``MStockOrderExecutor`` uses the verified mStock Type A order contract via
  the root-owned gateway, and only when both arm flags are set.
* A kill switch, daily order cap, one-position-per-leg rule and price collar
  are enforced before any executor is called.
* Client order IDs are deterministic so retries cannot duplicate an order.

No secrets, credentials, keys or OTP/TOTP values are read or stored here.
"""
from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
SCANNER = "sma9_live"
BUY = "BUY"
SELL = "SELL"

STATUS_NEW = "NEW"
STATUS_ACCEPTED = "ACCEPTED"
STATUS_DRY_RUN = "DRY_RUN_FILLED"
STATUS_REJECTED = "REJECTED"
STATUS_FAILED = "FAILED"
STATUS_FILLED = "FILLED"
STATUS_CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class RiskLimits:
    """Hard limits applied to every live-service order attempt."""

    max_orders_per_day: int = 4
    # Order quantity in underlying units. 75 = one NIFTY option lot.
    lot_size: int = 75
    collar_pct: float = 1.0
    kill_file: str = "/opt/tradingai/run/sma9_live.KILL"

    @classmethod
    def from_env(cls, environ=None) -> "RiskLimits":
        env = environ if environ is not None else os.environ
        limits = cls(
            max_orders_per_day=int(env.get("SMA9_LIVE_MAX_ORDERS_PER_DAY", "4")),
            lot_size=int(env.get("SMA9_LIVE_LOT_SIZE", "75")),
            collar_pct=float(env.get("SMA9_LIVE_PRICE_COLLAR_PCT", "1.0")),
            kill_file=env.get("SMA9_LIVE_KILL_FILE", cls.kill_file),
        )
        limits.validate()
        return limits

    def validate(self) -> None:
        if self.max_orders_per_day < 1:
            raise ValueError("SMA9_LIVE_MAX_ORDERS_PER_DAY must be >= 1")
        if self.lot_size < 1:
            raise ValueError("SMA9_LIVE_LOT_SIZE must be >= 1")
        if not (0 < self.collar_pct <= 5):
            raise ValueError("SMA9_LIVE_PRICE_COLLAR_PCT must be in (0, 5]")
        if not self.kill_file:
            raise ValueError("SMA9_LIVE_KILL_FILE must not be empty")


@dataclass
class OrderRecord:
    client_order_id: str
    trade_id: str
    option_type: str
    side: str
    symbol: str
    token: Optional[int]
    quantity: int
    intended_price: float
    limit_price: float
    collar_pct: float
    reason: str
    dry_run: bool = True
    status: str = STATUS_NEW
    broker_order_id: Optional[str] = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    order_date: str = field(
        default_factory=lambda: datetime.now(IST).date().isoformat()
    )

    def __post_init__(self) -> None:
        if self.side not in (BUY, SELL):
            raise ValueError(f"invalid order side: {self.side!r}")
        if self.option_type not in ("CE", "PE"):
            raise ValueError(f"invalid option type: {self.option_type!r}")
        if self.quantity < 1:
            raise ValueError("order quantity must be >= 1")
        if self.intended_price <= 0 or self.limit_price <= 0:
            raise ValueError("order prices must be positive")

    def as_row(self) -> tuple:
        return (
            self.client_order_id, SCANNER, self.trade_id, self.option_type,
            self.side, self.symbol, self.token, self.quantity,
            round(self.intended_price, 2), round(self.limit_price, 2),
            self.collar_pct, self.reason, int(self.dry_run), self.status,
            self.broker_order_id, self.created_at, self.order_date,
        )


ORDER_COLUMNS = (
    "client_order_id, scanner, trade_id, option_type, side, symbol, token, "
    "quantity, intended_price, limit_price, collar_pct, reason, dry_run, "
    "status, broker_order_id, created_at, order_date"
)


def make_client_order_id(trade_id: str, side: str, tag: str = "") -> str:
    """Stable idempotency key derived from the strategy trade and side."""
    raw = f"{SCANNER}|{trade_id}|{side}|{tag}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"S9L-{side}-{digest}"


def apply_price_collar(ltp: float, side: str, collar_pct: float) -> float:
    """Return a protective limit price around the sampled LTP."""
    if ltp <= 0:
        raise ValueError("ltp must be positive")
    factor = 1.0 + collar_pct / 100.0 if side == BUY else 1.0 - collar_pct / 100.0
    return round(ltp * factor, 2)


def kill_switch_active(limits: RiskLimits, environ=None) -> bool:
    env = environ if environ is not None else os.environ
    if str(env.get("SMA9_LIVE_KILLED", "")).strip().lower() in {"1", "true", "yes"}:
        return True
    try:
        return os.path.exists(limits.kill_file)
    except OSError:
        return False


def entry_allowed(
    open_positions, orders_today: int, limits: RiskLimits, environ=None
) -> tuple[bool, str]:
    """Gate a new BUY. Exits are never blocked by these risk controls."""
    if kill_switch_active(limits, environ):
        return False, "KILL_SWITCH_ACTIVE"
    if orders_today >= limits.max_orders_per_day:
        return False, "DAILY_ORDER_CAP"
    if len(list(open_positions)) >= 2:
        return False, "MAX_TWO_OPEN_LEGS"
    return True, "OK"


class OrderExecutor:
    """Interface implemented by dry-run and (future) real brokers."""

    name = "base"

    def place(self, record: OrderRecord) -> OrderRecord:
        raise NotImplementedError

    def order_status(self, record: OrderRecord) -> str:
        raise NotImplementedError


class DryRunOrderExecutor(OrderExecutor):
    """Records orders locally and returns a synthetic fill. Never calls a broker."""

    name = "dry_run"

    def place(self, record: OrderRecord) -> OrderRecord:
        record.dry_run = True
        record.status = STATUS_DRY_RUN
        record.broker_order_id = f"DRY-{record.client_order_id}"
        logger.info(
            "LIVE DRY-RUN ORDER %s %s %s qty=%d limit=%.2f reason=%s id=%s",
            record.side, record.option_type, record.symbol, record.quantity,
            record.limit_price, record.reason, record.client_order_id,
        )
        return record

    def order_status(self, record: OrderRecord) -> str:
        return STATUS_DRY_RUN


def _gateway_call(broker: str, method: str, **params):
    """Late import so tests can inject a fake without touching the gateway."""
    from broker_gateway.client import call

    return call(broker, method, **params)


class MStockOrderExecutor(OrderExecutor):
    """Real mStock Type A executor, reached only through the root-owned gateway.

    No credentials, keys or OTP/TOTP values are read here. Both arm flags, the
    kill switch and the daemon's order opt-in must be set before an order can
    leave the process; any failure fails closed and is recorded in the ledger.
    """

    name = "mstock"

    def __init__(self, caller=None, broker: str = "mstock", environ=None):
        self._call = caller or _gateway_call
        self.broker = broker
        self._env = environ if environ is not None else os.environ
        self.product = str(self._env.get("SMA9_LIVE_PRODUCT", "MIS")).strip().upper()
        self.variety = "reg"
        self.validity = "DAY"
        self.order_type = "LIMIT"

    def _require_armed(self) -> None:
        if not real_orders_armed(self._env):
            raise PermissionError(
                "real orders require SMA9_LIVE_ORDERS_ENABLED=true and "
                "SMA9_LIVE_ARM_REAL_ORDERS=ARMED"
            )
        if kill_switch_active(RiskLimits.from_env(self._env), self._env):
            raise PermissionError("sma9_live kill switch is active")

    def _order_params(self, record: OrderRecord) -> dict:
        symbol = str(record.symbol or "").strip()
        if ":" not in symbol:
            raise ValueError(f"order symbol must be EXCHANGE:SYMBOL, got {symbol!r}")
        exchange, tradingsymbol = symbol.split(":", 1)
        exchange = exchange.strip().upper()
        if exchange != "NFO" or not tradingsymbol.strip():
            raise ValueError(f"unsupported live order exchange/symbol: {symbol!r}")
        return {
            "variety": self.variety,
            "exchange": exchange,
            "tradingsymbol": tradingsymbol.strip(),
            "transaction_type": record.side,
            "order_type": self.order_type,
            "quantity": int(record.quantity),
            "product": self.product,
            "validity": self.validity,
            "price": float(record.limit_price),
            "tag": record.client_order_id,
        }

    def place(self, record: OrderRecord) -> OrderRecord:
        self._require_armed()
        params = self._order_params(record)
        try:
            result = self._call(self.broker, "place_order", **params) or {}
            broker_order_id = str(result.get("order_id") or "").strip()
        except Exception as exc:
            record.dry_run = False
            record.status = STATUS_REJECTED
            logger.error("mStock rejected %s: %s", record.client_order_id, exc)
            raise
        if not broker_order_id:
            record.dry_run = False
            record.status = STATUS_REJECTED
            raise RuntimeError("mStock order response did not contain an order_id")
        record.dry_run = False
        record.status = STATUS_ACCEPTED
        record.broker_order_id = broker_order_id
        logger.info(
            "LIVE REAL ORDER %s %s %s qty=%d limit=%.2f broker_id=%s id=%s",
            record.side, record.option_type, record.symbol, record.quantity,
            record.limit_price, broker_order_id, record.client_order_id,
        )
        return record

    def order_status(self, record: OrderRecord) -> str:
        if not record.broker_order_id:
            return record.status
        result = self._call(
            self.broker, "order_status", broker_order_id=record.broker_order_id
        ) or {}
        status = str(result.get("status") or STATUS_NEW).upper()
        if status == "OPEN":
            status = STATUS_ACCEPTED
        if status in {STATUS_NEW, STATUS_ACCEPTED, STATUS_FILLED,
                      STATUS_CANCELLED, STATUS_REJECTED, STATUS_FAILED}:
            return status
        return STATUS_NEW


def build_executor(environ=None) -> OrderExecutor:
    env = environ if environ is not None else os.environ
    name = str(env.get("SMA9_LIVE_EXECUTOR", "dry_run")).strip().lower()
    if name == DryRunOrderExecutor.name:
        return DryRunOrderExecutor()
    if name == MStockOrderExecutor.name:
        if not real_orders_armed(env):
            logger.warning(
                "SMA9_LIVE_EXECUTOR=mstock selected but orders are not armed; "
                "every attempt will fail closed"
            )
        return MStockOrderExecutor(environ=env)
    raise ValueError(f"unknown SMA9_LIVE_EXECUTOR: {name!r}")


def real_orders_armed(environ=None) -> bool:
    """Second independent arm flag required before any real executor can act."""
    env = environ if environ is not None else os.environ
    return (
        str(env.get("SMA9_LIVE_ORDERS_ENABLED", "")).strip().lower() == "true"
        and str(env.get("SMA9_LIVE_ARM_REAL_ORDERS", "")).strip() == "ARMED"
    )
