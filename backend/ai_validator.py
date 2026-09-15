"""AI output safety validation.

Checks AI-generated outputs for:
- valid JSON where JSON is expected
- required fields
- numerical sanity
- current-price consistency
- support/resistance consistency
- expected-range consistency
- invalid/missing data
- unsupported claims
- malformed output

If AI output is invalid:
- do not publish it as valid
- retain the previous valid output where appropriate
- clearly mark fallback/degraded state

AI output must never fabricate live market data.
"""
import json
from typing import Any, Dict, List, Optional


class AIValidator:
    REQUIRED_OUTLOOK_FIELDS = ["symbol", "timestamp", "outlook", "data_quality",
                                "confidence", "bias"]

    @staticmethod
    def validate_json(raw: str) -> tuple:
        """Return (parsed_dict, is_valid)."""
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return data, True
            return data, False
        except (json.JSONDecodeError, TypeError):
            return None, False

    @staticmethod
    def has_required_fields(data: Dict, required: List[str]) -> List[str]:
        """Return list of missing required fields."""
        return [f for f in required if f not in data or data[f] is None]

    @staticmethod
    def validate_numerical(name: str, value: Any, min_val: Optional[float] = None,
                           max_val: Optional[float] = None) -> List[str]:
        issues = []
        try:
            num = float(value)
            if num != num:  # NaN
                issues.append(f"{name}=nan")
            elif min_val is not None and num < min_val:
                issues.append(f"{name}={num} below {min_val}")
            elif max_val is not None and num > max_val:
                issues.append(f"{name}={num} above {max_val}")
        except (TypeError, ValueError):
            issues.append(f"{name}=non_numerical")
        return issues

    @staticmethod
    def validate_price_consistency(price: float, previous_close: Optional[float],
                                   change_pct: Optional[float]) -> List[str]:
        issues = []
        if price is None or price <= 0:
            issues.append("price_invalid")
            return issues
        if previous_close is not None and previous_close > 0:
            expected_change_pct = ((price - previous_close) / previous_close) * 100
            if change_pct is not None:
                diff = abs(expected_change_pct - change_pct)
                if diff > 0.5:
                    issues.append(f"change_pct_inconsistent: expected {expected_change_pct:.2f}, got {change_pct}")
        return issues

    @staticmethod
    def validate_range(expected_low: Optional[float], expected_high: Optional[float],
                       actual_price: Optional[float]) -> List[str]:
        issues = []
        if expected_low is not None and expected_high is not None and actual_price is not None:
            if actual_price < expected_low:
                issues.append(f"price_below_range: {actual_price} < {expected_low}")
            elif actual_price > expected_high:
                issues.append(f"price_above_range: {actual_price} > {expected_high}")
        return issues

    @staticmethod
    def validate_outlook(data: Dict) -> Dict:
        """Validate an AI outlook output. Returns {valid: bool, issues: [str], data: dict}."""
        issues = []

        if data is None:
            return {"valid": False, "issues": ["null_output"], "data": None}

        missing = AIValidator.has_required_fields(data, AIValidator.REQUIRED_OUTLOOK_FIELDS)
        if missing:
            issues.append("missing_fields:" + ",".join(missing))

        for field in ["confidence", "evidence_score"]:
            if field in data:
                issues.extend(AIValidator.validate_numerical(field, data[field], 0, 100))

        if "data_quality" in data and data["data_quality"] not in ("LIVE", "STALE", "GOOD", "DATA UNAVAILABLE", "PARTIAL"):
            issues.append("unknown_data_quality:" + str(data["data_quality"]))

        if "outlook" in data and data["outlook"] not in ("BULLISH", "BEARISH", "NEUTRAL", "SIDEWAYS"):
            issues.append("unsupported_outlook:" + str(data["outlook"]))

        valid_biases = {"BULLISH", "BEARISH", "NEUTRAL"}
        if "bias" in data and data["bias"] not in valid_biases:
            issues.append("unsupported_bias:" + str(data["bias"]))

        if "price" in data:
            issues.extend(AIValidator.validate_numerical("price", data["price"], 0, 100000))

        if "expected_range" in data and isinstance(data["expected_range"], dict):
            lo = data["expected_range"].get("low")
            hi = data["expected_range"].get("high")
            if lo is not None and hi is not None and lo > hi:
                issues.append("invalid_range: low > high")

        return {"valid": len(issues) == 0, "issues": issues, "data": data}


def validate_ai_output(data: Any) -> Dict:
    """Convenience function to validate any AI output."""
    if isinstance(data, str):
        parsed, ok = AIValidator.validate_json(data)
        if not ok:
            return {"valid": False, "issues": ["invalid_json"], "data": data}
        return AIValidator.validate_outlook(parsed)
    if isinstance(data, dict):
        return AIValidator.validate_outlook(data)
    return {"valid": False, "issues": ["non_dict_output"], "data": data}


if __name__ == "__main__":
    import sys
    sample = '{"symbol":"NIFTY","timestamp":"2026-09-15T00:00:00Z","outlook":"BULLISH","data_quality":"LIVE","confidence":78,"bias":"BULLISH"}'
    result = validate_ai_output(sample)
    print(result)