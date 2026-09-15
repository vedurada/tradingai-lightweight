from __future__ import annotations

import os
import sys
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Optional
from collections import namedtuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backtest_engine import run_backtest, BacktestResult


WindowMetrics = namedtuple("WindowMetrics", [
    "total_trades", "completed_trades", "win_rate", "winning_trades",
    "losing_trades", "breakeven_trades", "net_pnl", "gross_pnl", "gross_loss",
    "profit_factor", "max_drawdown", "avg_r", "best_r", "worst_r",
    "still_open", "trade_count",
])

WalkForwardResult = namedtuple("WalkForwardResult", [
    "window_id",
    "development_start", "development_end",
    "validation_start", "validation_end",
    "test_start", "test_end",
    "symbol",
    "strategy_version", "indicator_version", "data_version", "cost_model_version",
    "development_metrics",
    "validation_metrics",
    "test_metrics",
    "total_trades",
    "completed_trades",
    "insufficient_data",
    "coverage",
    "message",
])


def _metrics_from_backtest(result: Optional[BacktestResult]) -> Optional[WindowMetrics]:
    if result is None or not result.trades:
        return None
    perf = result.performance
    return WindowMetrics(
        total_trades=perf.get("total_trades", 0),
        completed_trades=perf.get("completed_trades", 0),
        win_rate=perf.get("win_rate", 0),
        winning_trades=perf.get("winning_trades", 0),
        losing_trades=perf.get("losing_trades", 0),
        breakeven_trades=perf.get("breakeven_trades", 0),
        net_pnl=perf.get("net_pnl", 0),
        gross_pnl=perf.get("gross_pnl", 0),
        gross_loss=perf.get("gross_loss", 0),
        profit_factor=perf.get("profit_factor", 0),
        max_drawdown=perf.get("max_drawdown", 0),
        avg_r=perf.get("avg_r", 0),
        best_r=perf.get("best_r"),
        worst_r=perf.get("worst_r"),
        still_open=perf.get("total_trades", 0) - perf.get("completed_trades", 0),
        trade_count=len(result.trades),
    )


def _load_5m_candles(symbol: str, start: str, end: str, db_path: str):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT timestamp, open, high, low, close, volume FROM price_5m "
        "WHERE symbol=? AND timestamp>=? AND timestamp<=? ORDER BY timestamp",
        (symbol, start, end),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _candles_to_snapshots(candles, symbol: str, trade_setup_fn=None):
    snapshots = []
    for c in candles:
        market_state = {"spot": c["close"]}
        trade_setup = {"trade_readiness": "WAIT", "stages": {}}
        if trade_setup_fn:
            try:
                trade_setup = trade_setup_fn(c, symbol)
            except Exception:
                pass
        snapshots.append({
            "timestamp": c["timestamp"],
            "trade_setup": trade_setup,
            "market_state": market_state,
        })
    return snapshots


