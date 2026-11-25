#!/usr/bin/env python3
"""Read-only API for the paper `sma9_short` scanner.

Serves the dedicated `/live/sma9-short/` dashboard from
`database/sma9_short.db`. This module never writes to the database and never
places broker orders.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Blueprint, jsonify, request

bp = Blueprint("sma9_short_api", __name__)

IST = ZoneInfo("Asia/Kolkata")
DB_PATH = os.environ.get(
    "SMA9_SHORT_DB_PATH", "/opt/tradingai/database/sma9_short.db"
)

SCANNER_ID = "sma9_short"
SCANNER_NAME = "SMA9 SHORT - ATM+200 CE / ATM-200 PE (PAPER)"
SCANNER_VERSION = "1.0.0"
STRATEGY_TYPE = "SMA9_SHORT_ONLY"

TRADES_TABLE = "sma9_short_trades"
OPEN_TABLE = "sma9_short_open_positions"
STATE_TABLE = "sma9_short_scan_state"


def _conn():
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=10000")
    except Exception:
        pass
    return conn


def _live_state():
    """Read scanner heartbeat; empty dict when unavailable."""
    try:
        conn = _conn()
        row = conn.execute(
            f"SELECT value, updated_at FROM {STATE_TABLE} "
            "WHERE key='live_status'"
        ).fetchone()
        conn.close()
        if not row:
            return {}
        state = json.loads(row["value"])
        state["_state_updated_at"] = row["updated_at"]
        return state if isinstance(state, dict) else {}
    except Exception:
        return {}


def _health(state):
    now = datetime.now(IST)
    last = state.get("last_scan_at")
    age = None
    if last:
        try:
            age = (now - datetime.fromisoformat(last)).total_seconds()
        except Exception:
            age = None
    heartbeat = state.get("_state_updated_at")
    beat_age = None
    if heartbeat:
        try:
            beat_age = (now - datetime.fromisoformat(heartbeat)).total_seconds()
        except Exception:
            beat_age = None

    market_open = bool(state.get("market_open"))
    if last is None:
        if not market_open and beat_age is not None and beat_age <= 120:
            status = "IDLE_MARKET_CLOSED"
        else:
            status = "NOT_RUNNING"
    # Broker quote calls can occasionally take 20s. Use a 30s window so a slow
    # single poll does not briefly flag a healthy scanner as STALE.
    elif market_open and age is not None and age <= 30:
        status = "ACTIVE"
    elif market_open and age is not None and age > 30:
        status = "STALE"
    elif not market_open and age is not None and age <= 120:
        status = "IDLE_MARKET_CLOSED"
    else:
        status = "STOPPED"
    return status, age


@bp.route("/api/sma9-short/live-status", methods=["GET"])
def live_status():
    state = _live_state()
    if not state:
        return jsonify({
            "success": False,
            "status": "NOT_RUNNING",
            "error": "No scanner heartbeat found",
            "poll_seconds": 5,
        }), 200
    status, age = _health(state)
    state["status"] = status
    state["last_scan_age_seconds"] = round(age, 1) if age is not None else None
    state["server_time"] = datetime.now(IST).isoformat()
    return jsonify({"success": True, "data": state})


@bp.route("/api/sma9-short/scanner-status", methods=["GET"])
def scanner_status():
    try:
        dataset = request.args.get("dataset")
        conn = _conn()
        query = (
            "SELECT COUNT(*) total_trades, COALESCE(SUM(pnl_points),0) total_pnl, "
            "COALESCE(SUM(CASE WHEN pnl_points > 0 THEN 1 ELSE 0 END),0) wins, "
            "COALESCE(SUM(CASE WHEN pnl_points < 0 THEN 1 ELSE 0 END),0) losses "
            f"FROM {TRADES_TABLE}"
        )
        params = []
        if dataset:
            query += " WHERE dataset = ?"
            params.append(dataset)
        row = conn.execute(query, params).fetchone()
        conn.close()

        total = int(row["total_trades"] or 0)
        wins = int(row["wins"] or 0)
        losses = int(row["losses"] or 0)
        total_pnl = float(row["total_pnl"] or 0)
        state = _live_state()
        status, age = _health(state)
        return jsonify({
            "success": True,
            "scanner_id": SCANNER_ID,
            "scanner_name": SCANNER_NAME,
            "scanner_version": SCANNER_VERSION,
            "strategy_type": STRATEGY_TYPE,
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
            "poll_seconds": state.get("poll_seconds", 5),
            "actual_interval_seconds": state.get("actual_interval_seconds"),
            "market_open": state.get("market_open"),
            "spot": state.get("spot"),
            "spot_source": state.get("spot_source"),
            "atm_strike": state.get("atm_strike"),
            "strike_offsets": state.get("strike_offsets", {"CE": 200, "PE": -200}),
            "last_closed_spot": state.get("last_closed_spot"),
            "last_closed_atm_strike": state.get("last_closed_atm_strike"),
            "last_closed_candle_start": state.get("last_closed_candle_start"),
            "last_closed_spot_source": state.get("last_closed_spot_source"),
            "expiry": state.get("expiry"),
            "options": state.get("options", {}),
            "today": state.get("today", {}),
            "errors": state.get("errors", []),
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@bp.route("/api/sma9-short/signals", methods=["GET"])
@bp.route("/api/sma9-short/trades", methods=["GET"])
def signals():
    try:
        limit = min(int(request.args.get("limit", 100)), 1000)
        offset = max(int(request.args.get("offset", 0)), 0)
        option_type = request.args.get("option_type")
        trade_date = request.args.get("trade_date")
        dataset = request.args.get("dataset")

        query = f"SELECT * FROM {TRADES_TABLE} WHERE 1=1"
        params = []
        if option_type:
            query += " AND option_type = ?"
            params.append(option_type.upper())
        if trade_date:
            query += " AND trade_date = ?"
            params.append(trade_date)
        if dataset:
            query += " AND dataset = ?"
            params.append(dataset)
        count_query = query.replace("SELECT *", "SELECT COUNT(*)", 1)
        conn = _conn()
        total = conn.execute(count_query, params).fetchone()[0]
        query += " ORDER BY signal_timestamp DESC LIMIT ? OFFSET ?"
        rows = conn.execute(query, params + [limit, offset]).fetchall()
        conn.close()

        signals = [dict(r) for r in rows]
        return jsonify({
            "success": True,
            "signals": signals,
            "trades": signals,
            "count": len(signals),
            "total": total,
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@bp.route("/api/sma9-short/recent-trades", methods=["GET"])
def recent_trades():
    try:
        limit = min(int(request.args.get("limit", 50)), 500)
        dataset = request.args.get("dataset", "LIVE")
        trade_date = request.args.get("trade_date")
        query = f"SELECT * FROM {TRADES_TABLE} WHERE 1=1"
        params = []
        if dataset:
            query += " AND dataset = ?"
            params.append(dataset)
        if trade_date:
            query += " AND trade_date = ?"
            params.append(trade_date)
        count_query = query.replace("SELECT *", "SELECT COUNT(*)", 1)
        conn = _conn()
        total = conn.execute(count_query, params).fetchone()[0]
        query += " ORDER BY signal_timestamp DESC LIMIT ?"
        rows = conn.execute(query, params + [limit]).fetchall()
        conn.close()
        trades = [dict(r) for r in rows]
        return jsonify({
            "success": True,
            "trades": trades,
            "count": len(trades),
            "total": total,
            "dataset": dataset or "ALL",
            "trade_date": trade_date,
        })
    except Exception as exc:
        return jsonify({"success": False, "trades": [], "error": str(exc)}), 500


@bp.route("/api/sma9-short/daily-summary", methods=["GET"])
def daily_summary():
    try:
        dataset = request.args.get("dataset")
        query = f"""
            SELECT trade_date AS date,
                   COUNT(*) AS total_trades,
                   SUM(CASE WHEN pnl_points > 0 THEN 1 ELSE 0 END) AS wins,
                   SUM(CASE WHEN pnl_points < 0 THEN 1 ELSE 0 END) AS losses,
                   SUM(pnl_points) AS total_pnl_points,
                   ROUND(AVG(pnl_points), 2) AS avg_pnl,
                   GROUP_CONCAT(DISTINCT dataset) AS datasets
            FROM {TRADES_TABLE}
        """
        params = []
        if dataset:
            query += " WHERE dataset = ?"
            params.append(dataset)
        query += " GROUP BY trade_date ORDER BY trade_date DESC"
        conn = _conn()
        rows = conn.execute(query, params).fetchall()
        conn.close()
        daily = [dict(r) for r in rows]
        for d in daily:
            total = d["total_trades"] or 0
            d["win_rate"] = round((d["wins"] or 0) / total * 100, 2) if total else 0
        return jsonify({"success": True, "daily": daily, "dataset": dataset or "ALL"})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@bp.route("/api/sma9-short/open-positions", methods=["GET"])
def open_positions():
    try:
        conn = _conn()
        rows = conn.execute(
            f"SELECT * FROM {OPEN_TABLE} ORDER BY entry_timestamp"
        ).fetchall()
        conn.close()
        positions = [dict(r) for r in rows]
        return jsonify({"success": True, "positions": positions,
                        "count": len(positions)})
    except Exception as exc:
        return jsonify({"success": False, "positions": [], "error": str(exc)}), 500


@bp.route("/api/sma9-short/today", methods=["GET"])
def today():
    try:
        today = request.args.get("trade_date") or datetime.now(
            IST).date().isoformat()
        conn = _conn()
        rows = conn.execute(
            f"SELECT * FROM {TRADES_TABLE} "
            "WHERE dataset='LIVE' AND trade_date=? "
            "ORDER BY signal_timestamp DESC",
            (today,),
        ).fetchall()
        conn.close()
        trades = [dict(r) for r in rows]
        pnl = round(sum(float(t["pnl_points"] or 0) for t in trades), 2)
        return jsonify({
            "success": True,
            "trade_date": today,
            "trades": trades,
            "count": len(trades),
            "wins": sum(1 for t in trades if float(t["pnl_points"] or 0) > 0),
            "losses": sum(1 for t in trades if float(t["pnl_points"] or 0) < 0),
            "pnl_points": pnl,
            "is_today": True,
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc), "trades": []}), 500
