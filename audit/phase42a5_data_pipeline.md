# Phase 42A.5 Data Pipeline Trace

## Pipeline Architecture

```
Yahoo/NSE
   ↓
data_fetcher_db.py (cron: every 1 min, 9-15 IST)
   ↓
price_1m (SQLite)
   ↓
aggregate.py (cron: every 15 min, 9-15 IST)
   ↓
price_5m (SQLite)
   ↓
generate_json.py (cron: every 15 min, 9-15 IST)
   ↓
/data/*.json (nginx served)
   ↓
static/js/api.js → fetch /data/*.json
   ↓
Browser

Also:
API endpoints (/api/*) served by gunicorn on 127.0.0.1:8000
   ↓
nginx reverse proxy
   ↓
Browser
```

## BANKNIFTY Pipeline Stage Analysis

| Stage | Source | Latest Timestamp | Age | Status | Notes |
|---|---|---|---|---|---|
| Market source | Yahoo Finance | 2026-09-18 02:31 UTC | ~29 min | FRESH | NSE quotes: BANKNIFTY=56055.75 |
| price_1m | data_fetcher_db.py | 2026-09-18 02:31 UTC | ~29 min | FRESH | 34,380 rows |
| price_5m | aggregate.py | Pre-market | STALE | STALE | Will update at market open |
| /data/banknifty.json | generate_json.py | 2026-09-18 07:59 UTC | 4 min | FRESH | 7,159 bytes |
| /api/price/BANKNIFTY | API | 2026-09-17 15:31 | STALE | STALE | Yesterday's close |
| /api/market | API | 2026-09-17 | STALE | STALE | Yesterday's data |

## NIFTY Pipeline Stage Analysis

| Stage | Source | Latest Timestamp | Age | Status | Notes |
|---|---|---|---|---|---|
| Market source | Yahoo Finance | 2026-09-18 02:31 UTC | ~29 min | FRESH | NSE quotes: NIFTY=23270.6 |
| price_1m | data_fetcher_db.py | 2026-09-18 02:31 UTC | ~29 min | FRESH | 34,380 rows |
| price_5m | aggregate.py | Pre-market | STALE | STALE | Will update at market open |
| /data/nifty.json | generate_json.py | 2026-09-18 07:59 UTC | 4 min | FRESH | 7,132 bytes |
| /api/price/NIFTY | API | 2026-09-17 15:31 | STALE | STALE | Yesterday's close |
| /api/market | API | 2026-09-17 | STALE | STALE | Yesterday's data |

## First Broken Stage
**generate_json.py line 64** - `regime_engine.evaluate(price=...)` called with wrong arguments.

Every instrument generation crashed at this point, preventing any JSON files from being created.

## Secondary Broken Stage
**Crontab** - aggregate.py syntax error on line 56 (`echo` concatenated with next cron entry). data_fetcher_db.py and monitor.py cron entries existed but never executed.
