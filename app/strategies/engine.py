import json
from zoneinfo import ZoneInfo
_IST = ZoneInfo('Asia/Kolkata')

STRATEGY_CATEGORIES = {
    'BULLISH': ['Bull Put Spread', 'Bull Call Spread'],
    'BEARISH': ['Bear Call Spread', 'Bear Put Spread'],
    'RANGE': ['Iron Condor'],
}

OBJECTIVES = {'BULLISH': 'DIRECTIONAL', 'BEARISH': 'DIRECTIONAL', 'RANGE': 'THETA_DECAY', 'HYBRID': 'HYBRID'}

class StrategyEngine:
    # Credit spreads ONLY (owner policy): collected premium decays in our
    # favour, so direction no longer switches on volatility. Debit legs
    # (Bull Call / Bear Put) are never emitted.
    def select_strategy(self, scenario_type, direction, volatility, options_valid=True):
        if not options_valid:
            return {'status': 'NO_TRADE', 'reason': 'options_unavailable'}
        if direction == 'BULLISH':
            strategy = 'Bull Put Spread'
            objective = 'DIRECTIONAL'
        elif direction == 'BEARISH':
            strategy = 'Bear Call Spread'
            objective = 'DIRECTIONAL'
        else:
            strategy = 'Iron Condor'
            objective = 'THETA_DECAY'
        return {'strategy': strategy, 'objective': objective, 'direction': direction, 'scenario_type': scenario_type}
