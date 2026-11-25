"""Risk-controlled order execution for the isolated ``sma9_live`` service.

This module is deliberately separate from the paper scanners and from the
read-only Kite-compatible gateway shim. Nothing here places a broker order by
default:

* ``SMA9_LIVE_EXECUTOR`` defaults to ``dry_run``.
* ``MStockOrderExecutor`` uses the verified mStock Type A order contract via
  the root-owned gateway, and only when both arm flags are set.
* A kill switch, optional daily order cap and one-position-per-leg rule are
  enforced before any executor is called. The BUY price collar is disabled by
  default; operators may set it to 0 to leave no price gate at all.
* Real orders are MARKET orders; any optional collar value is only an audit
  reference on sampled LTP, never a broker-side limit price.
* Client order IDs are deterministic per attempt; bounded retries use a new
  ``rN`` tag and an explicit ``retry_of`` pointer, never a blind resubmission.
* Broker fill prices are recorded in a separate shadow log so signal-vs-fill
  slippage and estimated costs can be measured without altering trade P&L.

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

# Placement classification, kept separate from the broker's order status. The
# broker status answers "what happened to this order"; place_status answers
# "do we know whether the POST reached the broker at all".
PLACE_SUBMITTED = "SUBMITTED"
PLACE_PRE_POST_REFUSED = "PRE_POST_REFUSED"
PLACE_AMBIGUOUS = "AMBIGUOUS"
PLACE_DEFINITELY_REJECTED = "DEFINITELY_REJECTED"
PLACE_RETRY_DUE = "RETRY_DUE"
PLACE_RETRY_ATTEMPTED = "RETRY_ATTEMPTED"
PLACE_RETRY_EXHAUSTED = "RETRY_EXHAUSTED"
PLACE_MANUAL_REQUIRED = "MANUAL_REQUIRED"
PLACE_RESOLVED = "RESOLVED"


@dataclass(frozen=True)
class OrderLookup:
    """Result of a read-only broker order-book lookup by our client tag."""

    found: bool = False
    multiple: bool = False
    broker_order_id: Optional[str] = None
    status: Optional[str] = None
    fill_price: Optional[float] = None
    filled_quantity: Optional[float] = None
    quantity: Optional[float] = None
    raw_status: Optional[str] = None
    status_message: Optional[str] = None
    error_code: Optional[str] = None


@dataclass(frozen=True)
class OrderDetails:
    """Read-only broker status plus fill fields used by the shadow log.

    ``fill_price`` is best-effort: mStock may omit an average price until the
    order reaches a terminal state. A missing value is never treated as zero.
    """

    status: str
    fill_price: Optional[float] = None
    raw_status: Optional[str] = None
    status_message: Optional[str] = None
    filled_quantity: Optional[float] = None


@dataclass(frozen=True)
class RiskLimits:
    """Hard limits applied to every live-service order attempt."""

    # 0 means unlimited entries; the deployed service uses 0.
    max_orders_per_day: int = 4
    # 0 means resolve the quantity from the mStock instrument master per
    # contract; no hard-coded lot size in the scanner.
    lot_size: int = 0
    # 0 disables the pre-trade price collar; the operator removed this guard.
    collar_pct: float = 0.0
    kill_file: str = "/opt/tradingai/run/sma9_live.KILL"

    @classmethod
    def from_env(cls, environ=None) -> "RiskLimits":
        env = environ if environ is not None else os.environ
        limits = cls(
            max_orders_per_day=int(env.get("SMA9_LIVE_MAX_ORDERS_PER_DAY", "4")),
            lot_size=int(env.get("SMA9_LIVE_LOT_SIZE", "0")),
            collar_pct=float(env.get("SMA9_LIVE_PRICE_COLLAR_PCT", "0")),
            kill_file=env.get("SMA9_LIVE_KILL_FILE", cls.kill_file),
        )
        limits.validate()
        return limits

    def validate(self) -> None:
        if self.max_orders_per_day < 0:
            raise ValueError("SMA9_LIVE_MAX_ORDERS_PER_DAY must be >= 0 (0=unlimited)")
        if self.lot_size < 0:
            raise ValueError("SMA9_LIVE_LOT_SIZE must be >= 0 (0=fetch from mStock)")
        if not (0 <= self.collar_pct <= 5):
            raise ValueError("SMA9_LIVE_PRICE_COLLAR_PCT must be in [0, 5]")
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
    attempt_no: int = 0
    retry_of: Optional[str] = None
    retry_count: int = 0
    place_status: str = PLACE_SUBMITTED
    counts_toward_cap: bool = True

    def __post_init__(self) -> None:
        if self.side not in (BUY, SELL):
            raise ValueError(f"invalid order side: {self.side!r}")
        if self.option_type not in ("CE", "PE"):
            raise ValueError(f"invalid option type: {self.option_type!r}")
        if self.quantity < 1:
            raise ValueError("order quantity must be >= 1")
        if self.intended_price <= 0 or self.limit_price <= 0:
            raise ValueError("order prices must be positive")
        if self.attempt_no < 0 or self.retry_count < 0:
            raise ValueError("attempt/retry counters must be >= 0")

    def as_row(self) -> tuple:
        return (
            self.client_order_id, SCANNER, self.trade_id, self.option_type,
            self.side, self.symbol, self.token, self.quantity,
            round(self.intended_price, 2), round(self.limit_price, 2),
            self.collar_pct, self.reason, int(self.dry_run), self.status,
            self.broker_order_id, self.created_at, self.order_date,
            self.attempt_no, self.retry_of or self.client_order_id,
            self.retry_count, self.place_status, int(self.counts_toward_cap),
        )


ORDER_COLUMNS = (
    "client_order_id, scanner, trade_id, option_type, side, symbol, token, "
    "quantity, intended_price, limit_price, collar_pct, reason, dry_run, "
    "status, broker_order_id, created_at, order_date, attempt_no, retry_of, "
    "retry_count, place_status, counts_toward_cap"
)


def make_client_order_id(trade_id: str, side: str, tag: str = "") -> str:
    """Stable idempotency key derived from the strategy trade and side."""
    raw = f"{SCANNER}|{trade_id}|{side}|{tag}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"S9L-{side}-{digest}"


def apply_price_collar(ltp: float, side: str, collar_pct: float) -> float:
    """Return the reference price recorded in the ledger for an order.

    Real orders are MARKET orders, so this value is never sent to the broker.
    It remains useful as an audit reference and for the BUY sanity check.
    """
    if ltp <= 0:
        raise ValueError("ltp must be positive")
    factor = 1.0 + collar_pct / 100.0 if side == BUY else 1.0 - collar_pct / 100.0
    return round(ltp * factor, 2)


def price_collar_breached(
    price: float, reference: Optional[float], collar_pct: float
) -> bool:
    """True when a BUY price jumped more than ``collar_pct`` from the last poll.

    A missing reference (first poll, restart, unavailable quote) is treated as
    no breach so the service can still trade; exits bypass this check so a real
    position can always be closed.
    """
    if collar_pct <= 0:
        return False
    if not reference or reference <= 0 or price <= 0:
        return False
    move_pct = round(abs(float(price) / float(reference) - 1.0) * 100.0, 6)
    return move_pct > collar_pct


def measure_slippage(
    side: str, signal_price: float, fill_price: Optional[float], quantity: int
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Return (points, percent, rupee value) of execution gap vs signal LTP.

    Positive is always adverse: a BUY filled above the signal, or a SELL filled
    below it. Missing/invalid fills return all Nones rather than guessing.
    """
    if side not in (BUY, SELL):
        raise ValueError(f"invalid order side: {side!r}")
    if fill_price is None or signal_price <= 0 or quantity <= 0:
        return None, None, None
    try:
        fill = float(fill_price)
    except (TypeError, ValueError):
        return None, None, None
    if fill <= 0:
        return None, None, None
    points = (fill - signal_price) if side == BUY else (signal_price - fill)
    pct = points / signal_price * 100.0
    value = points * quantity
    return round(points, 4), round(pct, 4), round(value, 2)


