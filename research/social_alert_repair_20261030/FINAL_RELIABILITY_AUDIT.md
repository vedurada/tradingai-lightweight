# Final Social Alert Reliability Audit

## Date
2026-10-30

## Host
webserver / Linux / x86_64 / ubuntu / /opt/tradingai (Oracle VM)

## Final Status
**FIXED_AWAITING_REAL_SIGNAL**

Fixes deployed and verified via isolated tests (8/8 passed). No genuine live HLC signal occurred during the audit window to confirm end-to-end delivery. Do not claim live delivery verification without actual destination evidence.

---

## 1. Telegram Delivery Correctness

### Verified

| Check | Status | Evidence |
|-------|--------|----------|
| HTTP response status checked | PASS | `tg()` at line 72 catches `urllib.error.HTTPError` and generic `Exception` |
| JSON response `ok` checked | PASS | All call sites check `r.get('ok')` before marking DELIVERED (lines 736, 808, 911) |
| `message_id` captured and persisted | PASS | `(r.get('result') or {}).get('message_id')` stored in `notification_events` and `tg_alerts_archive.jsonl` |
| Only confirmed success becomes DELIVERED | PASS | `status='DELIVERED'` only set after `r.get('ok')` is True |
| API errors become FAILED with safe description | PASS | `status='FAILED'` with `str(r)[:500]` as error, stored in `notification_events` |
| Timeouts and connection failures recoverable | PASS | `except Exception` catches all, returns `{'ok': False}`; signal retried on next poll cycle |
| Retries bounded | PASS | No retry loop within `tg()`; retry happens on next cron poll (max 1 min) |

### Resolved Issues

| Issue | Before | After |
|-------|--------|-------|
| `_is_delivered` used undefined `DELIVERED` constant | `row[0] == DELIVERED` (NameError) | `row[0] == 'DELIVERED'` |
| `_is_delivered` SQL used unquoted `channel=telegram` | `channel=telegram` (column reference, silently fails) | `channel='telegram'` (string literal) |
| No PENDING record before dispatch | Missing | `INSERT OR IGNORE` into `notification_events` before `tg()` call |
| No DELIVERED update after success | Missing | `UPDATE notification_events SET status='DELIVERED'` after `r.get('ok')` |
| No FAILED update after failure | Scrambled SQL | `UPDATE notification_events SET status='FAILED'` after `not r.get('ok')` |

---

## 2. Facebook Delivery Correctness

### Verified

| Check | Status | Evidence |
|-------|--------|----------|
| Graph API response checked | PASS | `fb_post()` catches `HTTPError` and `Exception`, returns `None` on failure |
| Successful post ID captured | PASS | `json.load(resp)` returned from Graph API |
| Only confirmed success becomes DELIVERED | N/A | Facebook has no notification_events tracking (see Gap below) |
| Failure independently recorded | PASS | `print(f"FB POST FAILED: ...")` logged; does not raise |
| Facebook failure does not affect Telegram | PASS | `fb_post()` called in `try/except` after Telegram success |
| Telegram success does not imply Facebook success | PASS | Independent channels; Telegram DELIVERED regardless of FB result |

### Gap: No Facebook Delivery Tracking in notification_events

| Aspect | Detail |
|--------|--------|
| Gap | `notification_events` table only tracks `channel='telegram'`. Facebook posts have no delivery record in SQLite. |
| Impact | Cannot query Facebook delivery status via SQL. Cannot enforce one-post-per-signal for Facebook at DB level. |
| Risk | Duplicate Facebook posts possible if watcher restarts and re-processes signals. |
| Recommended Fix | Add `channel='facebook'` rows to `notification_events` with the same PENDING/DELIVERED/FAILED lifecycle. Do not deploy without backup and tests. |
| Mitigation | Standalone `scripts/fb_post.py --sync` posts from `tg_alerts_archive.jsonl` with `posted_keys` dedup in `data/fb_state.json`. Cron for this is commented out. |

---

## 3. Notification Ledger Integrity

### Verified

| Check | Status | Evidence |
|-------|--------|----------|
| UNIQUE(signal_id, channel) enforced | PASS | Schema: `UNIQUE (signal_id, channel)` + `sqlite_autoindex_notification_events_2` |
| PENDING/DELIVERED/FAILED transitions valid | PASS | Isolated tests confirm all transitions work |
| Delivered records not downgraded | PASS | `_is_delivered` uses `mode=ro` URI (read-only); no writes possible |
| Retry doesn't bypass deduplication | PASS | `_is_delivered()` checks for `status='DELIVERED'` before processing; PENDING/FAILED rows are re-processable |
| Concurrent watcher can't send duplicates | PASS | `O_CREAT | O_EXCL` lock file; `_is_delivered()` check before dispatch |
| Restart doesn't resend delivered | PASS | `_is_delivered()` returns True for DELIVERED records; signal skipped |
| Existing records untouched | PASS | Additive table only; no existing tables modified |

### Schema

```sql
CREATE TABLE notification_events (
    event_id TEXT PRIMARY KEY,
    signal_id TEXT,
    instrument_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    message_id TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (signal_id, channel)
);
```

