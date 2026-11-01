# Phase 5.9 — Next Session Runbook

## Next Market Session

- Date: 2026-10-30 (Friday)
- Market hours: 09:15-15:30 IST
- Pre-session setup: 09:00 IST

## Pre-Session Checklist

1. Verify market is open (Mon-Fri, 09:15-15:30 IST)
2. Verify services running: gunicorn, paper_scalp_live, market-data timer
3. Verify DB integrity: `PRAGMA integrity_check` → ok
4. Verify no experimental jobs running
5. Create timestamped log file

## Measurement Procedure

### Stage 1: Candle-End-to-Database (09:15-10:00)

For each 5-min candle completion, record:
- Candle timestamp (interval start)
- Candle end (timestamp + 5 min)
- ingested_at (from market_candles_5m)
- Delay = ingested_at - candle_end

### Stage 2: Database-to-Signal (09:15-10:00)

- Signal detection time (from paper_scalp_live log or API)
- Delay = signal_time - ingested_at

### Stage 3: Signal-to-Entry-Decision (09:15-10:00)

- Entry guard decision time
- Trade creation time (if created)
- Delay = trade_creation - signal_detection

### Stage 4: Rejected Signals (09:15-15:30)

- Count expired, failed, missing price, stale
- Record rejection reasons

### Stage 5: Missing/Duplicate Candles (09:15-15:30)

- Count expected vs actual candles
- Count duplicate candle_ids

## Stop Conditions

STOP immediately if:
1. Production write outside expected paths
2. Stale data (>20 min) accepted
3. Retroactive entry price used
4. Duplicate trades created
5. Service crash or unexpected restart
6. Telegram alerts sent during test
7. Error rate >10% of cycles
8. DB integrity failure

## Evidence Required Before Migration

1. Live ingestion delay: median <30s, P95 <120s
2. Live signal-to-trade latency: <30s
3. Expired signal rejection rate: <10%
4. Zero duplicate trades
5. Zero stale data accepted
6. DB integrity: ok
7. All services stable for full session
