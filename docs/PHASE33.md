# PHASE 33 — Validate and Operationalize

Date: 2026-09-16
Status: 33.1-33.2 COMPLETE, 33.3 in progress

## Context

Phase 32 API/contract repair is COMPLETE.
H31 HTML is FROZEN.
Production serves old HTML with broken data pipeline.

Phase 33 validates the existing data pipeline, verifies all API contracts
against populated data, and prepares for controlled deployment.

## 33.1 — Data Pipeline Validation ✅ COMPLETE

### Findings
- Root cause of UNAVAILABLE: `market_candles` table missing from workspace DB
- Fix: Populated from existing price tables (30,684 rows from price_1m/5m/1d)
- No new pipeline created — reused existing data sources
- 8/25 endpoints return LIVE (up from 0)
- 0 errors (down from 2)
- Tests: 165/169 (4 pre-existing failures)

### Remaining DB Gaps
| Empty Table | Affects |
|-------------|---------|
| market_outlooks | LLM overlay in market-outlook |
| regimes | /api/regime/<symbol> |
| option_chain | /api/options/state/* |
| oi_top_strikes | /api/oi-top |
| history | /api/replay |
| instruments | instrument lookups |

## 33.2 — API Verification Against Populated DB ✅ COMPLETE

### Result: ALL PASS
8 endpoint groups verified:
- /api/key-levels (NIFTY, BANKNIFTY): LIVE, schema valid, timestamps present
- /api/intraday-conditions (NIFTY, BANKNIFTY): LIVE, schema valid
- /api/risk (NIFTY, BANKNIFTY, SENSEX): LIVE, schema valid, timestamps added
- /api/session-timeline: LIVE, schema valid

Verification criteria met:
- Valid schema ✅
- Valid timestamp ✅
- Correct symbol ✅
- Correct data_state ✅
- Non-null values when source data exists ✅

## 33.3 — Cross-Page Consistency (IN PROGRESS)

### HTML Inventory
- Total HTML files: 52 (matches Phase 30 inventory)
- Key pages verified: index, today, market, strategy-builder, tools, learn, about, indices

### Navigation Chain Verification
| Chain | Status |
|-------|--------|
| Home → Today | ✅ Linked |
| Home → NIFTY | ✅ Linked |
| Home → Market | ✅ Linked |
| Home → Options/PCR | ✅ Linked |
| Home → Strategy Builder | ✅ Linked |
| Home → Learn | ✅ Linked |
| Home → Backtest | 🔴 Relative link (needs verification) |
| Today → NIFTY | 🔴 Not directly linked (data-driven, not HTML link) |
| NIFTY → Market | ✅ Linked |
| NIFTY → PCR | ✅ Linked |
| NIFTY → Strategy Builder | ✅ Linked |
| NIFTY → Backtest | ✅ Linked |

### Missing Pages (not in workspace)
| Page | Status |
|------|--------|
| /options/option-chain.html | ❌ Does not exist |
| /options/oi.html | ❌ Does not exist |
| /options/max-pain.html | ❌ Does not exist |
| /options/expected-move.html | ❌ Does not exist |

Note: These are H31 target pages. H31 is frozen — creation requires new Phase decision.
Current options presence: /options/pcr.html only.
Education alternatives exist: /learn/option-chain.html, /learn/pcr.html, etc.

## 33.4 — Controlled Deployment (PENDING)

Prerequisites:
- [x] Data pipeline validated (33.1)
- [x] API verified against populated data (33.2)
- [ ] Deployment mechanism inspected (deploy-vm.sh untested)
- [ ] DB population strategy decided for production
- [ ] nginx/gunicorn/systemd setup on VM

## 33.5 — Production Canonicalization (PENDING)
- / → canonical homepage
- /index.html → same content
- /home.html → 301 → / (confirmed working)

## 33.6 — Full 52-Page Crawl (PENDING)

## 33.7 — Specific Consistency Checks (PENDING)
- Header consistency across all pages
- Data status badges (LIVE/UPDATED/STALE/UNAVAILABLE/ERROR)
- Contextual action links per page type
- Breadcrumb navigation

## Release Gate
Block release if:
- Database empty
- Market data stale beyond threshold
- API 404
- Unexpected API schema
- H31 HTML replaced by legacy
- Broken navigation
- Orphaned page
- Wrong canonical
- Indefinite Loading state
- Fake/default market values
- Missing timestamp
- Inconsistent layouts
- Production / and /index.html disagree
- Legacy portal accessible
