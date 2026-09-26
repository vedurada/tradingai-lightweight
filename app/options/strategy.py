"""Phase 15: deterministic options strategy validation and trade economics.

Five approved strategies:
- BULL_PUT_SPREAD, BULL_CALL_SPREAD, BEAR_CALL_SPREAD, BEAR_PUT_SPREAD, IRON_CONDOR

Core rule: NO VALIDATED OPTIONS DATA → NO VALIDATED OPTIONS TRADE.
When data is unavailable, returns NO_TRADE with explicit reason.
Never fabricates contracts, premiums, IV, OI, or expiry.
"""
from enum import Enum
from app.options.contract import (OptionsFreshness, VALID_INSTRUMENTS,
                                    VALID_OPTION_TYPES, validate_contract)


class StrategyType(Enum):
    BULL_PUT_SPREAD = "BULL_PUT_SPREAD"
    BULL_CALL_SPREAD = "BULL_CALL_SPREAD"
    BEAR_CALL_SPREAD = "BEAR_CALL_SPREAD"
    BEAR_PUT_SPREAD = "BEAR_PUT_SPREAD"
    IRON_CONDOR = "IRON_CONDOR"


APPROVED_STRATEGIES = {s.value for s in StrategyType}

# Required fields per strategy leg
REQUIRED_FIELDS = {"instrument", "expiry", "strike", "option_type",
                   "last_price", "bid", "ask", "volume", "open_interest"}


class TradeResult:
    def __init__(self, status, reason=None, strategy=None, legs=None,
                 economics=None, errors=None):
        self.status = status        # NO_TRADE | STRATEGY_VALID
        self.reason = reason        # explicit reason for NO_TRADE
        self.strategy = strategy    # StrategyType or None
        self.legs = legs or []      # validated contract legs
        self.economics = economics  # calculated economics or None
        self.errors = errors or []  # validation errors

    def to_dict(self):
        return {"status": self.status, "reason": self.reason,
                "strategy": self.strategy.value if self.strategy else None,
                "legs": self.legs, "economics": self.economics,
                "errors": self.errors}


def validate_leg(contract, required_fields=None):
    """Validate a single option contract leg.
    Returns (is_valid, errors)."""
    if required_fields is None:
        required_fields = REQUIRED_FIELDS
    errors = []
    valid, val_errors = validate_contract(contract)
    if not valid:
        errors.extend(val_errors)
    for field in required_fields:
        if contract.get(field) is None:
            errors.append(f"MISSING_{field}")
    # Check freshness if timestamp present
    if contract.get("timestamp"):
        from app.options.contract import classify_freshness
        freshness, age = classify_freshness(contract["timestamp"])
        if freshness != OptionsFreshness.OPTIONS_FRESH:
            errors.append(f"CONTRACT_NOT_FRESH:{freshness.value}")
    # Price must be positive
    for p in ("last_price", "bid", "ask"):
        v = contract.get(p)
        if v is not None and v <= 0:
            errors.append(f"NON_POSITIVE_{p.upper()}")
    return len(errors) == 0, errors


def validate_legs(legs):
    """Validate all legs of a strategy.
    Returns (is_valid, errors)."""
    errors = []
    if not legs:
        return False, ["NO_LEGURES"]
    for i, leg in enumerate(legs):
        valid, leg_errors = validate_leg(leg)
        if not valid:
            errors.append(f"LEG_{i}:{', '.join(leg_errors)}")
    return len(errors) == 0, errors


def same_instrument(legs):
    return len(set(l.get("instrument") for l in legs)) == 1


def same_expiry(legs):
    return len(set(l.get("expiry") for l in legs)) == 1


def no_duplicates(legs):
    keys = [(l.get("instrument"), l.get("expiry"), l.get("strike"),
             l.get("option_type")) for l in legs]
    return len(keys) == len(set(keys))
