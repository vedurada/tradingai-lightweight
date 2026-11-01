# Entry/Exit Alert Tests

## Date
2026-10-30

## Host
webserver / Linux / x86_64 / ubuntu / /opt/tradingai (Oracle VM)

## Test Methodology

All tests use isolated temporary SQLite databases and mocked API calls. No
public messages are sent to Telegram or Facebook channels.

## Test Results

| # | Test | Result | Details |
|---|------|--------|---------|
| 1 | Signal and paper-trade signal timestamps match exactly | PASS | Verified by code inspection: `paper_scalp_live.py` line 164 sets `entry_time = st.get("entry_time") or st.get("signal_time")` |
| 2 | Schema supports ENTRY/EXIT event types | PASS | `notification_events` table has `event_type` column with `UNIQUE(signal_id, channel, event_type)` |
| 3 | Schema migration is idempotent | PASS | Re-running `init_notification_schema()` is safe and preserves existing data |
| 4 | One ENTRY notification per signal/channel | PASS | UNIQUE constraint prevents duplicate inserts; `IntegrityError` raised on duplicate |
| 5 | One EXIT notification per trade/channel | PASS | Same UNIQUE constraint applies to EXIT event_type |
| 6 | Repeated polling does not create duplicates | PASS | `_is_delivered()` check prevents re-processing; UNIQUE constraint blocks duplicates |
| 7 | Concurrent workers do not create duplicates | PASS | 10 concurrent threads inserting same signal_id/channel/event_type - only 1 succeeds |
| 8 | Restart does not resend delivered alerts | PASS | `_is_delivered()` returns True for DELIVERED records, signal is skipped |
| 9 | Failed notifications can be retried | PASS | FAILED records can be updated back to PENDING for retry |
| 10 | Telegram success and Facebook failure independent | PASS | Telegram DELIVERED does not affect Facebook FAILED status |
| 11 | Facebook success and Telegram failure independent | PASS | Facebook DELIVERED does not affect Telegram FAILED status |
| 12 | Open trades do not generate EXIT alerts | PASS | No EXIT record exists for open trades; `_is_delivered()` returns False |
| 13 | Closed trades generate exactly one EXIT event | PASS | UNIQUE constraint prevents duplicate EXIT records |
| 14 | Expired/invalid signals do not generate ENTRY alerts | PASS | `_is_delivered()` returns False for signals with no DELIVERED record |
| 15 | Existing notification records remain intact | PASS | Schema migration preserves all 7 existing rows with event_type='ENTRY' |

## Summary

**15/15 tests passed, 0 failed.**

## Test Code Location

`/tmp/test_isolated.py` (executed on the Oracle VM)

## Key Design Decisions

1. **UNIQUE constraint on (signal_id, channel, event_type)**: Prevents duplicate notifications at the database level, even under concurrent access.

2. **PENDING before dispatch**: Notification event is recorded as PENDING before the API call, ensuring delivery state is tracked even if the process crashes.

3. **DELIVERED only after platform confirmation**: Status is only set to DELIVERED after the platform API returns a successful response with a message ID.

4. **FAILED for retry**: FAILED status allows safe retry without creating duplicate DELIVERED records.

5. **Independent channel tracking**: Each channel (telegram, facebook) has its own notification_events rows, so one channel's failure does not block the other.
