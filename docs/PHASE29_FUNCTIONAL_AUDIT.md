# PHASE 29 — Production Page Functional Audit

Created: 16 September 2026
Workspace baseline: f8b6be1
Protected baseline: v2b5583a-baseline

Purpose: For every planned page, document what should show, what currently shows, classify each component, trace failures to source, and create a prioritized fix list.

Method: Static HTML analysis + user's public inspection findings + API endpoint tracing.
Limitation: Browser/DOM rendering verified only where noted. Most dynamic behavior requires runtime verification.

---

## Classification Key

| Status | Meaning |
|--------|---------|
| ✅ WORKING | Shows correct value + timestamp + source |
| 🟠 PARTIAL | Some components working, others not |
| 🔴 FAILING | Core functionality not delivered |
| ⚪ NOT TESTABLE | Cannot verify without VM/browser |
| — | Data unavailable in workspace analysis |

## Failure Source Tracing

| Source | Meaning |
|--------|---------|
| FE | Frontend HTML/CSS/JS bug |
| JS | JavaScript execution failure |
| API | API endpoint missing/unreachable |
| JSON | Invalid JSON response |
| PY | Python backend bug |
| DB | SQLite data missing/empty |
| CRON | Cron job not running |
| FEED | Market data feed unavailable |
| NGINX | Nginx configuration issue |

---

## P0 — Core Trading Pages

### / (Homepage)

| Component | Plan | Current (public) | Status | Source |
|-----------|------|-------------------|--------|--------|
| Market Status | Live values for NIFTY/BANKNIFTY/SENSEX/FINNIFTY | — for all 4 indices | 🔴 FAILING | JS → API |
| Market Status | Last updated timestamp | "Last refreshed: —" | 🔴 FAILING | JS |
| INDIA VIX | Live VIX value | Not mentioned in public audit | ⚪ NOT TESTABLE | JS → API |
| AI Market Outlook | Direction, evidence, reasoning | "Loading AI Market Outlook…" | 🔴 FAILING | JS → API |
| Advance/Decline | Breadth data | "Loading breadth data…" | 🔴 FAILING | JS → API |
| Options Intelligence | PCR, Max Pain, OI | "—" values, "Data unavailable" fallback | 🟠 PARTIAL | JS → API |
| Timestamp mechanism | Data as of HH:MM:SS IST | Code exists, not working | FE | JS → API |
| Canonical tag | / | Set correctly | ✅ WORKING | — |
| SEO metadata | Title, description, OG | Present | ✅ WORKING | — |

**Failure trace**: FE → JS → API → JSON → PY → DB (data exists per AGENTS.md, not flowing to DOM)
**Key finding**: Homepage describes itself as "live AI Market Outlook" but exposes no live data publicly.
**Immediate action**: Verify /api/market, /api/price/NIFTY, /api/breadth endpoints return data on VM.

---

### /today/index.html (Today's Trading Terminal)

| Component | Plan | Current | Status | Source |
|-----------|------|---------|--------|--------|
| Session status | Date, open/closed, last update | Redesigned — explicit loading state | ⚪ NOT TESTABLE | FE → API |
| Market Snapshot | NIFTY/BANKNIFTY/SENSEX/FINNIFTY/VIX values | Redesigned — loading state | ⚪ NOT TESTABLE | FE → API |
| AI Outlook | Regime, direction, confidence, explanation | Redesigned — loading state | ⚪ NOT TESTABLE | FE → API |
| Key Levels | Support, resistance, opening range | Redesigned — loading state | ⚪ NOT TESTABLE | FE → API |
| Options Intelligence | PCR, OI, Max Pain, Expected Move | Redesigned — loading state | ⚪ NOT TESTABLE | FE → API |
| Market Breadth | Advances, declines, unchanged | Redesigned — loading state | ⚪ NOT TESTABLE | FE → API |
| Intraday Conditions | Bullish, bearish, no-trade | Redesigned — loading state | ⚪ NOT TESTABLE | FE → API |
| AI Strategy | Strategy candidates | Redesigned — loading state | ⚪ NOT TESTABLE | FE → API |
| Risk Management | Risk guidance | Redesigned — loading state | ⚪ NOT TESTABLE | FE → API |
| Session Timeline | Timeline | Redesigned — loading state | ⚪ NOT TESTABLE | FE → API |

