"""Deterministic Strategy Backtesting Engine.

Uses the SAME trade lifecycle as LIVE and REPLAY environments.
One decision engine, three execution environments.

Input: Replay snapshots (Phase 5) + cost model
Output: Trade ledger + performance metrics

Key principle: AI NEVER calculates backtest numbers.
AI can EXPLAIN results, but the engine DETERMINISTICALLY calculates P&L.
"""
from __future__ import annotations

"""Deterministic Strategy Backtesting Engine.

Reuses Phase 4 TradeSetup + Phase 5 Replay.
One deterministic engine, three environments (LIVE, REPLAY, BACKTEST).
"""
import json
from typing import Any, Dict, List, Optional


class TradeRecord:
    """An immutable trade record from backtesting."""

    def __init__(self, *,
                 trade_id: str,
                 symbol: str,
                 entry_time: str,
                 exit_time: Optional[str],
                 direction: str,  # LONG, SHORT, NO_TRADE
                 setup_type: str,  # BREAKOUT, BOUNCE, RANGE
                 entry_price: Optional[float],
                 exit_price: Optional[float],
                 size: float,  # position size in units
                 stop_loss: Optional[float],
                 target: Optional[float],
                 invalidation: Optional[float],
                 outcome: str,  # WIN, LOSS, BREAKEVEN, INVALIDATED, TARGET, STILL_OPEN
                 costs: Dict[str, float],
                 gross_pnl: Optional[float],
                 net_pnl: Optional[float],
                 r_multiple: Optional[float],
                 entry_trigger: str = "",
                 confirmation: str = "",
                 evidence: List[str] = None,
                 setup_stage: str = "",):
        self.trade_id = trade_id
        self.symbol = symbol
        self.entry_time = entry_time
        self.exit_time = exit_time
        self.direction = direction
        self.setup_type = setup_type
        self.entry_price = entry_price
        self.exit_price = exit_price
        self.size = size
        self.stop_loss = stop_loss
        self.target = target
        self.invalidation = invalidation
        self.outcome = outcome
        self.costs = costs
        self.gross_pnl = gross_pnl
        self.net_pnl = net_pnl
        self.r_multiple = r_multiple
        self.entry_trigger = entry_trigger
        self.confirmation = confirmation
        self.evidence = sorted(evidence or [])
        self.setup_stage = setup_stage

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "entry_time": self.entry_time,
            "exit_time": self.exit_time,
            "direction": self.direction,
            "setup_type": self.setup_type,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "size": self.size,
            "stop_loss": self.stop_loss,
            "target": self.target,
            "invalidation": self.invalidation,
            "outcome": self.outcome,
            "costs": self.costs,
            "gross_pnl": self.gross_pnl,
            "net_pnl": self.net_pnl,
            "r_multiple": self.r_multiple,
            "entry_trigger": self.entry_trigger,
            "confirmation": self.confirmation,
            "evidence": self.evidence,
            "setup_stage": self.setup_stage,
        }


class CostModel:
    """Trading costs: brokerage, slippage, GST, exchange fees."""

    def __init__(self, *,
                 brokerage_per_lot: float = 20.0,
                 slippage_pct: float = 0.1,
                 gst_pct: float = 18.0,
                 stamp_charge: float = 0.003,
                 exchange_fee_pct: float = 0.05):
        self.brokerage_per_lot = brokerage_per_lot
        self.slippage_pct = slippage_pct
        self.gst_pct = gst_pct
        self.stamp_charge = stamp_charge
        self.exchange_fee_pct = exchange_fee_pct

    def calculate(self, entry_price: float, exit_price: float,
                  size: float, direction: str) -> Dict[str, float]:
        """Calculate all costs for a trade."""
        turnover = abs(exit_price - entry_price) * size
        lots = max(1, int(size / 25))  # NIFTY lot size = 25

        brokerage = self.brokerage_per_lot * lots * (2 if direction != "NO_TRADE" else 1)
        slippage = turnover * (self.slippage_pct / 100)
        exchange_fee = turnover * (self.exchange_fee_pct / 100)
        stamp = entry_price * size * (self.stamp_charge / 1000)

        subtotal = brokerage + slippage + exchange_fee + stamp
        gst = subtotal * (self.gst_pct / 100)
        total = subtotal + gst

        return {
            "brokerage": round(brokerage, 2),
            "slippage": round(slippage, 2),
            "exchange_fee": round(exchange_fee, 2),
            "stamp_charge": round(stamp, 2),
            "gst": round(gst, 2),
            "total_cost": round(total, 2),
        }


class BacktestResult:
    """Complete backtest result for a symbol+date period."""

    def __init__(self, *,
                 symbol: str,
                 period: str,
                 trades: List[TradeRecord],
                 performance: Dict[str, Any]):
        self.symbol = symbol
        self.period = period
        self.trades = trades
        self.performance = performance

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "period": self.period,
            "trades": [t.to_dict() for t in self.trades],
            "performance": self.performance,
        }


