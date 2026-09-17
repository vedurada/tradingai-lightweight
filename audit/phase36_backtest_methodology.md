# Backtest Methodology — Phase 36
Generated: 2026-09-17

## Classification: B — Rules-based reconstruction

The 30-day NIFTY 5-minute test is a **rules-based reconstruction**, NOT a
genuine AI prediction reconstruction.

### Rationale
1. **No historical AI predictions stored**: The `market_outlooks` table has
   only 202 records (insufficient for 30 days × 4 symbols)
2. **No `ai_outlooks` linkage**: The backtest does not use historical AI
   outlook predictions as signals — it uses deterministic EMA crossover rules
3. **Strategy**: EMA(9/21) crossover on 5-minute closes is a deterministic
   technical indicator, not an AI prediction
4. **No look-ahead**: All indicators calculated from data available at each
   timestamp only

### What This Test Actually Validates
- Whether the 5-minute price data is accurate and complete enough for
  deterministic strategy testing
- Whether the backtest infrastructure can process 5-minute candles correctly
- Whether basic risk metrics (P&L, drawdown, win rate) can be computed
  from historical data

### What This Test Does NOT Validate
- AI prediction accuracy (no AI predictions were tested)
- Strategy profitability (EMA crossover is not expected to be profitable)
- Real trading viability (12 trades is insufficient for statistical significance)

## Look-Ahead Bias Checks

| Check | Result | Evidence |
|-------|--------|----------|
| Chronological processing | PASS | Data loaded ASC by timestamp |
| No future candles | PASS | Only candles ≤ current timestamp used |
| No future indicators | PASS | EMA calculated from closes up to current point |
| No future daily values | PASS | No 1d data used in 5m backtest |
| No future options info | PASS | No options data used |
| No future AI output | PASS | No AI predictions used as signals |
| Signal precedes entry | PASS | Signal at candle close, entry at same close |
| Exit follows entry | PASS | All exit timestamps > entry timestamps |
| No overlapping positions | PASS | One trade at a time |
| Trades after signal | PASS | Entry within signal candle |

## Data Source Verification
- Source table: price_5m (17,400 records, 2026-06-24 to 2026-09-15)
- Timezone: UTC (timestamps map to IST market hours)
- No data gaps in test period except Sep 14-15 (market closure)
- All prices positive and reasonable (23,000-25,000 range for NIFTY)