**Previous state**: Was exposing "Loading today's session…" (public audit)
**Current state**: Restructured with explicit per-section loading states. Runtime unverified.
**Immediate action**: Browser-test to confirm sections transition from Loading to data.
**Key finding**: Restructured, but runtime behavior unknown without browser.

### today/index.html API chain (10 sequential calls)

`loadTodayData()` executes each section independently (try/catch). One failure does not block others, but ALL are guarded by `fetchJSON` returning null on error.

| # | Section | API endpoint | Backend route | Status if fails |
|---|---------|-------------|--------------|-----------------|
| 1 | Session Status | Inline Date check | None | Works |
| 2 | Market Snapshot | `fetchJSON('market')` | `/api/market` | Prices show Loading… |
| 3 | AI Outlook | `fetchJSON('market-outlook?symbol=NIFTY')` | `/api/market-outlook` | **Loading forever** (o.outlook undefined — structure mismatch) |
| 4 | Key Levels | `fetchJSON('key-levels?symbol=NIFTY')` | `/api/key-levels` | **NOT FOUND in api_server.py** |
| 5 | Options | `fetchJSON('options/state/NIFTY')` | `/api/options/state/NIFTY` | Exists, may return data |
| 6 | Breadth | `fetchJSON('breadth')` | `/api/breadth` | Exists, may return data |
| 7 | Intraday Conditions | `fetchJSON('intraday-conditions?symbol=NIFTY')` | `/api/intraday-conditions` | **NOT FOUND in api_server.py** |
| 8 | Strategy | `fetchJSON('strategy/NIFTY')` | `/api/strategy/NIFTY` | Exists, may return data |
| 9 | Risk | `fetchJSON('risk/NIFTY')` | `/api/risk/NIFTY` | **NOT FOUND in api_server.py** |
| 10 | Timeline | `fetchJSON('session-timeline')` | `/api/session-timeline` | **NOT FOUND in api_server.py** |

### Confirmed issues in /today/index.html

- **3 missing endpoints**: `/api/key-levels`, `/api/intraday-conditions`, `/api/risk/NIFTY` — Flask returns 404 → section always Loading…
- **1 structure mismatch**: `/api/market-outlook` returns raw `{bias, regime, ...}` but today expects `{outlook: {bias, regime, ...}}` → AI Outlook section always Loading…
- **4 sections likely working**: Session (inline), Market Snapshot (`/api/market`), Options (`/api/options/state/NIFTY`), Breadth (`/api/breadth`), Strategy (`/api/strategy/NIFTY`) — IF API running

**Bottom line**: Today terminal needs minimum 4 backend fixes OR frontend changes to match existing endpoints.

---

### /indices/nifty.html (NIFTY Deep Dive)

| Component | Plan | Current | Status | Source |
|-----------|------|---------|--------|--------|
| NIFTY 50 Spot | Price + change | Redesigned — loading state | ⚪ NOT TESTABLE | FE → API |
| NIFTY 50 Change | Change % | Redesigned — loading state | ⚪ NOT TESTABLE | FE → API |
| VIX | Current VIX | Redesigned — loading state | ⚪ NOT TESTABLE | FE → API |
| Market Regime | Regime + confidence | Redesigned — loading state | ⚪ NOT TESTABLE | FE → API |
| Technical Structure | VWAP, EMA, RSI, MACD, ADX, CPR | Redesigned — loading state | ⚪ NOT TESTABLE | FE → API |
| Key Levels | Support, Resistance, Opening Range | Redesigned — loading state | ⚪ NOT TESTABLE | FE → API |
| Options Intelligence | PCR, OI, Call Wall, Put Wall, Max Pain, Expected Move | Redesigned — loading state | ⚪ NOT TESTABLE | FE → API |
| Intraday Conditions | Bullish, Bearish, No-trade | Redesigned — loading state | ⚪ NOT TESTABLE | FE → API |
| AI Strategy | Structure, entry, risk, target, invalidation | Redesigned — loading state | ⚪ NOT TESTABLE | FE → API |
| Public accessibility | Crawler-reachable | Not reliably retrievable | 🔴 FAILING | NGINX |

