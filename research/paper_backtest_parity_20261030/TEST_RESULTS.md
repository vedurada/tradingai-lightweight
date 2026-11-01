# Test Results

## Date
2026-10-30

## Host
webserver / Linux / x86_64 / ubuntu / /opt/tradingai (Oracle VM)

## Isolated Tests (15/15 PASSED)

| # | Test | Result |
|---|------|--------|
| 1 | Signal and paper-trade signal timestamps match exactly | PASS |
| 2 | Schema supports ENTRY/EXIT event types | PASS |
| 3 | Schema migration is idempotent | PASS |
| 4 | One ENTRY notification per signal/channel | PASS |
| 5 | One EXIT notification per trade/channel | PASS |
| 6 | Repeated polling does not create duplicates | PASS |
| 7 | Concurrent workers do not create duplicates | PASS |
| 8 | Restart does not resend delivered alerts | PASS |
| 9 | Failed notifications can be retried safely | PASS |
| 10 | Telegram success and Facebook failure independent | PASS |
| 11 | Facebook success and Telegram failure independent | PASS |
| 12 | Open trades do not generate EXIT alerts | PASS |
| 13 | Closed trades generate exactly one EXIT event | PASS |
| 14 | Expired/invalid signals do not generate ENTRY alerts | PASS |
| 15 | Existing notification records remain intact | PASS |

## Backtest vs Live Parity

| Instrument | Backtest Signals | Live Signals | Exact Matches | Parity |
|------------|-----------------|--------------|---------------|--------|
| NIFTY | 7 | 7 | 7 | 100% |
| BANKNIFTY | 7 | 7 | 7 | 100% |

All 14 signals match exactly between backtest and live (same signal_time, direction, entry, entry_time, stop, target).

## Signal-to-Trade Latency

| Metric | Signal-to-Creation | Entry-to-Creation |
|--------|-------------------|-------------------|
| Average | -1.1s | 240.3s |
| Median | 0.0s | 324.0s |
| P95 | 0.1s | 363.2s |
| Maximum | 0.1s | 365.5s |

**Interpretation:**
- Signal-to-creation: Trades created in same polling cycle (sub-second delay)
- Entry-to-creation: 5-minute delay is inherent to next-candle execution strategy (signal at T, entry at T+5min)

## Signal Disposition (2026-10-30)

| Status | Count |
|--------|-------|
| TRADED | 28 |
| EXPIRED | 20 |
| NEW | 0 |
| IGNORED | 1 |
| Total | 49 |

**20 expired signals** were caused by the entry_time fallback defect (now fixed). Without the fix, signals with entry candle not yet ingested would expire 5 minutes after signal time instead of 5 minutes after entry candle time.

## Pre-Existing Test Failures

None related to this change. All existing tests pass with the fix applied.
