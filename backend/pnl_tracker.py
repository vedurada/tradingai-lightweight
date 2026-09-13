from __future__ import annotations

"""Daily paper-trade P&L tracker for indexes, gated by the AI Market Outlook.

AI-gated trading (from the previous session's outlook verdict):
- `evaluate`: intraday (every 5 min) — only locks an entry when the outlook says
  TRADE AND the strategy's intraday trigger fires (e.g. rally into resistance,
  then rejection). No row is written when the AI does not confirm a trade.
- `lock`  : 9:30 AM fallback — records a 9:30 entry ONLY when the outlook verdict
  is TRADE (Option A gate). No row is written for non-TRADE verdicts.
- `close` : 3:20 PM exit for locked trades.
- `backfill [YYYY-MM-DD]`: rebuild a past day from stored 1m candles (AI-gated).
- `archive [days]`: monthly archival of settled rows older than `days`.

Usage:
    python3 pnl_tracker.py evaluate
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


def _exit_candle(conn: sqlite3.Connection, symbol: str, date_str: str, exit_label: str = EXIT_LABEL):
    """Strict 3:20 PM exit candle; fallback to last candle of the day."""
    row = conn.execute(
        "SELECT close, timestamp FROM price_1m WHERE symbol=? AND timestamp LIKE ? ORDER BY timestamp ASC LIMIT 1",
        (symbol, f"{date_str} {exit_label}%"),
    ).fetchone()
    if row:
        return (row["close"], row["timestamp"])
    return _last_candle_of_day(conn, symbol, date_str)


def _direction_from_bias(bias: str) -> str:
    b = (bias or "").upper()
    if "BEAR" in b or b == "SELL":
        return "SHORT"
    return "LONG"


def _settle(entry_price: float, exit_price: float, direction: str) -> tuple[float, str]:
    if direction == "SHORT":
        points = round(entry_price - exit_price, 2)
    else:
        points = round(exit_price - entry_price, 2)
    result = "WIN" if points > 0 else ("LOSS" if points < 0 else "FLAT")
    return points, result


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


def _ist_now_hhmm() -> str:
    return datetime.now(IST).strftime("%H:%M")


def _latest_gate(conn: sqlite3.Connection, symbol: str, date_str: str) -> tuple:
    """Latest AI outlook published BEFORE date_str (gates that session). Returns (outlook_date, verdict, payload)."""
    row = conn.execute(
        "SELECT date, payload FROM market_outlooks WHERE UPPER(symbol)=UPPER(?) AND date < ? ORDER BY date DESC LIMIT 1",
        (symbol, date_str),
    ).fetchone()
    if not row:
        return None, None, None
    try:
        payload = json.loads(row["payload"])
    except Exception:
        return None, None, None
    verdict = ((payload.get("decision") or {}).get("verdict") or "").upper()
    return row["date"], verdict, payload


def _entry_outlook_snapshot(conn: sqlite3.Connection, symbol: str, date_str: str) -> str | None:
    """Latest stored AI outlook for the symbol at/after the entry date, as compact JSON (for future reference)."""
    try:
        row = conn.execute(
            "SELECT date, payload FROM market_outlooks WHERE UPPER(symbol)=UPPER(?) AND date<=? ORDER BY date DESC LIMIT 1",
            (symbol, date_str),
        ).fetchone()
        if not row:
            return None
        p = json.loads(row["payload"])
        strategies = p.get("strategies") or []
        return json.dumps({
            "date": row["date"],
            "verdict": (p.get("decision") or {}).get("verdict"),
            "regime": (p.get("regime") or {}).get("primary"),
            "bias": (p.get("bias") or {}).get("label"),
            "confidence": p.get("confidence"),
            "expected_range": p.get("expected_range"),
            "strategies": [s.get("name") for s in strategies if s.get("name")],
        }, ensure_ascii=False)
    except Exception:
        return None


def _snapshot_from_gate(payload: dict | None, fallback: dict) -> dict:
    if not payload:
        return fallback
    strategies = payload.get("strategies") or []
    s1 = strategies[0] if strategies else {}
    return {
        "strategy": s1.get("name") or "",
        "regime": (payload.get("regime") or {}).get("primary") or "",
        "bias": (payload.get("bias") or {}).get("label") or "",
        "confidence": payload.get("confidence") or 0,
        "summary": ((payload.get("decision") or {}).get("primary_view") or "")[:500],
    }


def _upsert_entry(conn: sqlite3.Connection, symbol: str, date_str: str, entry_time: str, entry_price: float, snap: dict) -> None:
    direction = _direction_from_bias(snap["bias"])
    outlook_snap = _entry_outlook_snapshot(conn, symbol, date_str)
    conn.execute(
        """INSERT INTO history (symbol, date, locked_price, closed_price, entry_time, exit_time, direction, points, result,
                strategy, market_regime, directional_bias, confidence, market_summary, entry_outlook, created_at)
           VALUES (?, ?, ?, NULL, ?, NULL, ?, NULL, 'OPEN', ?, ?, ?, ?, ?, ?, datetime('now'))
           ON CONFLICT(symbol, date) DO UPDATE SET
                locked_price=excluded.locked_price, entry_time=excluded.entry_time,
                direction=excluded.direction,
                strategy=excluded.strategy, market_regime=excluded.market_regime,
                directional_bias=excluded.directional_bias, confidence=excluded.confidence,
                market_summary=excluded.market_summary, no_trade_conditions=NULL,
                entry_outlook=COALESCE(excluded.entry_outlook, history.entry_outlook)""",
        (symbol, date_str, round(float(entry_price), 2), entry_time, direction,
         snap["strategy"], snap["regime"], snap["bias"], snap["confidence"], snap["summary"], outlook_snap),
    )
    print(f"entry {symbol} {date_str} {entry_time}: {direction} entry={round(float(entry_price), 2)} ({snap['strategy'] or snap['regime']})")


def _scan_trigger(conn: sqlite3.Connection, symbol: str, date_str: str, payload: dict | None,
                  now_hhmm: str | None = None) -> tuple:
    """Option B entry: scan today's 1m candles for the strategy trigger. Returns (HH:MM, price) or (None, None)."""
    entry_hhmm = now_hhmm or _ist_now_hhmm()
    scan_through = min(entry_hhmm, "14:45")
    strategies = (payload or {}).get("strategies") or []
    trig = next((s.get("entry_trigger") for s in strategies if s.get("entry_trigger")), None)
    if not trig or trig.get("mode") != "rally_into_resistance":
        return None, None
    zone = trig.get("zone") or {}
    lo = zone.get("lower")
    if lo is None:
        return None, None
    rows = conn.execute(
        "SELECT timestamp, high, low, close FROM price_1m WHERE symbol=? AND timestamp LIKE ? ORDER BY timestamp ASC",
        (symbol, f"{date_str}%"),
    ).fetchall()
    touched = False
    start = "09:15"
    for r in rows:
        hhmm = (r["timestamp"] or "")[11:16]
        if not hhmm or hhmm < start or hhmm > scan_through:
            continue
        hi, cl = r["high"], r["close"]
        if hi is None or cl is None:
            continue
        if not touched and hi >= lo:
            touched = True
        elif touched and cl < lo:
            return hhmm, cl
    return None, None


