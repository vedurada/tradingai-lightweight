#!/usr/bin/env python3
"""SMA9 ATM CE+PE LIVE-EXECUTION service - BUY ONLY.

Isolated from the paper ``sma9`` scanner: its own strategy id, database,
systemd unit and order ledger.  The signal logic is the same, but every entry
and exit is submitted through ``app.live_execution`` which applies a kill
switch, one-position-per-leg rule and a pre-trade BUY price-collar check. The
daily order cap is disabled in the deployed unit, and real orders are MARKET
orders with the quantity fetched from mStock's instrument master.

IMPORTANT: the default executor is ``dry_run``. Real mStock Type A orders are
available only through the root-owned gateway and require both arm flags;
``MStockOrderExecutor`` fails closed otherwise. No credentials, keys or
OTP/TOTP values are read here.

Polling is exactly every 5 seconds during market hours.  One batched quote
call per poll provides NIFTY spot + both option LTPs; historical candles are
fetched only when a new 5-minute candle appears (or at exit), never on every
poll.  State lives in database/sma9_live.db.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import time
import traceback
from datetime import date, datetime, time as dtime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

BASE = "/opt/tradingai"
CODE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if CODE_ROOT not in sys.path:
    sys.path.insert(0, CODE_ROOT)

from app.sma9_live_engine import (  # noqa: E402
    CANDLE_MINUTES,
    SMA_PERIOD,
    STRATEGY_ID,
    STRATEGY_TYPE,
    STRATEGY_VERSION,
    Evaluation,
    OptionStateMachine,
    Position,
    candle_end,
    evaluate_option,
    normalize_candles,
)
from app.live_execution import (  # noqa: E402
    BUY,
    SELL,
    ORDER_COLUMNS,
    OrderLookup,
    RiskLimits,
    OrderRecord,
    apply_price_collar,
    build_executor,
    entry_allowed,
    estimated_order_cost,
    kill_switch_active,
    make_client_order_id,
    measure_slippage,
    price_collar_breached,
    real_orders_armed,
    STATUS_ACCEPTED,
    STATUS_CANCELLED,
    STATUS_DRY_RUN,
    STATUS_FAILED,
    STATUS_FILLED,
    STATUS_NEW,
    STATUS_REJECTED,
    PLACE_AMBIGUOUS,
    PLACE_DEFINITELY_REJECTED,
    PLACE_MANUAL_REQUIRED,
    PLACE_PRE_POST_REFUSED,
    PLACE_RESOLVED,
    PLACE_RETRY_ATTEMPTED,
    PLACE_RETRY_DUE,
    PLACE_RETRY_EXHAUSTED,
    PLACE_SUBMITTED,
)

# Position lifecycle states, persisted alongside the open position.
LIFECYCLE_PENDING = "PENDING_FILL"
LIFECYCLE_ACTIVE = "ACTIVE"
LIFECYCLE_EXIT_PENDING = "EXIT_PENDING"
LIFECYCLE_ENTRY_UNCONFIRMED = "ENTRY_UNCONFIRMED"
LIFECYCLE_EXIT_FAILED = "EXIT_FAILED"
LIFECYCLE_ENTRY_RETRY_PENDING = "ENTRY_RETRY_PENDING"
LIFECYCLE_EXIT_RETRY_PENDING = "EXIT_RETRY_PENDING"
LIFECYCLE_ENTRY_PARTIAL = "ENTRY_PARTIAL"
LIFECYCLE_EXIT_PARTIAL = "EXIT_PARTIAL"
LIFECYCLE_ENTRY_BLOCKED = "ENTRY_BLOCKED"
LIFECYCLE_EXIT_BLOCKED = "EXIT_BLOCKED"

FILLED_STATUSES = frozenset({STATUS_FILLED, STATUS_DRY_RUN})
PENDING_STATUSES = frozenset({STATUS_NEW, STATUS_ACCEPTED})
FAILED_STATUSES = frozenset({STATUS_REJECTED, STATUS_CANCELLED, STATUS_FAILED})
ENABLED_FLAG = {"1", "true", "yes", "on"}

IST = ZoneInfo("Asia/Kolkata")
DB_PATH = os.environ.get(
    "SMA9_LIVE_DB_PATH", os.path.join(BASE, "database", "sma9_live.db"))
LOG_PATH = os.path.join(BASE, "logs", "live_sma9_live_scanner.log")

MARKET_OPEN = dtime(9, 0)
MARKET_CLOSE = dtime(15, 30)
EXCHANGE_OPEN = dtime(9, 15)  # real trading starts; 09:00-09:15 is warm-up only
ENTRY_START = dtime(9, 20)
ENTRY_END = dtime(15, 15)
# Special trading sessions (e.g. muhurat trading) that fall outside the
# normal weekday 09:00-15:30 window.  Date (ISO) -> (open, close) time.
MUHURAT_SESSIONS = {
    "2026-11-08": (dtime(14, 0), dtime(17, 0)),
}

# NSE weekday trading holidays mirrored from app/market/nse_calendar.py
# (NSE circular CMTR71775, verified 2026-09-28). These standalone scanners
# cannot import app/, so the 2026 table is duplicated here. Fail-safe:
# uncovered years fall back to the weekday rule, and scan() still refuses
# to trade when the broker quote is unavailable.
NSE_HOLIDAYS_2026 = frozenset({
    "2026-01-26", "2026-03-03", "2026-03-26", "2026-03-31", "2026-04-03",
    "2026-04-14", "2026-05-01", "2026-05-28", "2026-06-26", "2026-09-14",
    "2026-10-02", "2026-10-20", "2026-11-10", "2026-11-24", "2026-12-25",
})

def session_open_time(dt):
    return MUHURAT_SESSIONS.get(dt.date().isoformat(), (MARKET_OPEN, MARKET_CLOSE))[0]

def session_close_time(dt):
    return MUHURAT_SESSIONS.get(dt.date().isoformat(), (MARKET_OPEN, MARKET_CLOSE))[1]
POLL_SECONDS = 5
# Read-only broker order-status polling. It never places or modifies an order.
RECONCILE_ENABLED = (
    os.environ.get("SMA9_LIVE_RECONCILE_ENABLED", "true").strip().lower()
    in ENABLED_FLAG
)
RECONCILE_MAX_ATTEMPTS = max(
    1, int(os.environ.get("SMA9_LIVE_RECONCILE_MAX_ATTEMPTS", "120")))
RECONCILE_BATCH = max(
    1, int(os.environ.get("SMA9_LIVE_RECONCILE_BATCH", "50")))

# Stage 1: read-only broker lookup by our client tag. It can adopt a real
# broker order id after an ambiguous submit, but a miss never places a new
# order unless RETRY_AMBIGUOUS is explicitly enabled.
TAG_LOOKUP_MAX_ATTEMPTS = max(
    1, int(os.environ.get("SMA9_LIVE_TAG_LOOKUP_MAX_ATTEMPTS", "12")))

# Stage 2: bounded retries, disabled by default. Retries are only for broker-
# confirmed no-fill outcomes; an ambiguous timeout stays manual unless
# SMA9_LIVE_RETRY_AMBIGUOUS=true is set deliberately.
RETRY_ENABLED = (
    os.environ.get("SMA9_LIVE_RETRY_ENABLED", "").strip().lower() in ENABLED_FLAG
)
RETRY_MAX_ATTEMPTS = (
    min(3, max(0, int(os.environ.get("SMA9_LIVE_RETRY_MAX_ATTEMPTS", "1"))))
    if RETRY_ENABLED else 0
)
RETRY_BASE_DELAY_SEC = max(
    5, int(os.environ.get("SMA9_LIVE_RETRY_BASE_DELAY_SEC", "30")))
RETRY_MAX_AGE_SEC = max(
    60, int(os.environ.get("SMA9_LIVE_RETRY_MAX_AGE_SEC", "300")))
RETRY_AMBIGUOUS = (
    os.environ.get("SMA9_LIVE_RETRY_AMBIGUOUS", "").strip().lower()
    in ENABLED_FLAG
)
RETRY_SIDES = frozenset(
    side.strip().upper()
    for side in os.environ.get("SMA9_LIVE_RETRY_SIDES", "BUY,SELL").split(",")
    if side.strip().upper() in {BUY, SELL}
)
INSTRUMENT = "NIFTY"
TIMEFRAME = "5m"
SCANNER_NAME = "SMA9 Live - ATM Option Strike (BUY ONLY)"
STRATEGY_ID = STRATEGY_ID
STRATEGY_VERSION = STRATEGY_VERSION
STRATEGY_TYPE = STRATEGY_TYPE

# Fail closed at import time on invalid risk configuration.
LIMITS = RiskLimits.from_env()
EXECUTOR = build_executor()

# systemd appends stdout/stderr to LOG_PATH; a FileHandler here would double
# every line.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def now_ist() -> datetime:
    return datetime.now(IST)


def floor_5m(dt: datetime) -> datetime:
    return dt.replace(minute=(dt.minute // CANDLE_MINUTES) * CANDLE_MINUTES,
                      second=0, microsecond=0)


def is_weekday(dt: datetime) -> bool:
    if dt.date().isoformat() in MUHURAT_SESSIONS:
        return True
    if dt.date().isoformat() in NSE_HOLIDAYS_2026:
        return False
    return dt.weekday() < 5


def market_is_open(dt: datetime) -> bool:
    if not is_weekday(dt):
        return False
    return session_open_time(dt) <= dt.time() < session_close_time(dt)


def entry_window_is_open(dt):
    """True only inside the 09:20:00-15:14:59 entry window.

    The scanner starts at 09:00 (the exchange session is 09:15-15:30), but
    new paper entries are allowed only from 09:20 (so the 09:15 candle is
    never entered) and are blocked at 15:15
    (last entry candle is 15:10).  The entry cutoff does not close a
    position, but exits are not managed before the 09:15 exchange open
    (09:00-09:15 is warm-up only).
    """
    if not market_is_open(dt):
        return False
    return ENTRY_START <= dt.time() < ENTRY_END


def market_close_dt(dt: datetime) -> datetime:
    return datetime.combine(dt.date(), session_close_time(dt), tzinfo=IST)


def sleep_to_next_tick() -> None:
    now = now_ist()
    next_second = ((now.second // POLL_SECONDS) + 1) * POLL_SECONDS
    target = now.replace(microsecond=0) + timedelta(seconds=next_second - now.second)
    time.sleep(max(0.2, (target - now_ist()).total_seconds()))


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
TRADE_COLUMNS = (
    "trade_id, strategy_id, instrument, trade_date, option_type, strike, "
    "expiry, signal_timestamp, entry_timestamp, entry_price, exit_timestamp, "
    "exit_price, exit_reason, pnl_points, status, sma9_value, candle_open, "
    "candle_high, candle_low, candle_close, created_at, updated_at, dataset, "
    "prev_close, condition_a, condition_b, ltp_at_entry, entry_candle_start, "
    "entry_candle_end"
)


def db_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=15000")
    return conn


def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = db_conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sma9_live_trades (
            trade_id TEXT PRIMARY KEY,
            strategy_id TEXT NOT NULL DEFAULT 'sma9_live',
            instrument TEXT NOT NULL DEFAULT 'NIFTY',
            trade_date TEXT NOT NULL,
            option_type TEXT NOT NULL CHECK(option_type IN ('CE','PE')),
            strike REAL NOT NULL,
            expiry TEXT NOT NULL,
            signal_timestamp TEXT NOT NULL,
            entry_timestamp TEXT NOT NULL,
            entry_price REAL NOT NULL,
            exit_timestamp TEXT NOT NULL,
            exit_price REAL NOT NULL,
            exit_reason TEXT NOT NULL DEFAULT 'SAME_CANDLE_EXIT',
            pnl_points REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'CLOSED',
            sma9_value REAL,
            candle_open REAL,
            candle_high REAL,
            candle_low REAL,
            candle_close REAL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            dataset TEXT NOT NULL DEFAULT 'LIVE',
            prev_close REAL,
            condition_a INTEGER,
            condition_b INTEGER,
            ltp_at_entry REAL,
            entry_candle_start TEXT,
            entry_candle_end TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_sma9_live_trades_date ON sma9_live_trades(trade_date);
        CREATE INDEX IF NOT EXISTS idx_sma9_live_trades_option ON sma9_live_trades(option_type);
        CREATE INDEX IF NOT EXISTS idx_sma9_live_trades_status ON sma9_live_trades(status);
        CREATE INDEX IF NOT EXISTS idx_sma9_live_trades_dataset ON sma9_live_trades(dataset);

        CREATE TABLE IF NOT EXISTS sma9_live_open_positions (
            option_type TEXT PRIMARY KEY,
            trade_id TEXT NOT NULL,
            strike REAL NOT NULL,
            expiry TEXT NOT NULL,
            token INTEGER,
            tradingsymbol TEXT,
            entry_timestamp TEXT NOT NULL,
            entry_candle_start TEXT NOT NULL,
            entry_candle_end TEXT NOT NULL,
            entry_price REAL NOT NULL,
            sma9 REAL NOT NULL,
            prev_close REAL,
            current_open REAL,
            condition_a INTEGER,
            condition_b INTEGER,
            ltp_at_entry REAL,
            hwm REAL,
            stop REAL,
            be_locked INTEGER,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sma9_live_scan_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        -- Append-only order ledger. The deterministic client_order_id is the
        -- idempotency key for one attempt. Bounded retries use a new attempt
        -- tag but keep retry_of pointing at the original client_order_id.
        CREATE TABLE IF NOT EXISTS sma9_live_orders (
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
            broker_status TEXT,
            status_checked_at TEXT,
            reconcile_attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            created_at TEXT NOT NULL,
            order_date TEXT NOT NULL,
            attempt_no INTEGER NOT NULL DEFAULT 0,
            retry_of TEXT,
            retry_count INTEGER NOT NULL DEFAULT 0,
            place_status TEXT NOT NULL DEFAULT 'SUBMITTED',
            counts_toward_cap INTEGER NOT NULL DEFAULT 1,
            tag_lookup_attempts INTEGER NOT NULL DEFAULT 0,
            filled_quantity REAL,
            last_error_code TEXT,
            next_retry_at TEXT,
            updated_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_sma9_live_orders_date ON sma9_live_orders(order_date);
        CREATE INDEX IF NOT EXISTS idx_sma9_live_orders_trade ON sma9_live_orders(trade_id);

        -- Append-only audit trail for the real-trade lifecycle. The API never
        -- writes here; it is the operator-facing record of fill confirmations
        -- and broker mismatches.
        CREATE TABLE IF NOT EXISTS sma9_live_lifecycle_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_order_id TEXT NOT NULL,
            trade_id TEXT NOT NULL,
            side TEXT NOT NULL,
            event TEXT NOT NULL,
            detail TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sma9_live_events_trade
            ON sma9_live_lifecycle_events(trade_id);

        -- Shadow execution quality, one row per order leg. This does NOT alter
        -- trade P&L: it measures signal price vs broker fill and estimated cost.
        CREATE TABLE IF NOT EXISTS sma9_live_execution_quality (
            client_order_id TEXT PRIMARY KEY,
            trade_id TEXT NOT NULL,
            option_type TEXT NOT NULL CHECK(option_type IN ('CE','PE')),
            side TEXT NOT NULL CHECK(side IN ('BUY','SELL')),
            symbol TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            signal_price REAL NOT NULL,
            fill_price REAL,
            slippage_points REAL,
            slippage_pct REAL,
            slippage_value REAL,
            cost_estimate REAL NOT NULL DEFAULT 0,
            broker_status TEXT,
            raw_status TEXT,
            status_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sma9_live_quality_trade
            ON sma9_live_execution_quality(trade_id);
        CREATE INDEX IF NOT EXISTS idx_sma9_live_quality_created
            ON sma9_live_execution_quality(created_at);
        """
    )
    pos_cols = [r[1] for r in conn.execute(
        "PRAGMA table_info(sma9_live_open_positions)")]
    for col, decl in (("hwm", "REAL"), ("stop", "REAL"), ("be_locked", "INTEGER"),
                      ("lifecycle_state", "TEXT NOT NULL DEFAULT 'ACTIVE'")):
        if col not in pos_cols:
            conn.execute(
                f"ALTER TABLE sma9_live_open_positions ADD COLUMN {col} {decl}")
    order_cols = [r[1] for r in conn.execute(
        "PRAGMA table_info(sma9_live_orders)")]
    for col, decl in (
        ("broker_status", "TEXT"),
        ("status_checked_at", "TEXT"),
        ("reconcile_attempts", "INTEGER NOT NULL DEFAULT 0"),
        ("last_error", "TEXT"),
        ("attempt_no", "INTEGER NOT NULL DEFAULT 0"),
        ("retry_of", "TEXT"),
        ("retry_count", "INTEGER NOT NULL DEFAULT 0"),
        ("place_status", "TEXT NOT NULL DEFAULT 'SUBMITTED'"),
        ("counts_toward_cap", "INTEGER NOT NULL DEFAULT 1"),
        ("tag_lookup_attempts", "INTEGER NOT NULL DEFAULT 0"),
        ("filled_quantity", "REAL"),
        ("last_error_code", "TEXT"),
        ("next_retry_at", "TEXT"),
        ("updated_at", "TEXT"),
    ):
        if col not in order_cols:
            conn.execute(f"ALTER TABLE sma9_live_orders ADD COLUMN {col} {decl}")
    # Existing rows predate the retry family pointer; point them at themselves
    # so retry_of is always usable without nullable special cases.
    conn.execute(
        "UPDATE sma9_live_orders SET retry_of = client_order_id "
        "WHERE retry_of IS NULL")
    # Created after the column migration above: an existing DB from before the
    # retry work does not yet have place_status/next_retry_at at executescript
    # time, so creating this index there would abort startup.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sma9_live_orders_place "
        "ON sma9_live_orders(place_status, next_retry_at)")
    conn.commit()
    conn.close()


