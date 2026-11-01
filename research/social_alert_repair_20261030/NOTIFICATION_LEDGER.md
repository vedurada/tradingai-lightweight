# Notification Ledger

## Date
2026-10-30

## Host
webserver / Linux / x86_64 / ubuntu / /opt/tradingai (Oracle VM)

## Schema

The `notification_events` table tracks delivery status for ENTRY and EXIT
notifications across Telegram and Facebook channels.

```sql
CREATE TABLE notification_events (
    event_id TEXT PRIMARY KEY,
    signal_id TEXT,
    instrument_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    event_type TEXT NOT NULL DEFAULT 'ENTRY',
    status TEXT NOT NULL DEFAULT 'PENDING',
    message_id TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (signal_id, channel, event_type)
);
```

## Columns

| Column | Type | Description |
|--------|------|-------------|
| event_id | TEXT PRIMARY KEY | Unique event identifier (NE-<hash>) |
| signal_id | TEXT | Reference to scalp_signals.signal_id |
| instrument_id | TEXT NOT NULL | Instrument (NIFTY, BANKNIFTY, etc.) |
| channel | TEXT NOT NULL | Notification channel (telegram, facebook) |
| event_type | TEXT NOT NULL DEFAULT 'ENTRY' | ENTRY or EXIT |
| status | TEXT NOT NULL DEFAULT 'PENDING' | PENDING, DELIVERED, or FAILED |
| message_id | TEXT | External platform message ID (Telegram message_id, Facebook post ID) |
| error | TEXT | Error description for FAILED status |
| created_at | TEXT NOT NULL | Creation timestamp (IST ISO 8601) |
| updated_at | TEXT NOT NULL | Last update timestamp (IST ISO 8601) |

## Constraints

| Constraint | Description |
|------------|-------------|
| PRIMARY KEY (event_id) | Unique event identifier |
| UNIQUE (signal_id, channel, event_type) | One notification per signal per channel per event type |
| NOT NULL on instrument_id, channel, event_type, status, created_at, updated_at | Required fields |

## Status Lifecycle

```
PENDING --> DELIVERED (on successful platform confirmation)
PENDING --> FAILED (on API error or exception)
FAILED  --> PENDING (on retry)
```

DELIVERED records are never downgraded. FAILED records can be retried by
changing status back to PENDING.

## Migration

The table was migrated from the previous schema (`UNIQUE(signal_id, channel)`
without `event_type`) to the new schema (`UNIQUE(signal_id, channel,
event_type)` with `event_type` column). Migration steps:

1. Create new table with `event_type` column and new UNIQUE constraint
2. Copy existing rows with `event_type='ENTRY'`
3. Drop old table
4. Rename new table to `notification_events`

Existing 7 rows were preserved with `event_type='ENTRY'`.

## Event Types

| Event Type | Description | Trigger |
|------------|-------------|---------|
| ENTRY | Signal entry alert | New valid HLC signal detected |
| EXIT | Trade exit alert | Paper trade transitions to CLOSED |

## Channel Tracking

| Channel | Tracking in notification_events | Independent delivery |
|---------|--------------------------------|---------------------|
| telegram | Yes (channel='telegram') | Yes |
| facebook | Yes (channel='facebook') | Yes |

Each channel has its own notification_events rows, enabling independent
delivery tracking and retry logic.

## Delivery Confirmation

| Platform | Confirmation Field | Source |
|----------|-------------------|--------|
| Telegram | message_id | `r.get('result').get('message_id')` from Bot API response |
| Facebook | message_id | `fr.get('result').get('id')` from Graph API response |

An attempted HTTP request is NOT treated as successful delivery. Delivery is
only confirmed when the platform API returns a successful response.

## Current State

| Metric | Value |
|--------|-------|
| Total rows | 7 |
| DELIVERED rows | 7 |
| PENDING rows | 0 |
| FAILED rows | 0 |
| ENTRY rows | 7 |
| EXIT rows | 0 |

All existing rows were migrated from the previous schema with `event_type='ENTRY'`.

## SQL Queries

Check if a signal has been delivered:
```sql
SELECT status FROM notification_events
WHERE signal_id=? AND channel=? AND event_type=?
```

Insert a PENDING record:
```sql
INSERT OR IGNORE INTO notification_events
(event_id, signal_id, instrument_id, channel, event_type, status, created_at, updated_at)
VALUES (?,?,?,?,?,?,?,?)
```

Update to DELIVERED:
```sql
UPDATE notification_events SET status='DELIVERED', message_id=?, updated_at=?
WHERE signal_id=? AND channel=? AND event_type=?
```

Update to FAILED:
```sql
UPDATE notification_events SET status='FAILED', error=?, updated_at=?
WHERE signal_id=? AND channel=? AND event_type=?
```
