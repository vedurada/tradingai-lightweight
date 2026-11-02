#!/usr/bin/env python3
"""
TradingAI Options Trading Engine — SHADOW / Paper Trading Only.

Design:
- NIFTY weekly options, ATM CE/PE buying on HLC 3-bar signals
- BULL signal  -> buy ATM CE (nearest weekly expiry)
- BEAR signal  -> buy ATM PE (nearest weekly expiry)
- Premium captured at signal time from Zerodha option chain
- Exit on stop/target (underlying spot) or EOD 15:25 IST
- LIVE_EXECUTION_AUTHORIZED = False — no broker orders ever

Safety:
- Never fabricates option data; if chain unavailable -> signal degrades to spot-only
- All premiums/strikes sourced from Zerodha kiteconnect only
- Single open position per instrument (Mode C)
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
from typing import Optional, Dict, Any, List, Tuple

IST = ZoneInfo("Asia/Kolkata")

BASE = "/opt/tradingai"
DB_PATH = os.path.join(BASE, "database", "tradingai.db")
OPTION_TRADES_TABLE = "paper_option_trades"

# NIFTY lot size (standard F&O lot)
LOT_SIZE_NIFTY = 50

# Market hours IST
MARKET_OPEN = dtime(9, 15)
MARKET_CLOSE = dtime(15, 30)
EOD_EXIT = dtime(15, 25)

# SHADOW enforcement
LIVE_EXECUTION_AUTHORIZED = False


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def init_option_trades_table() -> None:
    """Create paper_option_trades table if not exists. Safe to repeat."""
    conn = _connect()
    try:
        conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {OPTION_TRADES_TABLE} (
            trade_id        TEXT PRIMARY KEY,
            signal_id       TEXT,
            instrument      TEXT NOT NULL,
            direction       TEXT NOT NULL CHECK(direction IN ('BULL','BEAR')),
            option_type     TEXT NOT NULL CHECK(option_type IN ('CE','PE')),
            expiry          TEXT NOT NULL,
            strike          REAL NOT NULL,
            spot_at_signal  REAL NOT NULL,
            premium_entry   REAL NOT NULL,
            stop_spot       REAL NOT NULL,
            target_spot     REAL NOT NULL,
            premium_exit    REAL,
            exit_reason     TEXT,
            pnl_points      REAL,
            pnl_rupees      REAL,
            status          TEXT NOT NULL DEFAULT 'OPEN'
                            CHECK(status IN ('OPEN','CLOSED','EXPIRED')),
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        )
        """)
        conn.commit()
    finally:
        conn.close()


def _now_iso() -> str:
    return _ist_now().isoformat()


def _ist_now() -> datetime:
    """Return current IST time. Patchable for testing."""
    return datetime.now(IST)


# ---------------------------------------------------------------------------
# Zerodha integration (kiteconnect)
# ---------------------------------------------------------------------------
def _load_zerodha_env() -> Dict[str, str]:
    """Load Zerodha credentials from /opt/tradingai/.env.zerodha."""
    env_path = os.path.join(BASE, ".env.zerodha")
    cfg: Dict[str, str] = {}
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                s = line.strip()
                if "=" in s and not s.startswith("#"):
                    k, v = s.split("=", 1)
                    cfg[k.strip()] = v.strip()
    return cfg


def _kite_client():
    """Return authenticated KiteConnect client or None."""
    try:
        from kiteconnect import KiteConnect
    except ImportError:
        return None
    cfg = _load_zerodha_env()
    api_key = cfg.get("KITE_API_KEY")
    access_token = cfg.get("KITE_ACCESS_TOKEN")
    if not api_key or not access_token:
        return None
    kc = KiteConnect(api_key=api_key)
    kc.set_access_token(access_token)
    return kc


# Zerodha quote symbol mapping for indices
_SPOT_SYMBOL_MAP = {
    "NIFTY": "NSE:NIFTY 50",
    "BANKNIFTY": "NSE:BANKNIFTY",
    "NIFTY 50": "NSE:NIFTY 50",
}


def get_spot_price(instrument: str = "NIFTY") -> Optional[float]:
    """Fetch spot quote for instrument from Zerodha. Returns price or None."""
    kc = _kite_client()
    if kc is None:
        return None
    try:
        symbol = _SPOT_SYMBOL_MAP.get(instrument, f"NSE:{instrument}")
        quote = kc.quote([symbol])
        q = quote.get(symbol, {})
        last = q.get("last_price") or q.get("ohlc", {}).get("close")
        return float(last) if last else None
    except Exception:
        return None


