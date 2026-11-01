"""Phase 16: Canonical decision state machine.

Authoritative backend states for the complete decision pipeline.
Every state is deterministic, explicit, with reason, timestamp,
instrument, and decision_as_of. No state implies a trade unless
all gates pass.
"""
from enum import Enum


class DecisionState(Enum):
    """Canonical decision states. Preserves backward compatibility
    with existing internal names while adding explicit options gate
    and daily-limit states."""

    # Pre-market (before 09:15 IST)
    PREMARKET = "PREMARKET"
    # Live session with valid data
    LIVE = "LIVE"
    # Qualified setup with complete evidence chain
    QUALIFIED = "QUALIFIED"
    # No trade — general rejection
    NO_TRADE = "NO_TRADE"
    # Options data unavailable
    OPTIONS_DATA_UNAVAILABLE = "OPTIONS_DATA_UNAVAILABLE"
    # Stale market data
    STALE = "STALE"
    # No market data
    NO_DATA = "NO_DATA"
    # Market closed (after 15:30 IST)
    MARKET_CLOSED = "MARKET_CLOSED"
    # Weekend
    WEEKEND = "WEEKEND"
    # Daily trade limit reached
    DAILY_TRADE_LIMIT_REACHED = "DAILY_TRADE_LIMIT_REACHED"
    # Rate limited
    RATE_LIMITED = "RATE_LIMITED"
    # Market holiday
    HOLIDAY = "HOLIDAY"
    # Options stale
    OPTIONS_STALE = "OPTIONS_STALE"
    # Partial chain
    OPTIONS_PARTIAL_CHAIN = "OPTIONS_PARTIAL_CHAIN"
    # Rate limited
    OPTIONS_RATE_LIMITED = "OPTIONS_RATE_LIMITED"
    # Unavailable
    OPTIONS_UNAVAILABLE = "OPTIONS_UNAVAILABLE"
    # Malformed
    OPTIONS_MALFORMED = "OPTIONS_MALFORMED"
    # Insufficient liquidity
    OPTIONS_INSUFFICIENT_LIQUIDITY = "OPTIONS_INSUFFICIENT_LIQUIDITY"
    # Invalid contract
    OPTIONS_INVALID_CONTRACT = "OPTIONS_INVALID_CONTRACT"
    # Index signal not confirmed
    INDEX_SIGNAL_NOT_CONFIRMED = "INDEX_SIGNAL_NOT_CONFIRMED"
    # Stale market data
    STALE_MARKET_DATA = "STALE_MARKET_DATA"
    # No completed candle
    NO_COMPLETED_CANDLE = "NO_COMPLETED_CANDLE"
    # Market index unavailable
    MARKET_INDEX_UNAVAILABLE = "MARKET_INDEX_UNAVAILABLE"
    # Invalid signal
    INVALID_SIGNAL = "INVALID_SIGNAL"

    @classmethod
    def canonical_states(cls) -> list[str]:
        """All canonical state names for the public API/frontend."""
        return [s.value for s in cls]

    @classmethod
    def is_tradeable(cls, state: str) -> bool:
        """Only QUALIFIED can produce a trade."""
        return state == cls.QUALIFIED.value

    @classmethod
    def is_data_gated(cls, state: str) -> bool:
        """States that indicate data unavailability."""
        return state in (
            cls.NO_DATA.value, cls.STALE.value,
            cls.OPTIONS_DATA_UNAVAILABLE.value,
            cls.OPTIONS_UNAVAILABLE.value,
            cls.OPTIONS_STALE.value,
            cls.OPTIONS_RATE_LIMITED.value,
            cls.OPTIONS_PARTIAL_CHAIN.value,
            cls.OPTIONS_MALFORMED.value,
            cls.OPTIONS_INSUFFICIENT_LIQUIDITY.value,
            cls.OPTIONS_INVALID_CONTRACT.value,
            cls.MARKET_INDEX_UNAVAILABLE.value,
            cls.INDEX_SIGNAL_NOT_CONFIRMED.value,
            cls.STALE_MARKET_DATA.value,
            cls.NO_COMPLETED_CANDLE.value,
            cls.RATE_LIMITED.value,
        )

    @classmethod
    def is_session_gated(cls, state: str) -> bool:
        """States that indicate the market is not open."""
        return state in (
            cls.PREMARKET.value, cls.MARKET_CLOSED.value,
            cls.WEEKEND.value, cls.HOLIDAY.value,
        )

    @classmethod
    def is_qualified(cls, state: str) -> bool:
        """Alias for is_tradeable."""
        return cls.is_tradeable(state)


# Backward compatibility mapping from internal names to canonical
INTERNAL_TO_CANONICAL = {
    "NO_DATA": DecisionState.NO_DATA.value,
    "PREMARKET": DecisionState.PREMARKET.value,
    "STALE": DecisionState.STALE.value,
    "MARKET_CLOSED": DecisionState.MARKET_CLOSED.value,
    "WEEKEND": DecisionState.WEEKEND.value,
    "NO_TRADE": DecisionState.NO_TRADE.value,
    "QUALIFIED": DecisionState.QUALIFIED.value,
}


def canonical_state(state: str) -> str:
    """Map any state name to its canonical form."""
    if state in INTERNAL_TO_CANONICAL:
        return INTERNAL_TO_CANONICAL[state]
    return state


def state_requires_reason(state: str) -> bool:
    """Every non-qualified state must have an explicit reason."""
    return not DecisionState.is_tradeable(state)


def validate_decision_output(output: dict) -> list[str]:
    """Validate that a decision output has all required fields.
    Returns list of validation errors (empty = valid)."""
    errors = []
    required = ["state", "timestamp", "instrument"]
    for field in required:
        if field not in output or output[field] is None:
            errors.append(f"MISSING_{field}")
    if output.get("state") and not DecisionState.is_tradeable(output.get("state", "")):
        if not output.get("reason"):
            errors.append("MISSING_REASON_FOR_NON_TRADE_STATE")
    return errors
