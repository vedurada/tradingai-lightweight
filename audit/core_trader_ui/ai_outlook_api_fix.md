# AI Outlook API Endpoint Fix — Audit Log

## Issue
`/api/ai-outlook/<symbol>` returned `data_state: UNAVAILABLE` because the `ai_outlooks_5m` table had 0 rows.

## Root Cause
The `ai_outlooks_5m` table is designed to be populated by `OutlookScheduler` (in `outlook_scheduler.py`), which generates AI outlooks every 5 minutes during market hours using `AIOutlookGenerator5m`. However, no cron job, systemd service, or on-demand trigger invokes the scheduler. The `/api/ai-outlook/scheduler` endpoint only does dry-run, not actual storage.

Result: The `/api/ai-outlook/<symbol>` endpoint depends solely on `ai_outlooks_5m` and returns `UNAVAILABLE` because the table is always empty.

## Fix Applied (deployed 2026-09-18)
Modified `/api/ai-outlook/<symbol>` and `/api/ai-outlook/timeline/<symbol>` to fall back to `ai_outlooks` table when `ai_outlooks_5m` is empty.

### Data mapping (ai_outlooks → ai_outlooks_5m schema):
- `outlook.directional_bias` → `bias`
- `outlook.confidence` → `confidence`
- `outlook.market_regime` → `market_regime`
- `outlook.market_summary` → `summary`
- `timestamp` → `generated_at`, `candle_timestamp`, `created_at`
- `outlook.evidence_strength` → `evidence_json`
- Default values for: `model`, `watch_levels_json`, `confirmation_json`, `invalidation_json`, `risk_json`, `trade_state`, `expected_horizon_minutes`, `material_changes_json`

### Changed file:
- `backend/api_server.py`: Added `_ai_outlook_from_legacy()` helper + fallback logic in `api_ai_outlook()` and `api_ai_outlook_timeline()`

## Verification (VM, 2026-09-18 22:03 IST)
| Symbol | data_state | bias | confidence | market_regime | summary |
|--------|-----------|------|------------|---------------|---------|
| NIFTY | DELAYED | BEARISH | 70 | BEARISH | ✓ |
| BANKNIFTY | DELAYED | BEARISH | 70 | BEARISH | ✓ |
| FINNIFTY | DELAYED | NEUTRAL | 0 | UNKNOWN | empty |
| SENSEX | DELAYED | DOWNWARD | 70 | BEARISH | ✓ |

Timeline endpoint: 1294 total outlooks, paginated correctly.

## Remaining (separate task)
- Set up cron job or service to populate `ai_outlooks_5m` during market hours
- Once populated, the fallback will no longer be needed
