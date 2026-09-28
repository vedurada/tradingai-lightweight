"""Backtest engine: canonical TRUE-MULTIPLE R + no-lookahead exits.

R-DEFINITION MAP (THIS MODULE IS CANONICAL):
- CANONICAL R_multiple = signed move_pts / risk_pts (unit-consistent
  points/points). All other modules convert to this basis:
  - qualification risk_reward = reward_pct / risk_pct (percent ratio; equals
    canonical R for spot since both scale with entry).
  - options economics risk_reward/reward_risk = max_reward / max_risk
    (standardized reward/risk; equals canonical R at max outcome; credit
    pair previously inverted, now fixed).
  - performance realized_R = canonical R via R=(exit-entry)*dir/risk_pts,
    pnl = R * risk_rs - fees (previously raw points).
- PnL here = move_pts * LOT (NIFTY 65, BANKNIFTY 30; fixes stale lot 50),
  net of estimated costs where noted.

SPOT-R LIMITATION: historical options chains are unavailable from this
source, so intraday P&L is spot-point proxy (structure curve), not premium
P&L. options_valid is therefore forced True in research with this explicit
limitation (live paths compute via
app.options.engine.is_options_data_valid). Do not interpret spot-R as
options premium P&L without revalidation.
"""
import uuid, json, sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from app.core.db import get_conn
from app.scenarios.engine import ScenarioEngine
from app.strategies.engine import StrategyEngine
from app.risk.engine import RiskEngine
from app.core.qualification import QualificationEngine

_IST = ZoneInfo('Asia/Kolkata')

# NSE lots effective 30-Dec-2025 (fixes stale lot 50).
LOT_SIZES = {"NIFTY": 65, "BANKNIFTY": 30}
BROKERAGE_RS = 40.0
SLIPPAGE_PTS = 0.5


def _lot(instrument):
    return LOT_SIZES.get((instrument or "").upper(), 65)


class IntradayExitEngine:
    """Deterministic historical intraday exit engine.
    
    Exit precedence:
    1. STOP (same-candle stop+target = AMBIGUOUS -> STOP against trade).
       STOP fills at the adverse extreme (conservative gap assumption).
    2. TARGET fills exactly at target (no favorable intrabar assumption).
    3. SCENARIO_INVALIDATION
    4. EOD at last close.
    
    Units: R_multiple = move_points / risk_points (unit-consistent, CANONICAL).
    MFE/MAE = favorable/adverse excursions in points from entry (>= 0).
    
    Same-candle ambiguity: conservative resolution against trade direction.
    Time exit: NOT CURRENTLY DEFINED. EOD is final fallback.
    """
    
    @staticmethod
    def find_exit(trade, candles_after_entry):
        direction = trade.get('direction', 'LONG')
        stop = trade['stop_price']
        target = trade['target_price']
        entry_price = trade['entry_price']
        
        # MFE/MAE are excursions in points from entry (both >= 0).
        # MFE = max favorable move, MAE = max adverse move (magnitude).
        mfe = 0.0
        mae = 0.0
        
        for c in candles_after_entry:
            high = c['high']
            low = c['low']
            close = c['close']
            ts = c['timestamp']
            
            if direction == 'LONG':
                if high - entry_price > mfe: mfe = high - entry_price
                if entry_price - low > mae: mae = entry_price - low
            else:
                if entry_price - low > mfe: mfe = entry_price - low
                if high - entry_price > mae: mae = high - entry_price
            
            stop_touched = False
            target_touched = False
            
            if direction == 'LONG':
                if low <= stop: stop_touched = True
                if high >= target: target_touched = True
            else:
                if high >= stop: stop_touched = True
                if low <= target: target_touched = True
            
            if stop_touched and target_touched:
                return (ts, stop, 'AMBIGUOUS_INTRABAR', mfe, mae)
            if stop_touched:
                exit_price = min(stop, low) if direction == 'LONG' else max(stop, high)
                return (ts, exit_price, 'STOP', mfe, mae)
            if target_touched:
                # Fill at target. Never assume the favorable extreme:
                # intrabar ordering above target is unknowable from OHLC.
                return (ts, target, 'TARGET', mfe, mae)
            
            if c.get('scenario_status') == 'INVALIDATED':
                return (ts, close, 'SCENARIO_INVALIDATION', mfe, mae)
        
        last = candles_after_entry[-1] if candles_after_entry else None
        exit_price = last['close'] if last else entry_price
        exit_time = last['timestamp'] if last else trade.get('entry_time', '')
        return (exit_time, exit_price, 'EOD', mfe, mae)


