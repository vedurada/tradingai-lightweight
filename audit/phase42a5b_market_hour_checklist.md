# Phase 42A.5B Market-Hour Validation Checklist

## Current Status
Current IST time: ~08:30 (market opens 09:15)
Status: PREPARING - waiting for market open

## VM State (Pre-Market)
- nginx: active ✅
- gunicorn: active (4 workers) ✅
- tradingai-api.service: active ✅
- monitor.service: installed (oneshot) ✅
- data-fetcher.service: installed (oneshot) ✅
- crontab: 36 lines (clean) ✅
- DB: 177.73 MB, integrity OK ✅
- price_1m: 34,380 rows ✅
- price_5m: 17,400 rows (stale, pre-market) ✅
- paper_trades: 1188 ✅

## API Endpoints (Pre-Market)
| Endpoint | Status | Notes |
|---|---|---|
| /api/health | 200 | Degraded (outlook stale, expected) |
| /api/price/NIFTY | 200 | STALE (yesterday close) |
| /api/price/BANKNIFTY | 200 | STALE (yesterday close) |
| /api/market | 200 | Data structure present |
| /api/NIFTY | 200 | Has ai_outlook |
| /api/BANKNIFTY | 200 | Has ai_outlook |
| /api/breadth | 200 | ADV=30 DEC=11 UNCH=6 |
| /api/key-levels | 200 | Supports+Resistances |
| /api/strategy/NIFTY | 200 | Strategies available |
| /api/risk/NIFTY | 200 | Risk data available |
| /api/session-timeline | 200 | PRE_MARKET state |
| /api/paper-trades/active | 200 | count:0 |
| /api/trade-qualification | 200 | NO_TRADE (fixed) |
| /api/options/state/NIFTY | 200 | LIVE data (fixed) |
| /api/options/state/BANKNIFTY | 200 | LIVE data (fixed) |
| /data/nifty.json | 200 | 7,132 bytes |
| /data/banknifty.json | 200 | 7,159 bytes |

## Market-Hour Checkpoints (TO LOG)

### 09:15 IST - Market Open
- [ ] data_fetcher_db.py runs via cron → data.log updated
- [ ] price_1m gets new rows with current timestamps
- [ ] /api/price/NIFTY returns FRESH data (age_minutes < 5)
- [ ] /api/market returns LIVE data
- [ ] Today page shows MARKET OPEN
- [ ] price_5m still stale (no completed candle yet)

### 09:20 IST - First 5m Candle
- [ ] aggregate.py runs → price_5m gets first candle
- [ ] /api/price/NIFTY still FRESH
- [ ] generate_json.py regenerates JSON
- [ ] AI outlook may generate (first completed candle trigger)

### 09:30 IST
- [ ] Multiple 5m candles complete
- [ ] price_5m updates with new candles
- [ ] Research collection triggers (monitor.py)

### 10:00, 11:00, 12:00, 13:00, 14:00, 15:00
- [ ] Data freshness maintained (age_minutes < 5)
- [ ] price_5m updates every 15 minutes
- [ ] AI outlooks generated on material changes
- [ ] No 500 errors in any endpoint

### 15:25-15:30 IST - Market Close
- [ ] Final AI outlook generated
- [ ] Session timeline shows MARKET CLOSED
- [ ] Last 5m candle completed

## Validation Criteria
- At least 1 completed market-hour 5m candle flows through pipeline
- All endpoints return 200 (no 500s)
- Data timestamps advance during market hours
- Today page shows live data (not Loading)
- Research tables get populated
- AI call log shows proper triggers
