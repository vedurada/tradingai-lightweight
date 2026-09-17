# Phase 41 — Trade Qualification Engine Documentation
Generated: 2026-09-17

## Overview

The Trade Qualification Engine (`backend/trade_qualification_engine.py`) is a 6-layer
deterministic qualification system that evaluates whether a market setup is eligible
for a paper trade. It produces three outcomes: TRADE, WAIT, NO_TRADE.

## Architecture

### Input

| Input | Source | Description |
|-------|--------|-------------|
| instrument | Caller | e.g., "NIFTY", "BANKNIFTY" |
| snapshot | market_snapshot.py | OHLCV, VWAP, indicators |
| evidence | market_evidence_engine.py | BULLISH/BEARISH/MIXED/RANGE |
| market_state | market_state_engine.py | Regime, trend, volatility |
| outlook | /api/ai-outlook/5m | AI bias, trade_state, confidence |
| options_data | options chain | Optional, for options strategies |
| active_trade | DB query | Current open paper trades |

### 6-Layer Check Pipeline

#### Layer 1: AI Outlook Validation (`_check_ai_outlook`)

Checks:
- `ai_outlook_present`: AI outlook dict provided (False if None)
- `ai_bias_valid`: bias in [BULLISH, BEARISH, RANGE, MIXED]
- `ai_trade_state_valid`: trade_state in [TRADE, WAIT, NO_TRADE, HOLD]
- `ai_trade_state_requires_trade`: trade_state must be TRADE for qualification
- `ai_confidence_reviewed`: Confidence logged but NOT used for qualification

#### Layer 2: Market Evidence (`_check_market_evidence`)

Checks:
- `evidence_available`: Evidence dict provided
- `evidence_directional`: Evidence overall_signal in [BULLISH, BEARISH]
- `evidence_no_severe_conflict`: No severe conflicting signals
- `evidence_sufficient_groups`: Sufficient evidence groups evaluated

#### Layer 3: Confirmation & Invalidation (`_check_confirmation`, `_check_invalidation`)

Checks:
- `bullish_confirmation`: Price above VWAP (BULLISH) or below (BEARISH)
- `bearish_confirmation`: Price below VWAP (BEARISH) or above (BULLISH)
- `range_confirmation`: Price in range (RANGE)
- `confirmation_not_required`: MIXED bias doesn't require confirmation
- `invalidation_defined`: Invalidation conditions provided by AI outlook
- `daily_risk_available`: Daily risk limit not exceeded

#### Layer 4: Risk (`_check_risk`)

Checks:
- `risk_calculable`: Stop and target are valid numbers (NOT None)
- `risk_reward_acceptable`: risk_reward >= 1.0
- `risk_within_limits`: risk_points <= max_risk_points
- `invalidation_defined`: Stop and target defined by strategy

#### Layer 5: Options Data (`_check_options_data`)

Checks:
- `options_data_available`: For BULLISH/BEARISH, options chain data needed
- `options_not_required`: For RANGE/MIXED, options not required
- In replay: Options data is N/A (historical data unavailable)

#### Layer 6: Data Quality & Protections (`_check_data_availability`, `_check_daily_risk`, `_check_active_trade`)

Checks:
- `core_data_available`: close, vwap, rsi available
- `no_active_trade_exists`: No OPEN paper trade
- `daily_risk_available`: Daily risk limit not exceeded

## Decision Logic

```
All checks PASS → TRADE
Some checks FAIL → WAIT (missing confirmation) or NO_TRADE (rejection)
No AI outlook → NO_TRADE (ai_outlook_present = False)
```

## Key Design Decisions

1. **AI is input, not calculation**: AI outlook is validated but never computed
2. **Never forces trade**: Trade_status is TRADE only if sufficient checks pass
3. **WAIT vs NO_TRADE**: WAIT = conditions forming, NO_TRADE = not warranted
4. **Options separation**: BULLISH/BEARISH require options; RANGE/MIXED don't
5. **Risk first**: Risk checks before strategy selection

## Test Coverage

- tests/test_phase41.py: 36 tests (all passing)
- Tests cover: lifecycle transitions, qualification checks, look-ahead protection, PnL, duplicate prevention, active trade prevention

## Known Issues in Replay Context

1. `risk_calculable` PASS was missing (fixed 2026-09-17, commit 144b7d4)
2. `_determine_strategy` requires trade_status=TRADE but called before replay_qualify modifies it → strategy=None in replay
3. Options data checks always FAIL in replay (historical data unavailable) but replay_qualify overrides this
4. AI confidence is logged but never used for qualification (by design)