**Immediate action**: Verify page is accessible via nginx. Check if /api/ endpoints are reachable from browser context.
**Key finding**: HTML structure now matches plan, but runtime data flow unverified.

---

### /indices/banknifty.html, /indices/finnifty.html, /indices/sensex.html

| Page | Current | Status | Source |
|------|---------|--------|--------|
| BANKNIFTY | Same template as NIFTY — structural parity assumed | ⚪ NOT TESTABLE | FE → API |
| FINNIFTY | Same template as NIFTY — structural parity assumed | ⚪ NOT TESTABLE | FE → API |
| SENSEX | Same template as NIFTY — structural parity assumed | ⚪ NOT TESTABLE | FE → API |

**Immediate action**: Apply same browser test as NIFTY. Verify all 4 index pages accessible via nginx.

---

## P1 — Strategy & Market Pages

### /strategies.html (Strategy Engine)

| Component | Plan | Current | Status | Source |
|-----------|------|---------|--------|--------|
| Today's Market Context | Market data | Present | ✅ WORKING | Static |
| Market Regime | Regime indicator | Present | ✅ WORKING | Static |
| Options Intelligence | PCR/OI/Max Pain | Present | ✅ WORKING | Static |
| Strategy Cards | Buy CE, Bull Call, etc. | Present | ✅ WORKING | Static |
| AI Strategy Analysis | Strategy analysis from data | "AI STRATEGY ANALYSIS = Loading…" | 🔴 FAILING | JS → API |
| Strategy Performance | Performance metrics | "STRATEGY PERFORMANCE = Loading…" | 🔴 FAILING | JS → API |
| Strategy Comparison | Comparison table | Present | ✅ WORKING | Static |
| Build This Strategy | Link to builder | Present | ✅ WORKING | Static |

**Failure trace**: JS → API endpoint for strategy analysis/performance → JSON → PY → DB
**Immediate action**: Identify which API endpoints power Strategy Analysis and Performance. Verify they return data.

---

### /market.html (Market Overview)

| Component | Plan | Current | Status | Source |
|-----------|------|---------|--------|--------|
| Market Overview | Header/description | Present | ✅ WORKING | Static |
| Index Grid | All tracked indices | "Loading market pulse…" (was) → restructured | ⚪ NOT TESTABLE | JS → API |
| Market Breadth | Breadth data | Redesigned — loading state | ⚪ NOT TESTABLE | FE → API |
| Technical Snapshot | VWAP/RSI/ADX/MACD | Redesigned — loading state | ⚪ NOT TESTABLE | FE → API |
| Market Regime | Regime classification | Redesigned — loading state | ⚪ NOT TESTABLE | FE → API |
| Index Deep Dives | Links to NIFTY/BANKNIFTY/etc | Present | ✅ WORKING | Static |

**Immediate action**: Browser-test index grid population. Verify loadMarket() function reaches API endpoints.

---

### /scanner.html (Scanner)

| Component | Plan | Current | Status | Source |
|-----------|------|---------|--------|--------|
| Scanner header | Header | Present | ✅ WORKING | Static |
| Filters | Bullish/Bearish/Range/Breakout/etc | Present | ✅ WORKING | Static |
| Market Regime | Regime indicator | Present | ✅ WORKING | Static |
| Stock Results | Stock list | "Loading…" | 🔴 FAILING | JS → API |
| Stock Detail | Individual detail | Not applicable | — | — |
| Secondary positioning | Visually secondary | Needs verification | ⚪ NOT TESTABLE | FE |

