"""Read-only API for the isolated `sma9_live` execution service.

The scanner owns `database/sma9_live.db`; this blueprint never writes to it and
exposes no source paths, credentials or broker keys. It mirrors the paper
scanner endpoints with an additional order-ledger view.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Blueprint, jsonify, request

bp = Blueprint("sma9_live_api", __name__)

DB_PATH = os.environ.get(
    "SMA9_LIVE_DB_PATH", "/opt/tradingai/database/sma9_live.db"
)
STRATEGY_ID = "sma9_live"
STRATEGY_NAME = "SMA9 LIVE - ATM Option Strike (BUY ONLY)"
STRATEGY_VERSION = "1.0.0"
STRATEGY_TYPE = "SMA9_LIVE_BUY_ONLY"
POLL_SECONDS = 5

ACTIVE_MAX_AGE_SEC = 30
IDLE_CLOSED_MAX_AGE_SEC = 900


def _conn() -> sqlite3.Connection:
    """Open the scanner DB read-only; never create it from the API process."""
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"database not found: {DB_PATH}")
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _live_state() -> dict:
    try:
        with closing(_conn()) as conn:
            row = conn.execute(
                "SELECT value, updated_at FROM sma9_live_scan_state "
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


@bp.route("/api/sma9-live/signals", methods=["GET"])
def signals():
    try:
        limit = min(int(request.args.get("limit", 100)), 1000)
        offset = int(request.args.get("offset", 0))
        option_type = request.args.get("option_type")
        trade_date = request.args.get("trade_date")
        query = "SELECT * FROM sma9_live_trades WHERE 1=1"
        params: list = []
        if option_type:
            query += " AND option_type = ?"
            params.append(option_type.upper())
        if trade_date:
            query += " AND trade_date = ?"
            params.append(trade_date)
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
            "success": True, "signals": result, "trades": result,
            "count": len(result), "total": total,
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@bp.route("/api/sma9-live/trades", methods=["GET"])
def trades():
    return signals()


@bp.route("/api/sma9-live/recent-trades", methods=["GET"])
def recent_trades():
    try:
        limit = min(int(request.args.get("limit", 50)), 500)
        trade_date = request.args.get("trade_date")
        query = "SELECT * FROM sma9_live_trades WHERE 1=1"
        params: list = []
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
        return jsonify({
            "success": True, "trades": [dict(r) for r in rows],
            "count": len(rows), "total": total, "trade_date": trade_date,
        })
    except Exception as exc:
        return jsonify({"success": False, "trades": [], "error": str(exc)}), 500


@bp.route("/api/sma9-live/daily-summary", methods=["GET"])
def daily_summary():
    try:
        query = """
            SELECT trade_date as date, COUNT(*) as total_trades,
                   SUM(CASE WHEN pnl_points > 0 THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN pnl_points < 0 THEN 1 ELSE 0 END) as losses,
                   SUM(pnl_points) as total_pnl_points,
                   ROUND(AVG(pnl_points), 2) as avg_pnl
            FROM sma9_live_trades GROUP BY trade_date ORDER BY trade_date DESC
        """
        with closing(_conn()) as conn:
            daily = [dict(row) for row in conn.execute(query).fetchall()]
        for item in daily:
            item["win_rate"] = (
                round(item["wins"] / item["total_trades"] * 100, 2)
                if item["total_trades"] else 0
            )
        return jsonify({"success": True, "daily": daily})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@bp.route("/api/sma9-live/today", methods=["GET"])
def today():
    try:
        trade_date = request.args.get("trade_date") or datetime.now(
            ZoneInfo("Asia/Kolkata")
        ).date().isoformat()
        with closing(_conn()) as conn:
            rows = conn.execute(
                "SELECT * FROM sma9_live_trades WHERE trade_date=? "
                "ORDER BY signal_timestamp DESC", (trade_date,),
            ).fetchall()
        trades = [dict(row) for row in rows]
        return jsonify({
            "success": True, "trade_date": trade_date, "trades": trades,
            "count": len(trades),
            "wins": sum(1 for t in trades if (t["pnl_points"] or 0) > 0),
            "losses": sum(1 for t in trades if (t["pnl_points"] or 0) < 0),
            "pnl_points": round(sum(t["pnl_points"] or 0 for t in trades), 2),
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc), "trades": []}), 500


@bp.route("/api/sma9-live/open-positions", methods=["GET"])
def open_positions():
    try:
        with closing(_conn()) as conn:
            rows = conn.execute(
                "SELECT * FROM sma9_live_open_positions ORDER BY entry_timestamp"
            ).fetchall()
        return jsonify({
            "success": True, "positions": [dict(r) for r in rows],
            "count": len(rows),
        })
    except Exception as exc:
        return jsonify({"success": False, "positions": [], "error": str(exc)}), 500


@bp.route("/api/sma9-live/orders", methods=["GET"])
def orders():
    try:
        limit = min(int(request.args.get("limit", 100)), 1000)
        with closing(_conn()) as conn:
            rows = conn.execute(
                "SELECT * FROM sma9_live_orders "
                "ORDER BY created_at DESC LIMIT ?", (limit,),
            ).fetchall()
        return jsonify({"success": True, "orders": [dict(r) for r in rows]})
    except Exception as exc:
        return jsonify({"success": False, "orders": [], "error": str(exc)}), 500


@bp.route("/api/sma9-live/scanner-status", methods=["GET"])
def scanner_status():
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
        "status": status,
        "last_scan_at": state.get("last_scan_at"),
        "last_scan_age_seconds": round(age, 1) if age is not None else None,
        "poll_seconds": state.get("poll_seconds", POLL_SECONDS),
        "market_open": state.get("market_open"),
        "spot": state.get("spot"),
        "atm_strike": state.get("atm_strike"),
        "expiry": state.get("expiry"),
        "options": state.get("options", {}),
        "today": state.get("today", {}),
        "execution": state.get("execution", {}),
        "errors": state.get("errors", []),
    })


@bp.route("/api/sma9-live/live-status", methods=["GET"])
def live_status():
    state = _live_state()
    if not state:
        return jsonify({
            "success": False, "status": "NOT_RUNNING",
            "error": "No scanner heartbeat found", "poll_seconds": POLL_SECONDS,
        }), 200
    status, age = _health(state)
    state["status"] = status
    state["last_scan_age_seconds"] = round(age, 1) if age is not None else None
    state["server_time"] = datetime.now(ZoneInfo("Asia/Kolkata")).isoformat()
    return jsonify({"success": True, "data": state})
