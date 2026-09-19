# Phase 42A.10C — Pre-Market Baseline (Saturday 2026-09-19)

## VM Inspection
```text
hostname: webserver
date: 2026-09-19 11:07 IST
UTC: 2026-09-19T05:37Z
uptime: 10 days, 16:46
VM commit: 20450f0d (main, 18 commits ahead of origin/main)
nginx: active
gunicorn: active (3 workers on 127.0.0.1:8000)
DB size: 269MB
DB integrity: OK
```

## Production Backup
```text
backup path: /opt/tradingai/backups/tradingai_pre_42a10c_20260919_110833.db
backup size: 269MB
integrity: OK
```

## Pre-Market Baseline (Friday Last-Valid)
```text
NIFTY:       23,346.40 (STALE, yfinance, 2026-09-18)
BANKNIFTY:   56,358.70 (STALE, 2026-09-18)
VIX:         11.39 (STALE, 2026-09-18 16:40 UTC)
```

## Key Table Counts
```text
paper_trades: 1188
ai_outlooks: 39148
ai_outlooks_5m: 0
market_snapshots_5m: 2
market_evidence_5m: 1
pre_market_scenarios: 0
scenario_events: 0
scenario_outcomes: 0
research_ai_call_log: 0
research_manifest: 1
research_outcome_tracking: 61672
research_data_health: 219
market_candles: 54274
market_outlooks: 206 (June 18 - Sep 18)
```

## Cron Schedulers
```text
AI Outlook: 30 9 * * 1-5 (NIFTY, BANKNIFTY, FINNIFTY, SENSEX)
Monitor: */5 9-15 * * 1-5
Aggregate: */15 9-15 * * 1-5
Health: */2 * * * *
```

## Expected Monday Behavior
- Friday STALE data shows as "LAST VALID" until new data arrives
- At 09:15 IST, market opens, new data arrives
- Last-valid → LIVE transition: new data replaces cached data
- New 5m snapshots and evidence records created
- AI outlook scheduler runs at 09:30 IST