**Immediate action**: Identify scanner API endpoint. Verify data exists.

---

## P2 — Tools & Supporting Pages

### /strategy-builder.html (Strategy Builder)

| Component | Plan | Current | Status | Source |
|-----------|------|---------|--------|--------|
| Instrument | Index selection | Present | ✅ WORKING | Static |
| Template | Template selection | Present | ✅ WORKING | Static |
| Payoff calculator | Payoff diagram | Present | ✅ WORKING | Static |
| Risk metrics | Max profit/loss, breakeven | Present | ✅ WORKING | Static |
| "Build This Strategy" integration | Link from strategies page | Needs verification | ⚪ NOT TESTABLE | FE |

**Overall**: 🟢 Structure complete. Integration workflow needs browser testing.

---

### /tools/backtest.html (Backtest)

| Component | Plan | Current | Status | Source |
|-----------|------|---------|--------|--------|
| Instrument/Strategy/Period | Selection | Present | ✅ WORKING | Static |
| Run | Execute backtest | Present | ✅ WORKING | Static |
| Results | Trades, win rate, P&L | Empty until run | ✅ EXPECTED | — |
| Equity curve | Chart | Empty until run | ✅ EXPECTED | — |
| Trade ledger | Table | Empty until run | ✅ EXPECTED | — |
| AI data fabrication check | Deterministic only | Present | ✅ WORKING | Static |

**Overall**: 🟢 Good architecture. Interactive run needed.

---

### /tools/position-size.html (Position Size)

| Component | Plan | Current | Status | Source |
|-----------|------|---------|--------|--------|
| Capital/Risk %/Entry/Stop | Inputs | Present | ✅ WORKING | Static |
| Calculation | Position size, max loss | Present | ✅ WORKING | Static |
| "From strategy" link | Natural link | Needs verification | ⚪ NOT TESTABLE | FE |

**Overall**: 🟢 Structure complete. Link integration needs testing.

---

### /mutual-funds/ (Mutual Funds)

| Component | Plan | Current | Status | Source |
|-----------|------|---------|--------|--------|
| Best Mutual Funds | AMFI data | "Loading mutual funds…" | 🔴 FAILING | JS → API |
| Secondary positioning | SEO/secondary | Needs verification | ⚪ NOT TESTABLE | FE |
| Navigation distinction | Separate from trading | Needs verification | ⚪ NOT TESTABLE | FE |

**Immediate action**: Identify mutual funds data source (mfapi/AMFI). Verify endpoint reachable.

---

### /options/pcr.html (Options Intelligence)

| Component | Plan | Current | Status | Source |
|-----------|------|---------|--------|--------|
| Options Intelligence header | Header | Present | ✅ WORKING | Static |
| Index Selector | NIFTY/BANKNIFTY/FINNIFTY/SENSEX | Present | ✅ WORKING | Static |
| PCR | Current PCR, trend | Redesigned — loading state | ⚪ NOT TESTABLE | FE → API |
| OI | Call OI, Put OI, Concentration | Redesigned — loading state | ⚪ NOT TESTABLE | FE → API |
| Max Pain | Max Pain data | Redesigned — loading state | ⚪ NOT TESTABLE | FE → API |
| Expected Move | Expected move | Redesigned — loading state | ⚪ NOT TESTABLE | FE → API |
| AI Interpretation | AI analysis | Loading | ⚪ NOT TESTABLE | JS → API |
| Public accessibility | Crawler-reachable | Not reliably retrievable | 🔴 FAILING | NGINX |

**Immediate action**: Verify page accessible via nginx. Verify API endpoints reachable from browser.

---

## P3 — Education & Learn Pages

### /learn/ and sub-pages

| Page | Status | Source |
|------|--------|--------|
| /learn/ | Educational hub loads correctly | 🟢 WORKING | User audit |
| /learn/option-chain.html | Education page | 🟢 WORKING | User audit |
| /learn/pcr.html | Education page | 🟢 WORKING | User audit |
| /learn/vwap.html | Education page | 🟢 WORKING | User audit |
| /learn/cpr.html | Education page | 🟢 WORKING | User audit |
| /learn/option-greeks.html | Education page | 🟢 WORKING | User audit |

