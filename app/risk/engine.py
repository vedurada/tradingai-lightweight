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
        max_risk_pct = candidate.get('max_risk', 0)
        expected_reward = candidate.get('expected_reward', 0)
        if entry <= 0 or stop <= 0 or target <= 0:
            reasons.append('invalid_levels')
            return False, reasons
        risk_pct = abs(entry - stop) / entry * 100 if entry else 0
        reward_pct = abs(target - entry) / entry * 100 if entry else 0
        if risk_pct <= 0:
            reasons.append('zero_risk')
            return False, reasons
        rr = reward_pct / risk_pct if risk_pct > 0 else 0
        candidate['risk_reward'] = rr
        if rr < self.min_reward_risk - 1e-9:
            reasons.append(f'reward_risk_insufficient ({rr:.2f} < {self.min_reward_risk})')
            return False, reasons
        if max_risk_pct > 0 and risk_pct > max_risk_pct + 1e-9:
            reasons.append(f'risk_exceeds_max ({risk_pct:.4f}% > {max_risk_pct}%)')
            return False, reasons
        return True, reasons
