#!/usr/bin/env python3
"""SMA9 ATM CE+PE live paper scanner with an ATR-scaled stop - BUY ONLY.

This is a standalone scanner.  It writes only to its own database
(database/sma9_atr.db), its own log, and runs under its own systemd unit.
No existing scanner is read or modified.

Entry (per option, from its own 5-minute candles):
    A) previous completed candle CLOSE > SMA9
    AND
    B) current forming candle OPEN > SMA9
  Entry: paper BUY immediately at the live LTP (no broker order)

Exit:
    1) ATR-scaled initial stop, filled at the ACTUAL live LTP
       distance = clamp(0.70 * premium ATR(14), 5% of entry, 30% of entry)
    2) trailing stop: +5 activate -> breakeven, then peak - 5;
       breakeven lock at +6 -> +2
    3) otherwise hold (no time-based exit)

Polling is exactly every 5 seconds during market hours.  One batched quote
call per poll provides NIFTY spot + both option LTPs; historical candles are
fetched only when a new 5-minute candle appears, never on every poll.

State is persisted in database/sma9_atr.db so a restart with an open position
resumes correctly with its original ATR stop.
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
from zoneinfo import ZoneInfo

BASE = "/opt/tradingai"
CODE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if CODE_ROOT not in sys.path:
    sys.path.insert(0, CODE_ROOT)

from app.sma9_atr_engine import (  # noqa: E402
    ATR_PERIOD,
    CANDLE_MINUTES,
    SMA_PERIOD,
    STOP_K,
    STRATEGY_ID,
    STRATEGY_TYPE,
    STRATEGY_VERSION,
    Evaluation,
    OptionStateMachine,
    Position,
    candle_end,
    compute_stop,
    evaluate_option,
    normalize_candles,
    premium_atr,
)

IST = ZoneInfo("Asia/Kolkata")
DB_PATH = os.environ.get("SMA9_ATR_DB_PATH",
                         os.path.join(BASE, "database", "sma9_atr.db"))
LOG_PATH = os.path.join(BASE, "logs", "live_sma9_atr_scanner.log")

MARKET_OPEN = dtime(9, 15)
MARKET_CLOSE = dtime(15, 30)
ENTRY_START = dtime(9, 20)
ENTRY_END = dtime(15, 15)
# Special trading sessions (e.g. muhurat trading) that fall outside the
# normal weekday 09:15-15:30 window.  Date (ISO) -> (open, close) time.
MUHURAT_SESSIONS = {
    "2026-11-08": (dtime(14, 0), dtime(17, 0)),
}

def session_open_time(dt):
    return MUHURAT_SESSIONS.get(dt.date().isoformat(), (MARKET_OPEN, MARKET_CLOSE))[0]

def session_close_time(dt):
    return MUHURAT_SESSIONS.get(dt.date().isoformat(), (MARKET_OPEN, MARKET_CLOSE))[1]
POLL_SECONDS = 5
INSTRUMENT = "NIFTY"
TIMEFRAME = "5m"
SCANNER_NAME = "SMA9 ATR Stop - ATM Option Strike (BUY ONLY)"
STRATEGY_ID = STRATEGY_ID
STRATEGY_VERSION = STRATEGY_VERSION
STRATEGY_TYPE = STRATEGY_TYPE

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
    return dt.weekday() < 5


def market_is_open(dt: datetime) -> bool:
    if not is_weekday(dt):
        return False
    return session_open_time(dt) <= dt.time() < session_close_time(dt)


def entry_window_is_open(dt):
    """True only inside the 09:20:00-15:14:59 entry window.

    The session is 09:15-15:30, but new paper entries are allowed only from
    09:20 (so the 09:15 candle is never entered) and are blocked at 15:15
    (last entry candle is 15:10).  Exits are not affected.
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
    "entry_candle_end, atr_at_entry, stop_price, stop_k, stop_distance_pct, "
    "stop_source"
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
        CREATE TABLE IF NOT EXISTS sma9_atr_trades (
            trade_id TEXT PRIMARY KEY,
            strategy_id TEXT NOT NULL DEFAULT 'sma9_atr',
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
            exit_reason TEXT NOT NULL DEFAULT 'STOP_LOSS_ATR',
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
            entry_candle_end TEXT,
            atr_at_entry REAL,
            stop_price REAL,
            stop_k REAL,
            stop_distance_pct REAL,
            stop_source TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_sma9_atr_trades_date
            ON sma9_atr_trades(trade_date);
        CREATE INDEX IF NOT EXISTS idx_sma9_atr_trades_option
            ON sma9_atr_trades(option_type);
        CREATE INDEX IF NOT EXISTS idx_sma9_atr_trades_status
            ON sma9_atr_trades(status);
        CREATE INDEX IF NOT EXISTS idx_sma9_atr_trades_dataset
            ON sma9_atr_trades(dataset);

        CREATE TABLE IF NOT EXISTS sma9_atr_open_positions (
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
            atr_at_entry REAL,
            stop_price REAL,
            stop_k REAL,
            stop_distance_pct REAL,
            stop_source TEXT,
            hwm REAL,
            trail_stop REAL,
            be_locked INTEGER,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sma9_atr_scan_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()


def save_trade(trade: dict) -> None:
    cols = TRADE_COLUMNS.split(",")
    cols = [c.strip() for c in cols]
    placeholders = ",".join("?" for _ in cols)
    conn = db_conn()
    try:
        conn.execute(
            f"INSERT OR REPLACE INTO sma9_atr_trades ({','.join(cols)}) VALUES ({placeholders})",
            tuple(trade.get(c) for c in cols),
        )
        conn.commit()
    finally:
        conn.close()


def save_open_position(pos: Position) -> None:
    conn = db_conn()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO sma9_atr_open_positions
               (option_type, trade_id, strike, expiry, token, tradingsymbol,
                entry_timestamp, entry_candle_start, entry_candle_end,
                entry_price, sma9, prev_close, current_open, condition_a,
                condition_b, ltp_at_entry, atr_at_entry, stop_price, stop_k,
                stop_distance_pct, stop_source, hwm, trail_stop, be_locked,
                updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                pos.option_type, pos.trade_id, pos.strike, pos.expiry, pos.token,
                pos.tradingsymbol, pos.entry_timestamp.isoformat(),
                pos.entry_candle_start.isoformat(), pos.entry_candle_end.isoformat(),
                pos.entry_price, pos.sma9, pos.prev_close, pos.current_open,
                1 if pos.condition_a else 0, 1 if pos.condition_b else 0,
                pos.ltp_at_entry, pos.atr_at_entry, pos.stop_price, pos.stop_k,
                pos.stop_distance_pct, pos.stop_source, pos.hwm, pos.stop,
                1 if pos.be_locked else 0, now_ist().isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def delete_open_position(option_type: str) -> None:
    conn = db_conn()
    try:
        conn.execute("DELETE FROM sma9_atr_open_positions WHERE option_type = ?",
                     (option_type,))
        conn.commit()
    finally:
        conn.close()


def load_open_positions() -> dict:
    conn = db_conn()
    try:
        rows = conn.execute("SELECT * FROM sma9_atr_open_positions").fetchall()
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
            atr_at_entry=d.get("atr_at_entry"),
            stop_price=d.get("stop_price"),
            stop_k=d.get("stop_k"),
            stop_distance_pct=d.get("stop_distance_pct"),
            stop_source=d.get("stop_source"),
            hwm=d.get("hwm") if d.get("hwm") is not None else d["entry_price"],
            stop=d.get("trail_stop"),
            be_locked=bool(d.get("be_locked")),
        )
    return result


def save_scan_state(state: dict) -> None:
    conn = db_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO sma9_atr_scan_state (key, value, updated_at) VALUES (?,?,?)",
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
                      COALESCE(SUM(CASE WHEN pnl_points < 0 THEN 1 ELSE 0 END),0) losses,
                      COALESCE(SUM(CASE WHEN exit_reason = 'STOP_LOSS_ATR' THEN 1 ELSE 0 END),0) stops
               FROM sma9_atr_trades WHERE dataset='LIVE' AND trade_date=?""",
            (today,),
        ).fetchone()
    finally:
        conn.close()
    return {
        "trades": row["n"],
        "pnl_points": round(row["pnl"], 2),
        "wins": row["wins"],
        "losses": row["losses"],
        "stop_outs": row["stops"],
    }


# ---------------------------------------------------------------------------
# Zerodha data feed
# ---------------------------------------------------------------------------
def load_zerodha_credentials() -> dict:
    env_path = os.path.join(BASE, ".env.zerodha")
    creds = {}
    with open(env_path, "r") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                creds[k.strip()] = v.strip()
    return creds


class KiteFeed:
    def __init__(self):
        from kiteconnect import KiteConnect

        creds = load_zerodha_credentials()
        self.kite = KiteConnect(api_key=creds["KITE_API_KEY"])
        self.kite.set_access_token(creds["KITE_ACCESS_TOKEN"])
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
class Sma9AtrLiveScanner:
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
        self.last_error = None
        self.last_candle_start = None

    # -- restart recovery ------------------------------------------------
    def recover_open_positions(self) -> None:
        positions = load_open_positions()
        if not positions:
            return
        now = now_ist()
        for opt, pos in positions.items():
            state = self.states[opt]
            state.restore(pos)
            if now.date() <= pos.entry_candle_start.date():
                # Same session: keep the position and let the live loop manage
                # the ATR stop / trail exactly as if there had been no restart.
                logger.info(
                    "Resumed open %s position %s entry=%.2f stop=%.2f hwm=%.2f "
                    "atr=%s (stop/trail continue live)",
                    opt, pos.trade_id, pos.entry_price,
                    pos.stop_price if pos.stop_price is not None else -1.0,
                    pos.hwm, pos.atr_at_entry)
                continue
            # Stale position from an earlier session: never carry an option
            # position across days.  Close at the current LTP.
            exit_px = pos.entry_price
            try:
                sym = f"NFO:{pos.tradingsymbol}"
                exit_px = float(self.feed.quote([sym])[sym]["last_price"])
            except Exception:
                pass
            trade = state.close(now, exit_px, "STALE_RECOVERY_EXIT")
            save_trade(trade)
            delete_open_position(opt)
            logger.info("Closed stale %s position %s at %.2f pnl=%.2f",
                        opt, pos.trade_id, exit_px, trade["pnl_points"])

    # -- contract selection ---------------------------------------------
    def refresh_contracts(self, spot: float, force: bool = False) -> None:
        atm = float(round(spot / 50) * 50)
        if (not force and self.atm_strike == atm and self.expiry is not None
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
        allow_entries = entry_window_is_open(now)

        try:
            nifty = self.feed.quote(["NSE:NIFTY 50"])
            self.spot = float(nifty["NSE:NIFTY 50"]["last_price"])
            self.refresh_contracts(self.spot, force=self.atm_strike is None)
        except Exception as exc:
            self.last_error = f"spot/contract error: {exc}"
            logger.error(self.last_error)
            return self._status(now, {}, errors=[self.last_error])

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

            atr = premium_atr(candles, ATR_PERIOD)
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

            if state.position is not None:
                stop_hit = state.update_trail(ltp)
                sl_hit = state.check_stop_loss(ltp)
                if stop_hit is not None:
                    exit_px = round(float(ltp), 2)
                    trade = state.close(now, exit_px, "TRAIL_STOP_EXIT")
                    save_trade(trade)
                    delete_open_position(opt)
                    logger.info(
                        "TRAIL EXIT %s %s strike=%.2f entry=%.2f exit=%.2f pnl=%.2f (stop=%.2f)",
                        opt, pos.tradingsymbol, pos.strike, pos.entry_price,
                        exit_px, trade["pnl_points"], pos.stop)
                elif sl_hit is not None:
                    trade = state.close(now, sl_hit, "STOP_LOSS_ATR")
                    save_trade(trade)
                    delete_open_position(opt)
                    logger.info(
                        "STOP EXIT %s %s strike=%s entry=%.2f exit=%.2f pnl=%.2f "
                        "stop_price=%.2f atr=%s reason=STOP_LOSS_ATR",
                        opt, pos.tradingsymbol, pos.strike, pos.entry_price,
                        sl_hit, trade["pnl_points"],
                        pos.stop_price if pos.stop_price is not None else -1.0,
                        pos.atr_at_entry)
            elif allow_entries and forming_is_current:
                new_pos = state.try_entry(
                    ev, now, strike, expiry_str, token,
                    contract["tradingsymbol"], market_close_dt(now), atr=atr)
                if new_pos is not None:
                    save_open_position(new_pos)
                    entry_made = True
                    logger.info(
                        "ENTRY %s %s strike=%s ltp=%.2f sma9=%.2f A=%s B=%s candle=%s "
                        "atr=%s stop=%.2f dist_pct=%.2f%% src=%s",
                        opt, new_pos.tradingsymbol, strike, new_pos.entry_price,
                        new_pos.sma9, new_pos.condition_a, new_pos.condition_b,
                        new_pos.entry_candle_start.isoformat(),
                        new_pos.atr_at_entry, new_pos.stop_price,
                        (new_pos.stop_distance_pct or 0) * 100,
                        new_pos.stop_source)

            option_status[opt] = {
                "tradingsymbol": contract["tradingsymbol"],
                "token": token,
                "strike": strike,
                "expiry": expiry_str,
                "ltp": ltp,
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
                "atr": round(atr, 2) if atr is not None else None,
                "stop_preview": compute_stop(ltp, atr)[0] if ltp else None,
                "position": state.position.as_dict() if state.position else None,
            }

        return self._status(now, option_status, errors=errors)

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
            "atm_strike": self.atm_strike,
            "expiry": self.expiry.isoformat() if hasattr(self.expiry, "isoformat") else self.expiry,
            "options": options,
            "today": today_stats(today),
            "errors": errors or [],
            "last_error": self.last_error,
        }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> int:
    logger.info("SMA9 ATR-STOP scanner starting (poll=%ss, db=%s, k=%.2f)",
                POLL_SECONDS, DB_PATH, STOP_K)
    init_db()
    try:
        feed = KiteFeed()
        feed.refresh_instruments()
    except Exception as exc:
        logger.error("Failed to initialise Kite feed: %s", exc)
        traceback.print_exc()
        return 1

    scanner = Sma9AtrLiveScanner(feed)
    try:
        scanner.recover_open_positions()
    except Exception as exc:
        logger.error("Open-position recovery failed: %s", exc)
        traceback.print_exc()

    logger.info("SMA9 ATR scanner ready")
    try:
        while True:
            now = now_ist()
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
        logger.info("SMA9 ATR scanner stopping (SIGINT)")
    finally:
        logger.info("SMA9 ATR scanner stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
