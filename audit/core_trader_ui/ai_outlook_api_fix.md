# AI Outlook API Endpoint Fix — Audit Log

## Issue 1 (Primary): /api/ai-outlook/<symbol> returned UNAVAILABLE
- **Cause**: `ai_outlooks_5m` table had 0 rows — OutlookScheduler never invoked
- **Fix**: Added `_ai_outlook_from_legacy()` fallback in `api_server.py` to use `ai_outlooks` table when `ai_outlooks_5m` is empty
- **Deployed**: 2026-09-18 22:00 IST (commit cbb2641)
- **Also fixed**: `/api/ai-outlook/timeline/<symbol>` (same fallback pattern)

## Issue 2 (Today page): "AI outlook error — check API endpoint" displayed
- **Cause**: `regimeText` function called at lines 180/183 but never defined in today/index.html → ReferenceError → catch block
- **Fix**: Added `function regimeText(r){...}` definition to today/index.html (commit a8cadc6)
- **Note**: Same function already existed in indices/nifty.html, indices/banknifty.html, indices/finnifty.html, indices/sensex.html

## Verification (VM, 2026-09-18 22:05 IST)
| Endpoint | Status |
|----------|--------|
| /api/ai-outlook/NIFTY | Returns data: bias=BEARISH, confidence=70 |
| /api/ai-outlook/BANKNIFTY | Returns data: bias=BEARISH, confidence=70 |
| /api/ai-outlook/SENSEX | Returns data: bias=DOWNWARD, confidence=70 |
| /api/ai-outlook/FINNIFTY | Returns data: bias=NEUTRAL, confidence=0 (legacy) |
| /api/ai-outlook/timeline/NIFTY | 1294 outlooks, paginated |
| /api/market-outlook?symbol=NIFTY | Returns valid data |
| today/index.html | regimeText defined, no ReferenceError |

## Remaining
- Set up cron job to populate `ai_outlooks_5m` during market hours