def run_backtest(symbol: str, snapshots: List[dict],
                     cost_model: Optional[CostModel] = None) -> BacktestResult:
    """Run deterministic backtest on replay snapshots.

    Input: Replay snapshots from Phase 5 (each with trade_setup data)
    Output: BacktestResult with trade ledger + performance metrics

    The decision to enter/exit is deterministic based on the trade setup:
    - Entry when trade_setup.trade_readiness == "GO" and ENTRY_WINDOW is ACTIVE
    - Exit when target or invalidation is reached in ACTIVE stage
    - No trade when trade_readiness remains WAIT throughout
    """
    if cost_model is None:
        cost_model = CostModel()

    trades: List[TradeRecord] = []
    trade_id_counter = 0
    current_trade: Optional[dict] = None

    for snap in snapshots:
        setup = snap.get("trade_setup")
        if not setup:
            continue

        trade_readiness = setup.get("trade_readiness")
        entry_window = setup.get("stages", {}).get("ENTRY_WINDOW")
        active_stage = setup.get("stages", {}).get("ACTIVE")

        if current_trade is None:
            # Check if we should enter
            if (trade_readiness == "GO" and entry_window
                    and entry_window.get("status") == "ACTIVE"
                    and entry_window.get("levels", {}).get("entry_window")):
                trade_id_counter += 1
                levels = entry_window.get("levels", {})
                current_trade = {
                    "trade_id": f"{symbol}_{trade_id_counter:04d}",
                    "symbol": symbol,
                    "entry_time": snap.get("timestamp", ""),
                    "exit_time": None,
                    "direction": "LONG",
                    "setup_type": setup.get("setup_type", "BREAKOUT"),
                    "entry_price": snap.get("market_state", {}).get("spot"),
                    "exit_price": None,
                    "size": 1,  # 1 lot for NIFTY
                    "stop_loss": levels.get("invalidation"),
                    "target": levels.get("target"),
                    "invalidation": levels.get("invalidation"),
                    "outcome": "STILL_OPEN",
                    "costs": {},
                    "gross_pnl": None,
                    "net_pnl": None,
                    "r_multiple": None,
                    "entry_trigger": setup.get("stages", {}).get("TRIGGER", {}).get("reason", ""),
                    "confirmation": setup.get("stages", {}).get("CONFIRMATION", {}).get("reason", ""),
                    "evidence": list(setup.get("evidence", [])[:5]),
                    "setup_stage": "ACTIVE",
                }
        else:
            # We have an active trade - check exit conditions
            spot = snap.get("market_state", {}).get("spot")
            if spot:
                current_trade["exit_price"] = spot

                # Check invalidation first
                if current_trade.get("stop_loss") and spot <= current_trade["stop_loss"]:
                    current_trade["exit_time"] = snap.get("timestamp", "")
                    current_trade["outcome"] = "INVALIDATED"
                    trades.append(finalize_trade(current_trade, cost_model))
                    current_trade = None
                # Check target
                elif current_trade.get("target") and spot >= current_trade["target"]:
                    current_trade["exit_time"] = snap.get("timestamp", "")
                    current_trade["outcome"] = "TARGET"
                    trades.append(finalize_trade(current_trade, cost_model))
                    current_trade = None
                # End of day close
                elif is_end_of_day(snap):
                    current_trade["exit_time"] = snap.get("timestamp", "")
                    current_trade["outcome"] = "EXIT"
                    trades.append(finalize_trade(current_trade, cost_model))
                    current_trade = None

    # Handle still-open trade at end
    if current_trade is not None:
        current_trade["exit_time"] = snapshots[-1].get("timestamp", "") if snapshots else ""
        current_trade["outcome"] = "STILL_OPEN"
        current_trade["exit_price"] = current_trade.get("exit_price") or current_trade.get("entry_price")
        trades.append(finalize_trade(current_trade, cost_model))

    # Calculate performance
    performance = calculate_performance(trades)

    return BacktestResult(
        symbol=symbol,
        period=f"{snapshots[0].get('timestamp','')} to {snapshots[-1].get('timestamp','')}" if snapshots else "",
        trades=trades,
        performance=performance,
    )


def finalize_trade(trade: dict, cost_model: CostModel) -> TradeRecord:
    """Calculate costs and P&L for a completed trade."""
    entry = trade.get("entry_price") or 0
    exit_p = trade.get("exit_price") or entry

    costs = cost_model.calculate(entry, exit_p, trade.get("size", 1), trade.get("direction", "LONG"))
    gross_pnl = (exit_p - entry) * trade.get("size", 1) if trade.get("direction") == "LONG" else (entry - exit_p) * trade.get("size", 1)
    net_pnl = gross_pnl - costs.get("total_cost", 0)

    risk = abs(entry - (trade.get("stop_loss") or entry))
    r_multiple = round(net_pnl / risk, 2) if risk > 0 else None

    return TradeRecord(
        trade_id=trade["trade_id"],
        symbol=trade["symbol"],
        entry_time=trade["entry_time"],
        exit_time=trade["exit_time"],
        direction=trade["direction"],
        setup_type=trade.get("setup_type", ""),
        entry_price=entry,
        exit_price=exit_p,
        size=trade.get("size", 1),
        stop_loss=trade.get("stop_loss"),
        target=trade.get("target"),
        invalidation=trade.get("invalidation"),
        outcome=trade.get("outcome", "STILL_OPEN"),
        costs=costs,
        gross_pnl=round(gross_pnl, 2),
        net_pnl=round(net_pnl, 2),
        r_multiple=r_multiple,
        entry_trigger=trade.get("entry_trigger", ""),
        confirmation=trade.get("confirmation", ""),
        evidence=trade.get("evidence", []),
        setup_stage=trade.get("setup_stage", ""),
    )