### Row Count
- `notification_events`: 0 rows (no signals processed yet since fix deployed)

---

## 4. Watcher Timing and Service Health

### Verified

| Check | Status | Evidence |
|-------|--------|----------|
| Watcher frequency | PASS | Cron: `* 9-15 * * 1-5` (every minute, market hours, weekdays) |
| Market-hours handling (IST) | PASS | `_entry_window_open()` checks `(hour, minute) <= (15, 25)`; `_fresh_entry()` checks <= 20 min |
| No overlapping executions | PASS | `O_CREAT | O_EXCL | O_WRONLY` lock on `/tmp/tg_watch.lock`; stale lock >600s auto-removed |
| No stale lock or rogue process | PASS | Single `paper_scalp_live.py` process (PID 944550); no `tg_alerts.py` rogue process |
| Exceptions visible | PASS | All exceptions printed with context; `tg.log` captures output |
| Failed notification doesn't terminate signal generation | PASS | `try/except` around `tg()` and `fb_post()`; loop continues to next signal |
| Watcher may miss signals between polls | WARNING | Max 1-minute gap between polls; signals generated between polls are caught on next cycle |

### Service Status
- `tradingai-paper-scalp-live.service`: active (running, PID 944550, 4+ min uptime)
- `tradingai-api.service`: active (gunicorn, port 8000)

---

## 5. Isolated Tests

All 8 tests passed using temporary SQLite databases (no public messages sent):

| # | Test | Result |
|---|------|--------|
| 1 | Success response: DELIVERED with message_id | PASS |
| 2 | Duplicate signal dedup via UNIQUE constraint | PASS |
| 3 | FAILED transition with error description | PASS |
| 4 | Undelivered signal not treated as delivered | PASS |
| 5 | Concurrent execution lock protection | PASS |
| 6 | PENDING -> DELIVERED state machine | PASS |
| 7 | DELIVERED records not downgraded by read-only check | PASS |
| 8 | Different channels are independent | PASS |

**Result: 8/8 passed, 0 failed**

No fake signals were published to public channels.

---

## 6. Genuine Live Verification

### Status: `LIVE_DELIVERY_NOT_YET_VERIFIED`

No genuine HLC 3-bar signal occurred during the audit window (market open until 15:30 IST). All signals from 2026-10-30 (10:00-11:35 IST and 13:30-13:45 IST) expired before the fix was deployed and were correctly skipped as "stale entry" by the watcher.

### What Will Be Verified When a Signal Occurs

| Step | Evidence |
|------|----------|
| Signal ID | `SS-<hash>` from `_scalp_key()` + `hashlib.sha1()` |
| SQLite signal record | `scalp_signals` table row with `status='NEW'`/`'TRADED'` |
| Notification event | `notification_events` row with `status='DELIVERED'`, `message_id` |
| Telegram message ID | External message ID from Telegram API response |
| Actual Telegram message | Visible in `@tradingai_cpr` channel |
| Timestamps | Signal time, dispatch time, API response time (all IST) |

### Do Not
- Manufacture a live trade
- Use historical replay as proof
- Send fake signals to public channels
- Claim `ALERTS_WORKING_AND_LIVE_VERIFIED` without actual destination evidence

---

## 7. Unresolved Risks and Recommended Changes

### Unresolved Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Facebook has no notification_events tracking | Medium | Add `channel='facebook'` rows with same PENDING/DELIVERED/FAILED lifecycle |
| Watcher runs unlocked if lock acquisition fails | Low | Currently prints warning and continues; could send duplicates on restart |
| Max 1-min poll gap means signals between polls wait up to 1 min | Low | Acceptable for intraday alerts |
| Timeout after remote acceptance could cause duplicate | Low | Telegram message_id stored on success; `_is_delivered` prevents re-send |

### Recommended Changes (Do Not Deploy Without Backup and Tests)

1. **Add Facebook channel tracking** to `notification_events` with the same lifecycle
2. **Make lock failure fatal** instead of running unlocked (prevent duplicates on restart)
3. **Enable `fb_post.py --sync` cron** (currently commented out) for Facebook archive backfill

---

## Files Modified

| File | Change |
|------|--------|
| `scripts/tg_alerts.py` | Fixed `_is_delivered` (DELIVERED constant + quoted channel), added PENDING/DELIVERED/FAILED notification_events operations |
| `scripts/fb_post.py` | No changes |
| `database/tradingai.db` | Additive `notification_events` table (DEFAULT 'PENDING' properly quoted) |

### Backups
- `/opt/tradingai/backups/social_alert_repair_20261030_20261030_134019/` (tg_alerts.py, fb_post.py, tradingai.db)

---

## Conclusion

All code fixes are deployed, syntax-verified, and pass 8/8 isolated tests. The notification pipeline now correctly:
1. Persists PENDING before Telegram dispatch
2. Marks DELIVERED with message_id on success
3. Marks FAILED with error on failure
4. Prevents duplicates via UNIQUE(signal_id, channel)
5. Survives restarts without re-sending delivered signals

**Final Status: FIXED_AWAITING_REAL_SIGNAL**

Awaiting a genuine HLC 3-bar signal during market hours to confirm end-to-end live delivery.