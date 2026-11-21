#!/usr/bin/env python3
"""SMA9 Trail live paper scanner - BUY ONLY with trailing-stop exit.

SELF-CONTAINED: entry selection is evaluated locally from fetched candles
(previous close > SMA9 AND current open > SMA9).  The scanner owns both entry
and exit -- no dependency on any base scanner API.

Exit: TRAILING STOP -- stop = peak - 5.0 pts, activates at +5.0 pts
      (breakeven at activation), ratchets up only.  Exit at the stop ONLY if
      the stop is above entry price (profitable lock).  Breakeven or loss
      stops are ignored -- the trade runs to candle close.
      Otherwise exit at the CLOSE of the entry 5-minute candle.

Polling is staggered by a small offset so scanners do not all request
historical candles on the same instant.

State is persisted in the dedicated database so a restart with an open
position resumes correctly.
"""

from __future__ import annotations

import json
import logging
import os
import random
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

from app.sma9_trail_engine import (  # noqa: E402
    CANDLE_MINUTES,
    STRATEGY_ID,
    STRATEGY_TYPE,
    STRATEGY_VERSION,
    Evaluation,
    OptionStateMachine,
    Position,
    TRAIL,
    ACTIVATE,
    candle_end,
    evaluate_option,
    make_trade_id,
    normalize_candles,
)

IST = ZoneInfo("Asia/Kolkata")
DB_PATH = os.environ.get("SMA9_TRAIL_DB_PATH", os.path.join(BASE, "database", "sma9_trail.db"))
LOG_PATH = os.path.join(BASE, "logs", "live_sma9_trail_scanner.log")

MARKET_OPEN = dtime(9, 0)
MARKET_CLOSE = dtime(15, 30)
EXCHANGE_OPEN = dtime(9, 15)  # real trading starts; 09:00-09:15 is warm-up only
# New paper entries are allowed only inside this window (exits are not
# affected).  The 09:15 candle is never entered and the last entry candle is
# 15:10, so nothing is opened at or after 15:15.
ENTRY_START = dtime(9, 20)
ENTRY_END = dtime(15, 15)
MUHURAT_SESSIONS = {
    "2026-11-08": (dtime(14, 0), dtime(17, 0)),
}


def session_open_time(dt):
    return MUHURAT_SESSIONS.get(dt.date().isoformat(), (MARKET_OPEN, MARKET_CLOSE))[0]


def session_close_time(dt):
    return MUHURAT_SESSIONS.get(dt.date().isoformat(), (MARKET_OPEN, MARKET_CLOSE))[1]


POLL_SECONDS = 5
# Per-scanner phase offset (seconds) inside the 5s tick window.  Without this
# every scanner re-aligns to the same wall-clock boundary and they all hit the
# Kite historical/quote endpoints at the same instant, which triggers
# "Too many requests".  Each variant gets a distinct offset from VARIANTS.
POLL_OFFSET_SECONDS = 1.2
# Historical lookback: 1 day is enough on normal days (previous session is
# included).  If fewer than CANDLE_MIN_ROWS rows come back (e.g. Monday, when
# 1 day back is Sunday) widen once to the fallback window so SMA20 still has
# enough completed candles.  This keeps payloads small without changing logic.
CANDLE_LOOKBACK_DAYS = 1
CANDLE_LOOKBACK_DAYS_FALLBACK = 3
CANDLE_MIN_ROWS = 25
# Boundary re-fetch backoff.  A small random jitter de-synchronises the
# scanners that are waiting for the exchange to publish the new candle.
CANDLE_BACKOFF_BASE = 8
CANDLE_BACKOFF_JITTER = 4
CANDLE_BACKOFF_MAX = 90
INSTRUMENT = "NIFTY"
TIMEFRAME = "5m"
SCANNER_NAME = "SMA9 Trail - ATM Option Strike + Trail Exit (BUY ONLY)"
STRATEGY_ID = STRATEGY_ID
STRATEGY_VERSION = STRATEGY_VERSION
STRATEGY_TYPE = STRATEGY_TYPE

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def now_ist():
    return datetime.now(IST)


