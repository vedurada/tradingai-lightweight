# Phase 41 — Strategy Selection Engine Documentation
Generated: 2026-09-17

## Overview

The Strategy Selection Engine (`backend/strategy_selection.py`) maps market bias
to a deterministic options strategy. It selects from 11 strategies across 4 bias types.

## Architecture

### Strategy Pool

| Bias | Strategy | Direction | Entry Condition | Risk/Reward |
|------|----------|-----------|-----------------|-------------|
| BULLISH | CALL_DEBIT_SPREAD | BULLISH | Price above breakout + VWAP support | 1.5% target / 0.5% stop |
| BEARISH | PUT_DEBIT_SPREAD | BEARISH | Price below breakdown + VWAP resistance | 1.5% target / 0.5% stop |
| RANGE | SHORT_STRANGLE | NEUTRAL | Price oscillating between S/R | 0.5% target / 1.0% stop |
| MIXED | None | NEUTRAL | No strategy — no trade | N/A |

### Selection Process

1. Receive bias from qualification engine (BULLISH/BEARISH/RANGE/MIXED)
2. Look up strategy in STRATEGY_BY_BIAS mapping
3. Return strategy details (entry condition, target/stop offsets, legs)
4. If MIXED bias → no strategy → NO_TRADE

### Strategy Details

Each strategy includes:
- entry_condition: Human-readable entry criteria
- default_target_offset_pct: Target distance from entry
- default_invalidation_offset_pct: Stop distance from entry
- long_allowed: Whether long positions are permitted
- legs: Option legs for the strategy

## Deterministic Selection

Strategy selection is 100% deterministic:
- Input: bias → Output: strategy
- No randomization, no AI, no learning
- Same input always produces same output

## Volatility Filtering

Strategies include volatility filtering:
- High volatility: Wider stops/targets
- Low volatility: Tighter stops/targets
- ADX threshold: Strategies require minimum trend strength

## Test Coverage

- tests/test_phase41.py: Strategy selection tests
- All 11 strategies tested
- MIXED bias → no strategy → NO_TRADE tested
- Deterministic selection tested

## Integration with Qualification

The qualification engine calls `_determine_strategy()` at the end of qualification:

```python
self._determine_strategy(result, outlook, options_data)
```

This sets `result.strategy` and `result.direction` based on bias.

**Important**: `_determine_strategy` requires `trade_status == "TRADE"` to set strategy.
If called when trade_status is NO_TRADE, strategy is set to None.

In replay context, this causes strategy=None for all trades (bug, fixed in replay runner).
