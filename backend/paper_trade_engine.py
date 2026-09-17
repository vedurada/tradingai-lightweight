from __future__ import annotations

import json
import os
import sys
import logging
import uuid
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logger = logging.getLogger("tradingai.paper_trade")

ENGINE_VERSION = "1.0.0-phase41"

DEFAULT_COSTS = {
    "brokerage_per_side": 20,
    "slippage_bps": 0.5,
    "exchange_fee_pct": 0.03,
    "gst_pct": 18,
    "stamp_charge_pct": 0.003,
}

TRADE_STATUSES = {
    "QUALIFIED", "WAITING_ENTRY", "OPEN", "TARGET_HIT",
    "STOPPED", "INVALIDATED", "EXPIRED", "CANCELLED", "CLOSED",
}

VALID_TRANSITIONS = {
    "QUALIFIED": {"WAITING_ENTRY", "CANCELLED"},
    "WAITING_ENTRY": {"OPEN", "CANCELLED"},
    "OPEN": {"TARGET_HIT", "STOPPED", "INVALIDATED", "EXPIRED", "CLOSED"},
    "TARGET_HIT": {"CLOSED"},
    "STOPPED": {"CLOSED"},
    "INVALIDATED": {"CLOSED"},
    "EXPIRED": {"CLOSED"},
    "CANCELLED": set(),
    "CLOSED": set(),
}

EXIT_REASONS = {
    "TARGET_HIT", "STOP_LOSS", "INVALIDATION", "SESSION_CLOSE",
    "AI_INVALIDATION", "OPPOSITE_REGIME", "TIME_EXIT", "DATA_INVALIDATION",
    "EXPIRED", "CANCELLED",
}


