# TradingAI Scenarios

## Scenario Types

### BULLISH_CONTINUATION
Direction: BULLISH | Objective: DIRECTIONAL
- Strong prior bullish session
- Positive opening behavior
- Price above key levels
- VWAP support
- Positive momentum

### BEARISH_CONTINUATION
Direction: BEARISH | Objective: DIRECTIONAL
- Strong prior bearish session
- Negative opening behavior
- Price below key levels
- VWAP resistance
- Negative momentum

### RANGE_PREMIUM_DECAY
Direction: NEUTRAL | Objective: THETA_DECAY
- Price inside established range
- Rejection at extremes
- Weak directional momentum
- Stable/reduced volatility

### BREAKOUT
Direction: BULLISH | Objective: HYBRID
- Initial breakout above range
- Volume confirmation
- Volatility expansion

### BREAKOUT_FAILURE_REVERSAL
Direction: BEARISH | Objective: HYBRID
- Breakout attempt fails
- Re-entry into range
- VWAP rejection
- Level failure

## Match States
- `WATCH` — Scenario active but not yet confirmed
- `PARTIALLY_MATCHED` — Some conditions met
- `CONFIRMED` — All required conditions satisfied
- `INVALIDATED` — Conditions no longer met
- `EXPIRED` — Scenario time window elapsed
