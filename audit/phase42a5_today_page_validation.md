# Phase 42A.5 Today Page Validation

## Page Structure
- URL: https://tradingai.in/today/index.html
- Size: ~25,583 bytes
- Entry: Inline JavaScript (18KB) with data fetching logic
- External scripts: keep-scroll.js, live-blink.js, consent.js

## Data Fetching (Inline Script)
The today page uses inline JavaScript that calls `/api/` endpoints (NOT `/data/*.json`):

| Component | Endpoint | Method | Expected Response |
|---|---|---|---|
| Market prices | `/api/market` | GET | {instruments: {NIFTY: {quote: {price, change}}}} |
| AI Outlook | `/api/market-outlook?symbol=NIFTY` | GET | {outlook: {bias, confidence, ...}} |
| Key Levels | `/api/key-levels?symbol=NIFTY` | GET | {supports, resistances, opening_range} |
| Options | `/api/options/state/NIFTY` | GET | {pcr, oi, max_pain, expected_move} |
| Breadth | `/api/breadth` | GET | {advances, declines, unchanged} |
| Intraday | `/api/intraday-conditions?symbol=NIFTY` | GET | {bullish, bearish, no_trade} |
| Strategy | `/api/strategy/NIFTY` | GET | {strategies: [{name, entry, risk}]} |
| Risk | `/api/risk/NIFTY` | GET | {max_risk, recommended_size, warnings} |
| Timeline | `/api/session-timeline` | GET | {pre_market, open_market, trading_hours, close} |
| Evidence | `/api/market-evidence/NIFTY` | GET | {data: {evidence: {groups: {...}}}} |
| Qualification | `/api/trade-qualification` | POST | {data: {trade_status, checks}} |
| Paper Trade | `/api/paper-trades/active` | GET | {data: {active_trades, count}} |

## Current Rendering (Pre-Market)
| Component | Status | Notes |
|---|---|---|
| Session Status | PRE-OPEN | Correct (market opens 09:15 IST) |
| NIFTY Price | Loading... | Will populate when /api/market returns data |
| BankNIFTY Price | Loading... | Will populate when /api/market returns data |
| AI Outlook | Loading... | Has stale data from API |
| Key Levels | Loading... | Will populate from API |
| Options | Loading... | Options endpoint returns 500 (known issue) |
| Breadth | Loading... | Will populate from API |
| Strategy | Loading... | Will populate from API |
| Risk | Loading... | Will populate from API |
| Timeline | Has PRE-MARKET text | Working ✅ |
| Evidence | Loading... | NO_DATA pre-market (expected) |
| Qualification | Loading... | Endpoint returns 500 (known issue) |
| Paper Trade | No active paper trade | Working ✅ |

## API Response Format Match
- /api/market returns instruments with quote.price ✅ (matches frontend expectations)
- /api/market-outlook returns outlook with bias.label ✅
- /api/key-levels returns supports/resistances ✅
- /api/risk/NIFTY returns max_risk/warnings ✅
- /api/strategy/NIFTY returns strategies array ✅

## Known Issues
1. /api/options/state/NIFTY returns 500 → shows ERROR in frontend (handled by try/catch)
2. /api/trade-qualification returns 500 → shows ERROR in frontend (handled by try/catch)
3. /api/market-evidence/NIFTY returns NO_DATA → shows UNAVAILABLE (handled)
4. Price data is stale (yesterday's close) → will be fresh after data_fetcher_db.py runs at market open

## Pre-Market Display
Page correctly shows PRE-OPEN status with "86 minutes until market open" ✅
Session status uses canonical PRE_MARKET/MARKET_OPEN/MARKET_CLOSED states ✅
