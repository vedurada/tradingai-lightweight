# Phase 5.19 — Working State Audit

## Read-Only Inventory

| Category | Count |
|----------|-------|
| Modified tracked files | 223 |
| Untracked files | 1,524 |
| Total dirty files | 1,747 |

**Note:** Earlier reports cited 1,842 (439 modified + 1,403 untracked). Current counts differ (223 modified + 1,524 untracked = 1,747). This may be due to files being added/removed between audits.

## Disk Space

- Total: 45G
- Used: 17G (37%)
- Available: 29G

## Memory

- Total: 956Mi
- Used: 339Mi
- Available: 511Mi (cached) + 105Mi (free)

## Database

- Path: /opt/tradingai/database/tradingai.db
- Size: 12M
- Journal mode: WAL
- WAL file: 4MB (db-wal)
- SHM file: 32KB (db-shm)
- Integrity: ok
- WAL checkpoint: (0, 693, 693) — all frames checkpointed

## Services

- Gunicorn: 3 processes (PIDs 802784, 824977, 829484)
- paper_scalp_live.py: 2 processes (PIDs 806096, 806158)
- market-data timer: active (last run 16:00:14 IST)
- tg_alerts: cron-scheduled

## Database Tables

| Table | Rows |
|-------|------|
| paper_trades | 94 |
| scalp_signals | 29 |
| paper_scalp | 217 |
| market_candles_5m | 16,936 |

## Working Tree Safety

- No Git commands used to modify working tree
- No files deleted, renamed, or overwritten
- All inventory via read-only commands
