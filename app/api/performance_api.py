#!/usr/bin/env python3
"""Day-wise performance report for every live scanner.

Read-only aggregation across the scanner databases. This module never writes
to a database, never places orders, and adds no trading behaviour — it only
reports closed-trade P&L per calendar day.

Endpoint:
    GET /api/performance/daily?days=30
    GET /api/performance/daily?from=2026-11-01&to=2026-11-18

All table and column names below are constants; request parameters are used
only as bound values (dates / integers).
"""

from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from flask import Blueprint, jsonify, request

bp = Blueprint("performance_api", __name__)

IST = ZoneInfo("Asia/Kolkata")
BASE = os.environ.get("TRADINGAI_BASE", "/opt/tradingai")
DB_DIR = os.path.join(BASE, "database")

# Both the trailing stop and the fixed stop-loss were fully live for every
# scanner from 2026-11-16 (2026-11-13 was a transition day that still had
# same-candle exits). Older trades stay in the databases but are not shown
# on the website.
REPORT_START = date(2026, 11, 16)

# key -> database/table metadata. `date_col` may be an expression.
SCANNERS = [
    {
        "key": "sma9_short",
        "label": "SMA9 SHORT",
        "db": "sma9_short.db",
        "table": "sma9_short_trades",
        "date_col": "trade_date",
        "where": "status = 'CLOSED'",
        "open_table": "sma9_short_open_positions",
        "min_date": "2026-11-25",
    },
    {
        "key": "sma9",
        "label": "SMA9",
        "db": "sma9.db",
        "table": "sma9_trades",
        "date_col": "trade_date",
        "where": "status = 'CLOSED'",
        "open_table": "sma9_open_positions",
    },
    {
        "key": "sma9_5min",
        "label": "SMA9 5min",
        "db": "sma9_5min.db",
        "table": "sma9_5min_trades",
        "date_col": "trade_date",
        "where": "status = 'CLOSED'",
        "open_table": "sma9_5min_open_positions",
    },
    {
        "key": "sma9_adx",
        "label": "SMA9 ADX",
        "db": "sma9_adx.db",
        "table": "sma9_adx_trades",
        "date_col": "trade_date",
        "where": "status = 'CLOSED'",
        "open_table": "sma9_adx_open_positions",
        # New standalone scanner; first live day 2026-11-22.
        "min_date": "2026-11-22",
    },
    {
        "key": "sma9_atr",
        "label": "SMA9 ATR",
        "db": "sma9_atr.db",
        "table": "sma9_atr_trades",
        "date_col": "trade_date",
        "where": "status = 'CLOSED'",
        "open_table": "sma9_atr_open_positions",
        # Standalone volatility-scaled-stop scanner; first live day 2026-11-19.
        "min_date": "2026-11-19",
    },
    {
        "key": "sma9_high",
        "label": "SMA9 HIGH",
        "db": "sma9_high.db",
        "table": "sma9_high_trades",
        "date_col": "trade_date",
        "where": "status = 'CLOSED'",
        "open_table": "sma9_high_open_positions",
    },
    {
        "key": "sma9_5pct_trail",
        "label": "SMA9 5% Trail",
        "db": "sma9_5pct_trail.db",
        "table": "sma9_5pct_trail_trades",
        "date_col": "trade_date",
        "where": "status = 'CLOSED'",
        "open_table": "sma9_5pct_trail_open_positions",
        # Fresh standalone scanner; first live day 2026-11-25.
        "min_date": "2026-11-25",
    },
    {
        "key": "sma9_trail",
        "label": "SMA9 Trail",
        "db": "sma9_trail.db",
        "table": "sma9_trail_trades",
        "date_col": "trade_date",
        "where": "status = 'CLOSED'",
        "open_table": "sma9_trail_open_positions",
    },
    {
        "key": "sma9_high_trail",
        "label": "SMA9 HIGH Trail",
        "db": "sma9_high_trail.db",
        "table": "sma9_high_trail_trades",
        "date_col": "trade_date",
        "where": "status = 'CLOSED'",
        "open_table": "sma9_high_trail_open_positions",
    },
]