def save_trade(trade: dict) -> None:
    cols = TRADE_COLUMNS.split(",")
    cols = [c.strip() for c in cols]
    placeholders = ",".join("?" for _ in cols)
    conn = db_conn()
    try:
        conn.execute(
            f"INSERT OR REPLACE INTO sma9_live_trades ({','.join(cols)}) VALUES ({placeholders})",
            tuple(trade.get(c) for c in cols),
        )
        # Atomic close: insert the trade and remove the open position in
        # the same transaction so a crash cannot leave both (or neither).
        conn.execute(
            "DELETE FROM sma9_live_open_positions WHERE option_type = ?",
            (trade.get("option_type"),),
        )
        conn.commit()
    finally:
        conn.close()


def save_open_position(pos: Position) -> None:
    conn = db_conn()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO sma9_live_open_positions
               (option_type, trade_id, strike, expiry, token, tradingsymbol,
                entry_timestamp, entry_candle_start, entry_candle_end,
                entry_price, sma9, prev_close, current_open, condition_a,
                condition_b, ltp_at_entry, hwm, stop, be_locked,
                lifecycle_state, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                pos.option_type, pos.trade_id, pos.strike, pos.expiry, pos.token,
                pos.tradingsymbol, pos.entry_timestamp.isoformat(),
                pos.entry_candle_start.isoformat(), pos.entry_candle_end.isoformat(),
                pos.entry_price, pos.sma9, pos.prev_close, pos.current_open,
                1 if pos.condition_a else 0, 1 if pos.condition_b else 0,
                pos.ltp_at_entry, pos.hwm, pos.stop,
                1 if pos.be_locked else 0,
                getattr(pos, "lifecycle_state", LIFECYCLE_ACTIVE),
                now_ist().isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def delete_open_position(option_type: str) -> None:
    conn = db_conn()
    try:
        conn.execute("DELETE FROM sma9_live_open_positions WHERE option_type = ?",
                     (option_type,))
        conn.commit()
    finally:
        conn.close()


def load_open_positions() -> dict:
    conn = db_conn()
    try:
        rows = conn.execute("SELECT * FROM sma9_live_open_positions").fetchall()
    finally:
        conn.close()
    result = {}
    for r in rows:
        d = dict(r)
        result[d["option_type"]] = Position(
            option_type=d["option_type"],
            trade_id=d["trade_id"],
            strike=d["strike"],
            expiry=d["expiry"],
            token=d["token"],
            tradingsymbol=d["tradingsymbol"],
            entry_timestamp=datetime.fromisoformat(d["entry_timestamp"]),
            entry_candle_start=datetime.fromisoformat(d["entry_candle_start"]),
            entry_candle_end=datetime.fromisoformat(d["entry_candle_end"]),
            entry_price=d["entry_price"],
            sma9=d["sma9"],
            prev_close=d["prev_close"],
            current_open=d["current_open"],
            condition_a=bool(d["condition_a"]),
            condition_b=bool(d["condition_b"]),
            ltp_at_entry=d["ltp_at_entry"],
            hwm=d.get("hwm") if d.get("hwm") is not None else 0.0,
            stop=d.get("stop"),
            be_locked=bool(d.get("be_locked")),
            lifecycle_state=d.get("lifecycle_state") or LIFECYCLE_ACTIVE,
        )
    return result


def save_scan_state(state: dict) -> None:
    conn = db_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO sma9_live_scan_state (key, value, updated_at) VALUES (?,?,?)",
            ("live_status", json.dumps(state, default=str), now_ist().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def today_stats(today: str) -> dict:
    conn = db_conn()
    try:
        row = conn.execute(
            """SELECT COUNT(*) n, COALESCE(SUM(pnl_points),0) pnl,
                      COALESCE(SUM(CASE WHEN pnl_points > 0 THEN 1 ELSE 0 END),0) wins,
                      COALESCE(SUM(CASE WHEN pnl_points < 0 THEN 1 ELSE 0 END),0) losses
               FROM sma9_live_trades WHERE dataset='LIVE' AND trade_date=?""",
            (today,),
        ).fetchone()
    finally:
        conn.close()
    return {
        "trades": row["n"],
        "pnl_points": round(row["pnl"], 2),
        "wins": row["wins"],
        "losses": row["losses"],
    }


# ---------------------------------------------------------------------------
# Order ledger
# ---------------------------------------------------------------------------
_ORDER_PLACEHOLDERS = ",".join("?" for _ in ORDER_COLUMNS.split(","))


def order_exists(client_order_id: str) -> bool:
    conn = db_conn()
    try:
        row = conn.execute(
            "SELECT 1 FROM sma9_live_orders WHERE client_order_id = ?",
            (client_order_id,),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def save_order_record(record: OrderRecord) -> bool:
    """Insert an order once. Returns True only for a new client_order_id."""
    conn = db_conn()
    try:
        cur = conn.execute(
            f"INSERT OR IGNORE INTO sma9_live_orders "
            f"({ORDER_COLUMNS}) VALUES ({_ORDER_PLACEHOLDERS})",
            record.as_row(),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def update_order_status(
    client_order_id: str, status: str, broker_order_id: str | None = None,
    *, broker_status: str | None = None, checked_at: str | None = None,
    attempts: int | None = None, error: str | None = None,
    place_status: str | None = None, tag_lookup_attempts: int | None = None,
    retry_count: int | None = None, filled_quantity: float | None = None,
    last_error_code: str | None = None, next_retry_at: str | None = None,
) -> None:
    """Persist the executor/broker result against the idempotency key."""
    sets = ["status = ?", "updated_at = ?"]
    values: list = [status, now_ist().isoformat()]
    if broker_order_id is not None:
        sets.append("broker_order_id = ?")
        values.append(broker_order_id)
    if broker_status is not None:
        sets.append("broker_status = ?")
        values.append(broker_status)
    if checked_at is not None:
        sets.append("status_checked_at = ?")
        values.append(checked_at)
    if attempts is not None:
        sets.append("reconcile_attempts = ?")
        values.append(attempts)
    if error is not None:
        sets.append("last_error = ?")
        values.append(error)
    if place_status is not None:
        sets.append("place_status = ?")
        values.append(place_status)
    if tag_lookup_attempts is not None:
        sets.append("tag_lookup_attempts = ?")
        values.append(tag_lookup_attempts)
    if retry_count is not None:
        sets.append("retry_count = ?")
        values.append(retry_count)
    if filled_quantity is not None:
        sets.append("filled_quantity = ?")
        values.append(filled_quantity)
    if last_error_code is not None:
        sets.append("last_error_code = ?")
        values.append(last_error_code)
    if next_retry_at is not None:
        sets.append("next_retry_at = ?")
        values.append(next_retry_at)
    values.append(client_order_id)
    conn = db_conn()
    try:
        conn.execute(
            f"UPDATE sma9_live_orders SET {', '.join(sets)} "
            "WHERE client_order_id = ?",
            values,
        )
        conn.commit()
    finally:
        conn.close()


def pending_order_rows(limit: int | None = None) -> list:
    """Real orders whose terminal broker status has not been confirmed yet."""
    conn = db_conn()
    try:
        query = (
            "SELECT * FROM sma9_live_orders "
            "WHERE dry_run = 0 AND broker_order_id IS NOT NULL "
            "AND status IN (?, ?) ORDER BY created_at ASC"
        )
        params = [STATUS_NEW, STATUS_ACCEPTED]
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        return [dict(r) for r in conn.execute(query, params).fetchall()]
    finally:
        conn.close()


def tag_lookup_rows(limit: int | None = None) -> list:
    """Ambiguous submits with no broker id, awaiting read-only tag lookup."""
    conn = db_conn()
    try:
        query = (
            "SELECT * FROM sma9_live_orders "
            "WHERE dry_run = 0 AND broker_order_id IS NULL "
            "AND place_status = ? AND status = ? "
            "ORDER BY created_at ASC"
        )
        params = [PLACE_AMBIGUOUS, STATUS_REJECTED]
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        return [dict(r) for r in conn.execute(query, params).fetchall()]
    finally:
        conn.close()


def retry_due_rows(limit: int | None = None) -> list:
    """Broker-confirmed no-fill attempts whose bounded retry is due."""
    conn = db_conn()
    try:
        query = (
            "SELECT * FROM sma9_live_orders "
            "WHERE dry_run = 0 AND place_status = ? "
            "AND (next_retry_at IS NULL OR next_retry_at <= ?) "
            "ORDER BY next_retry_at, created_at ASC"
        )
        params = [PLACE_RETRY_DUE, now_ist().isoformat()]
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        return [dict(r) for r in conn.execute(query, params).fetchall()]
    finally:
        conn.close()


def claim_retry(client_order_id: str) -> bool:
    """Atomically claim one due retry so restarts cannot duplicate it."""
    conn = db_conn()
    try:
        cur = conn.execute(
            """UPDATE sma9_live_orders
               SET place_status = ?, updated_at = ?
               WHERE client_order_id = ? AND place_status = ?""",
            (PLACE_RETRY_ATTEMPTED, now_ist().isoformat(),
             client_order_id, PLACE_RETRY_DUE),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def has_open_attempt(trade_id: str, side: str,
                     exclude_client_id: str | None = None) -> bool:
    """True when another attempt for this trade/side is still actionable.

    ``RETRY_ATTEMPTED`` is excluded on purpose: it is the bookkeeping state of
    an earlier attempt that has already been re-placed, not a live order.
    """
    conn = db_conn()
    try:
        row = conn.execute(
            """SELECT 1 FROM sma9_live_orders
               WHERE trade_id = ? AND side = ?
                 AND client_order_id != ?
                 AND dry_run = 0
                 AND (status IN (?, ?)
                      OR place_status = ?)
               LIMIT 1""",
            (trade_id, side, exclude_client_id or "", STATUS_NEW,
             STATUS_ACCEPTED, PLACE_RETRY_DUE),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def load_open_position_row(trade_id: str, option_type: str) -> dict | None:
    conn = db_conn()
    try:
        row = conn.execute(
            """SELECT * FROM sma9_live_open_positions
               WHERE trade_id = ? AND option_type = ?""",
            (trade_id, option_type),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def record_lifecycle_event(client_order_id: str, trade_id: str, side: str,
                           event: str, detail: str | None = None) -> None:
    conn = db_conn()
    try:
        conn.execute(
            """INSERT INTO sma9_live_lifecycle_events
               (client_order_id, trade_id, side, event, detail, created_at)
               VALUES (?,?,?,?,?,?)""",
            (client_order_id, trade_id, side, event, detail,
             now_ist().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def set_position_lifecycle(option_type: str, trade_id: str, state: str) -> bool:
    """Update the persisted lifecycle only for the matching trade."""
    conn = db_conn()
    try:
        cur = conn.execute(
            """UPDATE sma9_live_open_positions
               SET lifecycle_state = ?, updated_at = ?
               WHERE option_type = ? AND trade_id = ?""",
            (state, now_ist().isoformat(), option_type, trade_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def delete_open_position_by_trade(trade_id: str) -> bool:
    conn = db_conn()
    try:
        cur = conn.execute(
            "DELETE FROM sma9_live_open_positions WHERE trade_id = ?",
            (trade_id,),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def order_record_from_row(row: dict):
    """Rebuild an OrderRecord from a ledger row for status polling."""
    return OrderRecord(
        client_order_id=row["client_order_id"],
        trade_id=row["trade_id"],
        option_type=row["option_type"],
        side=row["side"],
        symbol=row["symbol"],
        token=row["token"],
        quantity=int(row["quantity"]),
        intended_price=float(row["intended_price"]),
        limit_price=float(row["limit_price"]),
        collar_pct=float(row["collar_pct"]),
        reason=row["reason"],
        dry_run=bool(row["dry_run"]),
        status=row["status"],
        broker_order_id=row["broker_order_id"],
        created_at=row["created_at"],
        order_date=row["order_date"],
        attempt_no=int(row.get("attempt_no") or 0),
        retry_of=row.get("retry_of") or row["client_order_id"],
        retry_count=int(row.get("retry_count") or 0),
        place_status=row.get("place_status") or PLACE_SUBMITTED,
        counts_toward_cap=bool(row.get("counts_toward_cap", 1)),
    )


def record_execution_quality(record: OrderRecord, details) -> None:
    """Upsert one leg's signal-vs-fill measurement into the shadow log.

    Idempotent on ``client_order_id``. A later poll that supplies a fill price
    enriches the row; a missing price never erases an already-known fill. Costs
    are estimates only and never modify the recorded trade P&L.
    """
    fill_price = getattr(details, "fill_price", None)
    pts, pct, value = measure_slippage(
        record.side, record.intended_price, fill_price, record.quantity)
    cost = estimated_order_cost(record.side, record.quantity)
    checked_at = now_ist().isoformat()
    conn = db_conn()
    try:
        conn.execute(
            """INSERT INTO sma9_live_execution_quality
               (client_order_id, trade_id, option_type, side, symbol, quantity,
                signal_price, fill_price, slippage_points, slippage_pct,
                slippage_value, cost_estimate, broker_status, raw_status,
                status_message, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(client_order_id) DO UPDATE SET
                 fill_price = COALESCE(
                     sma9_live_execution_quality.fill_price, excluded.fill_price),
                 slippage_points = COALESCE(
                     sma9_live_execution_quality.slippage_points,
                     excluded.slippage_points),
                 slippage_pct = COALESCE(
                     sma9_live_execution_quality.slippage_pct,
                     excluded.slippage_pct),
                 slippage_value = COALESCE(
                     sma9_live_execution_quality.slippage_value,
                     excluded.slippage_value),
                 cost_estimate = excluded.cost_estimate,
                 broker_status = excluded.broker_status,
                 raw_status = excluded.raw_status,
                 status_message = excluded.status_message,
                 updated_at = excluded.updated_at""",
            (
                record.client_order_id, record.trade_id, record.option_type,
                record.side, record.symbol, record.quantity,
                record.intended_price, fill_price, pts, pct, value, cost,
                getattr(details, "status", None),
                getattr(details, "raw_status", None),
                getattr(details, "status_message", None),
                checked_at, checked_at,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def orders_today(order_date: str) -> int:
    conn = db_conn()
    try:
        row = conn.execute(
            """SELECT COUNT(*) n FROM sma9_live_orders
               WHERE order_date = ? AND counts_toward_cap = 1""",
            (order_date,),
        ).fetchone()
        return int(row["n"])
    finally:
        conn.close()


def order_status_for(trade_id: str, side: str) -> dict | None:
    conn = db_conn()
    try:
        row = conn.execute(
            """SELECT client_order_id, side, status, dry_run, broker_order_id,
                      broker_status, status_checked_at, reconcile_attempts,
                      limit_price, order_date
               FROM sma9_live_orders
               WHERE trade_id = ? AND side = ?
               ORDER BY created_at DESC LIMIT 1""",
            (trade_id, side),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Broker data feed (via the read-only gateway shim)
# ---------------------------------------------------------------------------
# --- minimum premium gate (ATM first, then ITM in fixed steps) -----------
# New entries require option premium strictly above SMA9_MIN_PREMIUM (default
# 120).  If ATM premium is unavailable or <= that floor, walk ITM in
# SMA9_STRIKE_STEP increments (default 50), CE downward and PE upward, up to
# SMA9_ITM_MAX_STEPS strikes (default 8).  Exits are never gated.
MIN_PREMIUM = float(os.environ.get("SMA9_MIN_PREMIUM", "120"))
STRIKE_STEP = float(os.environ.get("SMA9_STRIKE_STEP", "50"))
ITM_MAX_STEPS = max(1, int(os.environ.get("SMA9_ITM_MAX_STEPS", "8")))


def _itm_strikes(atm_strike: float, option_type: str) -> list:
    """ATM-adjacent ITM strikes, nearest first (CE lower, PE higher)."""
    direction = -1.0 if option_type == "CE" else 1.0
    return [round(float(atm_strike) + direction * STRIKE_STEP * i, 2)
            for i in range(1, ITM_MAX_STEPS + 1)]


def _quote_ltp(quotes: dict, symbol: str):
    """Positive LTP from a quote batch, or None when unavailable."""
    try:
        price = float(quotes[symbol]["last_price"])
    except (KeyError, TypeError, ValueError):
        return None
    return price if price > 0 else None


class KiteFeed:
    def __init__(self):
        from kiteconnect import KiteConnect

        # The root-owned broker gateway holds the real credentials. The shim
        # ignores these placeholder values, so this service never reads or
        # handles any key/token file.
        self.kite = KiteConnect(api_key="gateway")
        self.kite.set_access_token("gateway")
        self._instruments = []
        self._instruments_date = None
        self._candles = {}  # token -> (rows, fetched_at, last_start)

    # -- instruments -----------------------------------------------------
    def refresh_instruments(self) -> None:
        today = now_ist().date()
        if self._instruments_date == today and self._instruments:
            return
        instruments = self.kite.instruments("NFO")
        self._instruments = [
            i for i in instruments
            if i.get("name") == "NIFTY"
            and i.get("instrument_type") in ("CE", "PE")
            and i.get("segment") == "NFO-OPT"
        ]
        self._instruments_date = today
        logger.info("Loaded %d NIFTY option instruments", len(self._instruments))

    def nearest_expiry(self) -> date:
        self.refresh_instruments()
        today = now_ist().date()
        expiries = sorted({i["expiry"] for i in self._instruments
                           if i["expiry"] >= today})
        if not expiries:
            raise RuntimeError("No NIFTY option expiry available")
        return expiries[0]

    def find_contract(self, strike: float, expiry: date, option_type: str):
        self.refresh_instruments()
        matches = [
            i for i in self._instruments
            if i["strike"] == float(strike)
            and i["expiry"] == expiry
            and i["instrument_type"] == option_type
        ]
        if not matches:
            return None
        # Prefer the nearest expiry / first deterministic match.
        matches.sort(key=lambda i: (i["expiry"], i["instrument_token"]))
        return matches[0]

    # -- quotes ----------------------------------------------------------
    def quote(self, symbols):
        return self.kite.quote(symbols)

    # -- candles ---------------------------------------------------------
    def _fetch_candles(self, token: int):
        now = now_ist()
        start = now - timedelta(days=45)
        start = start.replace(hour=9, minute=15, second=0, microsecond=0)
        raw = self.kite.historical_data(token, start, now, "5minute")
        rows = normalize_candles([
            {
                "start": r["date"].astimezone(IST) if hasattr(r["date"], "astimezone") else r["date"],
                "open": r["open"], "high": r["high"], "low": r["low"],
                "close": r["close"], "volume": r.get("volume", 0),
            }
            for r in raw
        ])
        last_start = rows[-1]["start"] if rows else None
        self._candles[token] = (rows, now, last_start)
        return rows

    def candles(self, token: int, force: bool = False):
        now = now_ist()
        cached = self._candles.get(token)
        if cached:
            rows, fetched_at, last_start = cached
            age = (now - fetched_at).total_seconds()
            current_start = floor_5m(now)
            # One fetch per new candle; small 8s backoff around the boundary
            # prevents hammering the API if the new candle is not published yet.
            if not force and age < 8:
                return rows
            if not force and last_start == current_start and age < 90:
                return rows
        return self._fetch_candles(token)

    def candle_at(self, token: int, candle_start: datetime, retries: int = 6):
        """Return the completed candle whose start matches candle_start.

        At a 5-minute boundary the exchange may take a few seconds to publish
        the just-completed candle, so retry briefly.  We only ever return the
        exact entry candle; a later candle is never substituted.
        """
        if token is None:
            return None
        target = candle_start.astimezone(IST)
        for attempt in range(retries):
            try:
                rows = self._fetch_candles(token)
            except Exception:
                rows = []
            for r in rows:
                if r["start"] == target:
                    return r
            if attempt < retries - 1:
                time.sleep(1.0)
        return None


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------
class Sma9LiveScanner:
    def __init__(self, feed: KiteFeed):
        self.feed = feed
        self.states = {"CE": OptionStateMachine("CE"), "PE": OptionStateMachine("PE")}
        self.started_at = now_ist().isoformat()
        self.last_scan_at = None
        self.actual_interval_seconds = None
        self.contracts = {"CE": None, "PE": None}
        self.atm_strike = None
        self.expiry = None
        self.spot = None
        self.spot_source = None
        self.quote_unavailable = False
        self.last_error = None
        self.last_candle_start = None
        self.last_closed_spot = None
        self.last_closed_atm_strike = None
        self.last_closed_candle_start = None
        self.last_closed_ce_close = None
        self.last_closed_pe_close = None
        self.last_closed_spot_source = None
        self.last_order_block = None
        self.last_reconcile = {
            "enabled": RECONCILE_ENABLED, "checked": 0, "filled": 0,
            "rejected": 0, "pending": 0, "errors": 0, "quality_errors": 0,
            "at": None,
        }
        self.last_tag_lookup = {
            "enabled": RECONCILE_ENABLED, "checked": 0, "resolved": 0,
            "pending": 0, "retry_scheduled": 0, "manual": 0, "errors": 0,
            "at": None,
        }
        self.last_retry = {
            "enabled": RETRY_ENABLED, "checked": 0, "submitted": 0,
            "rescheduled": 0, "exhausted": 0, "suppressed": 0,
            "errors": 0, "at": None,
        }
        # Previous poll's LTP per leg; used as the pre-trade BUY collar
        # reference for MARKET orders.
        self._last_ltp: dict[str, float] = {}

    # -- trade lifecycle / broker reconciliation -------------------------
    def _set_lifecycle(self, option_type: str, trade_id: str, state: str) -> None:
        set_position_lifecycle(option_type, trade_id, state)
        pos = self.states[option_type].position
        if pos is not None and pos.trade_id == trade_id:
            pos.lifecycle_state = state

    def _clear_position(self, option_type: str, trade_id: str) -> None:
        delete_open_position_by_trade(trade_id)
        pos = self.states[option_type].position
        if pos is not None and pos.trade_id == trade_id:
            self.states[option_type].position = None

    def _confirm_exit(self, option_type: str, trade_id: str, price: float,
                      reason: str) -> None:
        """Finalise the trade only after the broker confirms the SELL fill."""
        state = self.states[option_type]
        pos = state.position
        if pos is None or pos.trade_id != trade_id:
            stored = load_open_positions().get(option_type)
            if stored is None or stored.trade_id != trade_id:
                # Already finalised (e.g. two reconciliation workers); make
                # sure the open-position row cannot linger.
                delete_open_position_by_trade(trade_id)
                return
            state.restore(stored)
        symbol = pos.tradingsymbol
        trade = state.close(now_ist(), price, reason or "EXIT_CONFIRMED")
        if trade is not None:
            save_trade(trade)
            logger.info(
                "EXIT CONFIRMED %s %s trade=%s price=%.2f reason=%s",
                option_type, symbol, trade_id, price, reason)

    @staticmethod
    def _row_age_seconds(row: dict) -> float:
        try:
            created = datetime.fromisoformat(str(row.get("created_at") or ""))
        except (TypeError, ValueError):
            return 0.0
        if created.tzinfo is None:
            created = created.replace(tzinfo=IST)
        return max(0.0, (now_ist() - created).total_seconds())

    def _retry_decision(self, row: dict, status: str) -> tuple[bool, str]:
        """Return whether a terminal no-fill outcome may be retried."""
        if status not in FAILED_STATUSES:
            return False, "NOT_TERMINAL_FAILURE"
        if not RETRY_ENABLED or RETRY_MAX_ATTEMPTS <= 0:
            return False, "RETRY_DISABLED"
        if row.get("side") not in RETRY_SIDES:
            return False, "SIDE_NOT_ALLOWED"
        try:
            filled = float(row.get("filled_quantity") or 0)
        except (TypeError, ValueError):
            filled = 0.0
        if filled > 0:
            return False, "PARTIAL_FILL"
        if int(row.get("retry_count") or 0) >= RETRY_MAX_ATTEMPTS:
            return False, "MAX_ATTEMPTS"
        if self._row_age_seconds(row) > RETRY_MAX_AGE_SEC:
            return False, "SIGNAL_TOO_OLD"
        return True, "OK"

    def _schedule_retry(self, row: dict, status: str, reason: str) -> None:
        client_id = row["client_order_id"]
        next_at = (
            now_ist() + timedelta(seconds=RETRY_BASE_DELAY_SEC)
        ).isoformat()
        update_order_status(
            client_id, status,
            broker_status=row.get("broker_status") or status,
            place_status=PLACE_RETRY_DUE, next_retry_at=next_at,
            last_error_code=reason,
        )
        record_lifecycle_event(
            client_id, row["trade_id"], row["side"], "RETRY_SCHEDULED", reason)
        logger.warning(
            "RETRY SCHEDULED %s %s after %s (%s); next attempt at %s",
            row["side"], row["trade_id"], status, reason, next_at)

    def _apply_terminal_order(self, row: dict, status: str) -> None:
        """Drive the position lifecycle from a broker-terminal order status."""
        trade_id = row["trade_id"]
        side = row["side"]
        option_type = row["option_type"]
        client_id = row["client_order_id"]
        retry_ok, retry_reason = self._retry_decision(row, status)

        if status in FILLED_STATUSES:
            update_order_status(client_id, status, place_status=PLACE_RESOLVED)
        elif not retry_ok:
            place = (PLACE_MANUAL_REQUIRED if retry_reason == "PARTIAL_FILL"
                     else PLACE_DEFINITELY_REJECTED)
            update_order_status(client_id, status, place_status=place,
                                last_error_code=retry_reason)

        if side == BUY:
            if status in FILLED_STATUSES:
                self._set_lifecycle(option_type, trade_id, LIFECYCLE_ACTIVE)
                record_lifecycle_event(
                    client_id, trade_id, side, "BUY_FILL_CONFIRMED", status)
                logger.info(
                    "BUY FILL CONFIRMED %s trade=%s broker_id=%s",
                    trade_id, row["broker_order_id"])
            elif retry_ok:
                # Keep the phantom position so a bounded retry can reuse the
                # original signal/contract data. No SELL is generated while the
                # BUY is unconfirmed.
                self._schedule_retry(row, status, retry_reason)
                self._set_lifecycle(
                    option_type, trade_id, LIFECYCLE_ENTRY_RETRY_PENDING)
            elif retry_reason == "PARTIAL_FILL":
                # A partially filled BUY may represent real holdings. Keep the
                # position for manual verification and never re-place it.
                self._set_lifecycle(
                    option_type, trade_id, LIFECYCLE_ENTRY_PARTIAL)
                record_lifecycle_event(
                    client_id, trade_id, side, "PARTIAL_FILL_MANUAL", status)
                logger.error(
                    "CRITICAL: BUY %s partially filled (%s); manual verification "
                    "required for %s", client_id, status, trade_id)
            else:
                # The BUY never filled and will not be retried: remove the
                # phantom so no SELL can be generated against shares we do not hold.
                self._clear_position(option_type, trade_id)
                record_lifecycle_event(
                    client_id, trade_id, side, "PHANTOM_POSITION_REMOVED", status)
                logger.error(
                    "CRITICAL: BUY %s not filled (%s); removed phantom position %s",
                    client_id, status, trade_id)
            return

        if status in FILLED_STATUSES:
            self._confirm_exit(
                option_type, trade_id, float(row["intended_price"]),
                row["reason"])
            record_lifecycle_event(
                client_id, trade_id, side, "EXIT_FILL_CONFIRMED", status)
        elif retry_ok:
            self._schedule_retry(row, status, retry_reason)
            self._set_lifecycle(
                option_type, trade_id, LIFECYCLE_EXIT_RETRY_PENDING)
        elif retry_reason == "PARTIAL_FILL":
            self._set_lifecycle(option_type, trade_id, LIFECYCLE_EXIT_PARTIAL)
            record_lifecycle_event(
                client_id, trade_id, side, "PARTIAL_FILL_MANUAL", status)
            logger.error(
                "CRITICAL: exit SELL %s %s partially filled (%s); manual "
                "verification required", option_type, trade_id, status)
        else:
            self._set_lifecycle(option_type, trade_id, LIFECYCLE_EXIT_FAILED)
            record_lifecycle_event(
                client_id, trade_id, side, "EXIT_NOT_CONFIRMED", status)
            logger.error(
                "CRITICAL: exit SELL %s %s not confirmed by broker (%s); "
                "real position may still be open", option_type, trade_id, status)

    def _apply_submit_result(self, record: OrderRecord) -> None:
        """Apply the synchronous submit result before broker polling begins."""
        row = {
            "client_order_id": record.client_order_id,
            "trade_id": record.trade_id,
            "side": record.side,
            "option_type": record.option_type,
            "broker_order_id": record.broker_order_id,
            "intended_price": record.intended_price,
            "reason": record.reason,
            "created_at": record.created_at,
            "retry_count": record.retry_count,
            "place_status": record.place_status,
            "filled_quantity": 0,
        }
        if record.status in FILLED_STATUSES | FAILED_STATUSES:
            self._apply_terminal_order(row, record.status)
            return
        state = (LIFECYCLE_PENDING if record.side == BUY
                 else LIFECYCLE_EXIT_PENDING)
        self._set_lifecycle(record.option_type, record.trade_id, state)
        record_lifecycle_event(
            record.client_order_id, record.trade_id, record.side,
            "ORDER_SUBMITTED", f"{record.status}|{record.broker_order_id}")
        logger.info(
            "%s SUBMITTED trade=%s broker_id=%s; awaiting broker fill",
            record.side, record.trade_id, record.broker_order_id)

    def _apply_submit_failure(self, record: OrderRecord, error: str) -> None:
        """Classify a submit failure; ambiguous outcomes go to tag lookup."""
        pre_post = record.place_status == PLACE_PRE_POST_REFUSED
        if pre_post:
            state = (LIFECYCLE_ENTRY_BLOCKED if record.side == BUY
                     else LIFECYCLE_EXIT_BLOCKED)
            place = PLACE_PRE_POST_REFUSED
            event = "SUBMIT_BLOCKED_NO_SEND"
        else:
            state = (LIFECYCLE_ENTRY_UNCONFIRMED if record.side == BUY
                     else LIFECYCLE_EXIT_FAILED)
            place = PLACE_AMBIGUOUS
            event = "SUBMIT_FAILED"
        self._set_lifecycle(record.option_type, record.trade_id, state)
        update_order_status(
            record.client_order_id, record.status, place_status=place,
            last_error_code=("PRE_POST_REFUSED" if pre_post
                             else "SUBMIT_EXCEPTION"),
        )
        record_lifecycle_event(
            record.client_order_id, record.trade_id, record.side, event,
            type(error).__name__ if isinstance(error, BaseException) else "ERROR")
        if pre_post:
            logger.error(
                "CRITICAL: %s submit blocked for %s before any broker call; "
                "no order was sent", record.side, record.trade_id)
        else:
            logger.error(
                "CRITICAL: %s submit failed for %s; outcome at broker unknown, "
                "read-only tag lookup enabled and no blind retry",
                record.side, record.trade_id)

    def reconcile_orders(self) -> dict:
        """Poll broker status for every unfilled real order.

        Read-only at the broker: this method never places, amends or cancels an
        order. It only updates the local ledger and position lifecycle, so a
        gateway failure cannot produce a duplicate order.
        """
        summary = {
            "enabled": RECONCILE_ENABLED, "checked": 0, "filled": 0,
            "rejected": 0, "pending": 0, "errors": 0, "quality_errors": 0,
            "at": now_ist().isoformat(),
        }
        self.last_reconcile = summary
        if not RECONCILE_ENABLED:
            return summary
        rows = pending_order_rows(RECONCILE_BATCH)
        for row in rows:
            summary["checked"] += 1
            client_id = row["client_order_id"]
            attempts = int(row["reconcile_attempts"] or 0) + 1
            record = order_record_from_row(row)
            details = None
            try:
                details_fn = getattr(EXECUTOR, "order_details", None)
                if callable(details_fn):
                    # One gateway poll supplies both status and broker fill.
                    details = details_fn(record)
                    status = details.status
                else:
                    # Fakes/dry-run executors may only expose the string form.
                    status = EXECUTOR.order_status(record)
            except Exception as exc:
                summary["errors"] += 1
                update_order_status(
                    client_id, row["status"], row["broker_order_id"],
                    checked_at=now_ist().isoformat(), attempts=attempts,
                    error=str(exc))
                logger.error(
                    "Reconcile status error for %s: %s", client_id, exc)
                continue
            try:
                record_execution_quality(record, details)
            except Exception as exc:
                # Shadow logging must never block the fill lifecycle.
                summary["quality_errors"] += 1
                logger.error("Execution-quality log failed for %s: %s",
                             client_id, exc)
            filled_qty = getattr(details, "filled_quantity", None)
            if filled_qty is None:
                filled_qty = row.get("filled_quantity")
            if status in PENDING_STATUSES:
                summary["pending"] += 1
                update_order_status(
                    client_id, row["status"], row["broker_order_id"],
                    broker_status=status, checked_at=now_ist().isoformat(),
                    attempts=attempts)
                if attempts == RECONCILE_MAX_ATTEMPTS:
                    record_lifecycle_event(
                        client_id, row["trade_id"], row["side"],
                        "RECONCILE_STALE",
                        f"no terminal status after {attempts} checks")
                    logger.error(
                        "CRITICAL: broker order %s still unresolved after %d "
                        "checks; manual verification required",
                        client_id, attempts)
                continue
            update_order_status(
                client_id, status, row["broker_order_id"],
                broker_status=status, checked_at=now_ist().isoformat(),
                attempts=attempts, filled_quantity=filled_qty)
            if status in FILLED_STATUSES:
                summary["filled"] += 1
            else:
                summary["rejected"] += 1
            terminal_row = dict(row)
            terminal_row["filled_quantity"] = filled_qty
            self._apply_terminal_order(terminal_row, status)
        return summary

    def resolve_unknown_submits(self) -> dict:
        """Stage 1: read-only broker lookup for submits with unknown outcome."""
        summary = {
            "enabled": RECONCILE_ENABLED, "checked": 0, "resolved": 0,
            "pending": 0, "retry_scheduled": 0, "manual": 0, "errors": 0,
            "at": now_ist().isoformat(),
        }
        self.last_tag_lookup = summary
        if not RECONCILE_ENABLED:
            return summary
        for row in tag_lookup_rows(RECONCILE_BATCH):
            summary["checked"] += 1
            client_id = row["client_order_id"]
            record = order_record_from_row(row)
            attempts = int(row.get("tag_lookup_attempts") or 0) + 1
            update_order_status(
                client_id, row["status"],
                tag_lookup_attempts=attempts,
                checked_at=now_ist().isoformat())
            try:
                lookup = EXECUTOR.order_by_tag(record)
            except Exception as exc:
                summary["errors"] += 1
                logger.error("Tag lookup raised for %s: %s", client_id, exc)
                lookup = OrderLookup(error_code="LOOKUP_FAILED")
            if lookup.multiple or lookup.error_code == "MULTIPLE_ORDERS":
                update_order_status(
                    client_id, row["status"], place_status=PLACE_MANUAL_REQUIRED,
                    last_error_code="MULTIPLE_ORDERS")
                record_lifecycle_event(
                    client_id, row["trade_id"], row["side"],
                    "TAG_LOOKUP_MULTIPLE", "multiple broker orders with our tag")
                logger.error(
                    "CRITICAL: multiple broker orders found for %s; "
                    "manual verification required", client_id)
                summary["manual"] += 1
                continue
            if lookup.found and lookup.broker_order_id:
                status = lookup.status or STATUS_NEW
                summary["resolved"] += 1
                update_order_status(
                    client_id, status, lookup.broker_order_id,
                    broker_status=status, place_status=PLACE_RESOLVED,
                    filled_quantity=lookup.filled_quantity,
                    checked_at=now_ist().isoformat())
                record_lifecycle_event(
                    client_id, row["trade_id"], row["side"],
                    "TAG_LOOKUP_RESOLVED", f"{status}|{lookup.broker_order_id}")
                logger.info(
                    "TAG LOOKUP RESOLVED %s broker_id=%s status=%s",
                    client_id, lookup.broker_order_id, status)
                terminal_row = dict(row)
                terminal_row.update({
                    "status": status,
                    "broker_order_id": lookup.broker_order_id,
                    "broker_status": status,
                    "filled_quantity": lookup.filled_quantity,
                })
                if status in PENDING_STATUSES:
                    state = (LIFECYCLE_PENDING if row["side"] == BUY
                             else LIFECYCLE_EXIT_PENDING)
                    self._set_lifecycle(
                        row["option_type"], row["trade_id"], state)
                else:
                    self._apply_terminal_order(terminal_row, status)
                continue
            if attempts < TAG_LOOKUP_MAX_ATTEMPTS:
                summary["pending"] += 1
                logger.info(
                    "TAG LOOKUP pending %s attempt=%d/%d (no broker row yet)",
                    client_id, attempts, TAG_LOOKUP_MAX_ATTEMPTS)
                continue
            if (RETRY_ENABLED and RETRY_AMBIGUOUS
                    and row["side"] in RETRY_SIDES
                    and int(row.get("retry_count") or 0) < RETRY_MAX_ATTEMPTS):
                next_at = (
                    now_ist() + timedelta(seconds=RETRY_BASE_DELAY_SEC)
                ).isoformat()
                update_order_status(
                    client_id, row["status"], place_status=PLACE_RETRY_DUE,
                    next_retry_at=next_at, last_error_code="AMBIGUOUS_NO_FILL")
                self._set_lifecycle(
                    row["option_type"], row["trade_id"],
                    LIFECYCLE_ENTRY_RETRY_PENDING if row["side"] == BUY
                    else LIFECYCLE_EXIT_RETRY_PENDING)
                record_lifecycle_event(
                    client_id, row["trade_id"], row["side"],
                    "TAG_LOOKUP_NO_FILL_RETRY", "AMBIGUOUS_NO_FILL")
                logger.warning(
                    "CRITICAL: tag lookup found no broker order for %s; "
                    "bounded retry scheduled (explicit opt-in)", client_id)
                summary["retry_scheduled"] += 1
            else:
                update_order_status(
                    client_id, row["status"], place_status=PLACE_MANUAL_REQUIRED,
                    last_error_code="AMBIGUOUS_UNRESOLVED")
                record_lifecycle_event(
                    client_id, row["trade_id"], row["side"],
                    "TAG_LOOKUP_UNRESOLVED", "AMBIGUOUS_UNRESOLVED")
                logger.error(
                    "CRITICAL: tag lookup could not resolve %s after %d checks; "
                    "manual verification required", client_id, attempts)
                summary["manual"] += 1
        return summary

    def _finish_retry(self, row: dict, retry_no: int, code: str) -> None:
        client_id = row["client_order_id"]
        update_order_status(
            client_id, row["status"], place_status=PLACE_RETRY_EXHAUSTED,
            retry_count=retry_no, last_error_code=code)
        record_lifecycle_event(
            client_id, row["trade_id"], row["side"], "RETRY_EXHAUSTED", code)
        if row["side"] == BUY:
            self._clear_position(row["option_type"], row["trade_id"])
        else:
            self._set_lifecycle(
                row["option_type"], row["trade_id"], LIFECYCLE_EXIT_FAILED)
        logger.error(
            "CRITICAL: retry %d for %s exhausted (%s); manual verification "
            "required", retry_no, client_id, code)

    def _reschedule_retry(self, row: dict, retry_no: int, code: str) -> None:
        next_at = (
            now_ist() + timedelta(seconds=RETRY_BASE_DELAY_SEC)
        ).isoformat()
        update_order_status(
            row["client_order_id"], row["status"], place_status=PLACE_RETRY_DUE,
            retry_count=retry_no, next_retry_at=next_at, last_error_code=code)
        record_lifecycle_event(
            row["client_order_id"], row["trade_id"], row["side"],
            "RETRY_SCHEDULED", code)

    def process_retries(self) -> dict:
        """Stage 2: bounded re-placement for broker-confirmed no-fill orders."""
        summary = {
            "enabled": RETRY_ENABLED, "checked": 0, "submitted": 0,
            "rescheduled": 0, "exhausted": 0, "suppressed": 0,
            "errors": 0, "at": now_ist().isoformat(),
        }
        self.last_retry = summary
        if not RETRY_ENABLED or RETRY_MAX_ATTEMPTS <= 0:
            return summary
        for row in retry_due_rows(RECONCILE_BATCH):
            client_id = row["client_order_id"]
            if not claim_retry(client_id):
                continue
            summary["checked"] += 1
            retry_no = int(row.get("retry_count") or 0) + 1
            if retry_no > RETRY_MAX_ATTEMPTS:
                self._finish_retry(row, retry_no - 1, "MAX_ATTEMPTS")
                summary["exhausted"] += 1
                continue
            if self._row_age_seconds(row) > RETRY_MAX_AGE_SEC:
                self._finish_retry(row, retry_no, "SIGNAL_TOO_OLD")
                summary["exhausted"] += 1
                continue
            if row["side"] not in RETRY_SIDES:
                self._finish_retry(row, retry_no, "SIDE_NOT_ALLOWED")
                summary["suppressed"] += 1
                continue
            if has_open_attempt(row["trade_id"], row["side"], client_id):
                update_order_status(
                    client_id, row["status"], place_status=PLACE_MANUAL_REQUIRED,
                    last_error_code="DUPLICATE_ATTEMPT")
                record_lifecycle_event(
                    client_id, row["trade_id"], row["side"],
                    "RETRY_SUPPRESSED", "DUPLICATE_ATTEMPT")
                logger.error(
                    "CRITICAL: retry suppressed for %s; another attempt is "
                    "still actionable", client_id)
                summary["suppressed"] += 1
                continue
            pos_row = load_open_position_row(row["trade_id"], row["option_type"])
            if not pos_row:
                self._finish_retry(row, retry_no, "POSITION_MISSING")
                summary["exhausted"] += 1
                continue
            symbol = str(row.get("symbol") or "")
            tradingsymbol = symbol.split(":", 1)[-1] if ":" in symbol else symbol
            pos = SimpleNamespace(
                trade_id=row["trade_id"],
                option_type=row["option_type"],
                tradingsymbol=tradingsymbol or pos_row.get("tradingsymbol"),
                token=row.get("token") or pos_row.get("token"),
                strike=pos_row.get("strike"),
                expiry=pos_row.get("expiry"),
                lifecycle_state=pos_row.get("lifecycle_state"),
            )
            try:
                # No quantity is passed: `_place_order` rechecks the current
                # mStock instrument master lot for every retry attempt.
                result = self._place_order(
                    pos, row["side"], float(row["intended_price"]), row["reason"],
                    tag=f"r{retry_no}",
                    retry_of=row.get("retry_of") or client_id,
                    attempt_no=int(row.get("attempt_no") or 0) + 1,
                    retry_count=retry_no, counts_toward_cap=False)
            except Exception as exc:
                summary["errors"] += 1
                self._finish_retry(row, retry_no, "RETRY_SUBMIT_EXCEPTION")
                logger.error("Retry submit raised for %s: %s", client_id, exc)
                continue
            if result is None:
                code = str(self.last_order_block or "BLOCKED_NO_SEND")
                if retry_no < RETRY_MAX_ATTEMPTS:
                    self._reschedule_retry(row, retry_no, code)
                    summary["rescheduled"] += 1
                else:
                    self._finish_retry(row, retry_no, code)
                    summary["exhausted"] += 1
                continue
            if result.status in FAILED_STATUSES:
                if (result.place_status == PLACE_PRE_POST_REFUSED
                        and retry_no < RETRY_MAX_ATTEMPTS):
                    self._reschedule_retry(row, retry_no, "PRE_POST_REFUSED")
                    summary["rescheduled"] += 1
                else:
                    code = result.place_status or "SUBMIT_FAILED"
                    self._finish_retry(row, retry_no, code)
                    summary["exhausted"] += 1
                continue
            update_order_status(client_id, row["status"],
                                place_status=PLACE_RETRY_ATTEMPTED)
            record_lifecycle_event(
                client_id, row["trade_id"], row["side"], "RETRY_SUBMITTED",
                result.client_order_id)
            logger.info(
                "RETRY SUBMITTED %s attempt=%d new_id=%s awaiting broker fill",
                client_id, retry_no, result.client_order_id)
            summary["submitted"] += 1
        return summary

    def _request_exit(self, state, pos: Position, price: float,
                      reason: str):
        """Submit one SELL and keep the position until the fill is confirmed."""
        if pos.lifecycle_state != LIFECYCLE_ACTIVE:
            return None
        if order_exists(make_client_order_id(pos.trade_id, SELL)):
            logger.info(
                "SELL already recorded for %s; awaiting broker confirmation",
                pos.trade_id)
            return None
        pos.lifecycle_state = LIFECYCLE_EXIT_PENDING
        save_open_position(pos)
        exit_order = self._place_order(pos, SELL, price, reason)
        if exit_order is None or exit_order.status in FAILED_STATUSES:
            logger.error(
                "CRITICAL: exit SELL failed for %s %s; position retained for "
                "manual handling", pos.option_type, pos.tradingsymbol)
        else:
            logger.info(
                "EXIT SUBMITTED %s %s trade=%s price=%.2f reason=%s; "
                "awaiting broker fill", pos.option_type, pos.tradingsymbol,
                pos.trade_id, float(price), reason)
        return exit_order

    # -- order execution -------------------------------------------------
    def _resolve_lot_size(self, pos: Position) -> int:
        """Return the contract quantity from mStock's instrument master.

        ``SMA9_LIVE_LOT_SIZE`` is an optional override for tests/dry runs. The
        deployed service leaves it at 0, so the exact CE/PE contract's lot_size
        is fetched through the read-only gateway. A failed lookup refuses the
        order rather than guessing a real-money quantity.
        """
        if LIMITS.lot_size > 0:
            return LIMITS.lot_size
        try:
            expiry_text = str(pos.expiry or "")[:10]
            expiry = date.fromisoformat(expiry_text) if expiry_text else None
            contract = (
                self.feed.find_contract(float(pos.strike), expiry, pos.option_type)
                if expiry is not None else None
            )
            lot_size = int((contract or {}).get("lot_size") or 0)
            if lot_size > 0:
                return lot_size
        except Exception as exc:
            logger.warning(
                "Could not resolve mStock lot size for %s: %s",
                pos.tradingsymbol, exc)
        raise RuntimeError(
            f"mStock lot size unavailable for {pos.tradingsymbol}; "
            "refusing to place an order with a guessed quantity")

    def _place_order(
        self, pos: Position, side: str, price: float, reason: str, *,
        tag: str = "", quantity: int | None = None, retry_of: str | None = None,
        attempt_no: int = 0, retry_count: int = 0,
        counts_toward_cap: bool = True,
    ) -> OrderRecord | None:
        """Record a guarded, idempotent order and hand it to the executor.

        The deterministic client_order_id makes repeated calls no-ops for one
        attempt. A bounded retry uses an ``rN`` tag and a new id while keeping
        ``retry_of`` pointing at the original order. Real executors need both
        arm flags in addition to the entry gate. Orders are MARKET orders; BUY
        entries are sanity-checked against the previous poll's LTP, while exits
        are never blocked so a real position can always be closed.
        """
        client_order_id = make_client_order_id(pos.trade_id, side, tag)
        if order_exists(client_order_id):
            logger.info("Order %s already recorded; skipping duplicate",
                        client_order_id)
            return None
        if EXECUTOR.name != "dry_run" and not real_orders_armed():
            logger.error(
                "REFUSED real %s order %s: orders are not armed",
                side, pos.trade_id)
            self.last_order_block = "REAL_ORDERS_NOT_ARMED"
            return None
        if side == BUY and price_collar_breached(
                float(price), self._last_ltp.get(pos.option_type),
                LIMITS.collar_pct):
            reference = self._last_ltp.get(pos.option_type) or 0.0
            logger.error(
                "BUY blocked by price collar for %s: ref=%.2f price=%.2f",
                pos.tradingsymbol, reference, float(price))
            self.last_order_block = "PRICE_COLLAR_BREACH"
            return None
        try:
            resolved_qty = (int(quantity) if quantity is not None
                            else self._resolve_lot_size(pos))
        except Exception as exc:
            logger.error("Order blocked for %s: %s", pos.tradingsymbol, exc)
            self.last_order_block = "LOT_SIZE_UNAVAILABLE"
            return None
        try:
            record = OrderRecord(
                client_order_id=client_order_id,
                trade_id=pos.trade_id,
                option_type=pos.option_type,
                side=side,
                symbol=f"NFO:{pos.tradingsymbol}",
                token=pos.token,
                quantity=resolved_qty,
                intended_price=round(float(price), 2),
                limit_price=apply_price_collar(
                    float(price), side, LIMITS.collar_pct),
                collar_pct=LIMITS.collar_pct,
                reason=reason,
                dry_run=EXECUTOR.name == "dry_run",
                order_date=now_ist().date().isoformat(),
                attempt_no=attempt_no,
                retry_of=retry_of or client_order_id,
                retry_count=retry_count,
                place_status=PLACE_SUBMITTED,
                counts_toward_cap=counts_toward_cap,
            )
        except Exception as exc:
            logger.error("Invalid %s order for %s: %s", side, pos.trade_id, exc)
            self.last_order_block = "INVALID_ORDER"
            return None

        if save_order_record(record):
            logger.info("ORDER RECORDED %s %s %s qty=%d ref=%.2f dry_run=%s",
                        record.client_order_id, side, record.symbol,
                        record.quantity, record.limit_price, record.dry_run)
        try:
            result = EXECUTOR.place(record)
        except Exception as exc:
            # A transport failure after the POST may still have reached the
            # exchange. Only pre-network refusals are definite no-sends.
            if record.place_status == PLACE_SUBMITTED:
                record.place_status = (
                    PLACE_PRE_POST_REFUSED
                    if isinstance(exc, (PermissionError, ValueError))
                    else PLACE_AMBIGUOUS
                )
            record.status = STATUS_REJECTED
            code = ("PRE_POST_REFUSED"
                    if record.place_status == PLACE_PRE_POST_REFUSED
                    else "SUBMIT_EXCEPTION")
            update_order_status(
                record.client_order_id, STATUS_REJECTED,
                place_status=record.place_status, last_error_code=code)
            logger.error("Executor submit failed %s: %s",
                         record.client_order_id, exc)
            self.last_order_block = code
            self._apply_submit_failure(record, str(exc))
            return record
        update_order_status(
            result.client_order_id, result.status, result.broker_order_id,
            place_status=result.place_status)
        logger.info("ORDER %s status=%s broker_id=%s", result.client_order_id,
                    result.status, result.broker_order_id)
        self._apply_submit_result(result)
        self.last_order_block = None
        return result

    # -- restart recovery ------------------------------------------------
    def recover_open_positions(self) -> None:
        positions = load_open_positions()
        if not positions:
            return
        now = now_ist()
        for opt, pos in positions.items():
            logger.info(
                "Recovered open %s position %s entry=%.2f candle=%s state=%s",
                opt, pos.trade_id, pos.entry_price,
                pos.entry_candle_start.isoformat(), pos.lifecycle_state)
            state = self.states[opt]
            state.restore(pos)
            if pos.lifecycle_state != LIFECYCLE_ACTIVE:
                # A pending/unconfirmed exit or entry must never be closed a
                # second time by recovery. Broker reconciliation owns it.
                logger.warning(
                    "Recovered %s position %s is %s; awaiting broker "
                    "reconciliation, no recovery SELL", opt, pos.trade_id,
                    pos.lifecycle_state)
                continue
            if now >= pos.entry_candle_end:
                token = pos.token
                if token is None:
                    try:
                        exp = date.fromisoformat(str(pos.expiry))
                        contract = self.feed.find_contract(pos.strike, exp, opt)
                        token = contract["instrument_token"] if contract else None
                    except Exception:
                        token = None
                candle = self.feed.candle_at(token, pos.entry_candle_start)
                close_px = candle["close"] if candle else pos.entry_price
                reason = "SAME_CANDLE_EXIT" if candle else "SAME_CANDLE_EXIT_LTP_FALLBACK"
                self._request_exit(state, pos, close_px, reason)

    # -- contract selection ---------------------------------------------
    # -- minimum premium gate --------------------------------------------
    def _premium_ok(self, option_type: str) -> bool:
        """Only a qualifying premium may open a new position."""
        gate = (getattr(self, "_premium_gate", {}).get(option_type) or {})
        return bool(gate.get("ok"))

    def _apply_min_premium(self, quotes: dict, symbol_for: dict,
                           errors: list) -> None:
        """Choose ATM or the first ITM strike with premium > MIN_PREMIUM.

        If ATM premium is missing or <= the floor, one extra batched quote
        pass covers candidate ITM strikes for both legs.  Open positions keep
        their own contract and exits are never gated.  Without a qualifying
        quote the leg is blocked for new entries.
        """
        gate = {}
        candidates = {}
        symbols = []
        for opt in ("CE", "PE"):
            if self.states[opt].position is not None:
                gate[opt] = {"ok": True, "reason": "OPEN_POSITION"}
                continue
            entry = symbol_for.get(opt)
            if not entry:
                gate[opt] = {"ok": False, "reason": "NO_CONTRACT"}
                continue
            symbol, contract = entry
            atm_ltp = _quote_ltp(quotes, symbol)
            if atm_ltp is None:
                gate[opt] = {"ok": False, "reason": "NO_ATM_QUOTE"}
                logger.warning("PREMIUM GATE %s blocked: ATM quote unavailable", opt)
                continue
            if atm_ltp > MIN_PREMIUM:
                gate[opt] = {
                    "ok": True, "reason": "ATM_PREMIUM_OK", "ltp": atm_ltp,
                }
                continue
            rows = []
            seen = set()
            contract_error = False
            for strike in _itm_strikes(contract["strike"], opt):
                try:
                    candidate = self.feed.find_contract(
                        strike, contract["expiry"], opt)
                except Exception as exc:
                    errors.append(f"min-premium contract error ({opt}): {exc}")
                    logger.error(errors[-1])
                    contract_error = True
                    break
                if not candidate:
                    continue
                sym = f"NFO:{candidate['tradingsymbol']}"
                if sym in seen:
                    continue
                seen.add(sym)
                rows.append((sym, candidate))
            if contract_error:
                gate[opt] = {"ok": False, "reason": "ITM_CONTRACT_ERROR"}
                continue
            if not rows:
                gate[opt] = {"ok": False, "reason": "NO_ITM_CONTRACT"}
                logger.warning(
                    "PREMIUM GATE %s blocked: no ITM contracts found", opt)
                continue
            candidates[opt] = rows
            for sym, _ in rows:
                if sym not in symbols:
                    symbols.append(sym)
        if symbols:
            try:
                quotes.update(self.feed.quote(symbols))
            except Exception as exc:
                errors.append(f"min-premium quote error: {exc}")
                logger.error(errors[-1])
        for opt, rows in candidates.items():
            chosen = None
            for sym, candidate in rows:
                price = _quote_ltp(quotes, sym)
                if price is not None and price > MIN_PREMIUM:
                    chosen = (sym, candidate, price)
                    break
            if chosen is None:
                gate[opt] = {"ok": False, "reason": "NO_ITM_PREMIUM"}
                logger.warning(
                    "PREMIUM GATE %s blocked: no ITM strike with LTP > %.2f",
                    opt, MIN_PREMIUM)
                continue
            old = (symbol_for.get(opt) or (None, {}))[1]
            symbol_for[opt] = (chosen[0], chosen[1])
            gate[opt] = {
                "ok": True, "reason": "ITM_PREMIUM_OK",
                "strike": float(chosen[1]["strike"]), "ltp": chosen[2],
            }
            logger.info(
                "PREMIUM GATE %s moved %s -> %s (LTP %.2f > %.2f)",
                opt, (old or {}).get("tradingsymbol"),
                chosen[1].get("tradingsymbol"), chosen[2], MIN_PREMIUM,
            )
        self._premium_gate = gate

    def refresh_contracts(self, spot: float, force: bool = False) -> None:
        atm = float(round(spot / 50) * 50)
        strikes_match = all(
            self.contracts.get(opt)
            and float(self.contracts[opt].get("strike", -1)) == atm
            for opt in ("CE", "PE")
        )
        if (not force and self.atm_strike == atm and strikes_match
                and self.expiry is not None
                and self.expiry >= now_ist().date()):
            return
        expiry = self.feed.nearest_expiry()
        self.atm_strike = atm
        self.expiry = expiry
        for opt in ("CE", "PE"):
            self.contracts[opt] = self.feed.find_contract(atm, expiry, opt)
        logger.info("ATM contract set: strike=%s expiry=%s CE=%s PE=%s",
                    atm, expiry,
                    (self.contracts["CE"] or {}).get("tradingsymbol"),
                    (self.contracts["PE"] or {}).get("tradingsymbol"))

    # -- main scan -------------------------------------------------------
    def _apply_closed_market_fallback(self, now) -> bool:
        """Resolve the authoritative last completed spot before contracts.

        Returns True when the effective ATM changed, so callers must force a
        contract re-resolution before building any symbol list.
        """
        if market_is_open(now):
            return False
        self._refresh_last_closed_spot(now, {})
        if self.last_closed_spot is None:
            return False
        current = self.spot
        if current is not None and abs(float(current) - self.last_closed_spot) <= 50:
            return False
        self.spot = self.last_closed_spot
        self.atm_strike = self.last_closed_atm_strike
        self.spot_source = "index_close_fallback"
        return True

    def _apply_quote_unavailable(self, now) -> None:
        """Never publish a stale broker-labelled spot after a quote failure."""
        self.quote_unavailable = True
        if not market_is_open(now) and self.last_closed_spot is not None:
            self.spot = self.last_closed_spot
            self.atm_strike = self.last_closed_atm_strike
            self.spot_source = "index_close_fallback"
        else:
            self.spot = None
            self.atm_strike = None
            self.spot_source = "unavailable"

    def scan(self) -> dict:
        now = now_ist()
        if self.last_scan_at:
            try:
                self.actual_interval_seconds = round(
                    (now - datetime.fromisoformat(self.last_scan_at)).total_seconds(), 2)
            except Exception:
                pass
        self.last_scan_at = now.isoformat()
        errors = []
        self._premium_gate = {}
        allow_entries = entry_window_is_open(now)

        try:
            nifty = self.feed.quote(["NSE:NIFTY 50"])
            self.spot = float(nifty["NSE:NIFTY 50"]["last_price"])
            self.spot_source = "broker_quote"
            self.quote_unavailable = False
            self.last_error = None
        except Exception as exc:
            self.last_error = f"spot/contract error: {exc}"
            logger.error(self.last_error)
            self._apply_quote_unavailable(now)
            return self._status(now, {}, errors=[self.last_error])

        forced_spot = self._apply_closed_market_fallback(now)
        self.refresh_contracts(self.spot, force=self.atm_strike is None or forced_spot)

        current_candle = floor_5m(now)
        self.last_candle_start = current_candle

        # Build one batched quote request for both option tokens.
        symbols = ["NSE:NIFTY 50"]
        symbol_for = {}
        for opt in ("CE", "PE"):
            pos = self.states[opt].position
            contract = None
            if pos is not None and pos.token:
                contract = {"tradingsymbol": pos.tradingsymbol,
                            "instrument_token": pos.token,
                            "strike": pos.strike, "expiry": pos.expiry}
            else:
                contract = self.contracts.get(opt)
            if contract:
                sym = f"NFO:{contract['tradingsymbol']}"
                symbols.append(sym)
                symbol_for[opt] = (sym, contract)

        try:
            quotes = self.feed.quote(symbols) if len(symbols) > 1 else {}
        except Exception as exc:
            quotes = {}
            errors.append(f"option quote error: {exc}")
            logger.error(errors[-1])

        self._apply_min_premium(quotes, symbol_for, errors)
        option_status = {}
        for opt in ("CE", "PE"):
            state = self.states[opt]
            pos = state.position
            sym_contract = symbol_for.get(opt)
            if not sym_contract:
                option_status[opt] = {"error": "contract not found"}
                continue
            sym, contract = sym_contract
            ltp = None
            try:
                ltp = float(quotes[sym]["last_price"])
            except Exception:
                errors.append(f"{opt} LTP unavailable")

            token = int(contract["instrument_token"])
            strike = float(contract["strike"])
            expiry = contract["expiry"]
            if isinstance(expiry, date) and not isinstance(expiry, datetime):
                expiry_str = expiry.isoformat()
            else:
                expiry_str = str(expiry)

            try:
                force_candles = state.needs_exit(now)
                candles = self.feed.candles(token, force=force_candles)
            except Exception as exc:
                errors.append(f"{opt} candle error: {exc}")
                logger.error(errors[-1])
                option_status[opt] = {"error": str(exc)}
                continue

            forming_is_current = bool(candles) and candles[-1]["start"] == current_candle
            if forming_is_current:
                ev = evaluate_option(candles, opt, ltp)
            else:
                # The exchange has not published the current 5-minute candle
                # yet.  Evaluating the previous (already closed) candle as if
                # it were forming could create a zero-duration trade at the
                # boundary, so wait for the real candle.
                ev = Evaluation(
                    option_type=opt, ltp=ltp,
                    reason="waiting for current 5-minute candle")
            entry_made = False

            if (state.position is not None
                    and state.position.lifecycle_state == LIFECYCLE_ACTIVE
                    and now.time() >= EXCHANGE_OPEN):
                prev_hwm, prev_stop = state.position.hwm, state.position.stop
                stop_hit = state.update_trail(ltp)
                # Persist a ratcheted high-water-mark/stop so a restart
                # cannot roll the trailing stop back to a lower level.
                trail_pos = state.position
                if (trail_pos is not None
                        and (trail_pos.hwm != prev_hwm or trail_pos.stop != prev_stop)):
                    save_open_position(trail_pos)
                sl_hit = state.check_stop_loss(ltp)
                if stop_hit is not None:
                    exit_px = round(float(ltp), 2)
                    self._request_exit(state, state.position, exit_px,
                                       "TRAIL_STOP_EXIT")
                    logger.info(
                        "TRAIL EXIT requested %s %s strike=%.2f entry=%.2f "
                        "exit=%.2f (stop=%.2f)",
                        opt, pos.tradingsymbol, pos.strike, pos.entry_price,
                        exit_px, pos.stop)
                elif sl_hit is not None:
                    self._request_exit(state, state.position, sl_hit,
                                       "STOP_LOSS_5PCT")
                    logger.info(
                        "STOP EXIT requested %s %s strike=%s entry=%.2f "
                        "exit=%.2f reason=STOP_LOSS_5PCT",
                        opt, pos.tradingsymbol, pos.strike, pos.entry_price,
                        sl_hit)
            elif allow_entries and forming_is_current and self._premium_ok(opt):
                # Recompute per leg so a CE entry immediately counts against
                # the two-leg limit for the PE leg (the daily cap is off).
                gate_ok, gate_reason = entry_allowed(
                    [p for p in (s.position for s in self.states.values())
                     if p is not None],
                    orders_today(now.date().isoformat()), LIMITS,
                )
                if not gate_ok:
                    self.last_order_block = gate_reason
                    logger.warning("ENTRY BLOCKED for %s: %s", opt, gate_reason)
                else:
                    new_pos = state.try_entry(
                        ev, now, strike, expiry_str, token,
                        contract["tradingsymbol"], market_close_dt(now))
                    if new_pos is not None:
                        # ACTIVE only after the broker confirms the BUY fill.
                        new_pos.lifecycle_state = LIFECYCLE_PENDING
                        save_open_position(new_pos)
                        order = self._place_order(
                            new_pos, BUY, new_pos.entry_price, "SMA9_ENTRY")
                        if order is None:
                            self._set_lifecycle(
                                new_pos.option_type, new_pos.trade_id,
                                LIFECYCLE_ENTRY_UNCONFIRMED)
                        if (order is None or order.status in (
                                STATUS_REJECTED, STATUS_FAILED)):
                            # The submit outcome at the broker is unknown. The
                            # position stays in ENTRY_UNCONFIRMED and no exit
                            # or new entry is generated until it is resolved.
                            self.last_order_block = "ENTRY_UNCONFIRMED"
                            logger.error(
                                "ENTRY UNCONFIRMED for %s %s; awaiting manual "
                                "verification, no automatic retry",
                                opt, new_pos.tradingsymbol)
                        else:
                            entry_made = True
                            self.last_order_block = None
                            logger.info(
                                "ENTRY %s %s strike=%s ltp=%.2f sma9=%.2f A=%s B=%s candle=%s",
                                opt, new_pos.tradingsymbol, strike, new_pos.entry_price,
                                new_pos.sma9, new_pos.condition_a, new_pos.condition_b,
                                new_pos.entry_candle_start.isoformat())

            option_status[opt] = {
                "tradingsymbol": contract["tradingsymbol"],
                "token": token,
                "strike": strike,
                "expiry": expiry_str,
                "ltp": ltp,
                "ltp_source": "broker_quote" if ltp is not None else "unavailable",
                "quote_unavailable": ltp is None,
                "sma9": round(ev.sma9, 2) if ev.sma9 is not None else None,
                "prev_close": ev.prev_close,
                "current_open": ev.current_open,
                "condition_a": ev.condition_a,
                "condition_b": ev.condition_b,
                "qualified": ev.qualified,
                "confirmation": ev.confirmation,
                "signal": ev.signal,
                "ready": ev.ready,
                "forming_is_current": forming_is_current,
                "reason": ev.reason,
                "entry_made": entry_made,
                "lifecycle_state": (
                    state.position.lifecycle_state if state.position else None),
                "position": state.position.as_dict() if state.position else None,
                "buy_order": (
                    order_status_for(state.position.trade_id, BUY)
                    if state.position else None
                ),
                "sell_order": (
                    order_status_for(state.position.trade_id, SELL)
                    if state.position else None
                ),
            }
            if ltp is not None:
                self._last_ltp[opt] = float(ltp)

        self._refresh_last_closed_spot(now, option_status)
        return self._status(now, option_status, errors=errors)

    def _refresh_last_closed_spot(self, now, option_status):
        """Set last completed 5m NIFTY spot from real index candles.

        mStock serves NIFTY 50 index history on NSE token 26000. The previous
        CE/PE parity reconstruction was unreliable because option history can
        contain frozen, zero-volume bars that imply a completely wrong spot.
        The index bar is authoritative; CE/PE closes are cleared because they
        are no longer part of this calculation.
        """
        nifty_index_token = 26000
        try:
            cached = getattr(self, "_last_closed_index_bar", None)
            cached_at = getattr(self, "_last_closed_index_bar_at", None)
            cached_boundary = getattr(self, "_last_closed_index_bar_boundary", None)
            bar_start = floor_5m(now)
            if (cached and cached_at and cached_boundary == bar_start
                    and (now - cached_at).total_seconds() < 300):
                bar = cached
            else:
                start = now - timedelta(days=7)
                start = start.replace(hour=9, minute=15, second=0, microsecond=0)
                raw = self.feed.kite.historical_data(
                    nifty_index_token, start, now, "5minute"
                )
                rows = normalize_candles([
                    {
                        "start": r["date"], "open": r["open"], "high": r["high"],
                        "low": r["low"], "close": r["close"],
                        "volume": r.get("volume", 0),
                    }
                    for r in (raw or [])
                ])
                completed = [r for r in rows if r["start"] < bar_start]
                if not completed:
                    return
                last = completed[-1]
                bar = {"start": last["start"], "close": float(last["close"])}
                self._last_closed_index_bar = bar
                self._last_closed_index_bar_at = now
                self._last_closed_index_bar_boundary = bar_start
            spot = float(bar["close"])
            self.last_closed_spot = round(spot, 2)
            self.last_closed_atm_strike = float(round(spot / 50.0) * 50)
            self.last_closed_candle_start = bar["start"].isoformat()
            self.last_closed_ce_close = None
            self.last_closed_pe_close = None
            self.last_closed_spot_source = "nifty_index_5m_close"
        except Exception:
            pass

    def _status(self, now: datetime, options: dict, errors=None) -> dict:
        today = now.date().isoformat()
        return {
            "scanner_id": STRATEGY_ID,
            "scanner_name": SCANNER_NAME,
            "scanner_version": STRATEGY_VERSION,
            "strategy_type": STRATEGY_TYPE,
            "instrument": INSTRUMENT,
            "timeframe": TIMEFRAME,
            "running": True,
            "market_open": market_is_open(now),
            "started_at": self.started_at,
            "last_scan_at": self.last_scan_at,
            "poll_seconds": POLL_SECONDS,
            "actual_interval_seconds": self.actual_interval_seconds,
            "spot": self.spot,
            "spot_source": (
                getattr(self, "spot_source", None)
                if self.spot is not None else "unavailable"
            ),
            "quote_unavailable": bool(getattr(self, "quote_unavailable", False)),
            "atm_strike": self.atm_strike,
            "premium_gate": getattr(self, "_premium_gate", {}),
            "last_closed_spot": self.last_closed_spot,
            "last_closed_atm_strike": self.last_closed_atm_strike,
            "last_closed_candle_start": self.last_closed_candle_start,
            "last_closed_ce_close": self.last_closed_ce_close,
            "last_closed_pe_close": self.last_closed_pe_close,
            "last_closed_spot_source": self.last_closed_spot_source,
            "bar_source": getattr(getattr(self.feed, "kite", None), "bar_source", "broker_history"),
            "expiry": self.expiry.isoformat() if hasattr(self.expiry, "isoformat") else self.expiry,
            "options": options,
            "today": today_stats(today),
            "execution": {
                "executor": EXECUTOR.name,
                "dry_run": EXECUTOR.name == "dry_run",
                "real_orders_armed": real_orders_armed(),
                "kill_switch_active": kill_switch_active(LIMITS),
                "orders_today": orders_today(today),
                "max_orders_per_day": LIMITS.max_orders_per_day or "UNLIMITED",
                "lot_size": LIMITS.lot_size or None,
                "lot_source": (
                    "mstock_instrument_master" if LIMITS.lot_size == 0
                    else "env_override"),
                "order_type": "MARKET",
                "price_collar_pct": LIMITS.collar_pct,
                "last_block": getattr(self, "last_order_block", None),
                "reconciliation": dict(self.last_reconcile),
                "tag_lookup": dict(getattr(self, "last_tag_lookup", {})),
                "retries": {
                    "enabled": RETRY_ENABLED,
                    "max_attempts": RETRY_MAX_ATTEMPTS,
                    "ambiguous_opt_in": RETRY_AMBIGUOUS,
                    "sides": sorted(RETRY_SIDES),
                    "base_delay_sec": RETRY_BASE_DELAY_SEC,
                    "last": dict(getattr(self, "last_retry", {})),
                },
            },
            "errors": errors or [],
            "last_error": self.last_error,
        }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> int:
    logger.info(
        "SMA9 LIVE service starting (poll=%ss, db=%s, executor=%s, dry_run=%s, "
        "max_orders=%s, lot=%s, collar=%.2f%%, reconcile=%s)",
        POLL_SECONDS, DB_PATH, EXECUTOR.name, EXECUTOR.name == "dry_run",
        LIMITS.max_orders_per_day or "UNLIMITED",
        LIMITS.lot_size or "mstock", LIMITS.collar_pct,
        "on" if RECONCILE_ENABLED else "off",
    )
    logger.info(
        "SMA9 LIVE recovery policy: tag_lookup=%s max_checks=%d retry=%s "
        "max_attempts=%d delay=%ss ambiguous_retry=%s sides=%s",
        "on" if RECONCILE_ENABLED else "off", TAG_LOOKUP_MAX_ATTEMPTS,
        "on" if RETRY_ENABLED else "off", RETRY_MAX_ATTEMPTS,
        RETRY_BASE_DELAY_SEC, "on" if RETRY_AMBIGUOUS else "off",
        ",".join(sorted(RETRY_SIDES)) or "NONE",
    )
    if EXECUTOR.name != "dry_run" and not real_orders_armed():
        logger.error("Real executor selected but orders are NOT armed; failing closed")
        return 2
    init_db()
    try:
        feed = KiteFeed()
        feed.refresh_instruments()
    except Exception as exc:
        logger.error("Failed to initialise Kite feed: %s", exc)
        traceback.print_exc()
        return 1

    scanner = Sma9LiveScanner(feed)
    try:
        scanner.recover_open_positions()
    except Exception as exc:
        logger.error("Open-position recovery failed: %s", exc)
        traceback.print_exc()

    logger.info("SMA9 scanner ready")
    try:
        while True:
            now = now_ist()
            # Broker fill confirmation must keep running even when the market
            # is closed or the day is a holiday: exits from an earlier session
            # may still need to be reconciled.
            try:
                scanner.reconcile_orders()
            except Exception as exc:
                logger.error("Reconciliation pass failed: %s", exc)
                traceback.print_exc()
            try:
                scanner.resolve_unknown_submits()
            except Exception as exc:
                logger.error("Tag lookup pass failed: %s", exc)
                traceback.print_exc()
            try:
                scanner.process_retries()
            except Exception as exc:
                logger.error("Retry pass failed: %s", exc)
                traceback.print_exc()
            try:
                if not is_weekday(now):
                    state = scanner.scan()
                    state["errors"] = list(state.get("errors", [])) + ["weekend"]
                    save_scan_state(state)
                elif now.time() < session_open_time(now):
                    save_scan_state(scanner._status(now, {}, errors=["pre-market"]))
                elif now.time() >= session_close_time(now) and not any(
                        s.position for s in scanner.states.values()):
                    save_scan_state(scanner._status(now, {}, errors=["market closed"]))
                else:
                    state = scanner.scan()
                    save_scan_state(state)
            except Exception as exc:
                scanner.last_error = f"scan loop error: {exc}"
                logger.error(scanner.last_error)
                traceback.print_exc()
                try:
                    save_scan_state(scanner._status(now, {}, errors=[scanner.last_error]))
                except Exception:
                    pass
            sleep_to_next_tick()
    except KeyboardInterrupt:
        logger.info("SMA9 scanner stopping (SIGINT)")
    finally:
        logger.info("SMA9 scanner stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
