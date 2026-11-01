"""Strategy selection: credit-only default with correct volatility mapping.

R-DEFINITION MAP: this module emits names only (no R math). Downstream
risk_reward (percent ratio) equals canonical backtest R for spot trades;
options economics reward/risk equals canonical R at max outcome.

VOLATILITY MAPPING (fixes inverted HIGH->debit):
- Correct economics: HIGH vol -> CREDIT (Bull Put / Bear Call — short
  premium richly priced, theta in our favour).
- LOW vol -> DEBIT (Bull Call / Bear Put — cheap long premium).
- NORMAL/None -> CREDIT (conservative default).
- CREDIT_ONLY=True (owner policy, default) gates debit legs: even when
  volatility is LOW, credit spreads are emitted and debit calculators are
  NOT dispatched (see app/options/engine.py CREDIT_ONLY gate). Set
  CREDIT_ONLY=False in research to allow debit dispatch.
- RANGE / non-directional -> Iron Condor (THETA_DECAY). Condor is WIRED
  (dispatched in options engine); not removed.

STRATEGY_CATEGORIES retains debit names for taxonomy/research; live
dispatch is gated by CREDIT_ONLY.
"""
import json
from zoneinfo import ZoneInfo
_IST = ZoneInfo('Asia/Kolkata')

STRATEGY_CATEGORIES = {
    'BULLISH': ['Bull Put Spread', 'Bull Call Spread'],
    'BEARISH': ['Bear Call Spread', 'Bear Put Spread'],
    'RANGE': ['Iron Condor'],
}

OBJECTIVES = {'BULLISH': 'DIRECTIONAL', 'BEARISH': 'DIRECTIONAL', 'RANGE': 'THETA_DECAY', 'HYBRID': 'HYBRID'}

# Owner policy: credit spreads ONLY by default. Debit legs never emitted
# unless explicitly opted out (research).
CREDIT_ONLY = True

class StrategyEngine:
    def select_strategy(self, scenario_type, direction, volatility, options_valid=True, credit_only=None):
        """Select strategy with correct HIGH->credit / LOW->debit mapping.

        Args:
            scenario_type: e.g. RANGE (forces Iron Condor).
            direction: BULLISH / BEARISH / else (condor).
            volatility: HIGH / LOW / NORMAL / None.
            options_valid: False -> NO_TRADE (computed upstream via
                app.options.engine.is_options_data_valid; research forces
                True as spot-proxy with documented limitation).
            credit_only: override module CREDIT_ONLY when not None.
        """
        if not options_valid:
            return {'status': 'NO_TRADE', 'reason': 'options_unavailable'}
        gate = CREDIT_ONLY if credit_only is None else bool(credit_only)
        vol = (volatility or 'NORMAL').upper()
        # RANGE scenario or non-directional -> Iron Condor (wired).
        if (scenario_type or '').upper() == 'RANGE' or direction not in ('BULLISH', 'BEARISH'):
            if direction not in ('BULLISH', 'BEARISH'):
                return {'strategy': 'Iron Condor', 'objective': 'THETA_DECAY', 'direction': direction, 'scenario_type': scenario_type}
            # Directional within RANGE scenario still directional credit by default.
            pass
        if direction == 'BULLISH':
            # FIX: HIGH->credit (Bull Put), LOW->debit (Bull Call).
            if gate:
                strategy = 'Bull Put Spread'
            else:
                strategy = 'Bull Put Spread' if vol in ('HIGH', 'NORMAL') else 'Bull Call Spread'
            objective = 'DIRECTIONAL'
        elif direction == 'BEARISH':
            # FIX: HIGH->credit (Bear Call), LOW->debit (Bear Put).
            if gate:
                strategy = 'Bear Call Spread'
            else:
                strategy = 'Bear Call Spread' if vol in ('HIGH', 'NORMAL') else 'Bear Put Spread'
            objective = 'DIRECTIONAL'
        else:
            strategy = 'Iron Condor'
            objective = 'THETA_DECAY'
        return {'strategy': strategy, 'objective': objective, 'direction': direction, 'scenario_type': scenario_type}