def _connect(db_name: str) -> sqlite3.Connection:
    path = os.path.join(DB_DIR, db_name)
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def _scan_daily(scanner: dict, start: str, end: str) -> list[dict]:
    """Closed-trade aggregates per day for one scanner."""
    date_col = scanner["date_col"]
    # A scanner may have a later verified start than the report-wide start.
    if scanner.get("min_date") and start < scanner["min_date"]:
        start = scanner["min_date"]
    sql = f"""
        SELECT {date_col} AS day,
               COUNT(*) AS trades,
               SUM(CASE WHEN COALESCE(pnl_points, 0) > 0 THEN 1 ELSE 0 END) AS wins,
               SUM(CASE WHEN COALESCE(pnl_points, 0) < 0 THEN 1 ELSE 0 END) AS losses,
               SUM(CASE WHEN COALESCE(pnl_points, 0) = 0 THEN 1 ELSE 0 END) AS flat,
               ROUND(SUM(COALESCE(pnl_points, 0)), 2) AS pnl_points,
               ROUND(AVG(COALESCE(pnl_points, 0)), 2) AS avg_pnl,
               ROUND(MAX(COALESCE(pnl_points, 0)), 2) AS best,
               ROUND(MIN(COALESCE(pnl_points, 0)), 2) AS worst
        FROM {scanner["table"]}
        WHERE {scanner["where"]}
          AND {date_col} BETWEEN ? AND ?
        GROUP BY day
        ORDER BY day
    """
    conn = _connect(scanner["db"])
    try:
        rows = conn.execute(sql, (start, end)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def _open_count(scanner: dict) -> int:
    """Currently open positions for one scanner."""
    if scanner.get("open_table"):
        sql = f"SELECT COUNT(*) FROM {scanner['open_table']}"
        args: tuple = ()
    else:
        sql = (f"SELECT COUNT(*) FROM {scanner['table']} "
               f"WHERE {scanner['open_where']}")
        args = ()
    conn = _connect(scanner["db"])
    try:
        row = conn.execute(sql, args).fetchone()
        return int(row[0] or 0)
    finally:
        conn.close()


def _totals(items: list[dict]) -> dict:
    trades = sum(int(i.get("trades") or 0) for i in items)
    wins = sum(int(i.get("wins") or 0) for i in items)
    losses = sum(int(i.get("losses") or 0) for i in items)
    flat = sum(int(i.get("flat") or 0) for i in items)
    pnl = round(sum(float(i.get("pnl_points") or 0) for i in items), 2)
    return {
        "trades": trades,
        "wins": wins,
        "losses": losses,
        "flat": flat,
        "pnl_points": pnl,
        "win_rate": round(wins / trades * 100, 2) if trades else 0.0,
        "avg_pnl": round(pnl / trades, 2) if trades else 0.0,
    }


@bp.route("/api/performance/daily", methods=["GET"])
def daily_performance():
    """Day-wise closed-trade performance for all scanners (read-only)."""
    today = datetime.now(IST).date()
    raw_from = (request.args.get("from") or "").strip()
    raw_to = (request.args.get("to") or "").strip()
    raw_days = (request.args.get("days") or "30").strip()

    try:
        end = date.fromisoformat(raw_to) if raw_to else today
        if raw_from:
            start = date.fromisoformat(raw_from)
        else:
            n = max(1, min(int(raw_days), 3650))
            start = end - timedelta(days=n - 1)
    except (ValueError, TypeError):
        return jsonify({
            "success": False,
            "error": "invalid 'days' or date; use days=30 or from=YYYY-MM-DD&to=YYYY-MM-DD",
        }), 400

    if start > end:
        return jsonify({"success": False,
                        "error": "'from' must be on or before 'to'"}), 400

    # Never report trades from before the unified SL + trail model.
    if start < REPORT_START:
        start = REPORT_START
    if end < REPORT_START:
        return jsonify({
            "success": True,
            "from": REPORT_START.isoformat(),
            "to": REPORT_START.isoformat(),
            "report_start": REPORT_START.isoformat(),
            "generated_at": datetime.now(IST).isoformat(),
            "scanners": [{"key": s["key"], "label": s["label"]} for s in SCANNERS],
            "days": [],
            "summary": [],
            "totals": {"trades": 0, "wins": 0, "losses": 0, "flat": 0,
                       "pnl_points": 0.0, "win_rate": 0.0, "avg_pnl": 0.0},
        })

    start_s, end_s = start.isoformat(), end.isoformat()

    by_day: dict[str, dict] = {}
    summary: list[dict] = []

    for scanner in SCANNERS:
        item = {
            "key": scanner["key"],
            "label": scanner["label"],
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "flat": 0,
            "pnl_points": 0.0,
            "win_rate": 0.0,
            "avg_pnl": 0.0,
            "best": 0.0,
            "worst": 0.0,
            "active": 0,
            "error": None,
        }
        try:
            rows = _scan_daily(scanner, start_s, end_s)
            item["active"] = _open_count(scanner)
        except Exception as exc:  # missing DB/table must not break the report
            rows = []
            item["error"] = f"{type(exc).__name__}: {exc}"

        best = None
        worst = None
        for row in rows:
            day = row.get("day")
            if not day:
                continue
            day = str(day)
            by_day.setdefault(day, {"date": day, "scanners": {}})
            by_day[day]["scanners"][scanner["key"]] = row
            item["trades"] += int(row.get("trades") or 0)
            item["wins"] += int(row.get("wins") or 0)
            item["losses"] += int(row.get("losses") or 0)
            item["flat"] += int(row.get("flat") or 0)
            item["pnl_points"] += float(row.get("pnl_points") or 0)
            if row.get("best") is not None:
                best = row["best"] if best is None else max(best, row["best"])
            if row.get("worst") is not None:
                worst = row["worst"] if worst is None else min(worst, row["worst"])

        item["pnl_points"] = round(item["pnl_points"], 2)
        item["win_rate"] = (round(item["wins"] / item["trades"] * 100, 2)
                            if item["trades"] else 0.0)
        item["avg_pnl"] = (round(item["pnl_points"] / item["trades"], 2)
                           if item["trades"] else 0.0)
        item["best"] = best if best is not None else 0.0
        item["worst"] = worst if worst is not None else 0.0
        summary.append(item)

    days = []
    for day in sorted(by_day.keys(), reverse=True):
        entry = by_day[day]
        cells = list(entry["scanners"].values())
        days.append({
            "date": day,
            "scanners": entry["scanners"],
            "total": _totals(cells),
        })

    return jsonify({
        "success": True,
        "from": start_s,
        "to": end_s,
        "report_start": REPORT_START.isoformat(),
        "generated_at": datetime.now(IST).isoformat(),
        "scanners": [{"key": s["key"], "label": s["label"]} for s in SCANNERS],
        "days": days,
        "summary": summary,
        "totals": _totals(summary),
    })
