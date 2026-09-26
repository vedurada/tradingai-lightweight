import json, sqlite3, uuid
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
        self.research_daily_locks = set()

    def reset_research_locks(self):
        self.research_daily_locks.clear()

    def qualify(self, instrument_id, market_state, options_valid=True, research=False, trade_date=None,
                  as_of=None):
        reasons = []
        if trade_date is None:
            trade_date = datetime.now(_IST).strftime('%Y-%m-%d')
        daily_lock_key = (instrument_id, trade_date)
        if daily_lock_key in self.research_daily_locks:
            return {'decision': 'NO_TRADE', 'reasons': ['DAILY_TRADE_LIMIT_REACHED'], 'trade': None}
        # Point-in-time rule: historical decisions (as_of set) use the latest
        # scenario known at that timestamp; live path (as_of None) uses current state.
        if as_of is not None:
            active = self.scenario.get_scenario_for_timestamp(instrument_id, as_of)
        else:
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
            options_valid)
        if strategy_info.get('status') == 'NO_TRADE':
            return {'decision': 'NO_TRADE', 'reasons': [strategy_info['reason']], 'trade': None}
        if not market_state.get('price'):
            return {'decision': 'NO_TRADE', 'reasons': ['PRICE_UNAVAILABLE'], 'trade': None}
        # Legacy intraday levels: 0.5% under signal, 1% stop, 2% target.
        # NOTE: the approved CPR-trigger book (cpr_trigger_engine run_opens_range
        # + paper_align) uses 0.5% stop / 2% target on next-open entries instead.
        # The two paths intentionally differ; do not "unify" without revalidation.
        entry = market_state['price'] * 0.995
        stop = entry - (entry * 0.01)
        target = entry + (entry * 0.02)
        risk_pct = round((entry - stop) / entry * 100, 4)
        reward_pct = round((target - entry) / entry * 100, 4)
        candidate = {
            'entry': round(entry, 2), 'stop': round(stop, 2), 'target': round(target, 2),
            'max_risk': risk_pct, 'expected_reward': reward_pct,
            'strategy': strategy_info['strategy'], 'objective': strategy_info['objective'],
            'direction': strategy_info['direction'], 'scenario': active['candidate']['scenario_type']
        }
        risk_ok, risk_reasons = self.risk.validate(candidate)
        if not risk_ok:
            return {'decision': 'NO_TRADE', 'reasons': risk_reasons, 'trade': None}
        if not options_valid:
            return {'decision': 'NO_TRADE', 'reasons': ['options_data_unavailable'], 'trade': None}
        if not research:
            # Cross-worker race guard: UNIQUE(instrument_id, date) means a
            # concurrent worker may persist first; the loser sees
            # IntegrityError and must report daily-limit (never a 500).
            try:
                trade_id = str(uuid.uuid4())[:16].upper()
                date_str = trade_date
                self.conn.execute('INSERT INTO qualified_trades (trade_id, instrument_id, date, timestamp, scenario, strategy, objective, direction, entry, stop, target, max_risk, expected_reward, risk_reward, qualification_evidence, status, daily_lock_consumed, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (trade_id, instrument_id, date_str, datetime.now(_IST).isoformat(), candidate['scenario'], strategy_info['strategy'], strategy_info['objective'], strategy_info['direction'], candidate['entry'], candidate['stop'], candidate['target'], candidate['max_risk'], candidate['expected_reward'], candidate['expected_reward'] / candidate['max_risk'] if candidate['max_risk'] else 0, json.dumps(market_state), 'QUALIFIED', 0, datetime.now(_IST).isoformat()))
                self.conn.execute('INSERT OR REPLACE INTO daily_trade_locks (lock_id, instrument_id, date, status, trade_id, locked_at, consumed_at, created_at) VALUES (?,?,?,?,?,?,?,?)',
                    (f'LCK-{instrument_id}-{date_str}', instrument_id, date_str, 'CONSUMED', trade_id, datetime.now(_IST).isoformat(), datetime.now(_IST).isoformat(), datetime.now(_IST).isoformat()))
                self.conn.commit()
            except sqlite3.IntegrityError:
                self.conn.rollback()
                self.research_daily_locks.add(daily_lock_key)
                return {'decision': 'NO_TRADE', 'reasons': ['DAILY_TRADE_LIMIT_REACHED'], 'trade': None}
        self.research_daily_locks.add(daily_lock_key)
        return {'decision': 'QUALIFIED_TRADE', 'trade_id': None if research else str(uuid.uuid4())[:16].upper(), 'trade': candidate, 'reasons': []}