def estimated_order_cost(side: str, quantity: int, environ=None) -> float:
    """Configurable ESTIMATE of one order's charges, in rupees.

    This is a shadow accounting figure only; it is never sent to the broker and
    does not claim to be the actual contract note. Defaults: zero brokerage
    (mStock plan) plus a flat per-order allowance for exchange/STT/GST/stamp.
    Override with SMA9_LIVE_COST_BROKERAGE_PER_ORDER,
    SMA9_LIVE_COST_OTHER_PER_ORDER, SMA9_LIVE_COST_SELL_EXTRA_PER_ORDER and
    SMA9_LIVE_COST_PER_UNIT. Negative values are treated as zero.
    """

    env = environ if environ is not None else os.environ

    def _num(key: str, default: str) -> float:
        try:
            return max(0.0, float(env.get(key, default)))
        except (TypeError, ValueError):
            return float(default)

    brokerage = _num("SMA9_LIVE_COST_BROKERAGE_PER_ORDER", "0")
    other = _num("SMA9_LIVE_COST_OTHER_PER_ORDER", "20")
    sell_extra = (_num("SMA9_LIVE_COST_SELL_EXTRA_PER_ORDER", "0")
                  if side == SELL else 0.0)
    per_unit = _num("SMA9_LIVE_COST_PER_UNIT", "0")
    return round(brokerage + other + sell_extra + per_unit * quantity, 2)


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
    if (limits.max_orders_per_day > 0
            and orders_today >= limits.max_orders_per_day):
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

    def order_details(self, record: OrderRecord) -> OrderDetails:
        """Broker status plus fills; fakes that only expose status inherit this."""
        return OrderDetails(status=self.order_status(record))

    def order_by_tag(self, record: OrderRecord) -> OrderLookup:
        """Read-only tag lookup; executors without broker support fail closed."""
        return OrderLookup(error_code="UNSUPPORTED")


