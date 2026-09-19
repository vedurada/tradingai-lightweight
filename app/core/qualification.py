import json, uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from app.core.db import get_conn
from app.scenarios.engine import ScenarioEngine
from app.strategies.engine import StrategyEngine
from app.risk.engine import RiskEngine

_IST = ZoneInfo('Asia/Kolkata')
MAX_TRADES_PER_DAY = 1

class QualificationEngine:
    def __init__(self, settings=None):
        self.conn = get_conn()
        self.scenario = ScenarioEngine()
        self.strategy = StrategyEngine()
        self.risk = RiskEngine(settings) if settings else RiskEngine()

    def qualify(self, instrument_id, market_state, options_valid=True):
        reasons = []
        daily_lock = self.conn.execute(
            'SELECT * FROM daily_trade_locks WHERE instrument_id=? AND date=?',
            (instrument_id, datetime.now(_IST).strftime('%Y-%m-%d'))
        ).fetchone()
        if daily_lock and daily_lock['status'] == 'CONSUMED':
            return {'decision': 'NO_TRADE', 'reasons': ['daily_trade_limit_consumed'], 'trade': None}
        active = self.scenario.get_active_scenario(instrument_id)
        if not active:
            return {'decision': 'NO_TRADE', 'reasons': ['no_active_scenario'], 'trade': None}
        match = active.get('match')
        if not match:
            return {'decision': 'NO_TRADE', 'reasons': ['scenario_not_matched'], 'trade': None}
        if match['match_state'] not in ('CONFIRMED',):
            return {'decision': 'NO_TRADE', 'reasons': [f'scenario_{match["match_state"].lower()}'], 'trade': None}
        strategy_info = self.strategy.select_strategy(
            active['candidate']['scenario_type'],
            market_state.get('trend', 'NEUTRAL'),
            market_state.get('volatility', 'NORMAL'),
            options_valid
        )
        if strategy_info.get('status') == 'NO_TRADE':
            return {'decision': 'NO_TRADE', 'reasons': [strategy_info['reason']], 'trade': None}
        entry = market_state.get('price', 0) * 0.995
        stop = entry - (entry * 0.01)
        target = entry + (entry * 0.02)
        candidate = {
            'entry': round(entry, 2), 'stop': round(stop, 2), 'target': round(target, 2),
            'max_risk': round(entry - stop, 2), 'expected_reward': round(target - entry, 2),
            'strategy': strategy_info['strategy'], 'objective': strategy_info['objective'],
            'direction': strategy_info['direction'], 'scenario': active['candidate']['scenario_type']
        }
        risk_ok, risk_reasons = self.risk.validate(candidate)
        if not risk_ok:
            return {'decision': 'NO_TRADE', 'reasons': risk_reasons, 'trade': None}
        if not options_valid:
            return {'decision': 'NO_TRADE', 'reasons': ['options_data_unavailable'], 'trade': None}
        trade_id = str(uuid.uuid4())[:16].upper()
        date_str = datetime.now(_IST).strftime('%Y-%m-%d')
        self.conn.execute('INSERT INTO qualified_trades (trade_id, instrument_id, date, timestamp, scenario, strategy, objective, direction, entry, stop, target, max_risk, expected_reward, risk_reward, qualification_evidence, status, daily_lock_consumed, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (trade_id, instrument_id, date_str, datetime.now(_IST).isoformat(), candidate['scenario'], strategy_info['strategy'], strategy_info['objective'], strategy_info['direction'], candidate['entry'], candidate['stop'], candidate['target'], candidate['max_risk'], candidate['expected_reward'], candidate['risk_reward'], json.dumps(market_state), 'QUALIFIED', 0, datetime.now(_IST).isoformat()))
        self.conn.execute('INSERT OR REPLACE INTO daily_trade_locks (lock_id, instrument_id, date, status, trade_id, locked_at, consumed_at, created_at) VALUES (?,?,?,?,?,?,?,?)',
            (f'LCK-{instrument_id}-{date_str}', instrument_id, date_str, 'CONSUMED', trade_id, datetime.now(_IST).isoformat(), datetime.now(_IST).isoformat(), datetime.now(_IST).isoformat()))
        self.conn.commit()
        return {'decision': 'QUALIFIED_TRADE', 'trade_id': trade_id, 'trade': candidate, 'reasons': []}
