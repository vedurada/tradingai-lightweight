# Scenario Definitions

This document defines all scenario types used in the TradingAI.in historical scenario engine.

## Bullish Continuation
- **ID**: BULLISH_CONTINUATION
- **Description**: Pattern where price consolidates during a bullish trend and then continues upward
- **Detection**: Opening range expansion in direction of trend, VWAP above prev close, positive momentum, low-to-medium volatility
- **Confirmation**: Price breaks and closes above opening range high
- **Invalidation**: Price breaks below opening range low
- **Trade Direction**: LONG
- **Typical Duration**: 1-5 candles
- **Expected Outcome**: Move toward session high or next resistance level

## Bearish Continuation
- **ID**: BEARISH_CONTINUATION
- **Description**: Pattern where price consolidates during a bearish trend and then continues downward
- **Detection**: Opening range expansion in direction of trend, VWAP below prev close, negative momentum, low-to-medium volatility
- **Confirmation**: Price breaks and closes below opening range low
- **Invalidation**: Price breaks above opening range high
- **Trade Direction**: SHORT
- **Typical Duration**: 1-5 candles
- **Expected Outcome**: Move toward session low or next support level

## Range Premium Decay
- **ID**: RANGE_PREMIUM_DECAY
- **Description**: Pattern where price trades in a tight range at premium/discount to fair value with decaying momentum
- **Detection**: Low range expansion, VWAP near session midpoint, neutral momentum, decreasing volatility
- **Confirmation**: Price closes outside range after momentum confirmation
- **Invalidation**: Range expands without directional commitment
- **Trade Direction**: DEPENDS on breakout direction
- **Typical Duration**: 3-10 candles
- **Expected Outcome**: Breakout from range with measured move

## Breakout
- **ID**: BREAKOUT
- **Description**: Decisive price movement through a key level (opening range high/low, session high/low, or volume profile point)
- **Detection**: Volume spike with price closing beyond reference level, high momentum, low-to-medium volatility
- **Confirmation**: Close beyond reference level with follow-through
- **Invalidation**: Immediate reversal back within range (failed breakout)
- **Trade Direction**: LONG if above resistance, SHORT if below support
- **Typical Duration**: 1-3 candles
- **Expected Outcome**: Measured move of range width

## Breakout Failure Reversal
- **ID**: BREAKOUT_FAILURE_REVERSAL
- **Description**: Pattern where a breakout attempt fails and price reverses strongly
- **Detection**: Initial breakout signal followed by rejection, increasing volume against breakout direction, momentum shift
- **Confirmation**: Price closes back within range after failed breakout, momentum confirms reversal
- **Invalidation**: Price recaptures breakout level
- **Trade Direction**: OPPOSITE of failed breakout direction
- **Typical Duration**: 2-5 candles
- **Expected Outcome**: Return to range or move to opposite extreme

## Scenario Priority Matrix

When multiple scenarios are active simultaneously, priority determines which is used for qualification:

1. BREAKOUT (highest priority) - Most actionable, highest expected value
2. BREAKOUT_FAILURE_REVERSAL - Strong reversal signal
3. BULLISH_CONTINUATION / BEARISH_CONTINUATION - Trend continuation
4. RANGE_PREMIUM_DECAY (lowest priority) - Lowest conviction

## Validation Criteria

All scenarios must meet minimum data quality standards:
- Minimum 5 candles of historical context
- Price data must be non-zero and non-negative
- VWAP must be calculable from available candles
- Momentum indicator must have valid range [-1, 1]
- Volatility classification must be one of: LOW, NORMAL, HIGH
- No future data may be used in detection (strict lookahead protection)
