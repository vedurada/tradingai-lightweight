# Final Deployment Manifest

## Phase 42A.10C — Production Validation

## VM State
```text
VM: webserver (129.159.224.81)
Branch: main
Commit: 20450f0d (18 commits ahead of origin/main)
Uptime: 10 days
```

## Deployed Fixes (from Phase 42A.10B)
```text
1. /var/www/tradingai.in/html/assets/js/api.js — isMarketHours SyntaxError fixed
2. /var/www/tradingai.in/html/index.html — render() function defined
```

## Services
```text
nginx: active
gunicorn: active (3 workers, 127.0.0.1:8000)
DB: SQLite at /opt/tradingai/database/tradingai.db (WAL mode)
```

## Monitored Pages
- /
- /today/index.html
- /indices/nifty.html
- /indices/banknifty.html
- /indices/sensex.html
- /indices/finnifty.html
- /strategies.html
- /options/pcr.html
- /tools/backtest.html

## Monitored APIs
See api_json_validation.md for full list.

## Backup
```text
Path: /opt/tradingai/backups/tradingai_pre_42a10c_20260919_110833.db
Size: 269MB
Integrity: OK
```

## Audit Artifacts
```text
audit/phase42a10c/production_pre_market_baseline.md
audit/phase42a10c/last_valid_to_live_validation.md
audit/phase42a10c/ai_scheduler_validation.md
audit/phase42a10c/api_json_validation.md
audit/phase42a10c/production_db_integrity.md
audit/phase42a10c/errors_and_repairs.md
audit/phase42a10c/final_deployment_manifest.md
audit/phase42a10c/phase42a10c_validation_report.md (to be completed)
```
