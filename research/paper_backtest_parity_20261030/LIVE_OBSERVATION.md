# Live Observation

## Date
2026-10-30

## Host
webserver / Linux / x86_64 / ubuntu / /opt/tradingai (Oracle VM)

## Observation Window

Market session: 09:15-15:30 IST
Observation period: Fix deployed at ~14:50 IST, market closes at 15:30 IST

## Signal Activity During Observation

No new HLC 3-bar signals occurred after the fix was deployed at 14:50 IST. The last signal before the fix was:

| Signal ID | Instrument | Direction | Signal Time | Entry Time | Status |
|-----------|------------|-----------|-------------|------------|--------|
| SS-987CFD569F81 | BANKNIFTY | BEAR | 14:45:00 | 14:50:00 | TRADED |

## Live Verification Status

**LIVE_DELIVERY_NOT_YET_VERIFIED**

No genuine HLC 3-bar signal occurred after the fix was deployed. The fix cannot be verified with a new live signal in this session.

## Fix Verification (Code Analysis)

The fix has been verified through:

1. **Code review:** The fix correctly computes `entry_time` as `signal_time + 5min` when `entry_time` is None, preventing premature signal expiration.

2. **Syntax verification:** `python3 -m py_compile` passes for the modified file.

3. **Service deployment:** `tradingai-paper-scalp-live.service` restarted and running with the fix (PID 972875).

4. **Isolated tests:** 15/15 passed before deployment.

5. **Backtest vs live parity:** 100% match (7/7 for both NIFTY and BANKNIFTY), confirming the signal generation logic is identical between backtest and live.

## What Will Be Verified When a New Signal Occurs

| Step | Evidence |
|------|----------|
| Signal generated | `scalp_signals` table row with `status='NEW'` |
| Signal persisted | `paper_scalp_live.log` shows signal processing |
| Paper trade created | `paper_trades` table row with matching `entry_time` |
| ENTRY alert delivered | `notification_events` table with `status='DELIVERED'`, `event_type='ENTRY'`, `channel='telegram'` |
| Telegram message ID | `notification_events.message_id` populated |
| Actual Telegram message | Visible in `@tradingai_cpr` channel |

## Recommendation

Wait for the next market session (2026-10-31 or later) to observe a genuine HLC signal and verify end-to-end delivery with the fix in place.
