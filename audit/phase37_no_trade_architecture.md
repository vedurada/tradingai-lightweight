# No-Trade Architecture Review — Phase 37
Generated: 2026-09-17

## Conclusion: Architecture already supports separation

The current system already produces market outlook direction and trade decision independently. No architectural change required in Phase 37.

## Current State

### Market Outlook Direction (BULLISH/BEARISH/RANGE/MIXED)
Source: `build_outlook()` in backend/outlook.py (frozen model)
Stored: `market_outlooks` table (payload JSON)
API: `/api/market-outlook`, `/api/market-outlook/<date>`, `/api/market-outlooks`

Fields:
- `bias.label`: BULLISH / BEARISH / NEUTRAL / RANGE
- `decision.verdict`: GO / WAIT / NO_TRADE
- `decision.primary_view`: Narrative (BULLISH/BEARISH/RANGE/MIXED equivalent)
- `confidence`: 0-100
- `regime`: Market regime (TRENDING_BULLISH, TRENDING_BEARISH, BULLISH_RANGE, BEARISH_RANGE, RANGE_BOUND)

### Trade Decision (TRADE/WAIT/NO_TRADE)
Source: `detect_trade_setup()` in backend/trade_lifecycle.py
Stored: Per-session (live) or TradeSetup namedtuple (historical)
API: `/api/trade-setup/<symbol>`

Fields:
- `trade_readiness`: GO / WAIT / NO_SETUP
- `stages`: 6 lifecycle stages
- `entry`, `stop`, `target`: Trade levels
- `strategy`: Strategy name

## How Separation Works

The outlook direction (BULLISH/BEARISH/RANGE/MIXED) answers: "What is the market doing?"
The trade decision (TRADE/WAIT/NO_TRADE) answers: "Should I enter a position?"

These are INDEPENDENT decisions:

1. **BULLISH market + NO_TRADE**: Market is bullish but options data doesn't support a trade
2. **BEARISH market + TRADE**: Market is bearish and options signal confirms short entry
3. **RANGE market + WAIT**: Market is ranging, waiting for breakout confirmation
4. **MIXED market + NO_SETUP**: Conflicting signals, no trade warranted

## Concrete Examples from Live Data

From the live `/api/market-outlook` (2026-09-17):
```json
{
  "bias": { "label": "NEUTRAL" },
  "decision": {
    "verdict": "WAIT",
    "primary_view": "Regime is bearish but short-term oversold..."
  },
  "confidence": 64
}
```

If `/api/trade-setup/NIFTY` returns:
```json
{
  "trade_readiness": "WAIT",
  "stages": { "DETECTED": "active", "TRIGGER": "pending" }
}
```

Both agree: market is uncertain, wait for confirmation.

## Minimum Change Required (Future Enhancement Only)

If explicit "market direction" and "trade decision" need to be MORE clearly separated in API responses, the minimum change would be:

1. Add `market_direction` field to trade-setup response:
```json
{
  "market_direction": "BEARISH",
  "trade_decision": "WAIT",
  "trade_readiness": "WAIT"
}
```

This is a cosmetic change, not an architectural one. The data already exists; it just needs to be surfaced together.

## Immutability Preserved
- Market outlook records: immutable (UNIQUE constraint on date+symbol)
- Trade setup records: fresh calculation per request for live data
- No circular dependencies between outlook and trade setup storage
- Neither system modifies the other's data