def evaluate(date_str: str | None = None) -> None:
    """AI-gated intraday entry (Option B). Runs repeatedly; idempotent per day."""
    date_str = date_str or _ist_today()
    conn = _conn()
    now_hhmm = _ist_now_hhmm()
    for symbol in INDEX_SYMBOLS:
        gate_date, verdict, payload = _latest_gate(conn, symbol, date_str)
        snap = _snapshot_from_gate(payload, _snapshot(conn, symbol))
        if gate_date is None:
            print(f"evaluate {symbol} {date_str}: no prior outlook, no AI gate → skipped")
            continue
        if verdict != "TRADE":
            reason = f"AI verdict {verdict} ({gate_date} outlook) — no fresh exposure."
            print(f"evaluate {symbol} {date_str}: {reason} (not logged)")
            continue
        entry_time, entry_price = _scan_trigger(conn, symbol, date_str, payload, now_hhmm)
        if entry_time is None:
            if now_hhmm >= "14:45":
                print(f"evaluate {symbol} {date_str}: TRADE but entry trigger never fired by 14:45 (not logged)")
            else:
                print(f"evaluate {symbol} {date_str}: TRADE, trigger not fired yet ({now_hhmm}) — waiting")
            continue
        _upsert_entry(conn, symbol, date_str, entry_time, entry_price, snap)
        lock_strategy(conn, symbol, date_str)
    conn.commit()
    conn.close()


