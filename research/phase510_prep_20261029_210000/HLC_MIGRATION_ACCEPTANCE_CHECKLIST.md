# Phase 5.10 — HLC Migration Acceptance Checklist

## Acceptance Criteria

| # | Criterion | Status | Evidence Required |
|---|-----------|--------|-------------------|
| 1 | Feature flag default and fail-safe | NOT IMPLEMENTED | Code review + test |
| 2 | One new-trade initiation path per mode | DESIGNED | Code review |
| 3 | Existing open trade monitoring preserved | VERIFIED (code review) | Code review |
| 4 | Idempotency and duplicate prevention | VERIFIED (tests) | 16/16 PASS |
| 5 | Entry-price validity and 5-min expiry guard | VERIFIED (tests) | 5/5 PASS |
| 6 | Configurable daily trade limit | NOT IMPLEMENTED | Code + test |
| 7 | Daily limit policy explicitly approved | NOT APPROVED | User decision |
| 8 | API/dashboard/DB/Telegram compatibility | VERIFIED (code review) | Code review |
| 9 | Service restart and recovery | DESIGNED | Not tested |
| 10 | Backup and rollback rehearsal | NOT REHEARSED | Production rehearsal |
| 11 | Non-destructive deployment | NOT ESTABLISHED | B1 open |
| 12 | Live-session latency evidence | NOT COLLECTED | Market closed |
| 13 | Paper-only operation (no broker) | VERIFIED | Code review |
| 14 | CPR retained for rollback | VERIFIED | Code review |

## Mode C Baseline (Reference)

The existing Mode C behavior (one open position per instrument) must remain the reference baseline unless the user explicitly approves a different policy.

## Default: Daily Limit Disabled

Daily trade limit must default to disabled. Requires explicit opt-in.
