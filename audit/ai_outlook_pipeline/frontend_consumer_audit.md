# Frontend Consumer Audit

Date: 2026-09-18

## All Pages That Consume AI Outlook Data

### 1. /today/index.html (Primary Trader Page)

**AI Outlook Source**: `/api/ai-outlook/NIFTY` (and other index symbols)
**How**: The page loads AI outlook data to display in the "AI Outlook" section of the terminal.

**Current State**: After fix (commit a8cadc6 — regimeText added), page renders:
- Regime badge (BEARISH/BULLISH/RANGE)
- Confidence level
- "RANGE — 64% confidence" style text
- No ReferenceError

**Known Issue** (from PHASE 29 audit): `/today/index.html` calls 3 nonexistent endpoints:
- `/api/key-levels` — NOT FOUND
- `/api/intraday-conditions` — NOT FOUND
- `/api/risk/NIFTY` — NOT FOUND

**Frontend expectation**: Expects `{outlook: {...}}` wrapper from `/api/market-outlook`, but `/api/ai-outlook/<symbol>` returns `{success: true, data: {instrument, current, previous, ...}}` — different structure.

### 2. /indices/nifty.html (NIFTY Index Page)

**AI Outlook Source**: `/api/NIFTY` (via static/js/nifty.js)
**Data field**: `data.ai_outlook` (from /api/<symbol>)
**Current State**: Works — displays AI outlook narrative from ai_outlooks table

### 3. /indices/banknifty.html (BANKNIFTY Index Page)

**AI Outlook Source**: `/api/BANKNIFTY` (via static/js/banknifty.js)
**Current State**: Works — same pattern as NIFTY

### 4. /indices/finnifty.html (FINNIFTY Index Page)

**AI Outlook Source**: `/api/FINNIFTY`
**Current State**: Works

### 5. /indices/sensex.html (SENSEX Index Page)

**AI Outlook Source**: `/api/SENSEX`
**Current State**: Works

### 6. / (Home Page)

**AI Outlook Source**: `/api/market-outlook?symbol=NIFTY`
**Note**: Home page was found to be publicly reachable despite 301 config (PHASE 29 finding)

### 7. /options/index.html (Options Page)

**AI Outlook Source**: None directly — uses options-specific data
**Note**: FINNIFTY options marked as historical only (NOT available as live product)

### 8. /ai-track-record.html (AI Track Record)

**AI Outlook Source**: None — shows historical AI performance
**Created**: This session (new page)

### 9. /research/index.html (Research Page)

**AI Outlook Source**: None — research/analysis page
**Created**: This session (new page)

## Shared JavaScript Files Using AI Outlook

### static/js/ai-outlook.js
**Purpose**: Shared AI outlook dashboard JS component
**API calls**: 
- `/api/market-outlook?symbol=X` — gets outlook data
- `/api/<symbol>` — gets per-symbol data with `data.ai_outlook`

### static/js/nifty.js, banknifty.js, finnifty.js, sensex.js
**Purpose**: Per-index page JavaScript
**API calls**: `/api/<symbol>` for data including `ai_outlook` field
**Pattern**: `data.ai_outlook` is used from the `/api/<symbol>` response

## Frontend Data States

| Data State | Meaning | Display |
|------------|---------|---------|
| LIVE | Real-time 5m data available | Green, fresh |
| DELAYED | Market closed, historical data | Yellow, stale |
| UNAVAILABLE | No data at all | Red, unavailable |
| NO_OUTLOOK | No outlook generated yet | Red, no outlook |
| STALE | Outlook older than 30 min | Warning |
| AGING | Outlook older than 15 min | Warning |
| FRESH | Outlook newer than 15 min | Good |

## Cross-Page AI Outlook Consistency Issues

| Issue | Description |
|-------|-------------|
| Today page uses /api/ai-outlook/NIFTY | Returns {data: {current, previous, timeline}} structure |
| Index pages use /api/NIFTY | Returns {data: {..., ai_outlook: {...}}} structure |
| Market outlook uses /api/market-outlook | Returns {outlook: {...}, ...} structure |
| 5m endpoints use /api/outlook/5m/latest | Returns {data: {current_state, material_change, ...}} structure |
| **No consistent schema** | Each endpoint returns different structure |

## Frontend Loading/Empty States

**Issue (from PHASE 29 audit)**: When data unavailable, many pages show "Loading" state indefinitely because the 5-minute pipeline is broken.
