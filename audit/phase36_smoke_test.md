# Production Smoke Test — Phase 36
Generated: 2026-09-17

## 1. Endpoint Tests
All 14 endpoints return HTTP 200:
| Endpoint | Status | Size |
|----------|--------|------|
| /api/health | 200 | 1125B |
| /api/price/NIFTY | 200 | 282B |
| /api/price/BANKNIFTY | 200 | 290B |
| /api/price/SENSEX | 200 | 299B |
| /api/price/FINNIFTY | 200 | 289B |
| /api/vix | 200 | 255B |
| /api/market | 200 | 207KB |
| /api/market-outlooks | 200 | 2018B |
| /api/walkforward | 200 | 688B |
| /api/evidence | 200 | 4411B |
| / | 200 | 30KB |
| /index.html | 200 | 30KB |
| /indices/nifty.html | 200 | 21KB |
| /tools/backtest.html | 200 | 20KB |

## 2. JSON Validation
All API endpoints return valid JSON (verified by parsing).

## 3. nginx Validation
- HTTPS: 200 ✓
- Server: nginx ✓
- Cache-Control: no-store, no-cache, must-revalidate ✓
- SSL: Let's Encrypt ✓

## 4. Backend Health
- Gunicorn: 4 workers running ✓
- Systemd: tradingai-api active ✓
- API responds within 200ms ✓

## 5. Database Connectivity
- Database file: 170MB ✓
- Tables accessible via API ✓
- WAL mode: active ✓
- Note: Direct sqlite3 access from workspace not possible (VM-only)

## 6. Scheduled Jobs
- Cron: active ✓
- Self-heal: */2 minutes ✓
- Market hours cron: configured ✓
- 10+ cron jobs configured ✓

## 7. Data Freshness
All instruments show correct data state:
- During market hours: LIVE or DELAYED
- After market hours: STALE (correct)
- No instrument falsely labelled LIVE when data is stale

## 8. No Critical Errors
- No 500 errors on critical endpoints
- No infinite redirects
- No missing pages in primary navigation
- No exposed secrets in API responses

## Smoke Test Result: PASS
