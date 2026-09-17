# Outlook vs Strategy Separation — Phase 37
Generated: 2026-09-17

## Conclusion: Architecture already supports separation

The system already produces AI Market Outlook and Options Trade Strategy as logically separate outputs. No redesign required.

## Current Architecture

### AI Market Outlook (Market Direction)
**Endpoint**: `/api/market-outlook` (latest), `/api/market-outlook/<date>` (historical), `/api/market-outlooks` (range)

**Output fields**:
- `bias.label`: BULLISH / BEARISH / NEUTRAL / RANGE
- `decision.verdict`: GO / WAIT / NO_TRADE (whether to trade at all)
- `decision.primary_view`: Narrative market view (BULLISH/BEARISH/RANGE/MIXED equivalent)
- `confidence`: 0-100 scale
- `regime`: Market regime classification
- `expiry`: Options expiry date
- `expected_range`: Support/resistance range
- `ai_source`: RULE_REPLAY or LLM

**Purpose**: Answers "What is the market doing?" — directional view without committing to a trade.

### Options Trade Strategy (Entry/Exit Decision)
**Endpoint**: `/api/trade-setup/<symbol>`

**Output fields**:
- `trade_readiness`: GO / WAIT / NO_SETUP
- `stages`: 6 lifecycle stages (DETECTED → TRIGGER → CONFIRMATION → ENTRY_WINDOW → ACTIVE → COMPLETE)
- `entry`: Entry trigger level
- `stop`: Invalidation level
- `target`: Target level
- `strategy`: Strategy name (SUPPORT_RESISTANCE, VWAP_CROSSOVER, OPENING_RANGE, MOMENTUM, OPEN_INTEREST)
- `confidence`: Trade confidence
- `data_quality`: Data quality flag

**Purpose**: Answers "Should I enter a specific options position?" — actionable trade setup.

## Separation Verification

| Market Outlook | Trade Strategy |
|---|---|
| BULLISH + verdict: GO | Bullish regime → GO entry window active |
| BULLISH + verdict: WAIT | Bullish regime but WAIT conditions forming |
| BULLISH + verdict: NO_TRADE | Bullish regime but NO_SETUP (no options signal) |
| BEARISH + verdict: GO | Bearish regime → GO short entry available |
| RANGE + verdict: NO_TRADE | Range regime often → NO_SETUP |
| MIXED + verdict: WAIT | Mixed signals → WAIT for confirmation |

## Example Scenarios

### Scenario 1: Outlook bullish, no trade warranted
```
Market Outlook: { bias: BULLISH, verdict: NO_TRADE, confidence: 40 }
Trade Setup:   { trade_readiness: NO_SETUP, reason: "insufficient options signal" }
```
The market is bullish but options data doesn't support a trade. Correct behavior.

### Scenario 2: Outlook bearish, trade available
```
Market Outlook: { bias: BEARISH, verdict: GO, confidence: 75 }
Trade Setup:   { trade_readiness: GO, entry: 23200, stop: 23350, target: 22800, strategy: OPENING_RANGE }
```
Bearish outlook confirmed by options signal. Trade setup provided.

### Scenario 3: Outlook neutral, wait for confirmation
```
Market Outlook: { bias: NEUTRAL, verdict: WAIT, confidence: 64 }
Trade Setup:   { trade_readiness: WAIT, stages: { DETECTED: active, TRIGGER: pending } }
```
Market direction unclear. Wait for more data before entering.

## Key Design Principle
Market outlook (direction) and trade setup (action) are independent decisions.
The outlook influences but does NOT determine the trade setup. Options data,
expiry timing, and IV conditions independently affect trade readiness.

## Immutability
- Market outlook records in `market_outlooks` table: UNIQUE(date, symbol) — immutable historical record
- Trade setup records: stored per-session, recalculated on each request for live data
- Neither AI outlook nor trade setup modifies the other's stored data
