# Phase 5.8 — Live-Session Validation Runbook

## Purpose

Measure actual provider and collector latency during a live market session.
Preserve current strategy and entry guard. No HLC-only mode. No real Telegram alerts.

## Pre-Session Checklist

1. Verify market is open: Mon-Fri, 09:15-15:30 IST
2. Verify services running: gunicorn, paper_scalp_live, market-data timer
3. Verify DB integrity: `PRAGMA integrity_check` → ok
4. Verify no experimental jobs running
5. Create timestamped log file: `/opt/tradingai/logs/phase58_live_YYYYMMDD.log`

## Measurement Procedure

### Stage 1: Candle-End-to-Provider-Observation

For each 5-min candle completion, record:
- Candle timestamp (interval start)
- Candle end (timestamp + 5 min)
- First observed in yfinance (manual check or collector log)
- Delay = first_observed - candle_end

### Stage 2: Candle-End-to-Database

- Candle end (timestamp + 5 min)
- ingested_at (from market_candles_5m)
- Delay = ingested_at - candle_end

### Stage 3: Database-to-Signal

- ingested_at (from market_candles_5m)
- Signal detection time (from paper_scalp_live log or API)
- Delay = signal_time - ingested_at

### Stage 4: Signal-to-Entry-Decision

- Signal detection time
- Entry guard decision time
- Trade creation time (if created)
- Delay = trade_creation - signal_detection

### Stage 5: Expired-Signal Rejection Counts

- Count signals rejected as 'expired' by entry guard
- Count signals rejected as 'failed' (missing entry time, bad format)
- Count signals skipped (missing entry price)
- Count signals skipped (stale data)

### Stage 6: Missing/Duplicate Candle Counts

- Count expected candles (75 per instrument per day)
- Count actual candles in DB
- Count duplicate candle_ids (should be 0 due to INSERT OR IGNORE)

## Stop Conditions

STOP immediately if:
1. Production write outside expected paths
2. Stale data (>20 min) accepted for trade creation
3. Retroactive entry price used
4. Duplicate trades created
5. Service crash or unexpected restart
6. Telegram alerts sent during test
7. Error rate >10% of cycles
8. Any DB integrity failure

## Evidence Required Before Migration

1. Live ingestion delay: median <30s, P95 <120s
2. Live signal-to-trade latency: <30s
3. Expired signal rejection rate: <10%
4. Zero duplicate trades
5. Zero stale data accepted
6. DB integrity: ok
7. All services stable for full session
