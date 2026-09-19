# TradingAI Backtest

## Running a Backtest
```bash
POST /api/backtest/run
{"instrument": "NIFTY", "date_start": "2026-09-01", "date_end": "2026-09-19"}
```

## Backtest Process
1. Load historical 5-minute candles for date range
2. For each candle (chronologically):
   - Calculate market state at that point in time
   - Match scenarios using only data available at that timestamp
   - Evaluate qualification conditions
   - Simulate trade if qualified
   - Record outcome at candle close
3. Calculate aggregated metrics
4. Validate no-look-ahead

## No-Look-Ahead Validation
Every decision records:
- `latest_allowed_data_timestamp`: The candle timestamp used
- `actual_latest_data_timestamp`: Must be ≤ decision timestamp

Validation endpoint: `GET /api/backtest/{run_id}/validation`

## Metrics
- Total trades, wins, losses, breakeven
- Win rate (shown as INSUFFICIENT SAMPLE if 0 trades)
- Average/median outcome
- Profit factor
- Maximum drawdown
- Average holding time
- Exit reasons breakdown

## Idempotency
Same inputs + same config = same output. Backtest uses deterministic logic only.

## Live DB Isolation
Backtest writes only to backtest_* tables. It never modifies:
- qualified_trades
- paper_trades
- daily_trade_locks
