from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import Database

logger = logging.getLogger("tradingai.backtest")


class BacktestEngine:
    def __init__(self, db_path: str) -> None:
        self.db = Database(db_path)

    def run(self, symbol: str, days: int = 30) -> dict[str, Any]:
        history = self.db.get_history(symbol, days=days)
        if not history:
            return {"symbol": symbol, "period_days": days, "total_trades": 0, "message": "No history data"}

        trades = [h for h in history if h.get("result") in ("WIN", "LOSS")]
        if not trades:
            return {"symbol": symbol, "period_days": days, "total_trades": 0, "message": "No closed trades"}

        wins = sum(1 for t in trades if t["result"] == "WIN")
        losses = sum(1 for t in trades if t["result"] == "LOSS")
        flats = sum(1 for t in trades if t["result"] == "FLAT")
        total_points = sum(t.get("points", 0) or 0 for t in trades)
        win_points = [t.get("points", 0) or 0 for t in trades if t["result"] == "WIN"]
        loss_points = [abs(t.get("points", 0) or 0) for t in trades if t["result"] == "LOSS"]
        avg_win = sum(win_points) / len(win_points) if win_points else 0
        avg_loss = sum(loss_points) / len(loss_points) if loss_points else 0
        max_win = max(win_points) if win_points else 0
        max_loss = max(loss_points) if loss_points else 0
        win_rate = (wins / len(trades)) * 100 if trades else 0
        profit_factor = (sum(win_points) / sum(loss_points)) if loss_points else 0

        consecutive_wins = 0
        max_consecutive_wins = 0
        consecutive_losses = 0
        max_consecutive_losses = 0
        for t in trades:
            if t["result"] == "WIN":
                consecutive_wins += 1
                consecutive_losses = 0
                max_consecutive_wins = max(max_consecutive_wins, consecutive_wins)
            elif t["result"] == "LOSS":
                consecutive_losses += 1
                consecutive_wins = 0
                max_consecutive_losses = max(max_consecutive_losses, consecutive_losses)

        equity = 0
        peak = 0
        max_dd = 0
        for t in trades:
            pts = t.get("points", 0) or 0
            equity += pts
            if equity > peak:
                peak = equity
            dd = peak - equity
            if dd > max_dd:
                max_dd = dd

        strategy_breakdown: dict[str, dict[str, Any]] = {}
        for t in trades:
            strat = t.get("strategy", "UNKNOWN")
            if strat not in strategy_breakdown:
                strategy_breakdown[strat] = {"trades": 0, "wins": 0, "losses": 0, "total_points": 0}
            strategy_breakdown[strat]["trades"] += 1
            if t["result"] == "WIN":
                strategy_breakdown[strat]["wins"] += 1
            elif t["result"] == "LOSS":
                strategy_breakdown[strat]["losses"] += 1
            strategy_breakdown[strat]["total_points"] += t.get("points", 0) or 0

        return {
            "symbol": symbol,
            "period_days": days,
            "total_trades": len(trades),
            "wins": wins,
            "losses": losses,
            "flats": flats,
            "win_rate": round(win_rate, 1),
            "total_points": round(total_points, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "max_win": round(max_win, 2),
            "max_loss": round(max_loss, 2),
            "profit_factor": round(profit_factor, 2),
            "max_consecutive_wins": max_consecutive_wins,
            "max_consecutive_losses": max_consecutive_losses,
            "max_drawdown": round(max_dd, 2),
            "strategy_breakdown": strategy_breakdown,
            "trades": trades,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }