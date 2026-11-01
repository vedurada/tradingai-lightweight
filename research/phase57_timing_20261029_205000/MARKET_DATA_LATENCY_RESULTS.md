# Phase 5.7 — Market Data Latency Results

## Measurement Method

Historical analysis of `market_candles_5m` table: for each candle, compute
`ingested_at - (timestamp + 5 minutes)` = ingestion delay after candle completion.

Data source: Production database (read-only), Oct 29, 2026 session.

## Results by Instrument

| Instrument | Samples | Min (s) | Median (s) | P95 (s) | Max (s) | Mean (s) | Fresh (<30s) | Late (>=60s) |
|-----------|---------|---------|------------|---------|---------|----------|-------------|-------------|
| NIFTY | 75 | 0.2 | 8.6 | 78.4 | 85.6 | 15.9 | 67 | 8 |
| BANKNIFTY | 75 | 0.1 | 9.3 | 79.6 | 86.1 | 16.5 | 67 | 8 |
| INDIA_VIX | 75 | 0.3 | 9.4 | 80.4 | 86.3 | 16.7 | 67 | 8 |

## Latency Breakdown

| Stage | Median | P95 | Max |
|-------|--------|-----|-----|
| Candle completion → collector run | 0-20s (RandomizedDelaySec) | 0-20s | 0-20s |
| Collector run → DB persistence | 8.6s | 78.4s | 85.6s |
| DB persistence → paper_scalp_live poll | 0-5s | 0-5s | 0-5s |
| Poll → signal scan | <1s | <1s | <1s |
| Signal scan → entry price resolution | <1s | <1s | <1s |
| Entry price → entry guard | <1ms | <1ms | <1ms |
| Entry guard → trade creation | <100ms | <100ms | <100ms |
| **Total (estimated)** | **~15s** | **~90s** | **~100s** |

## Fresh vs Late Candles

| Category | Count | Percentage | Cause |
|----------|-------|------------|-------|
| Fresh (<30s) | 67/75 | 89.3% | Normal collector operation |
| Late (>=60s) | 8/75 | 10.7% | RandomizedDelaySec=20 + collector processing + yfinance delay |

## Critical Finding

**The 5-minute entry window is NOT exceeded.** Even in the worst case (~100s), the total latency is well within the 300s (5-minute) entry window.

The previous "5-6 minute delay" reports were based on a misunderstanding of the collector timer cadence. The timer runs every 5 minutes, but each run fetches all recent completed candles (10-day window), so the latest completed candle is ingested within seconds of its completion.

## Live-Session Latency

**NOT RUN — MARKET CLOSED.** All measurements are from historical data. Live-session verification requires a market session (09:15-15:30 IST, Mon-Fri).

## Caveats

1. Historical data may not represent live-session behavior (yfinance rate limiting, network conditions)
2. RandomizedDelaySec=20 adds up to 20s jitter per collector run
3. Collector fetches 10 days of data per run — if yfinance is slow, all candles are delayed
4. No measurement of provider publication latency (when yfinance first makes a candle available)
