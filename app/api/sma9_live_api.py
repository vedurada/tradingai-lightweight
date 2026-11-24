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


@bp.route("/api/sma9-live/reconciliation", methods=["GET"])
def reconciliation():
    """Read-only view of broker fill monitoring and lifecycle audit events."""
    try:
        limit = min(int(request.args.get("limit", 50)), 500)
        with closing(_conn()) as conn:
            pending = [dict(r) for r in conn.execute(
                """SELECT client_order_id, trade_id, option_type, side, symbol,
                          quantity, status, broker_status, broker_order_id,
                          status_checked_at, reconcile_attempts, last_error,
                          created_at
                   FROM sma9_live_orders
                   WHERE dry_run = 0 AND broker_order_id IS NOT NULL
                     AND status IN ('NEW', 'ACCEPTED')
                   ORDER BY created_at DESC LIMIT ?""", (limit,))]
            events = [dict(r) for r in conn.execute(
                """SELECT * FROM sma9_live_lifecycle_events
                   ORDER BY id DESC LIMIT ?""", (limit,))]
            positions = [dict(r) for r in conn.execute(
                """SELECT option_type, trade_id, lifecycle_state, updated_at
                   FROM sma9_live_open_positions ORDER BY option_type""")]
        state = _live_state()
        return jsonify({
            "success": True,
            "summary": state.get("execution", {}).get("reconciliation", {}),
            "pending_orders": pending,
            "lifecycle_events": events,
            "positions": positions,
        })
    except Exception as exc:
        return jsonify({
            "success": False, "summary": {}, "pending_orders": [],
            "lifecycle_events": [], "positions": [], "error": str(exc),
        }), 500


@bp.route("/api/sma9-live/execution-quality", methods=["GET"])
def execution_quality():
    """Read-only shadow log: signal price vs broker fill, slippage and cost.

    Costs are configurable estimates, not contract-note figures. Nothing here
    writes to the scanner DB or changes recorded trade P&L.
    """
    try:
        limit = min(int(request.args.get("limit", 100)), 500)
        with closing(_conn()) as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM sma9_live_execution_quality"
            ).fetchone()[0]
            legs = [dict(r) for r in conn.execute(
                "SELECT * FROM sma9_live_execution_quality "
                "ORDER BY created_at DESC LIMIT ?", (limit,))]
            agg = dict(conn.execute(
                """SELECT COUNT(*) AS legs,
                          COALESCE(SUM(CASE WHEN fill_price IS NOT NULL
                                            THEN 1 ELSE 0 END), 0) AS filled_legs,
                          COALESCE(SUM(CASE WHEN fill_price IS NULL
                                            THEN 1 ELSE 0 END), 0) AS missing_fills,
                          COALESCE(SUM(slippage_points), 0) AS slippage_points,
                          COALESCE(SUM(slippage_pct), 0) AS slippage_pct,
                          COALESCE(SUM(slippage_value), 0) AS slippage_value,
                          COALESCE(SUM(cost_estimate), 0) AS cost_estimate
                   FROM sma9_live_execution_quality""").fetchone())
            grouped = [dict(r) for r in conn.execute(
                """SELECT trade_id, MAX(option_type) AS option_type,
                          MAX(CASE WHEN side='BUY' THEN signal_price END) AS signal_entry,
                          MAX(CASE WHEN side='BUY' THEN fill_price END) AS entry_fill,
                          MAX(CASE WHEN side='SELL' THEN signal_price END) AS signal_exit,
                          MAX(CASE WHEN side='SELL' THEN fill_price END) AS exit_fill,
                          MAX(quantity) AS quantity, COUNT(*) AS legs,
                          SUM(CASE WHEN fill_price IS NOT NULL THEN 1 ELSE 0 END)
                              AS filled_legs,
                          COALESCE(SUM(slippage_points), 0) AS slippage_points,
                          COALESCE(SUM(slippage_value), 0) AS slippage_value,
                          COALESCE(SUM(cost_estimate), 0) AS cost_estimate
                   FROM sma9_live_execution_quality
                   GROUP BY trade_id ORDER BY MAX(created_at) DESC LIMIT ?""",
                (limit,))]
            paper = {r["trade_id"]: r["pnl_points"] for r in conn.execute(
                "SELECT trade_id, pnl_points FROM sma9_live_trades")}

        trades = []
        for row in grouped:
            signal_entry = row["signal_entry"]
            signal_exit = row["signal_exit"]
            paper_pnl = paper.get(row["trade_id"])
            if paper_pnl is None and signal_entry and signal_exit:
                paper_pnl = signal_exit - signal_entry
            paper_pnl = round(float(paper_pnl or 0), 2)
            both_fills = row["entry_fill"] is not None and row["exit_fill"] is not None
            adjusted = (round(paper_pnl - float(row["slippage_points"]), 2)
                        if both_fills else None)
            qty = int(row["quantity"] or 0)
            realized = (round(adjusted * qty - float(row["cost_estimate"]), 2)
                        if both_fills and qty else None)
            trades.append({
                **row,
                "paper_pnl_points": paper_pnl,
                "fill_adjusted_pnl_points": adjusted,
                "estimated_realized_rupees": realized,
            })

        complete = [t for t in trades if t["fill_adjusted_pnl_points"] is not None]
        return jsonify({
            "success": True,
            "summary": {
                **agg,
                "total": total,
                "trades_shown": len(trades),
                "trades_with_both_fills": len(complete),
                "paper_pnl_points": round(
                    sum(t["paper_pnl_points"] for t in trades), 2),
                "fill_adjusted_pnl_points": round(
                    sum(t["fill_adjusted_pnl_points"] for t in complete), 2),
                "estimated_realized_rupees": round(
                    sum(t["estimated_realized_rupees"] for t in complete
                        if t["estimated_realized_rupees"] is not None), 2),
                "cost_note": (
                    "ESTIMATE only: configurable brokerage/charge allowances; "
                    "not contract-note figures. Slippage is positive when "
                    "adverse versus the signal LTP."
                ),
            },
            "legs": legs,
            "trades": trades,
        })
    except Exception as exc:
        return jsonify({
            "success": False, "summary": {}, "legs": [], "trades": [],
            "error": str(exc),
        }), 500


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
        "reconciliation": state.get("execution", {}).get("reconciliation", {}),
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
