from zoneinfo import ZoneInfo
_IST = ZoneInfo('Asia/Kolkata')

class RiskEngine:
    def __init__(self, settings=None):
        # settings.json nests these under risk:{...}; accept both shapes so
        # config stays effective (previously top-level lookup always missed
        # and silently fell back to literals).
        cfg = (settings or {})
        rk = cfg.get('risk', cfg) if isinstance(cfg, dict) else {}
        if not isinstance(rk, dict):
            rk = {}
        self.max_risk_pct = 2.0
        self.min_reward_risk = 1.5
        self.max_holding_hours = 4
        if rk:
            self.max_risk_pct = rk.get('max_risk_pct', 2.0)
            self.min_reward_risk = rk.get('min_reward_risk', 1.5)
            self.max_holding_hours = rk.get('max_holding_hours', 4)

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
        # eps 1e-4 absorbs 2-decimal rounding noise (~4e-5 in %-units at 23k prices); true breaches (>=1e-3) still rejected. (Phase 7 B4)
        if rr < self.min_reward_risk - 1e-4:
            reasons.append(f'reward_risk_insufficient ({rr:.2f} < {self.min_reward_risk})')
            return False, reasons
        if max_risk_pct > 0 and risk_pct > max_risk_pct + 1e-4:
            reasons.append(f'risk_exceeds_max ({risk_pct:.4f}% > {max_risk_pct}%)')
            return False, reasons
        return True, reasons
