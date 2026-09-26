# Backtest Methodology

## Entry Methodology

Entry occurs at the **completed candle close** where qualification conditions are met.
Entry price = market_state.price * 0.995.

The entry is based solely on data available at the decision timestamp. No future data is used.

## Stop Methodology

Stop price = entry * 0.99 (1% below entry for LONG, 1% above for SHORT).
Stop is frozen at entry and never modified retrospectively.

For LONG trades: stop triggers when candle LOW <= stop price.
For SHORT trades: stop triggers when candle HIGH >= stop price.

## Target Methodology

Target price = entry * 1.02 (2% above entry for LONG, 2% below for SHORT).
Target is frozen at entry and never modified retrospectively.

For LONG trades: target triggers when candle HIGH >= target price.
For SHORT trades: target triggers when candle LOW <= target price.

## Exit Precedence

1. **STOP** - Price reaches stop level (conservative: same-candle stop+target = STOP)
2. **TARGET** - Price reaches target level (only if stop not triggered first)
3. **SCENARIO_INVALIDATION** - Scenario no longer valid (checked at candle close)
4. **EOD** - End of trading session (final fallback)
5. **TIME_EXIT** - NOT CURRENTLY DEFINED (EOD is final fallback)

## Same-Candle Ambiguity

When both stop and target are touched within the same 5-minute candle:
- Classification: **AMBIGUOUS_INTRABAR**
- Resolution: Conservative against the trade direction
- For LONG trades: resolves as **STOP** (worse outcome)
- For SHORT trades: resolves as **STOP** (worse outcome)

No favorable assumption is made when the exact intrabar sequence is unknown from OHLC data.

## End-of-Day Rule

All trades must close by end of trading session (15:25 IST for NIFTY/BANKNIFTY).
The last completed 5-minute candle close is used as the EOD exit price.

Trades do not carry overnight into the next trading day.

## MFE (Maximum Favorable Excursion)

MFE = highest price reached after entry (for LONG) or lowest price (for SHORT),
using only candles available after the entry candle.

Calculation:
- Start with entry price
- For each subsequent completed candle, update MFE if the high (LONG) or low (SHORT) is more favorable
- Only uses candles after the entry candle, not the entry candle's own range

## MAE (Maximum Adverse Excursion)

MAE = lowest price reached after entry (for LONG) or highest price (for SHORT),
using only candles available after the entry candle.

Calculation:
- Start with entry price
- For each subsequent completed candle, update MAE if the low (LONG) or high (SHORT) is more adverse
- Only uses candles after the entry candle, not the entry candle's own range

## R Multiple Calculation

R = realized PnL / initial risk

Initial risk = |entry - stop| (frozen at entry)
Realized PnL = (exit - entry) * lot_size (50 for indices)

R is calculated using the initial risk, never recalculated after trade starts.

## P&L Calculation

GROSS PnL = (exit_price - entry_price) * lot_size (for LONG, positive if exit > entry)

NET PnL = NOT AVAILABLE (transaction costs not modeled)

Slippage = not modeled

## Transaction Cost Limitation

Transaction costs (brokerage, exchange fees, slippage) are NOT modeled in this research engine.
NET PnL should be considered an upper bound on actual achievable results.

## Data Source

Market data: yfinance 5-minute OHLCV candles
Timezone: Asia/Kolkata
Instrument lot size: 50 (for index calculations)

## Data Quality

All candles must pass:
- Timestamp validation (timezone-aware, Asia/Kolkata)
- OHLC validation (high >= low, open/close within range)
- Duplicate timestamp validation
- Session continuity validation