class PaperTradeEngine:
    def __init__(self, db_path: str = None, costs: dict = None):
        from db_schema import DB_PATH
        self.db_path = db_path or DB_PATH
        self.costs = {**DEFAULT_COSTS, **(costs or {})}

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def _store(self, table: str, data: dict):
        conn = self._get_conn()
        try:
            cols = ", ".join(data.keys())
            placeholders = ", ".join(["?"] * len(data))
            values = list(data.values())
            conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({placeholders})", values)
            conn.commit()
        except sqlite3.IntegrityError:
            logger.info(f"Duplicate insert into {table}: {data.get('trade_id', data.get('id', 'unknown'))}")
        finally:
            conn.close()

    def _get_latest_trade(self, instrument: str) -> Optional[dict]:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM paper_trades WHERE instrument=? ORDER BY created_at DESC LIMIT 1",
                (instrument,),
            ).fetchone()
            if not row:
                return None
            return dict(row)
        finally:
            conn.close()

    def _has_active_trade(self, instrument: str) -> bool:
        trade = self._get_latest_trade(instrument)
        return trade is not None and trade.get("status") in ("OPEN", "WAITING_ENTRY")

    def _generate_trade_id(self) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return f"PT-{ts}-{uuid.uuid4().hex[:6].upper()}"

    def _generate_setup_fingerprint(
        self, direction: str, strategy: str, entry_condition: str,
        instrument: str, outlook_id: str,
    ) -> str:
        raw = f"{instrument}|{direction}|{strategy}|{entry_condition}|{outlook_id}"
        import hashlib
        return hashlib.sha256(raw.encode()).hexdigest()[:16].upper()

    def is_duplicate(self, fingerprint: str) -> bool:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM paper_trades WHERE setup_fingerprint=?",
                (fingerprint,),
            ).fetchone()
            return row[0] > 0
        finally:
            conn.close()

    def _add_event(self, trade_id: str, event: str, reason: str, price: float = None):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        event_data = {
            "trade_id": trade_id,
            "timestamp": now,
            "event": event,
            "reason": reason,
            "price": price,
            "engine_version": ENGINE_VERSION,
        }
        self._store("paper_trade_events", event_data)
        logger.info(f"[{trade_id}] Event: {event} reason={reason}")

    def qualify_trade(
        self,
        qualification: dict,
        outlook: dict,
        snapshot: dict,
        evidence: dict,
        options_data: dict = None,
        active_trade: dict = None,
    ) -> dict:
        if qualification.get("trade_status") != "TRADE":
            logger.info(f"Qualification not TRADE: {qualification.get('trade_status')}")
            return {"created": False, "reason": "Not qualified"}

        instrument = qualification.get("instrument", "")
        if active_trade and active_trade.get("status") in ("OPEN", "WAITING_ENTRY"):
            logger.info(f"Active trade exists for {instrument}")
            return {"created": False, "reason": "ACTIVE_TRADE_EXISTS"}
        if self._has_active_trade(instrument):
            logger.info(f"Active trade exists for {instrument}")
            return {"created": False, "reason": "ACTIVE_TRADE_EXISTS"}

        fingerprint = self._generate_setup_fingerprint(
            qualification.get("direction", "NEUTRAL"),
            qualification.get("strategy", ""),
            qualification.get("confirmation", ""),
            instrument,
            qualification.get("outlook_id", ""),
        )

        if self.is_duplicate(fingerprint):
            logger.info(f"Duplicate fingerprint: {fingerprint}")
            return {"created": False, "reason": "DUPLICATE_SETUP", "fingerprint": fingerprint}

        bias = outlook.get("bias", "MIXED") if outlook else "MIXED"
        strategy_result = self._get_strategy_detail(bias)

        entry_condition = qualification.get("confirmation", "")
        invalidation = qualification.get("invalidation", "")
        stop = qualification.get("stop_price")
        target = qualification.get("target_price")
        risk_points = qualification.get("risk_points", 0)
        reward_points = qualification.get("reward_points", 0)
        rr = qualification.get("risk_reward", 0)

        close = snapshot.get("close", 0)
        quantity = self._calculate_quantity(close, risk_points)
        max_loss = risk_points * quantity
        max_profit = reward_points * quantity

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        trade_id = self._generate_trade_id()

        trade = {
            "trade_id": trade_id,
            "instrument": instrument,
            "outlook_id": outlook.get("outlook_id", ""),
            "evidence_id": evidence.get("evidence_id", "") if evidence else "",
            "direction": qualification.get("direction", "NEUTRAL"),
            "strategy": qualification.get("strategy", ""),
            "status": "WAITING_ENTRY",
            "setup_fingerprint": fingerprint,
            "qualification_timestamp": qualification.get("qualification_timestamp", now),
            "entry_condition": entry_condition,
            "invalidation": invalidation,
            "entry_price": None,
            "stop_price": stop,
            "target_price": target,
            "max_loss": max_loss,
            "max_profit": max_profit,
            "risk_reward": rr,
            "quantity": quantity,
            "option_legs_json": json.dumps(strategy_result.get("legs", [])),
            "outcome": None,
            "exit_reason": None,
            "exit_timestamp": None,
            "exit_price": None,
            "pnl": None,
            "pnl_percent": None,
            "holding_minutes": None,
            "holding_seconds": None,
            "data_quality": "LIVE",
            "engine_version": ENGINE_VERSION,
            "created_at": now,
            "updated_at": now,
        }

        self._store("paper_trades", trade)
        self._add_event(trade_id, "QUALIFIED", "Trade qualified by deterministic engine", close)

        logger.info(f"[{trade_id}] Trade qualified: {instrument} {qualification.get('direction')} {qualification.get('strategy')}")
        return {"created": True, "trade_id": trade_id, "status": "WAITING_ENTRY", "fingerprint": fingerprint}

    def _get_strategy_detail(self, bias: str) -> dict:
        from strategy_selection import STRATEGY_COMPATIBILITY
        return STRATEGY_COMPATIBILITY.get(bias, {})

    def _calculate_quantity(self, entry_price: float, risk_points: float) -> int:
        capital = 500000
        max_risk = capital * 0.005
        if risk_points <= 0 or entry_price <= 0:
            return 0
        max_quantity = int(max_risk / risk_points)
        max_by_capital = int(capital / entry_price)
        return min(max_quantity, max_by_capital, 100)

    def trigger_entry(self, trade_id: str, entry_price: float, timestamp: str = None):
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM paper_trades WHERE trade_id=? AND status=?",
                (trade_id, "WAITING_ENTRY"),
            ).fetchone()
            if not row:
                logger.warning(f"Cannot trigger entry for {trade_id}: not WAITING_ENTRY")
                return False

            now = timestamp or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            close = entry_price

            conn.execute(
                "UPDATE paper_trades SET status=?, entry_price=?, entry_timestamp=?, "
                "updated_at=? WHERE trade_id=?",
                ("OPEN", close, now, now, trade_id),
            )
            conn.commit()

            self._add_event(trade_id, "ENTRY_TRIGGERED", "Entry condition satisfied", close)
            return True
        finally:
            conn.close()

    def trigger_exit(self, trade_id: str, exit_reason: str, exit_price: float = None, timestamp: str = None):
        if exit_reason not in EXIT_REASONS:
            logger.warning(f"Invalid exit reason: {exit_reason}")
            return False

        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM paper_trades WHERE trade_id=? AND status=?",
                (trade_id, "OPEN"),
            ).fetchone()
            if not row:
                logger.warning(f"Cannot exit {trade_id}: not OPEN")
                return False

            now = timestamp or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            trade = dict(row)
            entry_price = trade.get("entry_price", 0) or exit_price or 0
            quantity = trade.get("quantity", 1) or 1
            max_loss = trade.get("max_loss", 0) or 0
            max_profit = trade.get("max_profit", 0) or 0

            pnl = (exit_price - entry_price) * quantity if exit_price and entry_price else 0
            pnl_percent = (pnl / (entry_price * quantity)) * 100 if entry_price and quantity else 0

            holding_start = trade.get("entry_timestamp", trade.get("created_at", now))
            try:
                dt_start = datetime.fromisoformat(holding_start.replace("Z", "+00:00"))
                dt_end = datetime.fromisoformat(now.replace("Z", "+00:00"))
                holding_minutes = (dt_end - dt_start).total_seconds() / 60
            except Exception:
                holding_minutes = 0

            outcome = self._determine_outcome(exit_reason, exit_price, trade.get("stop_price"), trade.get("target_price"))

            conn.execute(
                "UPDATE paper_trades SET status=?, exit_timestamp=?, exit_price=?, "
                "exit_reason=?, pnl=?, pnl_percent=?, holding_minutes=?, outcome=?, "
                "updated_at=? WHERE trade_id=?",
                (outcome, now, exit_price, exit_reason, pnl, pnl_percent,
                 holding_minutes, outcome, now, trade_id),
            )
            conn.commit()

            self._add_event(trade_id, outcome.upper(), exit_reason, exit_price)
            self._add_event(trade_id, "CLOSED", f"Closed with {outcome}", exit_price)
            return True
        finally:
            conn.close()

    def _determine_outcome(self, exit_reason: str, exit_price: float, stop: float, target: float) -> str:
        if exit_reason in ("TARGET_HIT",):
            return "TARGET_HIT"
        if exit_reason in ("STOP_LOSS", "STOPPED"):
            return "STOPPED"
        if exit_reason in ("INVALIDATION", "AI_INVALIDATION", "DATA_INVALIDATION"):
            return "INVALIDATED"
        if exit_reason == "OPPOSITE_REGIME":
            return "INVALIDATED"
        if exit_reason == "SESSION_CLOSE":
            return "EXPIRED"
        if exit_reason == "TIME_EXIT":
            return "EXPIRED"
        if exit_reason == "EXPIRED":
            return "EXPIRED"
        if exit_reason == "CANCELLED":
            return "CANCELLED"
        return "CLOSED"

    def evaluate_exits(self, instrument: str, current_price: float, timestamp: str = None):
        results = []
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM paper_trades WHERE instrument=? AND status='OPEN'",
                (instrument,),
            ).fetchall()
            now = timestamp or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            for row in rows:
                trade = dict(row)
                price = current_price
                stop = trade.get("stop_price")
                target = trade.get("target_price")

                if stop and price <= stop and trade.get("direction") == "BULLISH":
                    self.trigger_exit(trade["trade_id"], "STOP_LOSS", stop, now)
                    results.append({"trade_id": trade["trade_id"], "exit": "STOP_LOSS"})
                elif target and price >= target and trade.get("direction") == "BULLISH":
                    self.trigger_exit(trade["trade_id"], "TARGET_HIT", target, now)
                    results.append({"trade_id": trade["trade_id"], "exit": "TARGET_HIT"})
                elif stop and price >= stop and trade.get("direction") == "BEARISH":
                    self.trigger_exit(trade["trade_id"], "STOP_LOSS", stop, now)
                    results.append({"trade_id": trade["trade_id"], "exit": "STOP_LOSS"})
                elif target and price <= target and trade.get("direction") == "BEARISH":
                    self.trigger_exit(trade["trade_id"], "TARGET_HIT", target, now)
                    results.append({"trade_id": trade["trade_id"], "exit": "TARGET_HIT"})
        finally:
            conn.close()
        return results

    def get_active_trades(self, instrument: str = None) -> list:
        conn = self._get_conn()
        try:
            if instrument:
                rows = conn.execute(
                    "SELECT * FROM paper_trades WHERE instrument=? AND status IN ('OPEN','WAITING_ENTRY') ORDER BY created_at DESC",
                    (instrument,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM paper_trades WHERE status IN ('OPEN','WAITING_ENTRY') ORDER BY created_at DESC",
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_all_trades(self, instrument: str = None, limit: int = 100) -> list:
        conn = self._get_conn()
        try:
            if instrument:
                rows = conn.execute(
                    "SELECT * FROM paper_trades WHERE instrument=? ORDER BY created_at DESC LIMIT ?",
                    (instrument, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM paper_trades ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_trade(self, trade_id: str) -> Optional[dict]:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM paper_trades WHERE trade_id=?",
                (trade_id,),
            ).fetchone()
            if not row:
                return None
            return dict(row)
        finally:
            conn.close()

    def get_trade_events(self, trade_id: str) -> list:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM paper_trade_events WHERE trade_id=? ORDER BY timestamp ASC",
                (trade_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def qualify_paper_trade(*args, **kwargs):
    engine = PaperTradeEngine()
    return engine.qualify_trade(*args, **kwargs)


def trigger_paper_entry(*args, **kwargs):
    engine = PaperTradeEngine()
    return engine.trigger_entry(*args, **kwargs)


def trigger_paper_exit(*args, **kwargs):
    engine = PaperTradeEngine()
    return engine.trigger_exit(*args, **kwargs)
