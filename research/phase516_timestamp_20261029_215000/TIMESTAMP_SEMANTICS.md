# Phase 5.16 — Timestamp Semantics

## Canonical Timestamp Policy

### Representation

All timestamps in the system use ISO 8601 with +05:30 offset (Asia/Kolkata):
- Format: `YYYY-MM-DDTHH:MM:SS+05:30`
- Example: `2026-07-07T15:25:00+05:30`
- Timezone: Asia/Kolkata (IST, UTC+5:30)
- No daylight saving time

### Signal Timestamp

- `signal_time` = 3rd confirming candle's open timestamp
- Example: signal fires at 15:25 (candle covering 15:25-15:30)
- Signal candle completes at 15:30
- Signal is available after 15:30

### Entry Timestamp

- `entry_time` = next candle's open timestamp
- Example: entry at 09:15 (next day, first candle)
- Entry candle covers [09:15, 09:20)
- Entry price = entry candle's open

### Expiry Window

- Entry window: [entry_time, entry_time + 5 min)
- Expired if: now > entry_time + 5 min
- Signal age not checked (only entry window)

### Session Date Derivation

- Session date = IST date of the timestamp
- Derived from timestamp[:10] (date portion)
- No UTC conversion for session date

### Timezone Handling

- Naive timestamps assumed IST
- UTC timestamps converted to IST for comparison
- All internal comparisons use aware datetimes
- Fail closed on ambiguous inputs

### ET10 Resolution

The ET10 timezone-mismatch test (Phase 5.15) was a design question. Resolution:
- Same instant in UTC and IST produces identical expiry decisions
- The comparison uses instants (datetime objects), not labels
- Naive timestamps are assumed IST
- Fail closed on ambiguous inputs

### Compatibility Risks

1. If a timestamp is stored without timezone info, it's assumed IST. If the actual timezone was UTC, the instant would be wrong by 5.5 hours.
2. The system does not handle DST (not applicable for IST, but relevant if expanded to other timezones).
3. Session date is derived from IST, not UTC. A candle at 23:30 UTC (05:00 IST next day) would be assigned to the next day's session.
