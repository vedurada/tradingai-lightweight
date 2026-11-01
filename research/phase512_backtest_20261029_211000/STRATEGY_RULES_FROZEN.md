# Phase 5.12 — Strategy Rules (Frozen)

## HLC 3-Bar Scalp Strategy

### Signal Detection
- 3 consecutive 5-minute candles where high, low, and close all move in the same direction
- BULL: each candle's high > prev high AND low > prev low AND close > prev close
- BEAR: each candle's high < prev high AND low < prev low AND close < prev close
- Signal fires on the 3rd confirming candle

### Entry
- Entry candle: next candle after signal (candles[i+1])
- Entry price: entry candle's open
- Entry time: entry candle's timestamp

### Stop Loss
- BULL: signal candle's low − 1.0
- BEAR: signal candle's high + 1.0

### Target
- Risk = |entry − stop|
- BULL: entry + 1.5 × risk
- BEAR: entry − 1.5 × risk
- Risk ≤ 0 → trade rejected

### Exit
- Scan forward from entry candle
- If stop and target both hit in same candle → STOP (conservative)
- If stop hit → STOP
- If target hit → TARGET
- If neither hit by session end → EOD (last close)
- Session boundary: stop scanning when candle date changes

### Position Management
- Mode C: one open position per instrument at a time
- New signal blocked if position still open

### Re-entry
- After position closes, next qualifying signal creates new trade

### No Lookahead
- Signal uses only completed candles
- Entry at next candle's open (not same candle)
- Exit determined by forward scan (first hit)