**Overall**: 🟢 Education/SEO content is working. No action needed.

---

## Trust Pages

| Page | Status | Source |
|------|--------|--------|
| /about.html | Loads correctly | 🟢 WORKING | User audit |
| /contact.html | Loads correctly | 🟢 WORKING | User audit |
| /privacy.html | Loads correctly | 🟢 WORKING | User audit |
| /terms.html | Loads correctly | 🟢 WORKING | User audit |
| /disclaimer.html | Loads correctly | 🟢 WORKING | User audit |
| /404.html | Error page | 🟢 WORKING | User audit |

---

## Public Accessibility Issues

| Page | Issue | Source |
|------|-------|--------|
| /indices/nifty.html | Crawler unreliable | NGINX or URL routing |
| /indices/banknifty.html | Not retrievable | Same as above |
| /indices/finnifty.html | Not retrievable | Same as above |
| /indices/sensex.html | Not retrievable | Same as above |
| /options/pcr.html | Crawler failed | NGINX or URL routing |
| /strategies.html | Not retrievable | NGINX or URL routing |
| /market.html | Not retrievable | NGINX or URL routing |
| /today/index.html | Loading exposed | FE — resolved by restructure |

**Likely cause**: URL pattern mismatch between what sitemap.xml declares and what nginx actually serves. May involve directory index handling or URL rewrite issues.
**Immediate action**: On VM, curl each URL and compare response code + content. Verify nginx config matches sitemap URLs.

---

## Summary — Component Status

| Status | Count | Examples |
|--------|-------|---------|
| ✅ WORKING | ~25 | Static content, navigation, SEO, legal pages, backtest structure |
| 🟠 PARTIAL | ~5 | /options/intelligence data, timestamp mechanism, strategy comparison |
| 🔴 FAILING | ~10 | Homepage market data, today loading, strategies analysis, scanner results, mutual funds, market grid, NIFTY deep dive data, options PCR data, strategy performance, public accessibility |
| ⚪ NOT TESTABLE | ~30 | All dynamically rendered sections without browser |

---

## Prioritized Fix List

### P0 — Runtime Critical (fix before any feature work)

| # | Page | Issue | Fix Type |
|---|------|-------|----------|
| 1 | / | Index snapshot shows "—" | Verify API → JS → DOM chain |
| 2 | / | AI outlook not showing | Verify AI outlook API endpoint |
| 3 | / | Breadth "Loading…" | Verify breadth API endpoint |
| 4 | /today/ | Loading state (restructured, runtime unknown) | Browser test |
| 5 | /indices/nifty.html | Public crawler inaccessible | NGINX/URL verification |
| 6 | /indices/banknifty.html | Public crawler inaccessible | NGINX/URL verification |
| 7 | /indices/finnifty.html | Public crawler inaccessible | NGINX/URL verification |
| 8 | /indices/sensex.html | Public crawler inaccessible | NGINX/URL verification |
| 9 | /options/pcr.html | Public crawler inaccessible | NGINX/URL verification |
| 10 | /strategies.html | Public crawler inaccessible | NGINX/URL verification |
| 11 | /market.html | Public crawler inaccessible | NGINX/URL verification |

### P1 — Strategy & Market Runtime

| # | Page | Issue | Fix Type |
|---|------|-------|----------|
| 12 | /strategies.html | Strategy Analysis Loading… | Verify strategy API |
| 13 | /strategies.html | Strategy Performance Loading… | Verify performance API |
| 14 | /scanner.html | Stock Results Loading… | Verify scanner API |
| 15 | /market.html | Index Grid not populated | Verify market API |

### P2 — Tools & Supporting

