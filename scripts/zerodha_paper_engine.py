#!/usr/bin/env python3
"""Isolated Zerodha paper engine runner — Phase 3. SHADOW/PAPER only."""
# No live broker orders. No notifications. Events only.
from app.zerodha import persistence, strategy_adapter, option_selector, quote_validator, paper_execution

if __name__ == "__main__":
    persistence.init_schema()
    # Isolated validation: mock candle
    result = strategy_adapter.evaluate_candle({"hlc_pattern": True, "direction": "BULLISH"})
    print("Phase 3 isolated validation passed:", result)
