# Phase 5.17 — Live Paper Observation Runbook

## Required Session Dates

- Minimum 5 trading sessions (Mon-Fri)
- Preferred: 10+ sessions for statistical significance
- Must include both trending and range-bound days

## Observation Window

- Pre-market: 09:00-09:15 (setup verification)
- Market hours: 09:15-15:30 (active observation)
- Post-market: 15:30-16:00 (reconciliation)

## Measurements Required

1. **Candle timestamp** — interval start time (e.g., 09:15:00)
2. **Observation timestamp** — when first seen in DB (ingested_at)
3. **Signal timestamp** — when 3-bar alignment detected
4. **Entry eligibility** — _entry_time_guard result (ok/expired/failed)
5. **Signal age** — now - signal_time
6. **Entry price availability** — first time entry candle open is observable
7. **Rejected stale signals** — count and reasons
8. **Duplicate signals** — count and dedup verification
9. **Restart scenarios** — recovery behavior
10. **Open trade monitoring** — exit evaluation and closure
11. **API/dashboard consistency** — compare API output with DB state
12. **Telegram consistency** — alerts match persisted trades

## Evidence Retention

- Save all API responses as JSON files
- Save paper_scalp_live.py logs
- Save tg_alerts.py logs
- Record DB row counts before/after each session
- Save signal and trade snapshots

## Failure Handling

- Stop if any production write outside expected paths
- Stop if stale data accepted for trade creation
- Stop if duplicate trades created
- Stop if DB integrity fails
- Document all stop events

## Session-End Reconciliation

1. Count signals detected vs trades created
2. Count rejected signals by reason
3. Verify no duplicate trades
4. Verify DB integrity
5. Compare API output with DB state
6. Verify Telegram alerts match trades
