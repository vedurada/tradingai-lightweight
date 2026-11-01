# Phase 5.7 — HLC Market-Data Timing and Production-Path Validation

## Environment

- Host: `webserver` (Oracle VM)
- Application root: `/opt/tradingai`
- Production database: `/opt/tradingai/database/tradingai.db`
- Market-data timer: `tradingai-market-data.timer` (5-min cadence, RandomizedDelaySec=20)
- Phase 5.6A report: `/opt/tradingai/research/phase56a_readiness_20261029_204000/PHASE56A_REPORT.md`
- Report directory: `/opt/tradingai/research/phase57_timing_20261029_205000/`

## Phase A — Readiness Baseline

### Collector Configuration

- Timer: `tradingai-market-data.timer` — OnCalendar every 5 minutes (09:01, 09:06, ... 09:56, 10:00, 10:05, ...)
- RandomizedDelaySec: 20 seconds
- Service: `tradingai-market-data.service` (oneshot, user=ubuntu)
- Collector: `/opt/tradingai/app/market/collector.py`
- Provider: yfinance (via `MarketDataProvider._fetch_history`)
- Cutoff logic: `get_completed_cutoff()` — only completed candles (interval end < now)
- PIT invariant: only candles with timestamp <= cutoff stored
- is_complete: 1 (all stored candles are completed)

### Candle Provider and Timestamp Semantics

- Provider: yfinance 5-minute bars
- Timestamp: candle START time (e.g., 09:15:00 = candle covering 09:15-09:20)
- Candle end = timestamp + 5 minutes
- All timestamps in Asia/Kolkata (+05:30)
- ingested_at: when collector persisted the candle

### HLC Signal Detection

- Engine: `app/research/scalp_engine.py`
- `_scan_signals()`: requires 3 consecutive bars with same-direction H/L/C movement
- `_live_signal()`: computes entry from next candle (idx+1) or computes timestamp if not ingested
- `today_state()`: filters candles to `timestamp <= now`, scans for signals
- Entry price: from entry candle's open (historical) or live provider (forming candle)

### Entry Guard

- Function: `_entry_time_guard()` in `scripts/paper_scalp_live.py`
- Rule: Entry candle interval is [entry_time, entry_time + 5min). Reject if now > entry_time + 5min.
- Returns: ('ok', None), ('expired', 'entry_candle_closed'), or ('failed', reason)
- 5-minute window is UNCHANGED from original design

### Actual Call Path

```
collector.py:collect_all() → get_conn() → INSERT INTO market_candles_5m
  → paper_scalp_live.py:run_once() (polls every 5s)
    → latest_candle() → validate_candle()
    → today_signals() → scalp_engine._scan_signals()
    → _entry_time_guard(entry_time, now)
    → _get_entry_price_from_provider() (if entry is None)
    → record_signal() → try_create_trade()
      → has_open_position() (Mode C check)
      → PaperTradeEngine.create_paper_trade()
    → PaperTradeEngine.monitor() (exit evaluation)
```

### Production Write Paths

1. `market_candles_5m` — collector writes candles
2. `paper_trades` — paper_scalp_live writes trades
3. `scalp_signals` — paper_scalp_live writes signals
4. `paper_trade_events` — monitor writes exit events
5. `data/tg_state.json` — tg_alerts writes dedup state
6. `data/tg_alerts_archive.jsonl` — tg_alerts writes alert log

### External Side Effects

1. Telegram API calls (tg_alerts.py) — only for existing trades
2. yfinance API calls (collector, provider) — read-only
3. No broker API calls (paper trading only)

## Phase B — Timing Measurements

### Candle-End-to-Database Latency (Oct 29, 2026)

| Instrument | Samples | Min (s) | Median (s) | P95 (s) | Max (s) | Mean (s) | Fresh (<30s) | Late (>=60s) |
|-----------|---------|---------|------------|---------|---------|----------|-------------|-------------|
| NIFTY | 75 | 0.2 | 8.6 | 78.4 | 85.6 | 15.9 | 67 | 8 |
| BANKNIFTY | 75 | 0.1 | 9.3 | 79.6 | 86.1 | 16.5 | 67 | 8 |
| INDIA_VIX | 75 | 0.3 | 9.4 | 80.4 | 86.3 | 16.7 | 67 | 8 |

