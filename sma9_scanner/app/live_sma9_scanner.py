#!/usr/bin/env python3
"""SMA9 ATM CE+PE live paper scanner - BUY ONLY.

Both CE and PE use the same long-only rule set:
  Qualification (per option, from its own 5-minute candles):
    A) previous completed candle CLOSE > SMA9
       OR
    B) current forming candle OPEN > SMA9
  Confirmation:
    live option LTP > SMA9
  Entry:
    paper BUY immediately (no broker order)
  Exit:
    at the CLOSE of the entry 5-minute candle

Polling is exactly every 5 seconds during market hours.  One batched quote
call per poll provides NIFTY spot + both option LTPs; historical candles are
fetched only when a new 5-minute candle appears (or at exit), never on every
poll.

State is persisted in database/sma9.db so a restart with an open position
resumes correctly and still exits at the original entry candle's close.
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

from app.sma9_engine import (  # noqa: E402
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

IST = ZoneInfo("Asia/Kolkata")
DB_PATH = os.environ.get("SMA9_DB_PATH", os.path.join(BASE, "database", "sma9.db"))
LOG_PATH = os.path.join(BASE, "logs", "live_sma9_scanner.log")

MARKET_OPEN = dtime(9, 15)
MARKET_CLOSE = dtime(15, 30)
POLL_SECONDS = 5
INSTRUMENT = "NIFTY"
TIMEFRAME = "5m"
SCANNER_NAME = "SMA9 Only - ATM Option Strike (BUY ONLY)"
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
    return dt.weekday() < 5


def market_is_open(dt: datetime) -> bool:
    return is_weekday(dt) and MARKET_OPEN <= dt.time() < MARKET_CLOSE


def market_close_dt(dt: datetime) -> datetime:
    return datetime.combine(dt.date(), MARKET_CLOSE, tzinfo=IST)


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
        CREATE TABLE IF NOT EXISTS sma9_trades (
            trade_id TEXT PRIMARY KEY,
            strategy_id TEXT NOT NULL DEFAULT 'sma9_only',
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
        CREATE INDEX IF NOT EXISTS idx_sma9_trades_date ON sma9_trades(trade_date);
        CREATE INDEX IF NOT EXISTS idx_sma9_trades_option ON sma9_trades(option_type);
        CREATE INDEX IF NOT EXISTS idx_sma9_trades_status ON sma9_trades(status);
        CREATE INDEX IF NOT EXISTS idx_sma9_trades_dataset ON sma9_trades(dataset);

        CREATE TABLE IF NOT EXISTS sma9_open_positions (
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
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sma9_scan_state (
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
            f"INSERT OR REPLACE INTO sma9_trades ({','.join(cols)}) VALUES ({placeholders})",
            tuple(trade.get(c) for c in cols),
        )
        conn.commit()
    finally:
        conn.close()


def save_open_position(pos: Position) -> None:
    conn = db_conn()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO sma9_open_positions
               (option_type, trade_id, strike, expiry, token, tradingsymbol,
                entry_timestamp, entry_candle_start, entry_candle_end,
                entry_price, sma9, prev_close, current_open, condition_a,
                condition_b, ltp_at_entry, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                pos.option_type, pos.trade_id, pos.strike, pos.expiry, pos.token,
                pos.tradingsymbol, pos.entry_timestamp.isoformat(),
                pos.entry_candle_start.isoformat(), pos.entry_candle_end.isoformat(),
                pos.entry_price, pos.sma9, pos.prev_close, pos.current_open,
                1 if pos.condition_a else 0, 1 if pos.condition_b else 0,
                pos.ltp_at_entry, now_ist().isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def delete_open_position(option_type: str) -> None:
    conn = db_conn()
    try:
        conn.execute("DELETE FROM sma9_open_positions WHERE option_type = ?",
                     (option_type,))
        conn.commit()
    finally:
        conn.close()


def load_open_positions() -> dict:
    conn = db_conn()
    try:
        rows = conn.execute("SELECT * FROM sma9_open_positions").fetchall()
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
        )
    return result


def save_scan_state(state: dict) -> None:
    conn = db_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO sma9_scan_state (key, value, updated_at) VALUES (?,?,?)",
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
               FROM sma9_trades WHERE dataset='LIVE' AND trade_date=?""",
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
        start = now - timedelta(days=3)
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
        self.last_error = None
        self.last_candle_start = None

    # -- restart recovery ------------------------------------------------
    def recover_open_positions(self) -> None:
        positions = load_open_positions()
        if not positions:
            return
        now = now_ist()
        for opt, pos in positions.items():
            logger.info("Recovered open %s position %s entry=%.2f candle=%s",
                        opt, pos.trade_id, pos.entry_price,
                        pos.entry_candle_start.isoformat())
            state = self.states[opt]
            state.restore(pos)
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
                trade = state.close(pos.entry_candle_end, close_px, reason,
                                    candle_high=candle["high"] if candle else None,
                                    candle_low=candle["low"] if candle else None)
                save_trade(trade)
                delete_open_position(opt)
                logger.info("Recovered %s position closed at %.2f pnl=%.2f",
                            opt, close_px, trade["pnl_points"])

    # -- contract selection ---------------------------------------------
    def refresh_contracts(self, spot: float, force: bool = False) -> None:
        atm = float(round(spot / 50) * 50)
        if not force and self.atm_strike == atm and self.expiry is not None:
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
        allow_entries = market_is_open(now)

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
                if state.needs_exit(now):
                    candle = self.feed.candle_at(token, pos.entry_candle_start)
                    if candle is not None:
                        close_px = candle["close"]
                        reason = "SAME_CANDLE_EXIT"
                    else:
                        # Last-resort same-candle mark; never use a later candle.
                        close_px = ltp if ltp is not None else pos.entry_price
                        reason = "SAME_CANDLE_EXIT_LTP_FALLBACK"
                        errors.append(f"{opt} exit candle unavailable; used LTP")
                    trade = state.close(pos.entry_candle_end, close_px, reason,
                                        candle_high=candle["high"] if candle else None,
                                        candle_low=candle["low"] if candle else None)
                    save_trade(trade)
                    delete_open_position(opt)
                    logger.info(
                        "EXIT %s %s strike=%s entry=%.2f exit=%.2f pnl=%.2f reason=%s",
                        opt, pos.tradingsymbol, pos.strike, pos.entry_price,
                        close_px, trade["pnl_points"], reason)
            elif allow_entries and forming_is_current:
                new_pos = state.try_entry(
                    ev, now, strike, expiry_str, token,
                    contract["tradingsymbol"], market_close_dt(now))
                if new_pos is not None:
                    save_open_position(new_pos)
                    entry_made = True
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
    logger.info("SMA9 BUY-ONLY scanner starting (poll=%ss, db=%s)", POLL_SECONDS, DB_PATH)
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
            try:
                if not is_weekday(now):
                    save_scan_state(scanner._status(now, {}, errors=["weekend"]))
                elif now.time() < MARKET_OPEN:
                    save_scan_state(scanner._status(now, {}, errors=["pre-market"]))
                elif now.time() >= MARKET_CLOSE and not any(
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