def get_option_chain(
    instrument: str = "NIFTY",
) -> Optional[List[Dict[str, Any]]]:
    """
    Fetch option chain for nearest weekly expiry.
    Returns list of option contracts or None if unavailable.
    Each contract: {instrument, expiry, strike, option_type, last_price, ...}
    """
    kc = _kite_client()
    if kc is None:
        return None
    try:
        # Get instruments for NFO (options)
        instruments = kc.instruments("NFO")
        nifty_opts = [
            inst for inst in instruments
            if inst.get("name") == instrument
            and inst.get("instrument_type") in ("CE", "PE")
        ]
        if not nifty_opts:
            return None

        # Find nearest available weekly expiry from actual contracts
        from datetime import date, timedelta
        today = date.today()
        available_expiries = sorted(
            set(
                str(inst.get("expiry"))[:10]
                for inst in nifty_opts
                if inst.get("expiry")
            )
        )
        # Filter to future expiries only
        future_expiries = [e for e in available_expiries if e >= today.isoformat()]
        if not future_expiries:
            return None
        expiry_str = future_expiries[0]  # nearest future expiry

        weekly_opts = [
            inst for inst in nifty_opts
            if inst.get("expiry") and str(inst["expiry"])[:10] == expiry_str
        ]

        return weekly_opts
    except Exception:
        return None


