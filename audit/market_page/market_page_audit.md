# Market Page Audit — Phase 42A.6.x

Date: 2026-09-18
Auditor: OpenCode Agent
Decision: REMOVE (Option C)

## Executive Summary

`/market.html` (Market Overview) is a generic market dashboard that duplicates data already available on `/index.html`, `/today/index.html`, and `/indices/*.html`. Its only unique feature — sector performance data — is broken (`/api/sectors` returns 404). The page does not contribute to the core trader journey (scenario detection → activation → trade/wait/no-trade). It creates a competing destination that fragments user attention away from `/today/index.html` (the primary daily trader page).

**Recommendation**: Remove `/market.html` and redirect all traffic to `/today/index.html`.

## Audit Results

### Page Identity
| Property | Value |
|---|---|
| File | `/market.html` (209 lines, 17,407 bytes) |
| Title | Market Overview - TradingAI |
| Canonical | https://tradingai.in/market.html |
| Workspace/VM sync | IDENTICAL (md5 06d096e9) |
| Sitemap | Listed (priority 0.9, daily) |
| In navigation | YES (all pages link to it) |

### Sections (7 display + ticker + footer)
1. Updated Bar — "Last refreshed: —"
2. Ticker tape — "Loading market ticker…"
3. Market Overview (hero pulse) — NIFTY/BANKNIFTY/SENSEX/VIX tiles
4. Index Grid — All instruments as cards (price, change%, regime, VWAP, RSI, Support/Resistance)
5. Market Breadth — Advances, Declines, Unchanged, A/D Ratio
6. Sector & Market Condition — Top 6 sectors (BROKEN: /api/sectors → 404)
7. Technical Snapshot — VWAP, RSI, ADX, MACD
8. Market Regime — Primary, Confidence, Volatility favors
9. Index Deep Dives — Links to /indices/*.html

### API Endpoints
| Endpoint | Status | Notes |
|---|---|---|
| /api/market | 200 | Used 3x (no caching) |
| /api/breadth | 200 | Works |
| /api/sectors | **404** | **Permanent failure — unique data broken** |
| /api/index-breadth | Intermittent 502 | Upstream failures |

### Duplication Analysis
| Data Type | Duplicated On | Unique To market.html |
|---|---|---|
| Index price cards | /, /today/, /indices/*.html, /market.html | — |
| Market Breadth | /, /today/, /market.html | — |
| Technical indicators | /market.html, /indices/nifty.html | — |
| Sector performance | — | /market.html ONLY (broken) |
| AI Market Outlook | /, /today/, /indices/*.html | MISSING (not on market.html) |
| Index deep dive links | /market.html | — (navigation only) |

### Product Value Test (Q1-Q5)
| Question | Answer | Evidence |
|---|---|---|
| Q1: Does it help intraday trader make better decisions? | PARTIAL | Shows market data but lacks scenario, intent, trade qualification |
| Q2: Does it provide information unavailable elsewhere? | NO | Only sector data is unique; broken (404) |
| Q3: Does it have historical/SEO value? | LOW | Generic dashboard, no unique content, priority 0.9 in sitemap |
| Q4: Does it improve daily workflow? | MINIMAL | /today/index.html provides more useful data (session status, key levels, options, strategy) |
| Q5: Does it duplicate/conflict with other pages? | YES | Heavy duplication with /, /today/, /indices/*.html |

## Disposition Decision: REMOVE

Rationale:
1. Generic market dashboard — not scenario/activation focused
2. All unique data broken (/api/sectors → 404)
3. Heavy duplication with /, /today/, /indices/*.html
4. Does not contribute to core trader journey
5. Creates competing destination fragmenting user attention
6. /today/index.html is the superior destination for market data

## Migration Plan
1. Archive /market.html to archive/ directory
2. Remove from navigation on all pages
3. Remove from sitemap
4. Redirect /market.html → /today/index.html (nginx 301)
5. Update JS redirect logic on all pages (/market.html → /today/index.html)
6. Deploy to VM
7. Validate: curl tests, link checks, test suite

## Post-Removal Coverage
All market data previously on /market.html remains available on:
- /index.html — Market Status, Market Snapshot, Market Breadth, Options Intelligence
- /today/index.html — Session Status, Market Snapshot, AI Outlook, Key Levels, Options, Strategy, Risk, Session Timeline (PRIMARY destination)
- /indices/nifty.html, /indices/banknifty.html, /indices/finnifty.html, /indices/sensex.html — Per-index deep dives