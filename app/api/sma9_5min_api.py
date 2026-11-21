"""Read-only API for the isolated `sma9_5min` paper scanner.

The scanner owns `database/sma9_5min.db`; this blueprint never writes to it.
It exposes the same eight endpoints as the newer premium-scanner APIs, with
identity and cadence fields for the aligned 5-minute poll.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Blueprint, jsonify, request

bp = Blueprint("sma9_5min_api", __name__)

DB_PATH = os.environ.get(
    "SMA9_5MIN_DB_PATH", "/opt/tradingai/database/sma9_5min.db"
)
STRATEGY_ID = "sma9_5min"
STRATEGY_NAME = "SMA9 5min - ATM Option Strike (BUY ONLY)"
STRATEGY_VERSION = "1.0.0"
STRATEGY_TYPE = "SMA9_5MIN_BUY_ONLY"
POLL_SECONDS = 300
POLL_ALIGNMENT = "5m_boundary_plus_10s"

# One missed aligned poll plus slack; closed-market heartbeat is allowed longer.
ACTIVE_MAX_AGE_SEC = 420
IDLE_CLOSED_MAX_AGE_SEC = 900


def _conn() -> sqlite3.Connection:
    """Open the scanner DB read-only; never create it from the API process."""
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"database not found: {DB_PATH}")
    conn = sqlite3.connect(
        f"file:{DB_PATH}?mode=ro", uri=True, timeout=10
    )
    conn.row_factory = sqlite3.Row
    return conn


def _live_state() -> dict:
    """Read the scanner heartbeat row, or {} when unavailable."""
    try:
        with closing(_conn()) as conn:
            row = conn.execute(
                "SELECT value, updated_at FROM sma9_5min_scan_state "
                "WHERE key='live_status'"
            ).fetchone()
        if not row:
            return {}
        state = json.loads(row["value"])
        state["_state_updated_at"] = row["updated_at"]
        return state
    except Exception:
        return {}


def _health(state: dict) -> tuple[str, float | None]:
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    last = state.get("last_scan_at")
    age = None
    if last:
        try:
            age = (now - datetime.fromisoformat(last)).total_seconds()
        except Exception:
            age = None
    market_open = bool(state.get("market_open"))
    if last is None:
        status = "NOT_RUNNING"
    elif market_open and age is not None and age <= ACTIVE_MAX_AGE_SEC:
        status = "ACTIVE"
    elif market_open and age is not None and age > ACTIVE_MAX_AGE_SEC:
        status = "STALE"
    elif not market_open and age is not None and age <= IDLE_CLOSED_MAX_AGE_SEC:
        status = "IDLE_MARKET_CLOSED"
    else:
        status = "STOPPED"
    return status, age


@bp.route("/api/sma9-5min/signals", methods=["GET"])
def signals():
    try:
        limit = min(int(request.args.get("limit", 100)), 1000)
        offset = int(request.args.get("offset", 0))
        option_type = request.args.get("option_type")
        trade_date = request.args.get("trade_date")
        dataset = request.args.get("dataset")

        query = "SELECT * FROM sma9_5min_trades WHERE 1=1"
        params: list = []
        if option_type:
            query += " AND option_type = ?"
            params.append(option_type.upper())
        if trade_date:
            query += " AND trade_date = ?"
            params.append(trade_date)
        if dataset:
            query += " AND dataset = ?"
            params.append(dataset)

        with closing(_conn()) as conn:
            total = conn.execute(
                query.replace("SELECT *", "SELECT COUNT(*)", 1), params
            ).fetchone()[0]
            rows = conn.execute(
                query + " ORDER BY signal_timestamp DESC LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()
        result = [dict(row) for row in rows]
        return jsonify({
            "success": True,
            "signals": result,
            "trades": result,
            "count": len(result),
            "total": total,
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@bp.route("/api/sma9-5min/trades", methods=["GET"])
def trades():
    return signals()


@bp.route("/api/sma9-5min/daily-summary", methods=["GET"])
def daily_summary():
    try:
        dataset = request.args.get("dataset")
        query = """
            SELECT trade_date as date,
                   COUNT(*) as total_trades,
                   SUM(CASE WHEN pnl_points > 0 THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN pnl_points < 0 THEN 1 ELSE 0 END) as losses,
                   SUM(pnl_points) as total_pnl_points,
                   ROUND(AVG(pnl_points), 2) as avg_pnl,
                   GROUP_CONCAT(DISTINCT dataset) as datasets
            FROM sma9_5min_trades
        """
        params: list = []
        if dataset:
            query += " WHERE dataset = ?"
            params.append(dataset)
        query += " GROUP BY trade_date ORDER BY trade_date DESC"
        with closing(_conn()) as conn:
            daily = [dict(row) for row in conn.execute(query, params).fetchall()]
        for item in daily:
            item["win_rate"] = (
                round(item["wins"] / item["total_trades"] * 100, 2)
                if item["total_trades"] else 0
            )
        return jsonify({
            "success": True,
            "daily": daily,
            "dataset": dataset or "ALL",
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@bp.route("/api/sma9-5min/scanner-status", methods=["GET"])
def scanner_status():
    try:
        dataset = request.args.get("dataset")
        query = (
            "SELECT COUNT(*) as total_trades, SUM(pnl_points) as total_pnl, "
            "SUM(CASE WHEN pnl_points > 0 THEN 1 ELSE 0 END) as wins, "
            "SUM(CASE WHEN pnl_points < 0 THEN 1 ELSE 0 END) as losses "
            "FROM sma9_5min_trades"
        )
        params: list = []
        if dataset:
            query += " WHERE dataset = ?"
            params.append(dataset)
        with closing(_conn()) as conn:
            row = conn.execute(query, params).fetchone()
        total = row["total_trades"] or 0
        wins = row["wins"] or 0
        losses = row["losses"] or 0
        total_pnl = row["total_pnl"] or 0

        state = _live_state()
        status, age = _health(state)
        return jsonify({
            "success": True,
            "scanner_id": STRATEGY_ID,
            "scanner_name": state.get("scanner_name", STRATEGY_NAME),
            "scanner_version": state.get("scanner_version", STRATEGY_VERSION),
            "strategy_type": state.get("strategy_type", STRATEGY_TYPE),
            "instrument": "NIFTY",
            "timeframe": "5m",
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / total * 100, 2) if total else 0,
            "total_pnl": round(total_pnl, 2),
            "status": status,
            "last_scan_at": state.get("last_scan_at"),
            "last_scan_age_seconds": round(age, 1) if age is not None else None,
            "poll_seconds": state.get("poll_seconds", POLL_SECONDS),
            "poll_alignment": state.get("poll_alignment", POLL_ALIGNMENT),
            "actual_interval_seconds": state.get("actual_interval_seconds"),
            "market_open": state.get("market_open"),
            "spot": state.get("spot"),
            "atm_strike": state.get("atm_strike"),
            "last_closed_spot": state.get("last_closed_spot"),
            "last_closed_atm_strike": state.get("last_closed_atm_strike"),
            "last_closed_candle_start": state.get("last_closed_candle_start"),
            "last_closed_ce_close": state.get("last_closed_ce_close"),
            "last_closed_pe_close": state.get("last_closed_pe_close"),
            "last_closed_spot_source": state.get("last_closed_spot_source"),
            "expiry": state.get("expiry"),
            "options": state.get("options", {}),
            "today": state.get("today", {}),
            "errors": state.get("errors", []),
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@bp.route("/api/sma9-5min/live-status", methods=["GET"])
def live_status():
    state = _live_state()
    if not state:
        return jsonify({
            "success": False,
            "status": "NOT_RUNNING",
            "error": "No scanner heartbeat found",
            "poll_seconds": POLL_SECONDS,
            "poll_alignment": POLL_ALIGNMENT,
        }), 200
    status, age = _health(state)
    state["status"] = status
    state["last_scan_age_seconds"] = round(age, 1) if age is not None else None
    state["server_time"] = datetime.now(ZoneInfo("Asia/Kolkata")).isoformat()
    return jsonify({"success": True, "data": state})


@bp.route("/api/sma9-5min/recent-trades", methods=["GET"])
def recent_trades():
    try:
        limit = min(int(request.args.get("limit", 50)), 500)
        dataset = request.args.get("dataset")
        trade_date = request.args.get("trade_date")
        query = "SELECT * FROM sma9_5min_trades WHERE 1=1"
        params: list = []
        if dataset:
            query += " AND dataset = ?"
            params.append(dataset)
        if trade_date:
            query += " AND trade_date = ?"
            params.append(trade_date)
        with closing(_conn()) as conn:
            total = conn.execute(
                query.replace("SELECT *", "SELECT COUNT(*)", 1), params
            ).fetchone()[0]
            rows = conn.execute(
                query + " ORDER BY signal_timestamp DESC LIMIT ?",
                params + [limit],
            ).fetchall()
        result = [dict(row) for row in rows]
        return jsonify({
            "success": True,
            "trades": result,
            "count": len(result),
            "total": total,
            "dataset": dataset or "ALL",
            "trade_date": trade_date,
        })
    except Exception as exc:
        return jsonify({
            "success": False, "trades": [], "error": str(exc)
        }), 500


@bp.route("/api/sma9-5min/open-positions", methods=["GET"])
def open_positions():
    try:
        with closing(_conn()) as conn:
            rows = conn.execute(
                "SELECT * FROM sma9_5min_open_positions "
                "ORDER BY entry_timestamp"
            ).fetchall()
        positions = [dict(row) for row in rows]
        return jsonify({
            "success": True,
            "positions": positions,
            "count": len(positions),
        })
    except Exception as exc:
        return jsonify({
            "success": False, "positions": [], "error": str(exc)
        }), 500


@bp.route("/api/sma9-5min/today", methods=["GET"])
def today():
    try:
        trade_date = request.args.get("trade_date") or datetime.now(
            ZoneInfo("Asia/Kolkata")
        ).date().isoformat()
        with closing(_conn()) as conn:
            rows = conn.execute(
                "SELECT * FROM sma9_5min_trades "
                "WHERE dataset='LIVE' AND trade_date=? "
                "ORDER BY signal_timestamp DESC",
                (trade_date,),
            ).fetchall()
        trades = [dict(row) for row in rows]
        return jsonify({
            "success": True,
            "trade_date": trade_date,
            "trades": trades,
            "count": len(trades),
            "wins": sum(1 for t in trades if (t["pnl_points"] or 0) > 0),
            "losses": sum(1 for t in trades if (t["pnl_points"] or 0) < 0),
            "pnl_points": round(
                sum(t["pnl_points"] or 0 for t in trades), 2
            ),
            "is_today": True,
        })
    except Exception as exc:
        return jsonify({
            "success": False, "error": str(exc), "trades": []
        }), 500