def lock(date_str: str | None = None, entry_label: str = ENTRY_LABEL) -> None:
    """Record 9:30 AM entry prices for all indexes, gated by AI outlook verdict (Option A)."""
    date_str = date_str or _ist_today()
    conn = _conn()
    for symbol in INDEX_SYMBOLS:
        gate_date, verdict, payload = _latest_gate(conn, symbol, date_str)
        snap = _snapshot_from_gate(payload, _snapshot(conn, symbol))
        if gate_date is not None and verdict != "TRADE":
            print(f"lock {symbol} {date_str}: AI verdict {verdict} ({gate_date} outlook) — no fresh exposure (not logged)")
            continue
        price, ts = _candle_price(conn, symbol, date_str, "09:30")
        if price is None:
            price, ts = _latest_price(conn, symbol)
        if price is None:
            print(f"lock {symbol} {date_str}: no price available, skipped")
            continue
        _upsert_entry(conn, symbol, date_str, entry_label, float(price), snap)
        lock_strategy(conn, symbol, date_str)
    conn.commit()
    conn.close()


def lock_strategy(conn: sqlite3.Connection, symbol: str, date_str: str | None = None) -> None:
    """Freeze the day's strategy from the 9:30 AM outlook (indexes only)."""
    from zoneinfo import ZoneInfo as _ZI
    date_str = date_str or datetime.now(_ZI("Asia/Kolkata")).strftime("%Y-%m-%d")
    strat_row = conn.execute("SELECT * FROM strategies WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
    regime_row = conn.execute("SELECT regime, confidence FROM market_regime WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
    outlook_row = conn.execute("SELECT outlook FROM ai_outlooks WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
    if not strat_row:
        print(f"lock-strategy {symbol} {date_str}: no strategy row, skipped")
        return
    try:
        legs = json.loads(dict(strat_row).get("legs") or "{}")
        strategies = legs.get("all_strategies", []) if isinstance(legs, dict) else []
    except Exception:
        strategies = []
    if not strategies:
        s = dict(strat_row).get("strategy", "")
        strategies = [{"strategy": s}] if s else []
    bias = ""
    try:
        o = json.loads(dict(outlook_row)["outlook"]) if outlook_row and dict(outlook_row).get("outlook") else {}
        bias = o.get("directional_bias", "") if isinstance(o, dict) else ""
    except Exception:
        pass
    conn.execute(
        """INSERT INTO daily_strategy (symbol, date, strategy_json, regime, confidence, bias, locked_at, created_at)
           VALUES (?, ?, ?, ?, ?, ?, '09:30', datetime('now'))
           ON CONFLICT(symbol, date) DO UPDATE SET
                strategy_json=excluded.strategy_json, regime=excluded.regime,
                confidence=excluded.confidence, bias=excluded.bias""",
        (symbol, date_str, json.dumps(strategies),
         (dict(regime_row).get("regime", "") if regime_row else ""),
         (dict(regime_row).get("confidence", 0) if regime_row else 0), bias),
    )
    conn.commit()
    print(f"lock-strategy {symbol} {date_str}: {(strategies[0].get('strategy') if strategies else 'none')}")


def close(date_str: str | None = None, exit_label: str = EXIT_LABEL) -> None:
    """Record 3:20 PM exit prices and settle points/result for all indexes."""
    date_str = date_str or _ist_today()
    conn = _conn()
    for symbol in INDEX_SYMBOLS:
        price, ts = _exit_candle(conn, symbol, date_str, exit_label)
        if price is None:
            price, ts = _latest_price(conn, symbol)
        if price is None:
            print(f"close {symbol} {date_str}: no price available, skipped")
            continue
        exit_price = round(float(price), 2)
        row = conn.execute("SELECT locked_price, directional_bias, direction, result FROM history WHERE symbol=? AND date=?", (symbol, date_str)).fetchone()
        if row and (row["result"] or "").upper() == "NO_TRADE":
            print(f"close {symbol} {date_str}: NO_TRADE row — left untouched")
            continue
        if row and row["locked_price"]:
            entry_price = float(row["locked_price"])
            direction = (row["direction"] if "direction" in row.keys() and row["direction"] else None) or _direction_from_bias(row["directional_bias"] if "directional_bias" in row.keys() else "")
            points, result = _settle(entry_price, exit_price, direction)
            conn.execute(
                "UPDATE history SET closed_price=?, exit_time=?, direction=?, points=?, result=? WHERE symbol=? AND date=?",
                (exit_price, exit_label, direction, points, result, symbol, date_str),
            )
            print(f"close {symbol} {date_str} {exit_label}: {direction} entry={entry_price} exit={exit_price} points={points:+} {result}")
        else:
            outlook_snap = _entry_outlook_snapshot(conn, symbol, date_str)
            conn.execute(
                """INSERT INTO history (symbol, date, locked_price, closed_price, entry_time, exit_time, points, result, entry_outlook, created_at)
                   VALUES (?, ?, NULL, ?, NULL, ?, NULL, 'OPEN', ?, datetime('now'))
                   ON CONFLICT(symbol, date) DO UPDATE SET closed_price=excluded.closed_price, exit_time=excluded.exit_time""",
                (symbol, date_str, exit_price, exit_label, outlook_snap),
            )
            print(f"close {symbol} {date_str} {exit_label}: exit={exit_price} (no entry locked)")
    conn.commit()
    conn.close()


def backfill(date_str: str | None = None) -> None:
    """Rebuild one day from stored 1m candles: AI-gated entry (trigger if fired, else 09:30), last candle exit."""
    date_str = date_str or _ist_today()
    conn = _conn()
    for symbol in INDEX_SYMBOLS:
        gate_date, verdict, payload = _latest_gate(conn, symbol, date_str)
        snap = _snapshot_from_gate(payload, _snapshot(conn, symbol))
        if gate_date is not None and verdict != "TRADE":
            print(f"backfill {symbol} {date_str}: AI verdict {verdict} ({gate_date} outlook) — no fresh exposure (not logged)")
            continue
        entry_time, entry = _scan_trigger(conn, symbol, date_str, payload, now_hhmm="14:45")
        if entry_time is None:
            entry, _ = _candle_price(conn, symbol, date_str, "09:30")
            entry_time = ENTRY_LABEL
        exit_p, _ = _exit_candle(conn, symbol, date_str, EXIT_LABEL)
        if entry is None or exit_p is None:
            print(f"backfill {symbol} {date_str}: missing candles, skipped")
            continue
        entry = round(float(entry), 2)
        exit_p = round(float(exit_p), 2)
        direction = _direction_from_bias(snap["bias"])
        points, result = _settle(entry, exit_p, direction)
        outlook_snap = _entry_outlook_snapshot(conn, symbol, date_str)
        conn.execute(
            """INSERT INTO history (symbol, date, locked_price, closed_price, entry_time, exit_time, direction, points, result,
                    strategy, market_regime, directional_bias, confidence, market_summary, entry_outlook, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(symbol, date) DO UPDATE SET
                    locked_price=excluded.locked_price, closed_price=excluded.closed_price,
                    entry_time=excluded.entry_time, exit_time=excluded.exit_time,
                    direction=excluded.direction,
                    points=excluded.points, result=excluded.result, strategy=excluded.strategy,
                    market_regime=excluded.market_regime, directional_bias=excluded.directional_bias,
                    confidence=excluded.confidence, market_summary=excluded.market_summary,
                    no_trade_conditions=NULL, entry_outlook=COALESCE(excluded.entry_outlook, history.entry_outlook)""",
            (symbol, date_str, entry, exit_p, entry_time, EXIT_LABEL, direction, points, result,
             snap["strategy"], snap["regime"], snap["bias"], snap["confidence"], snap["summary"], outlook_snap),
        )
        print(f"backfill {symbol} {date_str}: {direction} {entry_time} {entry} → {EXIT_LABEL} {exit_p} = {points:+} {result}")
    conn.commit()
    conn.close()


def archive(retention_days: int = 365) -> None:
    """Monthly archival: move settled rows older than retention to history_archive (permanent)."""
    conn = _conn()
    conn.execute(
        """INSERT INTO history_archive (symbol, date, locked_price, closed_price, entry_time, exit_time, direction, points, result,
                strategy, market_regime, directional_bias, confidence, market_summary, entry_outlook, created_at, archived_at)
           SELECT symbol, date, locked_price, closed_price, entry_time, exit_time, direction, points, result,
                strategy, market_regime, directional_bias, confidence, market_summary, entry_outlook, created_at, datetime('now')
           FROM history WHERE closed_price IS NOT NULL AND date <= date('now', '-' || ? || ' days')""",
        (retention_days,),
    )
    n = conn.total_changes
    conn.execute("DELETE FROM history WHERE closed_price IS NOT NULL AND date <= date('now', '-' || ? || ' days')", (retention_days,))
    conn.commit()
    conn.close()
    print(f"archive: moved {n} rows older than {retention_days}d to history_archive")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "close"
    arg = sys.argv[2] if len(sys.argv) > 2 else None
    if cmd == "lock":
        lock(arg)
    elif cmd == "evaluate":
        evaluate(arg)
    elif cmd == "close":
        close(arg)
    elif cmd == "backfill":
        backfill(arg)
    elif cmd == "archive":
        archive(int(arg) if arg and arg.isdigit() else 365)
    else:
        print(__doc__)
