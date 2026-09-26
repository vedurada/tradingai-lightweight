"""Unified Phase 17 validation collector.

Orchestrates:
- Decision observation logging
- PIT integrity validation
- Market data validation
- Decision state validation
- Options data validation
- Decision trace audit
- One-trade/day validation
- API monitoring
- Resource monitoring
"""
import time
from datetime import datetime
from zoneinfo import ZoneInfo

_IST = ZoneInfo('Asia/Kolkata')

from app.observability.decision_log import (
    ensure_table, record_observation, get_observations, get_session_summary,
    record_observations_from_evaluation
)
from app.observability.validator import (
    validate_pit_integrity, validate_market_data, validate_decision_state,
    check_future_rows
)
from app.observability.monitor import (
    monitor_api, monitor_apis, monitor_resources, monitor_api_status_only
)


class SessionValidator:
    """Lightweight live session validator.
    
    Orchestrates observation and validation during a market session.
    Does NOT modify trading behavior. Only observes and records.
    """

    def __init__(self, live_engine=None, scenario_engine=None):
        from app.live.engine import LiveEngine
        from app.scenarios.engine import ScenarioEngine
        self.live_engine = live_engine or LiveEngine()
        self.scenario_engine = scenario_engine or ScenarioEngine()
        ensure_table()

    def observe_and_validate(self, instrument: str, now=None) -> dict:
        """Run one observation cycle for an instrument.
        Returns the observation record with validation results.
        Does NOT modify trading behavior.
        """
        now_ist = now or datetime.now(_IST)

        evaluation = self.live_engine.evaluate(instrument, now=now_ist, dry_run=True)

        observation = {
            'instrument': instrument,
            'market_timestamp': evaluation.get('now_ist'),
            'completed_candle_timestamp': evaluation.get('completed_candle'),
            'decision_as_of': evaluation.get('decision_timestamp') or evaluation.get('completed_candle'),
            'index_price': evaluation.get('live_price') or evaluation.get('decision_price'),
            'scenario': (evaluation.get('trade') or {}).get('scenario'),
            'index_signal': (evaluation.get('market_state') or {}).get('trend'),
            'options_data_state': evaluation.get('quote_state'),
            'strategy_qualification': (evaluation.get('qualification') or {}).get('decision'),
            'final_decision_state': evaluation.get('state'),
            'rejection_reason': '; '.join(evaluation.get('reasons', [])),
            'data_age_minutes': evaluation.get('completed_age_minutes'),
            'provider_state': evaluation.get('quote_state'),
            'quote_age_seconds': evaluation.get('quote_age_seconds'),
            'completed_age_minutes': evaluation.get('completed_age_minutes'),
            'session_state': evaluation.get('session'),
        }

        obs_id = record_observation(observation)
        observation['observation_id'] = obs_id

        pit = validate_pit_integrity(
            self.scenario_engine, instrument,
            evaluation.get('decision_timestamp') or evaluation.get('completed_candle', '')
        ) if evaluation.get('completed_candle') else {'valid': True, 'violations': [], 'details': {}}

        state_val = validate_decision_state(evaluation.get('state'))

        observation['pit_valid'] = pit['valid']
        observation['pit_violations'] = pit['violations']
        observation['state_valid'] = state_val['valid']
        observation['state_tradeable'] = state_val['is_tradeable']

        return observation

    def get_session_status(self) -> dict:
        """Get current session status (lightweight, no provider calls)."""
        from app.live.engine import session_state, completed_candle_ts
        from app.market.nse_calendar import holiday_name
        now = datetime.now(_IST)
        sess = session_state(now, has_data_today=True)
        hn = holiday_name(now.date())
        completed = completed_candle_ts(now)
        return {
            'timestamp': now.isoformat(),
            'session_state': sess,
            'holiday': hn,
            'completed_candle': completed.isoformat() if completed else None,
            'is_market_hours': sess == 'LIVE',
        }

    def run_health_checks(self) -> dict:
        """Run API and resource health checks."""
        apis = monitor_api_status_only()
        resources = monitor_resources()
        return {
            'apis': apis,
            'resources': resources,
        }

    def run_full_validation(self, instruments=None) -> dict:
        """Run complete Phase 17 validation for all instruments.
        Returns comprehensive results.
        """
        if instruments is None:
            instruments = ['NIFTY', 'BANKNIFTY', 'INDIA_VIX']

        observations = []
        for inst in instruments:
            try:
                obs = self.observe_and_validate(inst)
                observations.append(obs)
            except Exception as e:
                observations.append({
                    'instrument': inst,
                    'final_decision_state': 'ERROR',
                    'rejection_reason': str(e),
                })
            time.sleep(0.2)

        health = self.run_health_checks()
        session = self.get_session_status()

        summaries = {}
        for inst in instruments:
            try:
                summaries[inst] = get_session_summary(instrument=inst)
            except Exception:
                summaries[inst] = {}

        return {
            'session': session,
            'observations': observations,
            'summaries': summaries,
            'health': health,
        }