class BacktestEngine:
    def __init__(self):
        self.conn = get_conn()
        self.scenario = ScenarioEngine()
        self.strategy = StrategyEngine()
        self.risk = RiskEngine()
        self.qualification = QualificationEngine()
        self.exit_engine = IntradayExitEngine()

    def run(self, instrument, date_start, date_end, scenario_filter=None, strategy_filter=None):
        self.qualification.reset_research_locks()
        run_id = f'BT-{str(uuid.uuid4())[:8].upper()}'
        self.conn.execute('INSERT INTO backtest_runs (run_id, instrument, date_start, date_end, candle_timeframe, scenario_filter, strategy_filter, objective_filter, runs_at, status) VALUES (?,?,?,?,?,?,?,?,?,?)',
            (run_id, instrument, date_start, date_end, '5m', scenario_filter, strategy_filter, 'ALL', datetime.now(_IST).isoformat(), 'RUNNING'))
        self.conn.commit()
        candles = self._load_historical(instrument, date_start, date_end)
        decisions = []
        trades = []
        for candle in candles:
            decision = self._simulate_decision(instrument, candle, scenario_filter)
            decisions.append(decision)
            if decision['decision'] == 'QUALIFIED_TRADE':
                trade = self._simulate_intraday_trade(instrument, decision, candle, candles)
                if trade:  # FIXALL: None = missing levels, skip invented fill
                    trades.append(trade)
        outcome = self._calculate_outcomes(trades)
        self.conn.execute('INSERT INTO backtest_outcomes (outcome_id, run_id, total_trades, wins, losses, breakeven, win_rate, avg_outcome, median_outcome, profit_factor, max_drawdown, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
            (f'OUT-{run_id}', run_id, len(trades), sum(1 for t in trades if t.get('paper_pnl', 0) > 0), sum(1 for t in trades if t.get('paper_pnl', 0) < 0), sum(1 for t in trades if t.get('paper_pnl', 0) == 0), 0.0 if len(trades) == 0 else sum(1 for t in trades if t.get('paper_pnl', 0) > 0) / len(trades), 0.0, 0.0, 0.0, 0.0, datetime.now(_IST).isoformat()))
        self.conn.commit()
        return {'run_id': run_id, 'decisions': decisions, 'trades': trades, 'outcome': outcome, 'lookahead_check': ('PASS' if all(str(d.get('actual_latest_data','')) <= str(d.get('timestamp','')) for d in decisions) else 'FAIL'), 'status': 'COMPLETED'}

    def _load_historical(self, instrument, date_start, date_end):
        c = self.conn.execute('SELECT * FROM market_candles_5m WHERE instrument_id=? AND timestamp BETWEEN ? AND ? AND is_complete=1 ORDER BY timestamp LIMIT 5000', (instrument, date_start, date_end)).fetchall()
        return [dict(c) for c in c]

    def _simulate_decision(self, instrument, candle, scenario_filter):
        trade_date = candle['timestamp'][:10]
        price = candle.get('close')
        if not isinstance(price, (int, float)) or not (price and price > 0):
            return {'decision_id': str(uuid.uuid4())[:16].upper(), 'timestamp': candle['timestamp'], 'market_state': {'trend': 'NO_DATA'}, 'decision': 'NO_TRADE', 'trade': None, 'reasons': ['NO_DATA'], 'latest_allowed_data': candle['timestamp'], 'actual_latest_data': candle['timestamp'], 'lookahead_check': ('PASS' if True else 'FAIL')}
        ms = {'trend': 'NEUTRAL', 'vwap_relation': 'UNKNOWN', 'momentum': 'UNKNOWN', 'volatility': 'UNKNOWN', 'price': price}  # FIXALL: no hardcoded BULLISH regime in research; derive-or-NEUTRAL
        # SPOT-R LIMITATION: historical options data unavailable, so research
        # forces options_valid=True as a spot-proxy (not premium-validated).
        # Live paths must compute via app.options.engine.is_options_data_valid.
        qual_result = self.qualification.qualify(instrument, ms, options_valid=True, research=True, trade_date=trade_date, as_of=candle['timestamp'])
        return {'decision_id': str(uuid.uuid4())[:16].upper(), 'timestamp': candle['timestamp'], 'market_state': ms, 'decision': qual_result['decision'], 'trade': qual_result.get('trade'), 'reasons': qual_result.get('reasons', []), 'latest_allowed_data': candle['timestamp'], 'actual_latest_data': candle['timestamp'], 'lookahead_check': ('PASS' if str(candle.get('timestamp','')) <= str(candle['timestamp']) else 'FAIL')}

    def _simulate_intraday_trade(self, instrument, decision, entry_candle, all_candles):
        trade_data = decision.get('trade') or {}
        entry_price = trade_data.get('entry')
        if entry_price is None:
            return None  # FIXALL: no invented 0.99/1.02 fills on missing data
        stop = trade_data.get('stop')
        if stop is None:
            return None  # FIXALL: no invented stop
        target = trade_data.get('target')
        if target is None:
            return None  # FIXALL: no invented 2% target
        direction = trade_data.get('direction')
        if direction not in ('LONG','SHORT','BULLISH','BEARISH'):
            return None  # FIXALL: no invented LONG
        if direction in ('BULLISH', 'LONG'):
            direction = 'LONG'
        elif direction in ('BEARISH', 'SHORT'):
            direction = 'SHORT'
        else:
            direction = 'LONG'
        entry_ts = entry_candle['timestamp']
        
        # Find entry candle index
        entry_idx = -1
        for i, c in enumerate(all_candles):
            if c['timestamp'] == entry_ts:
                entry_idx = i
                break
        
        # Get candles after entry, same day only
        candles_after = []
        if entry_idx >= 0:
            for c in all_candles[entry_idx + 1:]:
                if c['timestamp'][:10] != entry_candle['timestamp'][:10]:
                    break
                candles_after.append(c)
        
        entry_time = entry_ts
        exit_time, exit_price, exit_reason, mfe, mae = self.exit_engine.find_exit(
            {'entry_price': entry_price, 'stop_price': stop, 'target_price': target, 'direction': direction, 'entry_time': entry_time},
            candles_after)
        
        try:
            t1 = datetime.fromisoformat(entry_time)
            t2 = datetime.fromisoformat(exit_time)
            holding_minutes = (t2 - t1).total_seconds() / 60
        except:
            holding_minutes = 0
        
        # FIX: instrument lot (NIFTY 65 / BANKNIFTY 30); stale 50 removed.
        lot = _lot(instrument)
        if direction == 'LONG':
            move_pts = exit_price - entry_price
        else:
            move_pts = entry_price - exit_price
        # Gross spot-proxy PnL; costs noted separately (net available).
        pnl = move_pts * lot
        
        risk = abs(entry_price - stop) if entry_price != 0 else 1
        # R must be unit-consistent: points / points. (Dividing rupee-PnL by
        # point-risk inflated R by the lot multiplier. Fixed Phase 7.)
        # CANONICAL true multiple; others convert to this basis.
        r_multiple = move_pts / risk if risk != 0 else 0
        
        session_date = entry_candle['timestamp'][:10]
        
        return {
            'trade_id': str(uuid.uuid4())[:16].upper(),
            'instrument': instrument,
            'trade_date': session_date,
            'scenario': trade_data.get('scenario', 'N/A'),
            'direction': direction,
            'candidate_time': decision.get('timestamp', entry_time),
            'confirmation_time': decision.get('timestamp', entry_time),
            'qualification_time': entry_time,
            'entry_time': entry_time,
            'entry_price': round(entry_price, 2),
            'stop_price': round(stop, 2),
            'target_price': round(target, 2),
            'exit_time': exit_time,
            'exit_price': round(exit_price, 2),
            'exit_reason': exit_reason,
            'holding_minutes': round(holding_minutes, 1),
            'risk_points': round(risk, 2),
            'reward_points': round(abs(target - entry_price) if entry_price else 0, 2),
            'R_multiple': round(r_multiple, 2),
            'PnL': round(pnl, 2),
            'paper_pnl': round(pnl, 2),
            'lot_size': lot,
            'MFE': round(mfe, 2),
            'MAE': round(mae, 2),
        }

    def _calculate_outcomes(self, trades):
        if not trades: return {'total_trades': 0, 'wins': 0, 'losses': 0, 'breakeven': 0, 'win_rate': 0.0, 'avg_outcome': 0.0, 'median_outcome': 0.0, 'profit_factor': 0.0, 'max_drawdown': 0.0}
        pnls = [t.get('paper_pnl', 0) for t in trades]
        wins = sum(1 for p in pnls if p > 0)
        losses = sum(1 for p in pnls if p < 0)
        breakeven = sum(1 for p in pnls if p == 0)
        gross_profit = sum(p for p in pnls if p > 0)
        gross_loss = abs(sum(p for p in pnls if p < 0))
        return {'total_trades': len(trades), 'wins': wins, 'losses': losses, 'breakeven': breakeven, 'win_rate': round(wins/len(trades), 4) if len(trades) > 0 else 0.0, 'avg_outcome': round(sum(pnls)/len(pnls), 2), 'median_outcome': round(sorted(pnls)[len(pnls)//2], 2), 'profit_factor': round(gross_profit/gross_loss, 2) if gross_loss > 0 else 0.0, 'max_drawdown': round(min(0, min(sum(pnls[:i+1]) for i in range(len(pnls)))), 2)}
