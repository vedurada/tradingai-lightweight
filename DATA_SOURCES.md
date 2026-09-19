# TradingAI Data Sources

## Market Data Provider: yfinance

### Configuration
- **Provider**: yfinance
- **Symbols**: NIFTY → `^NSEI`, BANKNIFTY → `^NSEBANK`, INDIA_VIX → `^INDIAVIX`
- **Refresh**: Every 5 minutes during market hours
- **Timeout**: 10 seconds
- **Retry**: 3 attempts

### Data Types
- 5-minute OHLCV candles
- Latest quote (price, change, change%)
- Market snapshots (indicators, levels)

### Data States
- `LIVE` — Fresh data within staleness threshold
- `STALE` — Data older than threshold but valid
- `UNAVAILABLE` — Provider returned no data
- `API_ERROR` — Provider request failed

### Known Limitations
- yfinance Indian index data may have 15-60 minute delays
- Historical data coverage depends on yfinance availability
- Option chain data NOT available from yfinance

## Options Data

**Status**: Currently UNAVAILABLE.

When options data is required for trade qualification, the system returns NO_TRADE.

A future options data provider (e.g., NSE API, validated public source) needs to be configured before options-dependent strategies can be qualified.

## Data Validation Pipeline

```
FETCH → VALIDATE → NORMALIZE → STORE → QUALITY CHECK → ENGINE
```

Validation checks:
- Timestamp integrity
- OHLC consistency (high >= low, close within range)
- Duplicate detection
- Missing candle detection
- Impossible price detection
- Staleness check
- Market session boundary check
