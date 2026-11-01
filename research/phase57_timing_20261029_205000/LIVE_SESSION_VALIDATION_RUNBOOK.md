# Phase 5.7 — Live-Session Validation Runbook

## Purpose

Safely measure actual provider and collector latency during a live market session.
Preserve current strategy and entry guard. No HLC-only mode. No real Telegram alerts.

## Pre-Session Checklist

1. Verify market is open: Mon-Fri, 09:15-15:30 IST
2. Verify services running: gunicorn, paper_scalp_live, market-data timer
3. Verify DB integrity: `PRAGMA integrity_check` → ok
4. Verify no experimental jobs running
5. Create timestamped log file: `/opt/tradingai/logs/phase57_live_YYYYMMDD.log`

## Measurement Procedure

### Step 1: Record Baseline (09:10 IST, before market open)

```bash
# Record service PIDs
ps aux | grep -E 'gunicorn|paper_scalp_live' | grep -v grep

# Record DB state
sqlite3 database/tradingai.db "SELECT COUNT(*) FROM paper_trades; SELECT COUNT(*) FROM scalp_signals;"

# Record last candle timestamp
sqlite3 database/tradingai.db "SELECT MAX(timestamp) FROM market_candles_5m WHERE instrument_id='NIFTY';"
```

### Step 2: Monitor Collector Latency (09:15-10:00 IST)

For each 5-min candle completion, record:
- Candle timestamp (interval start)
- Candle end (timestamp + 5 min)
- First observed in DB (ingested_at)
- Delay = ingested_at - candle_end

```bash
# Run every 30 seconds during market hours
watch -n 30 'sqlite3 database/tradingai.db "SELECT timestamp, ingested_at FROM market_candles_5m WHERE instrument_id=\"NIFTY\" ORDER BY timestamp DESC LIMIT 3;"'
```

### Step 3: Monitor Signal Detection (09:15-10:00 IST)

Check `/api/strategy/scalp` for signal state:
```bash
curl -s http://127.0.0.1:8000/api/strategy/scalp?instrument=NIFTY | python3 -m json.tool
```

Record:
- Signal detection time (when signal appears in API)
- Entry time (signal's entry_time)
- Entry guard result (ok/expired/failed)

### Step 4: Monitor Trade Creation (09:15-10:00 IST)

Check `/api/paper/scalp` for new trades:
```bash
curl -s http://127.0.0.1:8000/api/paper/scalp | python3 -m json.tool
```

Record:
- Trade creation time
- Trade ID
- Entry price
- Signal-to-trade latency

### Step 5: Monitor Rejected Signals (09:15-15:30 IST)

Check logs for rejected/expired signals:
```bash
grep -E "expired|rejected|failed" /opt/tradingai/logs/paper_scalp_live.log | tail -20
```

Record:
- Rejection reason (expired/failed/missing price)
- Signal timestamp
- Rejection time

### Step 6: Post-Session Analysis

1. Compute ingestion delay statistics (median, P95, max)
2. Compute signal-to-trade latency
3. Count rejected signals and reasons
4. Verify no duplicate trades
5. Verify DB integrity

## Stop Conditions

STOP the validation immediately if:
1. A production write occurs outside expected paths (paper_trades, scalp_signals, market_candles_5m)
2. Stale data (>20 min) is accepted for trade creation
3. A retroactive entry price is used
4. Duplicate trades are created
5. A service crashes or restarts unexpectedly
6. Telegram alerts are sent (should not happen during test)
7. Any error rate exceeds 10% of cycles

## Safety Measures

1. Do NOT enable HLC-only mode
2. Do NOT disable CPR
3. Do NOT send real Telegram alerts (tg_alerts cron will run normally — this is expected)
4. Do NOT modify any configuration
5. Do NOT restart any services
6. All measurements are read-only (API calls, log inspection, DB reads)

## Expected Outcomes

| Metric | Expected | Failure Threshold |
|--------|----------|-------------------|
| Ingestion delay (median) | <30s | >60s |
| Ingestion delay (P95) | <90s | >120s |
| Signal-to-trade latency | <10s | >30s |
| Rejected signals | <10% of signals | >25% of signals |
| Duplicate trades | 0 | >0 |
| DB integrity | ok | not ok |
