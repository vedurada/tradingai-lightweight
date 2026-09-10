from __future__ import annotations

"""Daily paper-trade P&L tracker for indexes.

Index trades: ENTRY 9:30 AM IST, EXIT 3:20 PM IST.
- `lock`  : record 9:30 entry price (+ strategy/regime snapshot) into history.
- `close` : record 3:20 exit price, compute points and WIN/LOSS/FLAT.
- `backfill [YYYY-MM-DD]`: rebuild a past day from stored 1m candles.

Usage:
    python3 pnl_tracker.py lock
    python3 pnl_tracker.py close
    python3 pnl_tracker.py backfill            # today
    python3 pnl_tracker.py backfill 2026-09-10
"""

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

IST = ZoneInfo("Asia/Kolkata")
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "database", "tradingai.db")

INDEX_SYMBOLS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"]
ENTRY_LABEL = "09:30"
EXIT_LABEL = "15:20"


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ist_today() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d")


def _latest_price(conn: sqlite3.Connection, symbol: str):
    row = conn.execute("SELECT close, timestamp FROM price_1m WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
    return (row["close"], row["timestamp"]) if row else (None, None)


def _candle_price(conn: sqlite3.Connection, symbol: str, date_str: str, hhmm: str):
    row = conn.execute(
        "SELECT close, timestamp FROM price_1m WHERE symbol=? AND timestamp LIKE ? ORDER BY timestamp ASC LIMIT 1",
        (symbol, f"{date_str} {hhmm}%"),
    ).fetchone()
    return (row["close"], row["timestamp"]) if row else (None, None)


def _last_candle_of_day(conn: sqlite3.Connection, symbol: str, date_str: str):
    row = conn.execute(
        "SELECT close, timestamp FROM price_1m WHERE symbol=? AND timestamp LIKE ? ORDER BY timestamp DESC LIMIT 1",
        (symbol, f"{date_str}%"),
    ).fetchone()
    return (row["close"], row["timestamp"]) if row else (None, None)


def _snapshot(conn: sqlite3.Connection, symbol: str) -> dict:
    snap = {"strategy": "", "regime": "", "bias": "", "confidence": 0, "summary": ""}
    try:
        r = conn.execute("SELECT strategy, legs FROM strategies WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
        if r:
            snap["strategy"] = r["strategy"] or ""
            try:
                full = json.loads(r["legs"] or "{}") if r["legs"] else {}
                strat_list = full.get("all_strategies", []) if isinstance(full, dict) else []
                if strat_list:
                    snap["strategy"] = strat_list[0].get("strategy", snap["strategy"])
            except Exception:
                pass
    except Exception:
        pass
    try:
        r = conn.execute("SELECT regime, confidence FROM market_regime WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
        if r:
            snap["regime"] = r["regime"] or ""
            snap["confidence"] = r["confidence"] or 0
    except Exception:
        pass
    try:
        r = conn.execute("SELECT outlook FROM ai_outlooks WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
        if r and r["outlook"]:
            try:
                o = json.loads(r["outlook"])
                snap["bias"] = o.get("directional_bias", "")
                snap["summary"] = (o.get("market_summary", "") or "")[:500]
            except Exception:
                pass
    except Exception:
        pass
    return snap


def lock(date_str: str | None = None, entry_label: str = ENTRY_LABEL) -> None:
    """Record 9:30 AM entry prices for all indexes (idempotent per day)."""
    date_str = date_str or _ist_today()
    conn = _conn()
    for symbol in INDEX_SYMBOLS:
        price, ts = _candle_price(conn, symbol, date_str, "09:30")
        if price is None:
            price, ts = _latest_price(conn, symbol)
        if price is None:
            print(f"lock {symbol} {date_str}: no price available, skipped")
            continue
        snap = _snapshot(conn, symbol)
        conn.execute(
            """INSERT INTO history (symbol, date, locked_price, closed_price, entry_time, exit_time, points, result,
                    strategy, market_regime, directional_bias, confidence, market_summary, created_at)
               VALUES (?, ?, ?, NULL, ?, NULL, NULL, 'OPEN', ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(symbol, date) DO UPDATE SET
                    locked_price=excluded.locked_price, entry_time=excluded.entry_time,
                    strategy=excluded.strategy, market_regime=excluded.market_regime,
                    directional_bias=excluded.directional_bias, confidence=excluded.confidence,
                    market_summary=excluded.market_summary""",
            (symbol, date_str, round(float(price), 2), entry_label, snap["strategy"], snap["regime"], snap["bias"], snap["confidence"], snap["summary"]),
        )
        print(f"lock {symbol} {date_str} {entry_label}: entry={round(float(price), 2)} ({snap['strategy'] or snap['regime']})")
    conn.commit()
    conn.close()


def close(date_str: str | None = None, exit_label: str = EXIT_LABEL) -> None:
    """Record 3:20 PM exit prices and settle points/result for all indexes."""
    date_str = date_str or _ist_today()
    conn = _conn()
    for symbol in INDEX_SYMBOLS:
        price, ts = _last_candle_of_day(conn, symbol, date_str)
        if price is None:
            price, ts = _latest_price(conn, symbol)
        if price is None:
            print(f"close {symbol} {date_str}: no price available, skipped")
            continue
        exit_price = round(float(price), 2)
        row = conn.execute("SELECT locked_price FROM history WHERE symbol=? AND date=?", (symbol, date_str)).fetchone()
        if row and row["locked_price"]:
            entry_price = float(row["locked_price"])
            points = round(exit_price - entry_price, 2)
            result = "WIN" if points > 0 else ("LOSS" if points < 0 else "FLAT")
            conn.execute(
                "UPDATE history SET closed_price=?, exit_time=?, points=?, result=? WHERE symbol=? AND date=?",
                (exit_price, exit_label, points, result, symbol, date_str),
            )
            print(f"close {symbol} {date_str} {exit_label}: entry={entry_price} exit={exit_price} points={points:+} {result}")
        else:
            conn.execute(
                """INSERT INTO history (symbol, date, locked_price, closed_price, entry_time, exit_time, points, result, created_at)
                   VALUES (?, ?, NULL, ?, NULL, ?, NULL, 'OPEN', datetime('now'))
                   ON CONFLICT(symbol, date) DO UPDATE SET closed_price=excluded.closed_price, exit_time=excluded.exit_time""",
                (symbol, date_str, exit_price, exit_label),
            )
            print(f"close {symbol} {date_str} {exit_label}: exit={exit_price} (no entry locked)")
    conn.commit()
    conn.close()


def backfill(date_str: str | None = None) -> None:
    """Rebuild one day from stored 1m candles: 09:30 entry, last candle exit."""
    date_str = date_str or _ist_today()
    conn = _conn()
    for symbol in INDEX_SYMBOLS:
        entry, _ = _candle_price(conn, symbol, date_str, "09:30")
        exit_p, _ = _last_candle_of_day(conn, symbol, date_str)
        if entry is None or exit_p is None:
            print(f"backfill {symbol} {date_str}: missing candles, skipped")
            continue
        entry = round(float(entry), 2)
        exit_p = round(float(exit_p), 2)
        points = round(exit_p - entry, 2)
        result = "WIN" if points > 0 else ("LOSS" if points < 0 else "FLAT")
        snap = _snapshot(conn, symbol)
        conn.execute(
            """INSERT INTO history (symbol, date, locked_price, closed_price, entry_time, exit_time, points, result,
                    strategy, market_regime, directional_bias, confidence, market_summary, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(symbol, date) DO UPDATE SET
                    locked_price=excluded.locked_price, closed_price=excluded.closed_price,
                    entry_time=excluded.entry_time, exit_time=excluded.exit_time,
                    points=excluded.points, result=excluded.result, strategy=excluded.strategy,
                    market_regime=excluded.market_regime, directional_bias=excluded.directional_bias,
                    confidence=excluded.confidence, market_summary=excluded.market_summary""",
            (symbol, date_str, entry, exit_p, ENTRY_LABEL, EXIT_LABEL, points, result,
             snap["strategy"], snap["regime"], snap["bias"], snap["confidence"], snap["summary"]),
        )
        print(f"backfill {symbol} {date_str}: {ENTRY_LABEL} {entry} → {EXIT_LABEL} {exit_p} = {points:+} {result}")
    conn.commit()
    conn.close()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "close"
    arg = sys.argv[2] if len(sys.argv) > 2 else None
    if cmd == "lock":
        lock(arg)
    elif cmd == "close":
        close(arg)
    elif cmd == "backfill":
        backfill(arg)
    else:
        print(__doc__)