class DryRunOrderExecutor(OrderExecutor):
    """Records orders locally and returns a synthetic fill. Never calls a broker."""

    name = "dry_run"

    def place(self, record: OrderRecord) -> OrderRecord:
        record.dry_run = True
        record.status = STATUS_DRY_RUN
        record.broker_order_id = f"DRY-{record.client_order_id}"
        logger.info(
            "LIVE DRY-RUN ORDER %s %s %s qty=%d ref=%.2f reason=%s id=%s",
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
        self.order_type = "MARKET"

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
            # MARKET orders carry no price. The collar reference stays in the
            # local ledger only; it is never sent as a broker limit price.
            "price": 0,
            "tag": record.client_order_id,
        }

    def place(self, record: OrderRecord) -> OrderRecord:
        # These checks happen before any network call: a failure here is a
        # definite no-send and is safe to re-evaluate later.
        self._require_armed()
        params = self._order_params(record)
        try:
            result = self._call(self.broker, "place_order", **params) or {}
            broker_order_id = str(result.get("order_id") or "").strip()
        except Exception as exc:
            record.dry_run = False
            record.status = STATUS_REJECTED
            # A timeout or connection error does not prove non-acceptance.
            record.place_status = PLACE_AMBIGUOUS
            logger.error("mStock submit failed %s: %s", record.client_order_id, exc)
            raise
        if not broker_order_id:
            record.dry_run = False
            record.status = STATUS_REJECTED
            record.place_status = PLACE_AMBIGUOUS
            raise RuntimeError("mStock order response did not contain an order_id")
        record.dry_run = False
        record.status = STATUS_ACCEPTED
        record.place_status = PLACE_SUBMITTED
        record.broker_order_id = broker_order_id
        logger.info(
            "LIVE REAL MARKET ORDER %s %s %s qty=%d ref=%.2f broker_id=%s id=%s",
            record.side, record.option_type, record.symbol, record.quantity,
            record.limit_price, broker_order_id, record.client_order_id,
        )
        return record

    @staticmethod
    def _normalise_lookup_status(value) -> str:
        status = str(value or "").strip().upper()
        if status in {"COMPLETE", "FILLED", "EXECUTED"}:
            return STATUS_FILLED
        if status in {"REJECT", "REJECTED"}:
            return STATUS_REJECTED
        if status in {"CANCEL", "CANCELLED", "CANCELED"}:
            return STATUS_CANCELLED
        if status in {"OPEN", "PENDING", "TRIGGERED", "PARTIAL", "AMENDED"}:
            return STATUS_ACCEPTED
        return STATUS_NEW

    @staticmethod
    def _optional_float(value) -> Optional[float]:
        if value in (None, ""):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if number >= 0 else None

    def order_by_tag(self, record: OrderRecord) -> OrderLookup:
        """Look up our client tag in the broker order book without placing."""
        try:
            result = self._call(
                self.broker, "order_by_tag", tag=record.client_order_id
            ) or {}
        except Exception as exc:
            logger.error("mStock tag lookup failed for %s: %s",
                         record.client_order_id, exc)
            return OrderLookup(error_code="LOOKUP_FAILED")
        orders = [row for row in (result.get("orders") or [])
                  if isinstance(row, dict)]
        if not orders:
            return OrderLookup()
        order_ids = {
            str(row.get("order_id") or "").strip()
            for row in orders if str(row.get("order_id") or "").strip()
        }
        if len(order_ids) > 1:
            # More than one broker order with our tag is a duplicate-risk
            # signal. Never resolve it automatically.
            return OrderLookup(found=True, multiple=True,
                               error_code="MULTIPLE_ORDERS")
        # Prefer a terminal fill, then any open order, then the first row.
        order = next(
            (row for row in orders
             if self._normalise_lookup_status(row.get("status")) == STATUS_FILLED),
            next(
                (row for row in orders
                 if self._normalise_lookup_status(row.get("status"))
                 == STATUS_ACCEPTED),
                orders[0],
            ),
        )
        return OrderLookup(
            found=True,
            broker_order_id=str(order.get("order_id") or "").strip() or None,
            status=self._normalise_lookup_status(order.get("status")),
            fill_price=self._optional_float(order.get("fill_price")),
            filled_quantity=self._optional_float(order.get("filled_quantity")),
            quantity=self._optional_float(order.get("quantity")),
            raw_status=order.get("raw_status"),
            status_message=order.get("status_message"),
        )

    def order_details(self, record: OrderRecord) -> OrderDetails:
        """One read-only status poll, including the broker's average fill price."""
        if not record.broker_order_id:
            return OrderDetails(status=record.status)
        result = self._call(
            self.broker, "order_status", broker_order_id=record.broker_order_id
        ) or {}
        status = str(result.get("status") or STATUS_NEW).strip().upper()
        # The adapter already normalises these, but map raw broker spellings
        # too so a gateway version change cannot turn a fill into NEW.
        if status in {"COMPLETE", "FILLED", "EXECUTED"}:
            status = STATUS_FILLED
        elif status in {"REJECT", "REJECTED"}:
            status = STATUS_REJECTED
        elif status in {"CANCEL", "CANCELLED", "CANCELED"}:
            status = STATUS_CANCELLED
        elif status in {"OPEN", "PENDING", "TRIGGERED", "PARTIAL", "AMENDED"}:
            status = STATUS_ACCEPTED
        if status not in {STATUS_NEW, STATUS_ACCEPTED, STATUS_FILLED,
                          STATUS_CANCELLED, STATUS_REJECTED, STATUS_FAILED}:
            status = STATUS_NEW
        raw_fill = result.get("fill_price")
        try:
            fill_price = float(raw_fill) if raw_fill not in (None, "") else None
        except (TypeError, ValueError):
            fill_price = None
        if fill_price is not None and fill_price <= 0:
            fill_price = None
        return OrderDetails(
            status=status,
            fill_price=fill_price,
            raw_status=result.get("raw_status"),
            status_message=result.get("status_message"),
            filled_quantity=self._optional_float(result.get("filled_quantity")),
        )

    def order_status(self, record: OrderRecord) -> str:
        """String-only compatibility wrapper around ``order_details``."""
        return self.order_details(record).status


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