def floor_5m(dt):
    return dt.replace(minute=(dt.minute // CANDLE_MINUTES) * CANDLE_MINUTES,
                      second=0, microsecond=0)


def is_weekday(dt):
    if dt.date().isoformat() in MUHURAT_SESSIONS:
        return True
    return dt.weekday() < 5


def market_is_open(dt):
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


def market_close_dt(dt):
    return datetime.combine(dt.date(), session_close_time(dt), tzinfo=IST)


def sleep_to_next_tick():
    """Sleep until the next 5s tick for THIS scanner.

    Ticks are aligned to ``POLL_OFFSET_SECONDS + k*POLL_SECONDS`` so the 7
    trail scanners fire at different instants instead of all together.
    """
    now = now_ist()
    epoch = now.timestamp()
    target = (
        (int(epoch - POLL_OFFSET_SECONDS) // POLL_SECONDS) + 1
    ) * POLL_SECONDS + POLL_OFFSET_SECONDS
    time.sleep(max(0.2, target - epoch))


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
TRADE_COLUMNS = (
    "trade_id, strategy_id, instrument, trade_date, option_type, strike, "
    "expiry, signal_timestamp, entry_timestamp, entry_price, exit_timestamp, "
    "exit_price, exit_reason, pnl_points, status, candle_open, "
    "candle_high, candle_low, candle_close, created_at, updated_at, dataset, "
    "prev_high, breakout, ltp_at_entry, entry_candle_start, "
    "entry_candle_end"
)


def db_conn():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=15000")
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = db_conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sma9_trail_trades (
            trade_id TEXT PRIMARY KEY,
            strategy_id TEXT NOT NULL DEFAULT 'sma9_trail',
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
            candle_open REAL,
            candle_high REAL,
            candle_low REAL,
            candle_close REAL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            dataset TEXT NOT NULL DEFAULT 'LIVE',
            prev_high REAL,
            breakout INTEGER,
            ltp_at_entry REAL,
            entry_candle_start TEXT,
            entry_candle_end TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_sma9_trail_trades_date ON sma9_trail_trades(trade_date);
        CREATE INDEX IF NOT EXISTS idx_sma9_trail_trades_option ON sma9_trail_trades(option_type);
        CREATE INDEX IF NOT EXISTS idx_sma9_trail_trades_status ON sma9_trail_trades(status);
        CREATE INDEX IF NOT EXISTS idx_sma9_trail_trades_dataset ON sma9_trail_trades(dataset);

        CREATE TABLE IF NOT EXISTS sma9_trail_open_positions (
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
            prev_high REAL,
            current_open REAL,
            breakout INTEGER,
            ltp_at_entry REAL,
            hwm REAL,
            stop REAL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sma9_trail_scan_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    # Idempotent migration: add be_locked to open_positions for existing DBs.
    try:
        cols = [r[1] for r in conn.execute(
            f"PRAGMA table_info(sma9_trail_open_positions)").fetchall()]
        if "be_locked" not in cols:
            conn.execute(
                f"ALTER TABLE sma9_trail_open_positions "
                "ADD COLUMN be_locked INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()


def save_trade(trade):
    cols = TRADE_COLUMNS.split(",")
    cols = [c.strip() for c in cols]
    placeholders = ",".join("?" for _ in cols)
    conn = db_conn()
    try:
        conn.execute(
            f"INSERT OR REPLACE INTO sma9_trail_trades ({','.join(cols)}) VALUES ({placeholders})",
            tuple(trade.get(c) for c in cols),
        )
        # Atomic close: insert the trade and remove the open position in
        # the same transaction so a crash cannot leave both (or neither).
        conn.execute(
            "DELETE FROM sma9_trail_open_positions WHERE option_type = ?",
            (trade.get("option_type"),),
        )
        conn.commit()
    finally:
        conn.close()


def save_open_position(pos):
    conn = db_conn()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO sma9_trail_open_positions
               (option_type, trade_id, strike, expiry, token, tradingsymbol,
                entry_timestamp, entry_candle_start, entry_candle_end,
                entry_price, prev_high, current_open, breakout, ltp_at_entry,
                hwm, stop, be_locked, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                pos.option_type, pos.trade_id, pos.strike, pos.expiry, pos.token,
                pos.tradingsymbol, pos.entry_timestamp.isoformat(),
                pos.entry_candle_start.isoformat(), pos.entry_candle_end.isoformat(),
                pos.entry_price, pos.prev_high, pos.current_open,
                1 if pos.breakout else 0, pos.ltp_at_entry,
                pos.hwm, pos.stop, 1 if pos.be_locked else 0,
                now_ist().isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def delete_open_position(option_type):
    conn = db_conn()
    try:
        conn.execute("DELETE FROM sma9_trail_open_positions WHERE option_type = ?",
                     (option_type,))
        conn.commit()
    finally:
        conn.close()


def load_open_positions():
    conn = db_conn()
    try:
        rows = conn.execute(f"SELECT * FROM sma9_trail_open_positions").fetchall()
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
            prev_high=d["prev_high"],
            current_open=d["current_open"],
            breakout=bool(d["breakout"]),
            ltp_at_entry=d["ltp_at_entry"],
            hwm=d["hwm"],
            stop=d["stop"],
            be_locked=bool(d["be_locked"]),
        )
    return result


def save_scan_state(state):
    conn = db_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO sma9_trail_scan_state (key, value, updated_at) VALUES (?,?,?)",
            ("live_status", json.dumps(state, default=str), now_ist().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def today_stats(today):
    conn = db_conn()
    try:
        row = conn.execute(
            f"""SELECT COUNT(*) n, COALESCE(SUM(pnl_points),0) pnl,
                      COALESCE(SUM(CASE WHEN pnl_points > 0 THEN 1 ELSE 0 END),0) wins,
                      COALESCE(SUM(CASE WHEN pnl_points < 0 THEN 1 ELSE 0 END),0) losses
               FROM sma9_trail_trades WHERE dataset='LIVE' AND trade_date=?""",
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
class KiteFeed:
    def __init__(self):
        from kiteconnect import KiteConnect

        creds = self._load_zerodha_credentials()
        self.kite = KiteConnect(api_key=creds["KITE_API_KEY"])
        self.kite.set_access_token(creds["KITE_ACCESS_TOKEN"])
        self._instruments = []
        self._instruments_date = None
        self._candles = {}

    def _load_zerodha_credentials(self):
        env_path = os.path.join(BASE, ".env.zerodha")
        creds = {}
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    creds[k.strip()] = v.strip()
        return creds

    def refresh_instruments(self):
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

    def nearest_expiry(self):
        self.refresh_instruments()
        today = now_ist().date()
        expiries = sorted({i["expiry"] for i in self._instruments
                           if i["expiry"] >= today})
        if not expiries:
            raise RuntimeError("No NIFTY option expiry available")
        return expiries[0]

    def find_contract(self, strike, expiry, option_type):
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

    def _fetch_candles(self, token):
        now = now_ist()

        def _fetch(days):
            start = now - timedelta(days=days)
            start = start.replace(hour=9, minute=15, second=0, microsecond=0)
            raw = self.kite.historical_data(token, start, now, "5minute")
            return normalize_candles([
                {
                    "start": r["date"].astimezone(IST) if hasattr(r["date"], "astimezone") else r["date"],
                    "open": r["open"], "high": r["high"], "low": r["low"],
                    "close": r["close"], "volume": r.get("volume", 0),
                }
                for r in raw
            ])

        rows = _fetch(CANDLE_LOOKBACK_DAYS)
        if len(rows) < CANDLE_MIN_ROWS:
            # Weekend/holiday: widen once so SMA20 still has enough history.
            rows = _fetch(CANDLE_LOOKBACK_DAYS_FALLBACK)
        last_start = rows[-1]["start"] if rows else None
        self._candles[token] = (rows, now, last_start)
        return rows

    def candles(self, token, force=False):
        now = now_ist()
        cached = self._candles.get(token)
        if cached:
            rows, fetched_at, last_start = cached
            age = (now - fetched_at).total_seconds()
            current_start = floor_5m(now)
            if not force and age < CANDLE_BACKOFF_BASE:
                return rows
            if (not force and last_start == current_start
                    and age < CANDLE_BACKOFF_MAX + random.uniform(0, CANDLE_BACKOFF_JITTER)):
                return rows
        return self._fetch_candles(token)

    def candle_at(self, token, candle_start, retries=6):
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
class TrailLiveScanner:
    def __init__(self, feed):
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

    def recover_open_positions(self):
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
                logger.info("Recovered %s position closed at %.2f pnl=%.2f",
                            opt, close_px, trade["pnl_points"])

    def _resolve_contract(self, opt):
        pos = self.states[opt].position
        if pos is not None and pos.token:
            return {"tradingsymbol": pos.tradingsymbol,
                    "instrument_token": pos.token,
                    "strike": pos.strike, "expiry": pos.expiry}
        return self.contracts.get(opt)

    def refresh_contracts(self, spot, force=False):
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

    def scan(self):
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

        current_candle = floor_5m(now)
        self.last_candle_start = current_candle

        # --- resolve contracts from existing positions or ATM cache ---
        symbol_for = {}
        for opt in ("CE", "PE"):
            contract = self._resolve_contract(opt)
            if contract:
                sym = f"NFO:{contract['tradingsymbol']}"
                symbol_for[opt] = (sym, contract)

        # --- quote spot first so we can compute ATM ---
        symbols = ["NSE:NIFTY 50"] + [sym for sym, _ in symbol_for.values()]
        quotes = {}
        try:
            quotes = self.feed.quote(symbols)
            self.spot = float(quotes["NSE:NIFTY 50"]["last_price"])
        except Exception as exc:
            # Batched call failed; retry spot alone so the scanner keeps going.
            try:
                nifty = self.feed.quote(["NSE:NIFTY 50"])
                self.spot = float(nifty["NSE:NIFTY 50"]["last_price"])
                quotes = {"NSE:NIFTY 50": nifty["NSE:NIFTY 50"]}
                errors.append(f"batched quote failed, retried spot: {exc}")
                logger.error(errors[-1])
            except Exception as exc2:
                self.last_error = f"spot/contract error: {exc2}"
                logger.error(self.last_error)
                return self._status(now, {}, errors=[self.last_error])

        # --- refresh ATM contracts from spot ---
        self.refresh_contracts(self.spot, force=self.atm_strike is None)

        # --- re-resolve contracts now that ATM is known ---
        symbol_for = {}
        for opt in ("CE", "PE"):
            contract = self._resolve_contract(opt)
            if contract:
                sym = f"NFO:{contract['tradingsymbol']}"
                symbol_for[opt] = (sym, contract)

        # --- fetch option quotes for any contracts not yet quoted ---
        missing = []
        for opt in ("CE", "PE"):
            contract = self._resolve_contract(opt)
            if not contract:
                symbol_for.pop(opt, None)
                continue
            sym = f"NFO:{contract['tradingsymbol']}"
            symbol_for[opt] = (sym, contract)
            if sym not in quotes and sym not in missing:
                missing.append(sym)
        if missing:
            try:
                quotes.update(self.feed.quote(missing))
            except Exception as exc:
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

            # --- entry evaluation (self-contained, no base scanner dependency) ---
            entry_made = False
            ev_local = None
            try:
                rows = self.feed.candles(token)
                ev_local = evaluate_option(rows, opt, ltp=ltp)

                if allow_entries and pos is None and ev_local.signal:
                    new_pos = state.try_entry(
                        ev_local, now, strike, expiry_str, token,
                        contract["tradingsymbol"], market_close_dt(now))
                    if new_pos is not None:
                        save_open_position(new_pos)
                        entry_made = True
                        pos = new_pos
                        logger.info(
                            "ENTRY %s %s strike=%s entry=%.2f candle=%s signal=%s",
                            opt, contract["tradingsymbol"], strike,
                            new_pos.entry_price, ev_local.candle_start.isoformat(),
                            ev_local.reason)
            except Exception as exc:
                errors.append(f"entry eval error ({opt}): {exc}")
                logger.error(errors[-1])

            # --- trail exit check (before candle-close exit) ---
            if pos is not None and now.time() >= EXCHANGE_OPEN:
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
                    # Exit price is the actual sampled LTP at the breach.
                    exit_px = round(float(ltp), 2)
                    trade = state.close(now, exit_px,
                                        "TRAIL_STOP_EXIT")
                    save_trade(trade)
                    logger.info(
                        "TRAIL EXIT %s %s strike=%s entry=%.2f exit=%.2f pnl=%.2f (stop=%.2f)",
                        opt, pos.tradingsymbol, pos.strike, pos.entry_price,
                        exit_px, trade["pnl_points"], pos.stop)
                elif sl_hit is not None:
                    trade = state.close(now, sl_hit, "STOP_LOSS_5PCT")
                    save_trade(trade)
                    logger.info(
                        "EXIT %s %s strike=%s entry=%.2f exit=%.2f pnl=%.2f reason=STOP_LOSS_5PCT",
                        opt, pos.tradingsymbol, pos.strike, pos.entry_price,
                        sl_hit, trade["pnl_points"])

            # --- build status from local evaluation ---
            if ev_local is not None:
                option_status[opt] = {
                    "tradingsymbol": contract["tradingsymbol"],
                    "token": token,
                    "strike": strike,
                    "expiry": expiry_str,
                    "ltp": ltp,
                    "sma": round(ev_local.sma, 2) if ev_local.sma is not None else None,
                    "prev_close": ev_local.prev_close,
                    "prev_high": ev_local.prev_high,
                    "current_open": ev_local.current_open,
                    "condition_a": ev_local.condition_a,
                    "condition_b": ev_local.condition_b,
                    "condition_c": ev_local.condition_c,
                    "qualified": ev_local.qualified,
                    "confirmation": ev_local.confirmation,
                    "breakout": ev_local.breakout,
                    "signal": ev_local.signal,
                    "ready": ev_local.ready,
                    "reason": ev_local.reason,
                    "entry_made": entry_made,
                    "position": state.position.as_dict() if state.position else None,
                }
            else:
                option_status[opt] = {
                    "tradingsymbol": contract["tradingsymbol"],
                    "token": token,
                    "strike": strike,
                    "expiry": expiry_str,
                    "ltp": ltp,
                    "entry_made": entry_made,
                    "position": state.position.as_dict() if state.position else None,
                }

        return self._status(now, option_status, errors=errors)

    def _status(self, now, options, errors=None):
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


def main():
    logger.info("SMA9 Trail - ATM Option Strike + Trail Exit (BUY ONLY) starting (poll=%ss, db=%s)", POLL_SECONDS, DB_PATH)
    init_db()
    try:
        feed = KiteFeed()
        feed.refresh_instruments()
    except Exception as exc:
        logger.error("Failed to initialise Kite feed: %s", exc)
        traceback.print_exc()
        return 1

    scanner = TrailLiveScanner(feed)
    try:
        scanner.recover_open_positions()
    except Exception as exc:
        logger.error("Open-position recovery failed: %s", exc)
        traceback.print_exc()

    logger.info("SMA9 Trail - ATM Option Strike + Trail Exit (BUY ONLY) ready")
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
        logger.info("SMA9 Trail - ATM Option Strike + Trail Exit (BUY ONLY) stopping (SIGINT)")
    finally:
        logger.info("SMA9 Trail - ATM Option Strike + Trail Exit (BUY ONLY) stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
