# Database Verification

## Verification Date
2026-10-30

## Host
webserver / Linux / x86_64 / ubuntu / /opt/tradingai

## SQLite Integrity
```
PRAGMA integrity_check;  -> ok
```

## Tables and Row Counts (production DB)
| Table | Row Count |
|---|---|
| market_candles_5m | 17,074 |
| paper_trades | 94 |
| scalp_signals | 36 |
| paper_trade_events | 33 |
| trade_journal | 246 |
| daily_trade_locks | 21 |
| qualified_trades | 20 |
| market_snapshots | 0 |

## SCALP_HLC Paper Trades (by status)
| Scenario | Status | Count |
|---|---|---|
| SCALP_HLC | CLOSED | 30 |

## SCALP_HLC Paper Trades (recent)
| Trade ID | Instrument | Direction | Entry | Stop | Target | Entry Time | Status |
|---|---|---|---|---|---|---|---|
| PT-0E1BB5B645 | NIFTY | BULL | 22704.6 | 22695.2 | 22718.7 | 2026-10-28T14:50:00+05:30 | CLOSED |
| PT-A4D82F95DF | NIFTY | BEAR | 22706.5 | 22724.8 | 22679.05 | 2026-10-28T14:00:00+05:30 | CLOSED |
| PT-86E7B96E9D | NIFTY | BULL | 22718.8 | 22697.8 | 22750.3 | 2026-10-28T12:55:00+05:30 | CLOSED |
| PT-7F4FF31032 | NIFTY | BULL | 22705.75 | 22695.25 | 22721.5 | 2026-10-28T12:50:00+05:30 | CLOSED |
| PT-F10674AE4A | NIFTY | BULL | 22696.25 | 22669.3 | 22736.67 | 2026-10-28T12:45:00+05:30 | CLOSED |
| PT-58E0E20BA3 | NIFTY | BULL | 22642.3 | 22622.4 | 22672.15 | 2026-10-28T12:05:00+05:30 | CLOSED |
| PT-DF37AC2412 | NIFTY | BULL | 22634.3 | 22615.15 | 22663.03 | 2026-10-28T12:00:00+05:30 | CLOSED |
| PT-8D5F520972 | BANKNIFTY | BULL | 54004.3 | 53921.85 | 54127.97 | 2026-10-28T11:05:00+05:30 | CLOSED |
| PT-F76F16D58C | BANKNIFTY | BULL | 53935.05 | 53875.7 | 54024.08 | 2026-10-28T11:00:00+05:30 | CLOSED |
| PT-1AFB06CC01 | NIFTY | BULL | 22575.1 | 22555.0 | 22605.25 | 2026-10-28T11:00:00+05:30 | CLOSED |

## Signal Status (today: 2026-10-30)
| Status | Count |
|---|---|
| EXPIRED | 7 |
| TRADED | 0 |
| NEW | 0 |

## Latest Market Candles (today: 2026-10-30)
| Instrument | Latest Candle | Count |
|---|---|---|
| NIFTY | 2026-10-30T13:20:00+05:30 | 50 |
| BANKNIFTY | 2026-10-30T13:20:00+05:30 | 50 |
| INDIA_VIX | 2026-10-30T13:20:00+05:30 | 50 |

## Schema Verification
Tables verified with correct schema:
- `paper_trades`: trade_id PK, instrument_id, scenario, direction, entry, stop, target, entry_time, exit_time, exit_price, exit_reason, paper_pnl, status, qualification_evidence, created_at, updated_at
- `scalp_signals`: signal_id PK, instrument_id, direction, signal_type, source_candle_ts, reference_price, reference_stop, reference_target, reference_level, status, paper_trade_id, created_at, updated_at
- `paper_trade_events`: event_id PK, trade_id, evidence, created_at
- `trade_journal`: journal_id PK, trade_id, event_type, event_time, details

## Preservation
- No database schema changes
- No data modifications or deletions
- All historical signals, trades, events, candles preserved
- SQLite backup: `/opt/tradingai/backups/paper_trade_repair_20261030_20261030_130913/tradingai.db`