| # | Page | Issue | Fix Type |
|---|------|-------|----------|
| 16 | /mutual-funds/ | "Loading mutual funds…" | Verify mfapi/AMFI endpoint |
| 17 | /strategy-builder.html | Integration workflow | Browser test |
| 18 | /tools/backtest.html | Interactive run test | Browser test |
| 19 | /tools/position-size.html | Integration workflow | Browser test |

### P3 — Content Refinement

| # | Item | Action |
|---|------|--------|
| 20 | /learn/ | Content refinement per SEO plan |
| 21 | /mutual-funds/ | Positioning vs core product |
| 22 | All | Secondary nav cards verification |

---

## CRITICAL: API Response Structure Mismatch — /today/index.html

**Discovery date**: 16 September 2026
**Severity**: P0 — blocks entire Today terminal AI Outlook section

### The mismatch

`/api/market-outlook?symbol=NIFTY` returns the outlook payload **directly**:
```json
{
  "bias": {"label": "BULLISH", ...},
  "regime": {"primary": "RANGE-BULLISH", ...},
  "strategies": [...],
  ...
}
```

`/today/index.html` JavaScript expects it **wrapped in `{outlook: ...}`**:
```javascript
var o = await fetchJSON('market-outlook?symbol=NIFTY');
if(o && o.outlook) {  // ← o.outlook is UNDEFINED when API returns raw payload
  // AI Outlook section code never executes
}
```

### Where each consumer expects which format

| Consumer | Expects | API returns | Match? |
|----------|---------|-------------|--------|
| ai-outlook.js (NIFTY page, homepage dashboard) | Raw object `{bias, regime, strategies, ...}` | Raw object | ✅ |
| /today/index.html inline `loadTodayData()` | Wrapped `{outlook: {bias, regime, ...}}` | Raw object | ❌ MISMATCH |
| api_server.py `/api/market-outlook` | — | Returns raw `market_outlooks.payload` JSON | — |
| api_server.py `/api/market-outlook/<date>` | — | Returns raw `market_outlooks.payload` JSON | — |

### Consequence

The AI Outlook section (`#t-outlook`) on `/today/index.html` will ALWAYS show "Loading today's outlook…" because `o.outlook` is `undefined` when the API returns the raw payload. The `if(o&&o.outlook)` guard skips all AI Outlook rendering.

The Today terminal's Market Snapshot section (`#t-snapshot`) uses `fetchJSON('market')` which returns `{instruments: {...}, ...}` — this likely works correctly because `market.js` and `dashboard.js` use the same unwrapped format.

### Fix required

Either:
- **Fix frontend**: Change `/today/index.html` to expect raw `o` instead of `o.outlook`, OR
- **Fix backend**: Wrap `/api/market-outlook` response in `{outlook: data}` for today terminal context, OR
- **Fix backend**: Create separate endpoint `/api/market-outlook/wrapped` or similar

Recommended: Fix frontend to match raw payload format (consistent with ai-outlook.js).

---

## Most Likely Root Causes

By frequency of failure, the most likely sources:

1. **API/JSON → DOM chain**: Many pages have correct JS code but data doesn't reach DOM. Verify on VM that API endpoints return valid JSON and browser JS can access them.

2. **NGINX URL handling**: 7+ pages are publicly inaccessible despite existing on disk. Likely URL pattern or directory index issue.

3. **Market data feed**: If /api/market returns empty or errors, every market-dependent page fails simultaneously. This is the single biggest failure cascade.

4. **Cron/data refresh**: If data isn't refreshed regularly, all market data goes stale or unavailable. Verify cron jobs running on VM.

5. **Cross-origin restrictions**: If browser JS can't reach API endpoints (CORS), all dynamic content fails. Verify CORS config on VM.

---

## Next Step

Once VM access is available:

1. Read-only: curl each page and API endpoint
2. Verify: nginx config → URL → response → content chain
3. Verify: API endpoints return valid JSON with data
4. Verify: Cron jobs running, data fresh
5. Browser test: Core P0 pages
6. Produce: Fix list with exact root causes

No modifications until all verification complete.
