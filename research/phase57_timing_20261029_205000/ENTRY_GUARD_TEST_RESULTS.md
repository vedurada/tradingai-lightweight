# Phase 5.7 — Entry Guard Test Results

## Function Tested

`_entry_time_guard(entry_time_s, now_dt=None)` from `/opt/tradingai/scripts/paper_scalp_live.py`

## Test Results

| Test ID | Scenario | Input | Expected | Actual | Result |
|---------|----------|-------|----------|--------|--------|
| EG1 | Valid timely entry (now within 5-min window) | entry=10:25, now=10:26 | ok, None | ok, None | PASS |
| EG2 | Expired entry (now > entry+5min) | entry=10:25, now=10:31 | expired, entry_candle_closed | expired, entry_candle_closed | PASS |
| EG3 | Missing entry time | entry="" | failed, missing_entry_time | failed, missing_entry_time | PASS |
| EG4 | Bad entry time format | entry="not-a-date" | failed, bad_entry_time | failed, bad_entry_time | PASS |
| EG5 | Timezone-naive entry (assumes IST) | entry="2026-10-29T10:25:00" | ok, None | ok, None | PASS |

## Additional Scenarios Tested (in isolated test DB)

| Test ID | Scenario | Result |
|---------|----------|--------|
| T2 | Expired signal rejected without creating trade | PASS |
| T3 | Missing entry price rejected safely | PASS |
| T4 | Duplicate signal cannot create duplicate trades | PASS |
| T8 | Persistence/alert failure handling | PASS |

## Guard Behavior Verified

1. Expired signals are rejected (no trade created)
2. No later candle or price is used to pretend entry occurred earlier
3. Missing/invalid entry times are rejected (not silently accepted)
4. Timezone-naive timestamps are assumed IST (consistent with system)
5. Entry window is exactly 5 minutes (entry_time to entry_time + 5min)

## 5-Minute Guard Preserved

The entry-time guard was NOT modified. The 5-minute window remains unchanged.
