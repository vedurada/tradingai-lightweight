# VIX Provenance — Phase 42A.9

## VIX Display Surfaces on TradingAI.in

### 1. /api/vix (Direct API)
- **Source**: SQLite database → vix table
- **Endpoint**: `/api/vix`
- **Current Value**: 11.39 (as of 2026-09-18T16:40:23Z = 2026-09-18 22:10 IST)
- **Data State**: STALE (age_minutes: 724, threshold: 60)
- **Data Quality**: STALE
- **Freshness**: Last Friday close (market closed Saturday)
- **Accessed by**: index.html (inline script), index-charts.js, strategies.html

### 2. /api/NIFTY (Includes VIX context)
- **Source**: Same database, vix table via NIFTY endpoint
- **Endpoint**: `/api/NIFTY`
- **VIX included in**: NIFTY overview data
- **Freshness**: Same as /api/vix

### 3. Strategies Page
- **Display**: VIX regime classification
- **Source**: /api/vix via external JS (vix.js) or inline JS
- **Label**: VIX regime (BEARISH/SIDEWAYS/BULLISH based on threshold)

### 4. Options PCR Page
- **Display**: VIX in context of options data
- **Source**: /api/vix or /api/options/state/NIFTY

### Consistency Check
- All VIX values come from the SAME database row (vix table)
- Timestamp is consistent: 2026-09-18T16:40:23Z across all surfaces
- No contradictory VIX values found across surfaces
- All show STALE state (Saturday market closed)

### Status
VIX provenance is CONSISTENT across all surfaces. All VIX values trace to the same source with the same timestamp. ✅

### Limitation
Live VIX (intraday) NOT available on Saturday. All VIX readings are from Friday 2026-09-18 close. This is expected — no new VIX data is generated when market is closed.

### Before Fix (404 assets)
VIX displays could not update because external JS was 404. VIX sections showed hardcoded or stale HTML text. After fix, VIX updates dynamically via JS.