def is_end_of_day(snapshot: dict) -> bool:
    """Check if snapshot is end of trading day (after 15:00 IST)."""
    ts = snapshot.get("timestamp", "") or ""
    return "15:" in ts or "16:" in ts or "17:" in ts


def calculate_performance(trades: List[TradeRecord]) -> Dict[str, Any]:
    """Calculate performance metrics deterministically.

    AI NEVER calculates these numbers. This is pure arithmetic.
    AI can later EXPLAIN patterns in the results, but never generates the numbers.
    """
    if not trades:
        return {
            "total_trades": 0,
            "message": "No trades to analyze",
        }

    completed = [t for t in trades if t.outcome not in ("STILL_OPEN",)]
    winners = [t for t in completed if t.net_pnl and t.net_pnl > 0]
    losers = [t for t in completed if t.net_pnl and t.net_pnl <= 0]
    breakeven = [t for t in completed if t.net_pnl and t.net_pnl == 0]

    total_trades = len(trades)
    completed_trades = len(completed)

    net_pnls = [t.net_pnl for t in completed if t.net_pnl is not None]

    # Equity curve
    equity = 0
    equity_curve = []
    for t in completed:
        if t.net_pnl is not None:
            equity += t.net_pnl
            equity_curve.append(round(equity, 2))

    # Drawdown curve
    peak = 0
    drawdown_curve = []
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = eq - peak if peak > 0 else 0
        drawdown_curve.append(round(dd, 2))

    # Max drawdown
    max_drawdown = max(drawdown_curve) if drawdown_curve else 0

    # Consecutive wins/losses
    max_consec_wins = 0
    max_consec_losses = 0
    current_wins = 0
    current_losses = 0
    for w in winners:
        current_wins += 1
        current_losses = 0
        if current_wins > max_consec_wins:
            max_consec_wins = current_wins
    for l in losers:
        current_losses += 1
        current_wins = 0
        if current_losses > max_consec_losses:
            max_consec_losses = current_losses

    # R-multiples
    r_multiples = [t.r_multiple for t in completed if t.r_multiple is not None]
    avg_r = sum(r_multiples) / len(r_multiples) if r_multiples else None

    # Time-of-day (entry hour distribution)
    hour_distribution = {}
    for t in completed:
        hour = (t.entry_time or "").split("T")[-1][:2] if t.entry_time else ""
        hour_distribution[hour] = hour_distribution.get(hour, 0) + 1

    # Average trade duration
    durations = []
    for t in completed:
        try:
            from datetime import datetime as _dt
            e = _dt.fromisoformat(t.entry_time.replace("+05:30", "+05:30"))
            x = _dt.fromisoformat(t.exit_time.replace("+05:30", "+05:30"))
            dur = (x - e).total_seconds() / 60
            durations.append(round(dur, 1))
        except Exception:
            pass

    total_costs = sum(t.costs.get("total_cost", 0) for t in completed)
    total_gross = sum(t.gross_pnl for t in completed if t.gross_pnl is not None)
    total_net = sum(t.net_pnl for t in completed if t.net_pnl is not None)

    return {
        "total_trades": total_trades,
        "completed_trades": completed_trades,
        "winning_trades": len(winners),
        "losing_trades": len(losers),
        "breakeven_trades": len(breakeven),
        "win_rate": round(len(winners) / len(completed) * 100, 1) if completed else 0,
        "average_r": round(avg_r, 2) if avg_r is not None else None,
        "profit_factor": round(sum(w.net_pnl for w in winners) / abs(sum(l.net_pnl for l in losers)), 2) if losers and any(l.net_pnl for l in losers) else None,
        "net_pnl": round(total_net, 2),
        "gross_pnl": round(total_gross, 2),
        "total_costs": round(total_costs, 2),
        "max_drawdown": round(max_drawdown, 2),
        "max_consecutive_wins": max_consec_wins,
        "max_consecutive_losses": max_consec_losses,
        "equity_curve": equity_curve[-20:] if len(equity_curve) > 20 else equity_curve,
        "drawdown_curve": drawdown_curve[-20:] if len(drawdown_curve) > 20 else drawdown_curve,
        "average_trade_duration_min": round(sum(durations) / len(durations), 1) if durations else None,
        "best_trade": max((t.net_pnl for t in completed if t.net_pnl is not None), default=0),
        "worst_trade": min((t.net_pnl for t in completed if t.net_pnl is not None), default=0),
        "entry_hour_distribution": hour_distribution,
        "r_multiples": [round(r, 2) for r in r_multiples],
    }
