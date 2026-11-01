# Phase 5.8 — Phase 5.7 Evidence Revalidation

## Revalidation of Phase 5.7 Claims

### 1. Sample Count and Calculation Method

| Item | Value | Verified |
|------|-------|----------|
| Sample count (NIFTY) | 75 candles | YES — from production DB, Oct 29, 2026 |
| Sample count (BANKNIFTY) | 75 candles | YES |
| Sample count (INDIA_VIX) | 75 candles | YES |
| Calculation method | `ingested_at - (timestamp + 5 min)` | YES — verified by re-running query |
| Median (NIFTY) | 8.6s | YES |
| P95 (NIFTY) | 78.4s | YES |
| Max (NIFTY) | 85.6s | YES |

### 2. Timestamp Semantics

The measured timestamp represents **candle END time** (timestamp + 5 minutes), NOT:
- Provider availability time (when yfinance first makes the candle available)
- Database persistence time (ingested_at)
- Collection scheduling time

The delay = time from candle completion to database persistence. This INCLUDES:
- Collection scheduling delay (RandomizedDelaySec=20)
- Collector processing time
- yfinance fetch time
- Database insert time

### 3. Collection Scheduling Delay

INCLUDED in measurements. The collector timer has RandomizedDelaySec=20, which adds 0-20s jitter per run. The 8 "late" candles (>=60s) are attributed to this jitter plus collector processing.

### 4. Production-Function Tests

| Test | Count | Executed | Passed | Evidence |
|------|-------|----------|--------|----------|
| Entry guard tests | 5 | YES | 5/5 | Isolated test DB |
| Production function tests | 16 | YES | 16/16 | Isolated test DB |

### 5. Mocked Dependencies

| Dependency | Mocked? | How |
|-----------|---------|-----|
| get_conn (DB) | YES | Patched to return test DB connection |
| MarketDataProvider | NOT CALLED | Tests don't invoke provider (entry price from synthetic data) |
| Telegram API | NOT CALLED | No alert tests in this phase |
| yfinance | NOT CALLED | No live data fetch in tests |

### 6. Test Write Restriction

ALL test writes went to isolated test DB: `/opt/tradingai/research/phase57_timing_20261029_205000/test_prod.db`

Production DB was NOT modified. Verified by `PRAGMA integrity_check` → ok and row counts unchanged.

### 7. Entry Guard Unchanged

The `_entry_time_guard()` function was NOT modified. The 5-minute window (entry_time to entry_time + 5min) remains unchanged. Tests verified all 5 branches (ok, expired, failed-missing, failed-bad, tz-naive).

### Distinction: Verified vs Copied

| Claim | Source | Verified? |
|-------|--------|-----------|
| 75 samples, median 8.6s | Phase 5.7 measurement | YES — re-run confirmed |
| 16/16 production tests PASS | Phase 5.7 test run | YES — re-run confirmed |
| 5/5 entry guard tests PASS | Phase 5.7 test run | YES — re-run confirmed |
| "5-6 minute delay" (Phase 4.x) | Earlier reports | CORRECTED — actual delay is ~9s median |
| Daily limit 1/day → ~6 trades | Phase 5.5 estimate | UNVERIFIED — not recalculated from ledger |
