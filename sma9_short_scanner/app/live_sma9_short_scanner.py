#!/usr/bin/env python3
"""SMA9 SHORT paper scanner: NIFTY ATM+200 CE / ATM-200 PE.

Paper/shadow only. No broker orders are placed.

Each leg is evaluated and positioned independently:
  CE contract = nearest ATM strike + 200
  PE contract = nearest ATM strike - 200
  SHORT entry when that leg's live LTP < its SMA9 (9 completed 5m closes)
  Initial stop = entry * 1.10
  Trailing stop = lowest LTP since entry * 1.10, ratcheted down only
  Any open short is closed flat at 15:20 IST (EOD_15_20_FLAT)
  Both CE and PE may be open at the same time.

State is persisted in database/sma9_short.db so restarts restore stops.
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

from app.sma9_short_engine import (  # noqa: E402
    CANDLE_MINUTES,
    EOD_EXIT_REASON,
    EOD_EXIT_TIME,
    SMA_PERIOD,
    STRATEGY_ID,
    STRATEGY_TYPE,
    STRATEGY_VERSION,
    STRIKE_OFFSETS,
    Evaluation,
    OptionStateMachine,
    Position,
    candle_end,
    eod_bar_open,
    evaluate_option,
    normalize_candles,
)

IST = ZoneInfo("Asia/Kolkata")
DB_PATH = os.environ.get(
    "SMA9_SHORT_DB_PATH", os.path.join(BASE, "database", "sma9_short.db")
)
LOG_PATH = os.path.join(BASE, "logs", "live_sma9_short_scanner.log")

MARKET_OPEN = dtime(9, 0)
MARKET_CLOSE = dtime(15, 30)
EXCHANGE_OPEN = dtime(9, 15)
ENTRY_START = dtime(9, 20)
ENTRY_END = dtime(15, 15)
POLL_SECONDS = 5
INSTRUMENT = "NIFTY"
TIMEFRAME = "5m"
SCANNER_NAME = "SMA9 SHORT - ATM+200 CE / ATM-200 PE (PAPER)"

NSE_HOLIDAYS_2026 = frozenset({
    "2026-01-26", "2026-03-03", "2026-03-26", "2026-03-31", "2026-04-03",
    "2026-04-14", "2026-05-01", "2026-05-28", "2026-06-26", "2026-09-14",
    "2026-10-02", "2026-10-20", "2026-11-10", "2026-11-24", "2026-12-25",
})
MUHURAT_SESSIONS = {
    "2026-11-08": (dtime(14, 0), dtime(17, 0)),
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


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


def session_open_time(dt):
    return MUHURAT_SESSIONS.get(dt.date().isoformat(), (MARKET_OPEN, MARKET_CLOSE))[0]


def session_close_time(dt):
    return MUHURAT_SESSIONS.get(dt.date().isoformat(), (MARKET_OPEN, MARKET_CLOSE))[1]


def market_is_open(dt: datetime) -> bool:
    if not is_weekday(dt):
        return False
    return session_open_time(dt) <= dt.time() < session_close_time(dt)


def entry_window_is_open(dt) -> bool:
    if not market_is_open(dt):
        return False
    return ENTRY_START <= dt.time() < ENTRY_END


def market_close_dt(dt: datetime) -> datetime:
    return datetime.combine(dt.date(), session_close_time(dt), tzinfo=IST)


def eod_exit_time(dt: datetime) -> dtime:
    """Daily flat cutoff. Muhurat sessions flatten at their special close."""
    if dt.date().isoformat() in MUHURAT_SESSIONS:
        return session_close_time(dt)
    return EOD_EXIT_TIME


def eod_exit_dt(dt: datetime) -> datetime:
    return datetime.combine(dt.date(), eod_exit_time(dt), tzinfo=IST)


def eod_exit_due(dt: datetime) -> bool:
    return dt >= eod_exit_dt(dt)


def eod_exit_price(candles, ltp, dt: datetime):
    """Fill at the current LTP, falling back to the 15:20 candle open."""
    if ltp is not None:
        return round(float(ltp), 2)
    return eod_bar_open(candles, eod_exit_dt(dt))


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
    "prev_close, condition_a, condition_b, ltp_at_entry, lowest_ltp, "
    "initial_stop, final_stop, entry_candle_start, entry_candle_end"
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
        CREATE TABLE IF NOT EXISTS sma9_short_trades (
            trade_id TEXT PRIMARY KEY,
            strategy_id TEXT NOT NULL DEFAULT 'sma9_short',
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
            exit_reason TEXT NOT NULL DEFAULT 'STOP_LOSS_10PCT',
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
            lowest_ltp REAL,
            initial_stop REAL,
            final_stop REAL,
            entry_candle_start TEXT,
            entry_candle_end TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_sma9_short_trades_date
            ON sma9_short_trades(trade_date);
        CREATE INDEX IF NOT EXISTS idx_sma9_short_trades_option
            ON sma9_short_trades(option_type);
        CREATE INDEX IF NOT EXISTS idx_sma9_short_trades_dataset
            ON sma9_short_trades(dataset);

        CREATE TABLE IF NOT EXISTS sma9_short_open_positions (
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
            lowest_ltp REAL NOT NULL,
            initial_stop REAL NOT NULL,
            stop REAL NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sma9_short_scan_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()


def save_trade(trade: dict) -> None:
    cols = [c.strip() for c in TRADE_COLUMNS.split(",")]
    placeholders = ",".join("?" for _ in cols)
    conn = db_conn()
    try:
        conn.execute(
            f"INSERT OR REPLACE INTO sma9_short_trades "
            f"({','.join(cols)}) VALUES ({placeholders})",
            tuple(trade.get(c) for c in cols),
        )
        conn.execute(
            "DELETE FROM sma9_short_open_positions WHERE option_type = ?",
            (trade.get("option_type"),),
        )
        conn.commit()
    finally:
        conn.close()


def save_open_position(pos: Position) -> None:
    conn = db_conn()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO sma9_short_open_positions
               (option_type, trade_id, strike, expiry, token, tradingsymbol,
                entry_timestamp, entry_candle_start, entry_candle_end,
                entry_price, sma9, prev_close, current_open, condition_a,
                condition_b, ltp_at_entry, lowest_ltp, initial_stop, stop,
                updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                pos.option_type, pos.trade_id, pos.strike, pos.expiry, pos.token,
                pos.tradingsymbol, pos.entry_timestamp.isoformat(),
                pos.entry_candle_start.isoformat(), pos.entry_candle_end.isoformat(),
                pos.entry_price, pos.sma9, pos.prev_close, pos.current_open,
                1 if pos.condition_a else 0, 1 if pos.condition_b else 0,
                pos.ltp_at_entry, pos.lowest_ltp, pos.initial_stop, pos.stop,
                now_ist().isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def load_open_positions() -> dict:
    conn = db_conn()
    try:
        rows = conn.execute("SELECT * FROM sma9_short_open_positions").fetchall()
    finally:
        conn.close()
    result = {}
    for r in rows:
        d = dict(r)
        entry_price = float(d["entry_price"])
        initial_stop = float(d.get("initial_stop") or round(entry_price * 1.10, 2))
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
            entry_price=entry_price,
            sma9=d["sma9"],
            prev_close=d["prev_close"],
            current_open=d["current_open"],
            condition_a=bool(d["condition_a"]),
            condition_b=bool(d["condition_b"]),
            ltp_at_entry=d["ltp_at_entry"],
            lowest_ltp=float(d.get("lowest_ltp") or entry_price),
            initial_stop=initial_stop,
            stop=float(d.get("stop") or initial_stop),
        )
    return result


def save_scan_state(state: dict) -> None:
    conn = db_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO sma9_short_scan_state "
            "(key, value, updated_at) VALUES (?,?,?)",
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
               FROM sma9_short_trades
               WHERE dataset='LIVE' AND trade_date=?""",
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
# Read-only market data feed (same gateway facade used by the paper scanners)
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


