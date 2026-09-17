from __future__ import annotations

import json
import os
import sys
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logger = logging.getLogger("tradingai.outcome")

HORIZONS = {
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "60m": 60,
}

MIN_SAMPLE_SIZE = 10


class OutcomeEngine:
    def __init__(self, db_path: str = None):
        from db_schema import DB_PATH
        self.db_path = db_path or DB_PATH

    def _get_conn(self):
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def record_outcome(
        self,
        outlook_id: str,
        symbol: str,
        entry_price: float,
        reference_price: float = None,
        horizon_minutes: int = 5,
        bias: str = "MIXED",
    ) -> dict:
        conn = self._get_conn()
        try:
            horizon_key = f"{horizon_minutes}m"
            if horizon_key not in HORIZONS:
                return {"error": f"Invalid horizon: {horizon_key}"}

            recorded_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            ref_price = reference_price or entry_price

            outcome = {
                "outlook_id": outlook_id,
                "symbol": symbol,
                "entry_price": entry_price,
                "reference_price": ref_price,
                "horizon_minutes": horizon_minutes,
                "bias": bias,
                "recorded_at": recorded_at,
                "status": "PENDING",
            }

            conn.execute(
                """INSERT INTO ai_outcome_predictions
                   (outlook_id, symbol, entry_price, reference_price, horizon_minutes,
                    bias, recorded_at, status, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    outlook_id, symbol, entry_price, ref_price, horizon_minutes,
                    bias, recorded_at, "PENDING", recorded_at,
                ),
            )
            conn.commit()
            return outcome
        finally:
            conn.close()

    def evaluate_outcome(self, outlook_id: str, symbol: str, horizon_minutes: int) -> Optional[dict]:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM ai_outcome_predictions WHERE outlook_id=? AND symbol=? AND horizon_minutes=?",
                (outlook_id, symbol, horizon_minutes),
            ).fetchone()
            if not row:
                return None

            row = dict(row)

            future_data = self._calculate_future_return(symbol, row["recorded_at"], horizon_minutes)

            if future_data is None:
                return {
                    **row,
                    "future_return_pct": None,
                    "correct": None,
                    "mfe_pct": None,
                    "mae_pct": None,
                    "evaluated_at": None,
                    "status": "PENDING",
                }

            future_return = future_data["return_pct"]
            future_price = future_data["future_price"]
            ref_price = row.get("reference_price", row.get("entry_price", 0))

            direction_correct = None
            mfe_pct = None
            mae_pct = None

            if bias := row.get("bias"):
                if bias == "BULLISH":
                    direction_correct = future_return > 0
                elif bias == "BEARISH":
                    direction_correct = future_return < 0
                elif bias in ("RANGE", "MIXED"):
                    range_tolerance = 0.3
                    direction_correct = abs(future_return) <= range_tolerance

            if ref_price and future_price:
                mfe_pct = ((future_price - ref_price) / ref_price) * 100 if ref_price else None
                adverse = -future_return if (future_return > 0) else future_return
                mae_pct = adverse

            evaluated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            result = {
                **row,
                "future_price": future_price,
                "future_return_pct": round(future_return, 4) if future_return is not None else None,
                "direction_correct": direction_correct,
                "mfe_pct": round(mfe_pct, 4) if mfe_pct is not None else None,
                "mae_pct": round(mae_pct, 4) if mae_pct is not None else None,
                "evaluated_at": evaluated_at,
                "status": "EVALUATED",
            }

            conn.execute(
                """UPDATE ai_outcome_predictions
                   SET future_price=?, future_return_pct=?, correct=?, mfe_pct=?, mae_pct=?,
                       evaluated_at=?, status=?
                   WHERE id=?""",
                (
                    result["future_price"], result["future_return_pct"], result["direction_correct"],
                    result["mfe_pct"], result["mae_pct"], evaluated_at, "EVALUATED", row["id"],
                ),
            )
            conn.commit()
            return result
        finally:
            conn.close()

    def _calculate_future_return(self, symbol: str, start_time: str, minutes: int) -> Optional[dict]:
        try:
            import sqlite3 as _sqlite3
            conn = _sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row

            start = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            end = start + timedelta(minutes=minutes)

            start_row = conn.execute(
                "SELECT close FROM price_5m WHERE symbol=? AND timestamp<=? ORDER BY timestamp DESC LIMIT 1",
                (symbol, start.isoformat()),
            ).fetchone()

            end_row = conn.execute(
                "SELECT close FROM price_5m WHERE symbol=? AND timestamp<=? ORDER BY timestamp DESC LIMIT 1",
                (symbol, end.isoformat()),
            ).fetchone()

            conn.close()

            if start_row and end_row and start_row["close"] and end_row["close"]:
                start_price = float(start_row["close"])
                end_price = float(end_row["close"])
                return_pct = ((end_price - start_price) / start_price) * 100
                return {
                    "return_pct": return_pct,
                    "future_price": end_price,
                    "start_price": start_price,
                }
        except Exception as e:
            logger.error(f"Future return calculation failed: {e}")

        return None

    def get_pending_evaluations(self, max_age_minutes: int = 60) -> list:
        conn = self._get_conn()
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
            rows = conn.execute(
                "SELECT * FROM ai_outcome_predictions WHERE status='PENDING' AND recorded_at>=? ORDER BY recorded_at DESC",
                (cutoff,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_aggregate_stats(self, min_sample: int = MIN_SAMPLE_SIZE) -> dict:
        conn = self._get_conn()
        try:
            total = conn.execute("SELECT COUNT(*) FROM ai_outcome_predictions WHERE status='EVALUATED'").fetchone()[0]
            if total < min_sample:
                return {
                    "total_evaluated": total,
                    "min_sample_required": min_sample,
                    "status": "INSUFFICIENT_DATA",
                    "message": f"Sample size {total} < {min_sample} minimum required",
                }

            by_bias = {}
            by_horizon = {}
            total_correct = 0

            rows = conn.execute(
                "SELECT bias, horizon_minutes, correct FROM ai_outcome_predictions WHERE status='EVALUATED'"
            ).fetchall()

            for r in rows:
                bias = r["bias"] or "UNKNOWN"
                horizon = f"{r['horizon_minutes']}m"

                if bias not in by_bias:
                    by_bias[bias] = {"total": 0, "correct": 0}
                by_bias[bias]["total"] += 1
                if r["correct"]:
                    by_bias[bias]["correct"] += 1
                    total_correct += 1

                if horizon not in by_horizon:
                    by_horizon[horizon] = {"total": 0, "correct": 0}
                by_horizon[horizon]["total"] += 1
                if r["correct"]:
                    by_horizon[horizon]["correct"] += 1

            result = {
                "total_evaluated": total,
                "min_sample_required": min_sample,
                "status": "SUFFICIENT_DATA",
                "by_bias": {},
                "by_horizon": {},
                "overall_accuracy": round(total_correct / total * 100, 2) if total else 0,
            }

            for bias, data in by_bias.items():
                result["by_bias"][bias] = {
                    "total": data["total"],
                    "correct": data["correct"],
                    "accuracy": round(data["correct"] / data["total"] * 100, 2) if data["total"] else 0,
                }

            for horizon, data in by_horizon.items():
                result["by_horizon"][horizon] = {
                    "total": data["total"],
                    "correct": data["correct"],
                    "accuracy": round(data["correct"] / data["total"] * 100, 2) if data["total"] else 0,
                }

            return result
        finally:
            conn.close()
