# Production DB Integrity Report

## Date: 2026-09-19 (Saturday, market CLOSED)

## Integrity Check
```text
PRAGMA integrity_check: OK
```

## Database Stats
```text
Path: /opt/tradingai/database/tradingai.db
Size: 269MB (282038272 bytes)
WAL mode: enabled
Busy timeout: 10000ms
```

## Key Table Counts
| Table | Count | Status |
|-------|-------|--------|
| paper_trades | 1188 | ✅ |
| ai_outlooks | 39148 | ✅ |
| ai_outlooks_5m | 0 | Expected (pre-Monday) |
| market_snapshots_5m | 2 | Expected (pre-Monday) |
| market_evidence_5m | 1 | Expected (pre-Monday) |
| pre_market_scenarios | 0 | Expected (pre-Monday) |
| scenario_events | 0 | Expected (pre-Monday) |
| scenario_outcomes | 0 | Expected (pre-Monday) |
| research_ai_call_log | 0 | Expected (pre-Monday) |
| research_manifest | 1 | ✅ |
| research_outcome_tracking | 61672 | ✅ |
| research_data_health | 219 | ✅ |
| market_candles | 54274 | ✅ |
| market_outlooks | 206 | ✅ (June 18 - Sep 18) |

## Backup
```text
Path: /opt/tradingai/backups/tradingai_pre_42a10c_20260919_110833.db
Size: 269MB
Integrity: OK
```

## WAL Status
```text
WAL file: 4MB (active)
SHM file: 32KB
```

## Pre-Market Data Verification
```text
NIFTY price: 23346.40 (STALE, yfinance, 2026-09-18)
BANKNIFTY price: 56358.70 (STALE, 2026-09-18)
VIX: 11.39 (STALE, 2026-09-18 16:40 UTC)
All three match expected baseline ✅
```

## Monday Insertion Points
- market_snapshots_5m: new rows every completed 5m candle
- market_evidence_5m: one row per eligible snapshot
- pre_market_scenarios: populated before 09:15 IST
- research_ai_call_log: populated by AI scheduler
- paper_trades: populated by qualification engine