def run_walkforward(
    symbol: str,
    start_date: str,
    end_date: str,
    dev_days: int = 30,
    val_days: int = 14,
    oos_days: int = 14,
    step_days: Optional[int] = None,
    db_path: Optional[str] = None,
    strategy_version: str = "unknown",
    indicator_version: str = "unknown",
    data_version: str = "unknown",
    cost_model_version: str = "unknown",
    trade_setup_fn=None,
) -> list[WalkForwardResult]:
    if step_days is None:
        step_days = oos_days

    if db_path is None:
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "database", "tradingai.db")

    if not os.path.exists(db_path):
        return [WalkForwardResult(
            "0", start_date, end_date, "", "", "", "", symbol,
            strategy_version, indicator_version, data_version, cost_model_version,
            None, None, None, 0, 0, True, {}, "DB not found",
        )]

    candles = _load_5m_candles(symbol, start_date, end_date, db_path)
    if not candles:
        return [WalkForwardResult(
            "0", start_date, end_date, "", "", "", "", symbol,
            strategy_version, indicator_version, data_version, cost_model_version,
            None, None, None, 0, 0, True, {}, "INSUFFICIENT_HISTORICAL_DATA",
        )]

    all_dates = sorted(set(c["timestamp"][:10] for c in candles))
    earliest = all_dates[0]
    latest = all_dates[-1]
    total_days = len(all_dates)

    coverage = {
        "symbol": symbol,
        "earliest": earliest,
        "latest": latest,
        "total_candles": len(candles),
        "total_trading_days": total_days,
        "data_start": start_date,
        "data_end": end_date,
    }

    min_window = dev_days + val_days + oos_days
    if total_days < min_window:
        return [WalkForwardResult(
            "0", start_date, end_date, "", "", "", "", symbol,
            strategy_version, indicator_version, data_version, cost_model_version,
            None, None, None, 0, 0, True, coverage,
            f"INSUFFICIENT_HISTORICAL_DATA: need {min_window} days, have {total_days}",
        )]

    windows = []
    current = 0
    window_idx = 0

    while current + min_window <= total_days:
        dev_start_idx = current
        dev_end_idx = min(current + dev_days, total_days)
        val_start_idx = dev_end_idx
        val_end_idx = min(val_start_idx + val_days, total_days)
        oos_start_idx = val_end_idx
        oos_end_idx = min(oos_start_idx + oos_days, total_days)

        if oos_end_idx <= oos_start_idx:
            break

        dev_start = all_dates[dev_start_idx]
        dev_end = all_dates[dev_end_idx - 1]
        val_start = all_dates[val_start_idx]
        val_end = all_dates[val_end_idx - 1]
        test_start = all_dates[oos_start_idx]
        test_end = all_dates[oos_end_idx - 1]

        window_id = f"{symbol}_WF_{window_idx:03d}"

        dev_metrics = _run_window(candles, dev_start_idx, dev_end_idx, symbol, trade_setup_fn)
        val_metrics = _run_window(candles, val_start_idx, val_end_idx, symbol, trade_setup_fn)
        test_metrics = _run_window(candles, oos_start_idx, oos_end_idx, symbol, trade_setup_fn)

        windows.append(WalkForwardResult(
            window_id=window_id,
            development_start=dev_start,
            development_end=dev_end,
            validation_start=val_start,
            validation_end=val_end,
            test_start=test_start,
            test_end=test_end,
            symbol=symbol,
            strategy_version=strategy_version,
            indicator_version=indicator_version,
            data_version=data_version,
            cost_model_version=cost_model_version,
            development_metrics=dev_metrics,
            validation_metrics=val_metrics,
            test_metrics=test_metrics,
            total_trades=(dev_metrics.total_trades if dev_metrics else 0)
                + (val_metrics.total_trades if val_metrics else 0)
                + (test_metrics.total_trades if test_metrics else 0),
            completed_trades=(dev_metrics.completed_trades if dev_metrics else 0)
                + (val_metrics.completed_trades if val_metrics else 0)
                + (test_metrics.completed_trades if test_metrics else 0),
            insufficient_data=False,
            coverage=coverage,
            message="",
        ))

        current += step_days
        window_idx += 1

    if not windows:
        return [WalkForwardResult(
            "0", start_date, end_date, "", "", "", "", symbol,
            strategy_version, indicator_version, data_version, cost_model_version,
            None, None, None, 0, 0, True, coverage,
            "INSUFFICIENT_HISTORICAL_DATA: no valid window positions found",
        )]

    return windows


def _run_window(candles, start_idx, end_idx, symbol: str, trade_setup_fn=None) -> Optional[WindowMetrics]:
    window_candles = candles[start_idx:end_idx]
    if not window_candles:
        return None

    snapshots = _candles_to_snapshots(window_candles, symbol, trade_setup_fn)

    try:
        result = run_backtest(symbol, snapshots)
        return _metrics_from_backtest(result)
    except Exception:
        return None
