from __future__ import annotations

"""Roll price_1m ticks into price_5m / price_15m OHLCV bars.

Buckets are aligned to UTC 5/15-minute boundaries (same clock the 1m rows
use). Keeps only the last ~30 days so the DB stays small.

Usage:
    python3 aggregate.py sweep    # aggregate all symbols (cron */15 9-15)
"""

import logging
import math
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "database", "tradingai.db")
KEEP_BARS_DAYS = 30
INTERVALS = {"5m": 5, "15m": 15}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("tradingai.aggregate")


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def _bucket_epoch(ts: str, minutes: int) -> int:
    """Round an ISO timestamp's epoch seconds down to the bar boundary."""
    dt = datetime.fromisoformat(ts).timestamp()
    return int(dt - (dt % (minutes * 60)))


def aggregate_symbol(conn: sqlite3.Connection, symbol: str, minutes: int) -> int:
    table = f"price_{minutes}m"
    source = "price_1m"
    cutoff = (datetime.now(timezone.utc) - timedelta(days=KEEP_BARS_DAYS)).isoformat()
    rows = conn.execute(
        "SELECT timestamp, open, high, low, close, volume FROM price_1m"
        " WHERE symbol=? AND timestamp>=? ORDER BY timestamp",
        (symbol, cutoff)).fetchall()
    if not rows:
        return 0

    # Build aligned bars ({ts}: first open, max high, min low, last close, sum volume)
    bars: dict[int, list] = {}
    order: list[int] = []
    for r in rows:
        b = _bucket_epoch(r["timestamp"], minutes)
        if b not in bars:
            bars[b] = [r["open"], r["high"], r["low"], r["close"], r["volume"] or 0]
            order.append(b)
        else:
            bars[b][1] = max(bars[b][1], r["high"])
            bars[b][2] = min(bars[b][2], r["low"])
            bars[b][3] = r["close"]
            bars[b][4] += r["volume"] or 0

    n = 0
    now = datetime.now(timezone.utc)
    prune_before = (now - timedelta(days=KEEP_BARS_DAYS)).isoformat()
    conn.execute(f"DELETE FROM {table} WHERE symbol=? AND timestamp<?", (symbol, prune_before))
    for b in order:
        o, h, l, c, v = bars[b]
        ts = datetime.fromtimestamp(b, tz=timezone.utc).isoformat()
        conn.execute(
            f"INSERT OR REPLACE INTO {table} (symbol, timestamp, open, high, low, close, volume)"
            " VALUES (?,?,?,?,?,?,?)",
            (symbol, ts, o, h, l, c, v))
        n += 1
    conn.commit()
    if n and minutes == 5:
        log.info("aggregate %s 5m: %d bars", symbol, n)
    return n


def sweep() -> int:
    conn = _conn()
    symbols = [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM price_1m").fetchall()]
    total = 0
    for sym in symbols:
        for minutes in (5, 15):
            total += aggregate_symbol(conn, sym, minutes)
    conn.close()
    log.info("aggregate sweep: %d symbols, %d bars", len(symbols), total)
    return total


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    print(sweep())