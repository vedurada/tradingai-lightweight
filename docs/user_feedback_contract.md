"""User Feedback Data Contract.

TradingAI allows traders to provide feedback on AI outputs.

Phase 1: Defines the schema and API contract only.
Phase 2+: Will build the full feedback UI.
"""

# Feedback types
FEEDBACK_HELPFUL = "helpful"
FEEDBACK_NOT_HELPFUL = "not_helpful"

REASON_CODES = [
    "market_view_accurate",
    "levels_useful",
    "strategy_useful",
    "explanation_clear",
    "too_late",
    "too_many_signals",
    "view_wrong",
    "strategy_unsuitable",
    "data_incorrect",
    "other",
]

TRADE_DECISIONS = ["traded", "paper_traded", "skipped"]

# Rating scale: 1-5
RATING_MIN = 1
RATING_MAX = 5

# Database schema (for future implementation)
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS user_feedback (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    ai_output_id TEXT,
    session_id TEXT,
    helpfulness TEXT CHECK(helpfulness IN ('helpful', 'not_helpful')),
    rating INTEGER CHECK(rating BETWEEN 1 AND 5),
    reasons TEXT,
    used_setup TEXT CHECK(used_setup IN ('traded', 'paper_traded', 'skipped')),
    created_at TEXT NOT NULL,
    category TEXT,
    source TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_feedback_user ON user_feedback(user_id);
CREATE INDEX IF NOT EXISTS idx_feedback_output ON user_feedback(ai_output_id);
CREATE INDEX IF NOT EXISTS idx_feedback_created ON user_feedback(created_at);
"""

# API endpoints (for future implementation)
API_CONTRACT = {
    "submit_feedback": {
        "method": "POST",
        "path": "/api/feedback",
        "description": "Submit feedback on an AI output",
        "auth": True,
        "required": ["ai_output_id", "helpfulness"],
        "optional": ["rating", "reasons", "used_setup", "category"],
    },
    "get_feedback": {
        "method": "GET",
        "path": "/api/feedback?symbol=NIFTY&date=2026-09-15",
        "description": "List feedback (admin)",
        "auth": True,
    },
    "get_stats": {
        "method": "GET",
        "path": "/api/feedback/stats?symbol=NIFTY",
        "description": "Aggregate feedback stats for product learning",
        "auth": True,
    },
}

# Product learning integration
PRODUCT_LEARNING = """
User feedback feeds into product-level learning:
- "Helpful" count per AI output type
- "Not helpful" reasons aggregation
- Rating distribution per feature
- Used setup vs skipped rates

This is distinct from user-specific personal learning (trade journal analysis).
"""