def _quote_ltp(quotes: dict, symbol: str):
    try:
        price = float(quotes[symbol]["last_price"])
    except (KeyError, TypeError, ValueError):
        return None
    return price if price > 0 else None


class KiteFeed:
    def __init__(self):
        from kiteconnect import KiteConnect

        creds = load_zerodha_credentials()
        self.kite = KiteConnect(api_key=creds["KITE_API_KEY"])
        self.kite.set_access_token(creds["KITE_ACCESS_TOKEN"])
        self._instruments = []
        self._instruments_date = None
        self._candles = {}

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
        matches.sort(key=lambda i: (i["expiry"], i["instrument_token"]))
        return matches[0]

    def quote(self, symbols):
        return self.kite.quote(symbols)

    def _fetch_candles(self, token: int):
        now = now_ist()
        start = now - timedelta(days=45)
        start = start.replace(hour=9, minute=15, second=0, microsecond=0)
        raw = self.kite.historical_data(token, start, now, "5minute")
        rows = normalize_candles([
            {
                "start": (r["date"].astimezone(IST)
                          if hasattr(r["date"], "astimezone") else r["date"]),
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
            if not force and age < 8:
                return rows
            if not force and last_start == current_start and age < 90:
                return rows
        return self._fetch_candles(token)


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------
class Sma9ShortLiveScanner:
    def __init__(self, feed: KiteFeed):
        self.feed = feed
        self.states = {
            "CE": OptionStateMachine("CE"),
            "PE": OptionStateMachine("PE"),
        }
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
        self.last_closed_spot_source = None

    def prime_expiry(self) -> None:
        """Set the nearest expiry from the in-memory master before market open.

        This keeps the pre-market heartbeat useful to the dashboard: it can ask
        /api/live-atm for the correct weekly contracts instead of falling back
        to the last expiry in the instrument master.
        """
        try:
            self.expiry = self.feed.nearest_expiry()
            logger.info("Primed nearest expiry: %s", self.expiry)
        except Exception as exc:
            logger.warning("Could not prime expiry: %s", exc)

    def recover_open_positions(self) -> None:
        """Restore open shorts and their ratcheted stops; never force-close."""
        positions = load_open_positions()
        for opt, pos in positions.items():
            self.states[opt].restore(pos)
            logger.info(
                "Recovered open SHORT %s %s strike=%s entry=%.2f stop=%.2f "
                "lowest=%.2f candle=%s",
                opt, pos.trade_id, pos.strike, pos.entry_price, pos.stop,
                pos.lowest_ltp, pos.entry_candle_start.isoformat(),
            )

    def refresh_contracts(self, spot: float, force: bool = False) -> None:
        atm = float(round(float(spot) / 50.0) * 50)
        targets = {
            opt: round(atm + float(offset), 2)
            for opt, offset in STRIKE_OFFSETS.items()
        }
        strikes_match = all(
            self.contracts.get(opt)
            and float(self.contracts[opt].get("strike", -1)) == targets[opt]
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
            self.contracts[opt] = self.feed.find_contract(targets[opt], expiry, opt)
        logger.info(
            "SHORT contract set: ATM=%s expiry=%s CE=%s (%s) PE=%s (%s)",
            atm, expiry,
            targets["CE"], (self.contracts["CE"] or {}).get("tradingsymbol"),
            targets["PE"], (self.contracts["PE"] or {}).get("tradingsymbol"),
        )

    def _apply_closed_market_fallback(self, now) -> bool:
        if market_is_open(now):
            return False
        self._refresh_last_closed_spot(now)
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
        self.quote_unavailable = True
        if not market_is_open(now) and self.last_closed_spot is not None:
            self.spot = self.last_closed_spot
            self.atm_strike = self.last_closed_atm_strike
            self.spot_source = "index_close_fallback"
        else:
            self.spot = None
            self.atm_strike = None
            self.spot_source = "unavailable"

    def _close_eod(self, opt, state, contract, candles, ltp, now):
        """Flatten one leg at the 15:20 cutoff; return the trade when filled."""
        price = eod_exit_price(candles, ltp, now)
        if price is None:
            logger.error("EOD EXIT %s blocked: no usable LTP or 15:20 bar", opt)
            return None
        trade = state.close(eod_exit_dt(now), price, EOD_EXIT_REASON)
        if trade is None:
            return None
        save_trade(trade)
        logger.info(
            "EOD EXIT %s %s strike=%.2f entry=%.2f exit=%.2f "
            "pnl=%.2f reason=%s",
            opt, contract.get("tradingsymbol"), float(contract.get("strike", 0)),
            trade["entry_price"], price, trade["pnl_points"], EOD_EXIT_REASON,
        )
        return trade

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
            self.spot_source = "broker_quote"
            self.quote_unavailable = False
            self.last_error = None
        except Exception as exc:
            self.last_error = f"spot quote error: {exc}"
            logger.error(self.last_error)
            self._apply_quote_unavailable(now)
            return self._status(now, {}, errors=[self.last_error])

        forced_spot = self._apply_closed_market_fallback(now)
        try:
            self.refresh_contracts(self.spot, force=self.atm_strike is None or forced_spot)
        except Exception as exc:
            self.last_error = f"contract error: {exc}"
            logger.error(self.last_error)
            return self._status(now, {}, errors=[self.last_error])

        current_candle = floor_5m(now)
        self.last_candle_start = current_candle

        symbols = ["NSE:NIFTY 50"]
        symbol_for = {}
        for opt in ("CE", "PE"):
            pos = self.states[opt].position
            if pos is not None and pos.token:
                contract = {
                    "tradingsymbol": pos.tradingsymbol,
                    "instrument_token": pos.token,
                    "strike": pos.strike,
                    "expiry": pos.expiry,
                }
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
            sym_contract = symbol_for.get(opt)
            if not sym_contract:
                option_status[opt] = {"error": "contract not found"}
                continue
            sym, contract = sym_contract
            ltp = _quote_ltp(quotes, sym)
            if ltp is None:
                errors.append(f"{opt} LTP unavailable")

            token = int(contract["instrument_token"])
            strike = float(contract["strike"])
            expiry = contract["expiry"]
            if isinstance(expiry, date) and not isinstance(expiry, datetime):
                expiry_str = expiry.isoformat()
            else:
                expiry_str = str(expiry)

            candle_error = None
            candles = []
            forming_is_current = False
            eod_due = state.position is not None and eod_exit_due(now)
            ev = Evaluation(option_type=opt, ltp=ltp,
                            reason="waiting for current 5-minute candle")
            try:
                candles = self.feed.candles(token, force=eod_due)
                forming_is_current = (
                    bool(candles) and candles[-1]["start"] == current_candle
                )
                if forming_is_current:
                    ev = evaluate_option(candles, opt, ltp)
            except Exception as exc:
                candle_error = str(exc)
                ev.reason = f"candle error: {exc}"
                errors.append(f"{opt} candle error: {exc}")
                logger.error(errors[-1])

            entry_made = False
            exit_reason = None
            exit_price = None
            if state.position is not None and now.time() >= EXCHANGE_OPEN and ltp is not None:
                prev_lowest = state.position.lowest_ltp
                prev_stop = state.position.stop
                state.update_trail(ltp)
                trail_pos = state.position
                if (trail_pos is not None
                        and (trail_pos.lowest_ltp != prev_lowest
                             or trail_pos.stop != prev_stop)):
                    save_open_position(trail_pos)
                sl_hit = state.check_stop_loss(ltp)
                if sl_hit is not None:
                    exit_reason = ("TRAIL_STOP_EXIT" if trail_pos.trailing_active()
                                   else "STOP_LOSS_10PCT")
                    exit_price = sl_hit
                    trade = state.close(now, sl_hit, exit_reason)
                    save_trade(trade)
                    logger.info(
                        "EXIT %s %s strike=%.2f entry=%.2f exit=%.2f "
                        "pnl=%.2f reason=%s stop=%.2f lowest=%.2f",
                        opt, pos.tradingsymbol if pos is not None else contract["tradingsymbol"],
                        strike, trade["entry_price"], sl_hit, trade["pnl_points"],
                        exit_reason, sl_hit, prev_lowest,
                    )

            if state.position is not None and eod_due:
                trade = self._close_eod(opt, state, contract, candles, ltp, now)
                if trade is not None:
                    exit_reason = EOD_EXIT_REASON
                    exit_price = trade["exit_price"]

            if state.position is None and (allow_entries and forming_is_current
                                           and ltp is not None and ev.signal):
                new_pos = state.try_entry(
                    ev, now, strike, expiry_str, token,
                    contract["tradingsymbol"], market_close_dt(now),
                )
                if new_pos is not None:
                    save_open_position(new_pos)
                    entry_made = True
                    logger.info(
                        "ENTRY %s %s strike=%.2f ltp=%.2f sma9=%.2f candle=%s",
                        opt, new_pos.tradingsymbol, strike, new_pos.entry_price,
                        new_pos.sma9, new_pos.entry_candle_start.isoformat(),
                    )

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
                "candle_error": candle_error,
                "entry_made": entry_made,
                "exit_reason": exit_reason,
                "exit_price": exit_price,
                "eod_due": bool(eod_due),
                "position": state.position.as_dict() if state.position else None,
            }

        self._refresh_last_closed_spot(now)
        return self._status(now, option_status, errors=errors)

    def _refresh_last_closed_spot(self, now) -> None:
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
            self.last_closed_spot_source = "nifty_index_5m_close"
        except Exception:
            pass

    def _idle_options(self, reason: str) -> dict:
        """Option shells kept in the heartbeat outside the scan window.

        The dashboard fills live LTP/strike from /api/live-atm. These shells mean
        the page can render the correct contract names immediately instead of
        showing "No data" until the first completed 5-minute candle.
        """
        options = {}
        for opt in ("CE", "PE"):
            pos = self.states[opt].position
            contract = self.contracts.get(opt) or {}
            expiry = contract.get("expiry")
            options[opt] = {
                "tradingsymbol": contract.get("tradingsymbol"),
                "token": contract.get("instrument_token"),
                "strike": contract.get("strike"),
                "expiry": expiry.isoformat() if hasattr(expiry, "isoformat") else expiry,
                "ltp": None,
                "ltp_source": "unavailable",
                "quote_unavailable": True,
                "sma9": None,
                "prev_close": None,
                "current_open": None,
                "condition_a": False,
                "condition_b": False,
                "qualified": False,
                "confirmation": False,
                "signal": False,
                "ready": False,
                "forming_is_current": False,
                "reason": f"{reason}; waiting for first completed 5m candle",
                "candle_error": None,
                "entry_made": False,
                "exit_reason": None,
                "exit_price": None,
                "eod_due": eod_exit_due(now_ist()),
                "position": pos.as_dict() if pos is not None else None,
            }
        return options

    def _idle_status(self, now: datetime, reason: str) -> dict:
        """Heartbeat used outside the scan window; keep last-scan visible."""
        self.last_scan_at = now.isoformat()
        self.quote_unavailable = True
        return self._status(now, self._idle_options(reason), errors=[reason])

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
            "spot_source": self.spot_source or "unavailable",
            "quote_unavailable": bool(self.quote_unavailable),
            "atm_strike": self.atm_strike,
            "strike_offsets": {k: float(v) for k, v in STRIKE_OFFSETS.items()},
            "sma_period": SMA_PERIOD,
            "stop_loss_pct": 0.10,
            "trail_pct": 0.10,
            "eod_exit_time": eod_exit_time(now).strftime("%H:%M"),
            "eod_exit_reason": EOD_EXIT_REASON,
            "last_closed_spot": self.last_closed_spot,
            "last_closed_atm_strike": self.last_closed_atm_strike,
            "last_closed_candle_start": self.last_closed_candle_start,
            "last_closed_spot_source": self.last_closed_spot_source,
            "bar_source": getattr(getattr(self.feed, "kite", None), "bar_source", "broker_history"),
            "expiry": self.expiry.isoformat() if hasattr(self.expiry, "isoformat") else self.expiry,
            "options": options,
            "today": today_stats(today),
            "errors": errors or [],
            "last_error": self.last_error,
        }


def main() -> int:
    logger.info("SMA9 SHORT paper scanner starting (poll=%ss, db=%s)",
                POLL_SECONDS, DB_PATH)
    init_db()
    try:
        feed = KiteFeed()
        feed.refresh_instruments()
    except Exception as exc:
        logger.error("Failed to initialise market feed: %s", exc)
        traceback.print_exc()
        return 1

    scanner = Sma9ShortLiveScanner(feed)
    scanner.prime_expiry()
    try:
        scanner.recover_open_positions()
    except Exception as exc:
        logger.error("Open-position recovery failed: %s", exc)
        traceback.print_exc()

    logger.info("SMA9 SHORT scanner ready")
    try:
        while True:
            now = now_ist()
            try:
                if not is_weekday(now):
                    save_scan_state(scanner._idle_status(now, "weekend"))
                elif now.time() < session_open_time(now):
                    save_scan_state(scanner._idle_status(now, "pre-market"))
                elif now.time() >= session_close_time(now) and not any(
                        s.position for s in scanner.states.values()):
                    save_scan_state(scanner._idle_status(now, "market closed"))
                else:
                    save_scan_state(scanner.scan())
            except Exception as exc:
                scanner.last_error = f"scan loop error: {exc}"
                logger.error(scanner.last_error)
                traceback.print_exc()
                try:
                    save_scan_state(scanner._idle_status(now, scanner.last_error))
                except Exception:
                    pass
            sleep_to_next_tick()
    except KeyboardInterrupt:
        logger.info("SMA9 SHORT scanner stopping (SIGINT)")
    finally:
        logger.info("SMA9 SHORT scanner stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