**Key findings:**
- Median ingestion delay: ~9 seconds (well within 5-min window)
- P95 ingestion delay: ~79 seconds (within 5-min window)
- Max ingestion delay: ~86 seconds (within 5-min window)
- 8/75 candles (10.7%) are "late" (>=60s) — caused by timer RandomizedDelaySec=20 + collector processing
- No candles exceed 5 minutes ingestion delay

### Total Candle-End-to-Entry-Decision Latency (Estimated)

| Stage | Estimated Time |
|-------|---------------|
| Candle completion → collector run | 0-5 min (timer cadence) |
| Collector run → DB persistence | 8.6s median, 78s P95 |
| DB persistence → paper_scalp_live poll | 0-5s (POLL_SECONDS=5) |
| Poll → signal scan | <1s |
| Signal scan → entry price resolution | <1s (provider call) |
| Entry price → entry guard | <1ms |
| Entry guard → trade creation | <100ms |
| **Total (median)** | **~15 seconds** |
| **Total (P95)** | **~90 seconds** |
| **Total (worst case)** | **~100 seconds** |

All within the 5-minute (300s) entry window.

**NOTE:** Live-session latency was NOT measured (market closed). These estimates are based on historical ingestion data and code analysis. Live verification requires a market session.

## Phase C — Entry Guard Tests

See `ENTRY_GUARD_TEST_RESULTS.md`. 5/5 tests passed using actual `_entry_time_guard()` function.

## Phase D — Production Function Tests

See `PRODUCTION_FUNCTION_TEST_RESULTS.md`. 16/16 tests passed using actual application functions.

## Phase E — Timing Constraint Assessment

### Root Cause of Previous "5-6 Minute Delay"

The previous reports (Phase 4.x) stated 5-6 minute ingestion delay. This was based on:
1. Collector timer running every 5 minutes
2. Assumption that collector only fetches the latest candle

**Actual finding:** The collector fetches 10 days of data per run. The latest completed candle is available from yfinance immediately after completion. The ingestion delay is the collector processing time + randomized delay (~9s median, ~79s P95), NOT 5 minutes.

The 5-minute delay was a MISINTERPRETATION of the timer cadence. The timer runs every 5 minutes, but each run fetches all recent completed candles, including ones that completed seconds ago.

### Data-Source Alternatives (Evaluated, Not Implemented)

| Alternative | Expected Freshness | Candle Trust | Historical Consistency | Failure Behavior | Cost | Changes Required | Guard Enforcement |
|------------|-------------------|-------------|----------------------|-----------------|------|-----------------|-------------------|
| yfinance (current) | ~9s median, ~79s P95 | High (completed only) | Good | Retry on next poll | Free | None | Unchanged |
| WebSocket (e.g., Kite/Zerodha) | ~1-3s | Medium (forming candles) | Requires reconciliation | Reconnect + backfill | Paid license | Major (new provider, candle builder) | Must enforce completion |
| NSE direct API | ~5-15s | High (completed only) | Good | Retry on next poll | Free (rate-limited) | Moderate (new provider) | Unchanged |
| TradingView webhook | ~1-5s | Medium (real-time) | Requires reconciliation | Webhook reliability | Paid | Major (new infrastructure) | Must enforce completion |

**Recommendation:** Current yfinance provider is sufficient for the 5-minute entry window. No change needed unless sub-10-second latency is required (not currently a requirement).

## Phase F — Live-Session Validation Plan

See `LIVE_SESSION_VALIDATION_RUNBOOK.md`.

## Phase G — Deployment Gate Review

See `DEPLOYMENT_BLOCKERS.csv`.

## Final Status

**PARTIAL — ISOLATED TESTS PASS; LIVE TIMING OR DEPENDENCIES UNRESOLVED**

Reasons:
- All 16 production function tests pass
- All 5 entry guard tests pass
- Timing analysis shows ingestion delay well within 5-min window
- BUT: Live-session latency NOT measured (market closed)
- BUT: Daily trade limit not implemented
- BUT: Feature flag not implemented
- BUT: Systemd unit not enabled
- BUT: Dirty working tree (1,842 files)
- BUT: No rollback rehearsal
