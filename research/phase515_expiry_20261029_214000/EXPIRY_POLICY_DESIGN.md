# Phase 5.15 — Expiry Policy Design (Research-Only, Not Activated)

## Policy: Fail-Closed Entry Expiry

### Conditions (all must pass for ACCEPTED)

1. **Signal time present and valid** — non-empty, parseable ISO timestamp
2. **Entry time present and valid** — non-empty, parseable ISO timestamp
3. **Not future-dated** — signal_time <= now
4. **Same session** — signal_date == entry_date (no cross-session carry)
5. **Entry after signal completion** — entry_time >= signal_time + 5 min
6. **Within entry window** — now <= entry_time + 5 min
7. **Entry price observable** — entry_time <= now (price available)

### Rejection Reasons

| Reason | Condition |
|--------|-----------|
| missing_signal_time | Signal time empty/null |
| missing_entry_time | Entry time empty/null |
| malformed_timestamp | Unparseable timestamp |
| future_dated_signal | Signal time > now |
| cross_session_signal | Signal date != entry date |
| entry_before_signal_completion | Entry time < signal candle end |
| entry_window_expired | now > entry_time + 5 min |

### Session Handling

- Trading sessions: Mon-Fri, 09:15-15:30 IST
- Market holidays: not handled (would need holiday calendar)
- Weekends: no trading, signals from Friday expire (cross-session)
- Overnight signals: rejected (cross-session check)

### Duplicate Processing

- Expiry policy is stateless and deterministic
- Same inputs always produce same result
- Process restart does not reset expiry clock
- Expired signals cannot be revived by re-reading

### Open Trade Monitoring

- Expiry policy applies to NEW trade creation only
- `monitor()` function continues to manage all ACTIVE/OPEN trades
- No change to exit logic or position management
