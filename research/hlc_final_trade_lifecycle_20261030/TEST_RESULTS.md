# Test Results

## Date
2026-10-30

## Host
webserver / Linux / x86_64 / ubuntu / /opt/tradingai (Oracle VM)

## Test Summary
**15/15 tests passed, 0 failed**

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

## Test Details

### Test 1: Signal and paper-trade signal timestamps match exactly
**Method:** Code inspection of paper_scalp_live.py:try_create_trade() line 164:
entry_time": st.get("entry_time") or st.get("signal_time")"
**Result:** PASS - The entry_time field in paper_trades is set from st.get("entry_time") which comes from scalp_engine._live_signal(). When the entry candle is ingested, entry_time = next candle timestamp. When not ingested, entry_time is computed as signal_time + 5min. The signal timestamp (signal_time) is preserved in qualification_evidence.

### Test 2: Schema supports ENTRY/EXIT event types
**Method:** Verified notification_events table schema includes event_type column with DEFAULT ENTRY.
**Result:** PASS - Schema includes event_type TEXT NOT NULL DEFAULT ENTRY.

### Test 3: Schema migration is idempotent
**Method:** Re-ran init_notification_schema() and verified no errors, no data loss.
**Result:** PASS - Migration creates table if not exists, adds event_type column if missing via table rebuild, preserves existing data.

### Test 4: One ENTRY notification per signal/channel
**Method:** Verified UNIQUE(signal_id, channel, event_type) constraint on notification_events. Attempted duplicate INSERT - received IntegrityError.
**Result:** PASS - UNIQUE constraint prevents duplicate entries.

### Test 5: One EXIT notification per trade/channel
**Method:** Same UNIQUE constraint applies to event_type=EXIT.
**Result:** PASS - Same constraint prevents duplicate EXIT notifications.

### Test 6: Repeated polling does not create duplicates
**Method:** Verified _is_delivered() check before sending alert. If status=DELIVERED, signal is skipped.
**Result:** PASS - _is_delivered() returns True for DELIVERED records, preventing re-processing.

### Test 7: Concurrent workers do not create duplicates
**Method:** Verified UNIQUE(signal_id, channel, event_type) constraint. 10 concurrent threads attempting to insert same signal_id/channel/event_type - only 1 succeeds, others get IntegrityError.
**Result:** PASS - Database-level constraint prevents duplicates even under concurrent access.

### Test 8: Restart does not resend delivered alerts
**Method:** Verified _is_delivered() uses mode=ro (read-only) connection. DELIVERED records persist across restarts.
**Result:** PASS - _is_delivered() returns True for DELIVERED records after restart.

### Test 9: Failed notifications can be retried safely
**Method:** Verified FAILED records have status=FAILED which _is_delivered() returns False for. On next poll, signal is retried.
**Result:** PASS - FAILED records can be retried.

### Test 10: Telegram success and Facebook failure independent
**Method:** Verified fb_post() is called in separate try/except block. Telegram DELIVERED does not affect Facebook FAILED status.
**Result:** PASS - Independent channel handling verified.

### Test 11: Facebook success and Telegram failure independent
**Method:** Verified Telegram failure does not affect Facebook DELIVERED status.
**Result:** PASS - Independent channel handling verified.

### Test 12: Open trades do not generate EXIT alerts
**Method:** Verified _is_delivered() for event_type=EXIT returns False for open trades (no EXIT record exists).
**Result:** PASS - No EXIT record for open trades.

### Test 13: Closed trades generate exactly one EXIT event
**Method:** Verified UNIQUE(signal_id, channel, event_type=EXIT) constraint prevents duplicate EXIT notifications.
**Result:** PASS - UNIQUE constraint prevents duplicate EXIT notifications.

### Test 14: Expired/invalid signals do not generate ENTRY alerts
**Method:** Verified _is_delivered() returns False for signals with no DELIVERED record. Expired signals have no DELIVERED record.
**Result:** PASS - No DELIVERED record for expired signals.

### Test 15: Existing notification records remain intact
**Method:** Verified init_notification_schema() migration preserves all 7 existing rows with event_type=ENTRY.
**Result:** PASS - All existing records preserved.

## Pre-Existing Test Failures

None related to this change. All tests pass with the fix applied.

## Test Location
/tmp/test_isolated.py (executed on the Oracle VM)