def select_atm_contract(
    chain: List[Dict[str, Any]],
    spot: float,
    option_type: str,
    expiry: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Select ATM option contract closest to spot price.
    option_type: 'CE' or 'PE'
    expiry: optional expiry filter (YYYY-MM-DD)
    """
    candidates = [
        c for c in chain
        if c.get("instrument_type") == option_type
    ]
    if expiry:
        candidates = [
            c for c in candidates
            if str(c.get("expiry", ""))[:10] == expiry
        ]
    if not candidates:
        return None

    # Sort by |strike - spot|
    candidates.sort(key=lambda c: abs(float(c["strike"]) - spot))
    return candidates[0]


def get_contract_quote(kc, tradingsymbol: str) -> Optional[float]:
    """Get last_price for a specific option contract."""
    try:
        quote = kc.quote([f"NFO:{tradingsymbol}"])
        q = quote.get(f"NFO:{tradingsymbol}", {})
        last = q.get("last_price")
        return float(last) if last else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------
class OptionsEngine:
    def __init__(self):
        init_option_trades_table()
        self.kc = _kite_client()
        self.open_positions: Dict[str, Dict] = {}  # instrument -> open trade
        self._load_open_positions()

    def _load_open_positions(self) -> None:
        """Load existing OPEN option trades from DB."""
        conn = _connect()
        try:
            rows = conn.execute(
                f"SELECT * FROM {OPTION_TRADES_TABLE} WHERE status = 'OPEN'"
            ).fetchall()
            for row in rows:
                self.open_positions[row["instrument"]] = dict(row)
        finally:
            conn.close()

    def has_open_position(self, instrument: str) -> bool:
        return instrument in self.open_positions

    def on_signal(
        self,
        instrument: str,
        direction: str,
        signal_time: str,
        entry_spot: float,
        stop_spot: float,
        target_spot: float,
        signal_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Process an HLC 3-bar signal and create an option paper trade.

        direction: 'BULL' -> buy ATM CE; 'BEAR' -> buy ATM PE
        Returns a result dict with status and details.
        """
        result: Dict[str, Any] = {
            "status": "NO_TRADE",
            "reason": "",
            "instrument": instrument,
            "direction": direction,
        }

        # SHADOW enforcement
        if LIVE_EXECUTION_AUTHORIZED:
            result["reason"] = "LIVE_EXECUTION_AUTHORIZED is True — refusing to run"
            return result

        # Market hours check
        now = _ist_now()
        if not (MARKET_OPEN <= now.time() <= MARKET_CLOSE):
            result["reason"] = "Outside market hours"
            return result

        # Mode C: one open position per instrument
        if self.has_open_position(instrument):
            result["reason"] = f"Already open position in {instrument}"
            return result

        # Need spot price
        if self.kc is None:
            result["reason"] = "Zerodha client not available"
            return result

        spot = get_spot_price(instrument)
        if spot is None:
            result["reason"] = "Spot price unavailable"
            return result

        # Fetch option chain
        chain = get_option_chain(instrument)
        if not chain:
            result["reason"] = "Option chain unavailable — degrading to spot-only"
            return result

        # Select ATM contract
        option_type = "CE" if direction == "BULL" else "PE"
        atm = select_atm_contract(chain, spot, option_type)
        if atm is None:
            result["reason"] = f"No {option_type} contract found"
            return result

        strike = float(atm["strike"])
        expiry = str(atm.get("expiry", ""))[:10]
        tradingsymbol = atm.get("tradingsymbol", "")

        # Capture premium at signal time
        premium_entry = get_contract_quote(self.kc, tradingsymbol)
        if premium_entry is None:
            result["reason"] = "Option premium unavailable"
            return result

        # Create paper trade
        trade_id = f"OPT-{instrument}-{_ist_now().strftime('%Y%m%d%H%M%S')}"
        conn = _connect()
        try:
            conn.execute(
                f"""
                INSERT INTO {OPTION_TRADES_TABLE}
                (trade_id, signal_id, instrument, direction, option_type,
                 expiry, strike, spot_at_signal, premium_entry,
                 stop_spot, target_spot, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?)
                """,
                (
                    trade_id,
                    signal_id,
                    instrument,
                    direction,
                    option_type,
                    expiry,
                    strike,
                    spot,
                    premium_entry,
                    stop_spot,
                    target_spot,
                    _now_iso(),
                    _now_iso(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

        # Track in memory
        self.open_positions[instrument] = {
            "trade_id": trade_id,
            "instrument": instrument,
            "direction": direction,
            "option_type": option_type,
            "expiry": expiry,
            "strike": strike,
            "spot_at_signal": spot,
            "premium_entry": premium_entry,
            "stop_spot": stop_spot,
            "target_spot": target_spot,
            "status": "OPEN",
            "tradingsymbol": tradingsymbol,
        }

        result.update({
            "status": "TRADE_CREATED",
            "trade_id": trade_id,
            "option_type": option_type,
            "expiry": expiry,
            "strike": strike,
            "spot_at_signal": spot,
            "premium_entry": premium_entry,
            "stop_spot": stop_spot,
            "target_spot": target_spot,
            "tradingsymbol": tradingsymbol,
        })
        return result

    def check_exits(self, current_spot: Optional[float] = None) -> List[Dict[str, Any]]:
        """
        Check all open positions for stop/target/EOD exit.
        Returns list of exit events.
        """
        if current_spot is None:
            current_spot = get_spot_price("NIFTY")
        if current_spot is None:
            return []

        now = _ist_now()
        exits: List[Dict[str, Any]] = []
        eod = now.time() >= EOD_EXIT

        for instrument, pos in list(self.open_positions.items()):
            exit_reason: Optional[str] = None

            if pos["direction"] == "BULL":
                if current_spot >= pos["target_spot"]:
                    exit_reason = "TARGET"
                elif current_spot <= pos["stop_spot"]:
                    exit_reason = "STOP"
            else:  # BEAR
                if current_spot <= pos["target_spot"]:
                    exit_reason = "TARGET"
                elif current_spot >= pos["stop_spot"]:
                    exit_reason = "STOP"

            if eod and exit_reason is None:
                exit_reason = "EOD"

            if exit_reason:
                # Capture exit premium
                premium_exit = None
                if self.kc is not None and pos.get("tradingsymbol"):
                    premium_exit = get_contract_quote(self.kc, pos["tradingsymbol"])

                # Calculate P&L
                if premium_exit is not None and pos["premium_entry"] is not None:
                    pnl_points = premium_exit - pos["premium_entry"]
                    pnl_rupees = pnl_points * LOT_SIZE_NIFTY
                else:
                    pnl_points = None
                    pnl_rupees = None

                # Close in DB
                conn = _connect()
                try:
                    conn.execute(
                        f"""
                        UPDATE {OPTION_TRADES_TABLE}
                        SET premium_exit = ?, exit_reason = ?, pnl_points = ?,
                            pnl_rupees = ?, status = 'CLOSED', updated_at = ?
                        WHERE trade_id = ?
                        """,
                        (
                            premium_exit,
                            exit_reason,
                            pnl_points,
                            pnl_rupees,
                            _now_iso(),
                            pos["trade_id"],
                        ),
                    )
                    conn.commit()
                finally:
                    conn.close()

                # Remove from memory
                del self.open_positions[instrument]

                exits.append({
                    "trade_id": pos["trade_id"],
                    "instrument": instrument,
                    "direction": pos["direction"],
                    "option_type": pos["option_type"],
                    "strike": pos["strike"],
                    "exit_reason": exit_reason,
                    "premium_entry": pos["premium_entry"],
                    "premium_exit": premium_exit,
                    "pnl_points": pnl_points,
                    "pnl_rupees": pnl_rupees,
                    "exit_spot": current_spot,
                })

        return exits

    def get_open_positions(self) -> List[Dict[str, Any]]:
        return list(self.open_positions.values())

    def get_trade_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        conn = _connect()
        try:
            rows = conn.execute(
                f"SELECT * FROM {OPTION_TRADES_TABLE} ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------
def _demo() -> None:
    engine = OptionsEngine()
    print("=== TradingAI Options Engine — Demo / Smoke Test ===")
    print(f"SHADOW mode: {LIVE_EXECUTION_AUTHORIZED}")
    print(f"Open positions: {len(engine.get_open_positions())}")

    # Try to fetch spot
    spot = get_spot_price("NIFTY")
    print(f"NIFTY spot: {spot}")

    # Try option chain
    chain = get_option_chain("NIFTY")
    if chain:
        print(f"Option contracts fetched: {len(chain)}")
        # Show sample
        for c in chain[:3]:
            print(f"  {c.get('tradingsymbol')} strike={c.get('strike')} type={c.get('instrument_type')} expiry={c.get('expiry')}")
    else:
        print("Option chain unavailable (expected if Zerodha API not reachable)")


if __name__ == "__main__":
    _demo()
