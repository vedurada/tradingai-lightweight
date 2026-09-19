from zoneinfo import ZoneInfo
_IST = ZoneInfo('Asia/Kolkata')

class RiskEngine:
    def __init__(self, settings=None):
        self.max_risk_pct = 2.0
        self.min_reward_risk = 1.5
        self.max_holding_hours = 4
        if settings:
            self.max_risk_pct = settings.get('max_risk_pct', 2.0)
            self.min_reward_risk = settings.get('min_reward_risk', 1.5)
            self.max_holding_hours = settings.get('max_holding_hours', 4)

    def validate(self, candidate):
        reasons = []
        entry = candidate.get('entry', 0)
        stop = candidate.get('stop', 0)
        target = candidate.get('target', 0)
        max_risk = candidate.get('max_risk', 0)
        expected_reward = candidate.get('expected_reward', 0)
        if entry <= 0 or stop <= 0 or target <= 0:
            reasons.append('invalid_levels')
            return False, reasons
        risk = abs(entry - stop)
        reward = abs(target - entry)
        if risk <= 0:
            reasons.append('zero_risk')
            return False, reasons
        rr = reward / risk if risk > 0 else 0
        candidate['risk_reward'] = rr
        if rr < self.min_reward_risk:
            reasons.append(f'reward_risk_insufficient ({rr:.2f} < {self.min_reward_risk})')
            return False, reasons
        if max_risk > 0 and risk > max_risk:
            reasons.append(f'risk_exceeds_max ({risk} > {max_risk})')
            return False, reasons
        return True, reasons
