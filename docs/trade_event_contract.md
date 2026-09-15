"""Trade Event / Entry Logging Data Contract.

Every TradingAI setup should have an immutable timeline:
  SETUP DETECTED → TRIGGER → CONFIRMATION → ENTRY WINDOW → ACTIVE → INVALIDATED/TARGET/EXIT

Then compare with the user's actual entry time.

This data powers:
- Feedback loop
- Trade review
- Historical setup analysis
- Personal learning (Phase 3+)

Phase 1: Defines the schema and API contract only.
Phase 2+: Will build the full trading UI.
"""

# Trade event types in the lifecycle
EVENT_SETUP_DETECTED = "setup_detected"
EVENT_TRIGGER = "trigger"
EVENT_CONFIRMATION = "confirmation"
EVENT_ENTRY_WINDOW = "entry_window"
EVENT_ACTIVE = "active"
EVENT_INVALIDATED = "invalidated"
EVENT_TARGET = "target"
EVENT_EXIT = "exit"
EVENT_NO_TRADE = "no_trade"

# All valid event types
ALL_EVENT_TYPES = [
    EVENT_SETUP_DETECTED,
    EVENT_TRIGGER,
    EVENT_CONFIRMATION,
    EVENT_ENTRY_WINDOW,
    EVENT_ACTIVE,
    EVENT_INVALIDATED,
    EVENT_TARGET,
    EVENT_EXIT,
    EVENT_NO_TRADE,
]

# Required fields for every trade event
REQUIRED_FIELDS = [
    "event_id",       # UUID, unique
    "event_type",     # One of ALL_EVENT_TYPES
    "symbol",         # NIFTY, BANKNIFTY, FINNIFTY, SENSEX, or stock symbol
    "strategy",       # Strategy name (e.g., "Bull Call Spread")
    "direction",      # LONG, SHORT, SPREAD
    "timestamp",      # ISO 8601 UTC (consistent timezone convention)
    "regime",         # TRENDING, RANGE, HIGH_VIX, LOW_VIX
    "confidence",     # 0-100
    "evidence_score", # 0-100
    "trigger_condition",       # What triggered this event
    "confirmation_conditions", # What confirms (for confirmation event)
    "invalidation",            # What would invalidate
    "target",                  # Price target
    "risk",                    # Risk amount or level
    "market_summary",          # Market context at event time
]

# Optional fields for trade events
OPTIONAL_FIELDS = [
    "actual_entry_time",
    "actual_exit_time",
    "actual_entry_price",
    "actual_exit_price",
    "quantity",
    "outcome",         # WIN, LOSS, BREAKEVEN, ACTIVE
    "mistake",         # Repeated mistake tag
    "trader_note",
    "setup_used",      # Was TradingAI setup used?
    "trigger_time",
    "confirmation_time",
]

# AI setup data (what TradingAI proposed)
AI_SETUP_FIELDS = [
    "setup_detection_time",
    "trigger_time",
    "confirmation_time",
    "entry_window_start",
    "entry_window_end",
    "strategy",
    "direction",
    "trigger_condition",
    "confirmation_conditions",
    "invalidation",
    "target",
    "risk",
    "regime",
    "evidence_score",
    "confidence",
    "current_price_at_setup",
]

# Database schema (for future implementation)
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS trade_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    symbol TEXT NOT NULL,
    strategy TEXT,
    direction TEXT,
    timestamp TEXT NOT NULL,
    regime TEXT,
    confidence INTEGER,
    evidence_score INTEGER,
    trigger_condition TEXT,
    confirmation_conditions TEXT,
    invalidation TEXT,
    target TEXT,
    risk TEXT,
    market_summary TEXT,
    actual_entry_time TEXT,
    actual_exit_time TEXT,
    actual_entry_price REAL,
    actual_exit_price REAL,
    quantity INTEGER,
    outcome TEXT,
    mistake TEXT,
    trader_note TEXT,
    created_at TEXT NOT NULL,
    immutable INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_trade_events_symbol ON trade_events(symbol);
CREATE INDEX IF NOT EXISTS idx_trade_events_timestamp ON trade_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_trade_events_type ON trade_events(event_type);
"""

# API endpoints (for future implementation)
API_CONTRACT = {
    "create_event": {
        "method": "POST",
        "path": "/api/trade-events",
        "description": "Create a new trade event",
        "auth": True,
        "required": ["event_id", "event_type", "symbol", "timestamp"],
    },
    "get_events": {
        "method": "GET",
        "path": "/api/trade-events?symbol=NIFTY&type=trigger",
        "description": "List trade events with filters",
        "auth": True,
    },
    "get_event": {
        "method": "GET",
        "path": "/api/trade-events/{event_id}",
        "description": "Get a specific trade event",
        "auth": True,
    },
    "get_timeline": {
        "method": "GET",
        "path": "/api/trade-events/{symbol}/timeline",
        "description": "Get full immutable timeline for a symbol/setup",
        "auth": True,
    },
}

# Timestamp convention: All timestamps must be ISO 8601 in UTC
# Example: "2026-09-15T09:45:00Z"
# All historical events must be auditable (immutable, never deleted)