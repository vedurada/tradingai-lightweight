# Phase 5.12 — Data Coverage and Quality

## Historical Data Available

| Instrument | Candles | Sessions | Date Range | Gaps |
|-----------|---------|----------|------------|------|
| NIFTY | 6,071 | 81 | 2026-07-06 to 2026-10-29 | 1 |
| BANKNIFTY | 6,071 | 81 | 2026-07-06 to 2026-10-29 | 1 |
| INDIA_VIX | 4,794 | 62 | 2026-07-29 to 2026-10-29 | 0 |

## Data Quality

- All candles: is_complete=1
- No duplicate candle_ids
- Timestamp convention: ISO 8601 with +05:30 offset (Asia/Kolkata)
- Candle interval: 5 minutes (09:15 to 15:25)
- Expected candles per session: 75
- 2 sessions with 73 candles (missing 2 each): 2026-09-21, 2026-10-15
- 1 gap: 2026-10-15 11:40 → 11:55 (missing 11:45, 11:50)

## Limitations

1. Only 3.5 months of data (not 12+ months as preferred)
2. No data before 2026-07-06
3. INDIA_VIX data starts 2026-07-29 (23 days later than NIFTY/BANKNIFTY)
4. One session with missing candles (Oct 15)
5. No volume data analysis performed
6. No market regime classification available
