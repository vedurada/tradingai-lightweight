# Phase 42A.5 Frontend Data Flow

## Data Flow Architecture

### Two Data Pathways

#### Pathway 1: /data/*.json (Static File Serving)
```
generate_json.py → /opt/tradingai/data/*.json
    → symlink → /var/www/tradingai.in/html/data/*.json
        → nginx serves at https://tradingai.in/data/*.json
            → static/js/api.js fetches via fetch('/data/{path}.json')
```
Used by: Pages that load static/js/api.js

#### Pathway 2: /api/* (Dynamic API)
```
SQLite database → api_server.py (Flask/Gunicorn)
    → nginx reverse proxy at https://tradingai.in/api/*
        → Inline JavaScript in HTML pages
```
Used by: today/index.html, indices/nifty.html, indices/banknifty.html (inline scripts)

## Today Page Data Flow (Detail)

```
1. Browser loads /today/index.html
2. Inline script starts on DOMContentLoaded
3. loadTodayData() executes:
   a. fetchJSON('market') → /api/market
      - Checks m.instruments for each symbol
      - Populates price/change elements
   b. fetchJSON('market-outlook?symbol=NIFTY') → /api/market-outlook
      - Populates AI outlook section
   c. fetchJSON('key-levels?symbol=NIFTY') → /api/key-levels
      - Populates support/resistance levels
   d. fetchJSON('options/state/NIFTY') → /api/options/state/NIFTY
      - Populates PCR, OI, Max Pain
      - On error: shows ERROR (try/catch)
   e. fetchJSON('breadth') → /api/breadth
      - Populates advance/decline/unchanged
   f. fetchJSON('intraday-conditions?symbol=NIFTY') → /api/intraday-conditions
      - Populates bullish/bearish/no_trade
   g. fetchJSON('strategy/NIFTY') → /api/strategy/NIFTY
      - Populates strategy cards
   h. fetchJSON('risk/NIFTY') → /api/risk/NIFTY
      - Populates risk data
   i. fetchJSON('session-timeline') → /api/session-timeline
      - Shows PRE-MARKET/MARKET_OPEN/MARKET_CLOSED
   j. fetchJSON('market-evidence/NIFTY') → /api/market-evidence
      - Populates evidence groups
   k. fetchJSON('trade-qualification', POST) → /api/trade-qualification
      - Shows TRADE/WAIT/NO_TRADE
   l. fetchJSON('paper-trades/active') → /api/paper-trades/active
      - Shows paper trade status
4. setInterval(loadTodayData, 30000) - refresh every 30 seconds
```

## Field Mapping Verification

### Frontend Expects → API Returns
- `m.instruments.NIFTY.quote.price` → ✅ `/api/market` returns this
- `m.instruments.NIFTY.quote.change` → ✅ `/api/market` returns this
- `o.outlook.bias.label` → ✅ `/api/market-outlook` returns this
- `kl.supports` → ✅ `/api/key-levels` returns this
- `kl.resistances` → ✅ `/api/key-levels` returns this
- `r.max_risk` → ✅ `/api/risk/NIFTY` returns this
- `str.strategies` → ✅ `/api/strategy/NIFTY` returns this
- `pt.data.active_trades` → ✅ `/api/paper-trades/active` returns this
- `ev.data.groups` → ✅ `/api/market-evidence/NIFTY` returns null (pre-market)
- `qual.data.trade_status` → ⚠️ `/api/trade-qualification` returns 500

## Independent Failure Handling
Each component has try/catch:
- Options failure → Does NOT block market data ✅
- Qualification failure → Does NOT block market data ✅
- Evidence failure → Does NOT block market data ✅
- AI outlook failure → Shows UNAVAILABLE ✅

## /data/*.json Serving (New)
After fix, /data/*.json files are served via nginx symlink:
- /data/nifty.json → 200 OK (7KB)
- /data/banknifty.json → 200 OK (7KB)
- /data/sensex.json → 200 OK (7KB)
- /data/finnifty.json → 200 OK (4.5KB)
