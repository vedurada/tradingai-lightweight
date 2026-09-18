# Phase 42A.4B — Production Data Pipeline Trace

**Date**: 2026-09-18
**Phase 41**: FROZEN

---

## Complete Pipeline Trace

```text
Yahoo Finance / NSE API
    ↓
data_fetcher_db.py (cron: * 9-15 * * 1-5 = every minute during market hours)
    ↓ [store_price_data → INSERT OR REPLACE INTO price_1m]
    ↓ [store_vix_data → INSERT OR REPLACE INTO vix_data]
    ↓ [store_option_chains → INSERT OR REPLACE INTO option_chain]
    ↓ [live_quotes → INSERT OR REPLACE INTO live_quotes]
price_1m (minute candles) ← LIVE data
live_quotes (live NSE quotes) ← LIVE data
price_1d (daily candles)
    ↓
aggregate.py (cron: */15 9-15 * * 1-5 = every 15 min during market hours)
    ↓ [INSERT OR REPLACE INTO price_5m]
    ↓ [INSERT OR REPLACE INTO price_15m]
price_5m (5-min candles)
price_15m (15-min candles)
    ↓
API server (gunicorn, 127.0.0.1:8000)
    ↓
Frontend (phase41.js, api.js, live-blink.js, etc.)
    ↓
API calls from frontend:
  /api/market (ticker)
  /api/price/NIFTY (single price)
  /api/<symbol> (generic)
  /api/market-outlook (AI outlook)
  /api/market-evidence/<symbol> (evidence)
  /api/trade-qualification (POST, qualification)
  /api/strategy/<symbol> (strategy)
  /api/risk/<symbol> (risk)
  /api/key-levels (key levels)
  /api/intraday-conditions (intraday conditions)
  /api/options/state/<symbol> (options)
  /api/breadth (breadth)
  /api/index-breadth (index breadth)
```

## Where Pipeline Currently Stops

| Stage | Status | Notes |
|-------|--------|-------|
| Data fetch | STOPPED | data_fetcher_db.py cron exists but only runs 09:15-15:30 |
| 5m aggregation | STOPPED | aggregate.py cron exists but only runs 09:15-15:30 |
| JSON generation | BROKEN | generate_json.py has NO cron job |
| Data freshness | STALE | price_1m age: 630+ minutes (pre-market) |
| Research collection | MISSING | No trigger mechanism |
| API | OPERATIONAL | Degraded (stale data) |
| Frontend | STALE | Shows stale/pre-market data |

## Research Collection Gap

ResearchCollector has methods (record_setup_identity, record_reentry, record_ai_call, record_outcome, record_data_health, update_manifest) but NOTHING calls them automatically.

- No cron trigger for research collection
- No monitor.py integration (added in this phase)
- No confirmed connection between 5m candle completion and collect() methods
- Research tables: 0 records (expected pre-collection)
