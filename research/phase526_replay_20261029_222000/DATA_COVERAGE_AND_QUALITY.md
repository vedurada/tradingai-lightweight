# Phase 5.26 — Data Coverage and Quality

## Historical Market Data

| Instrument | Candles | Sessions | Date Range | Gaps |
|-----------|---------|----------|------------|------|
| NIFTY | 6,071 | 81 | 2026-07-06 to 2026-10-29 | 1 (Oct 15) |
| BANKNIFTY | 6,071 | 81 | 2026-07-06 to 2026-10-29 | 1 (Oct 15) |
| INDIA_VIX | 4,794 | 62 | 2026-07-29 to 2026-10-29 | 0 |

## Data Quality

- All candles: is_complete=1
- No duplicate candle_ids
- Timestamp convention: ISO 8601 with +05:30 (Asia/Kolkata)
- Candle interval: 5 minutes (09:15 to 15:25)
- Expected candles per session: 75
- 2 sessions with 73 candles (Sep 21, Oct 15)
- 1 gap: Oct 15 11:40 → 11:55 (missing 11:45, 11:50)

## Replay Data Source

- Source: market_candles_5m table (production DB, read-only)
- Timeframe: 5-minute
- Timezone: Asia/Kolkata (+05:30)
- Coverage: 3.5 months (Jul 6 - Oct 29, 2026)
- No external data retrieval needed
