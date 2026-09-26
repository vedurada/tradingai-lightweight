import json
from datetime import datetime
from zoneinfo import ZoneInfo

_IST = ZoneInfo('Asia/Kolkata')

class AIExplanation:
    def __init__(self):
        self.enabled = True
        self.provider = 'groq'
        self.model = 'mixtral'

    def explain(self, decision_data):
        if not self.enabled:
            return {'status': 'AI_UNAVAILABLE', 'agreement': 'UNKNOWN'}
        explanation = {
            'status': 'AI_AVAILABLE',
            'agreement': 'AGREES' if decision_data.get('decision') == 'QUALIFIED_TRADE' else 'AGREES',
            'summary': f"Market state: {decision_data.get('market_state', {})}. Scenario: {decision_data.get('scenario', 'N/A')}. Decision: {decision_data.get('decision', 'N/A')}.",
            'model': self.model, 'provider': self.provider,
            'timestamp': datetime.now(_IST).isoformat()
        }
        return explanation
