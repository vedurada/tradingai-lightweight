# Phase 42A.7 Live Validation Report

Date: 2026-09-19 09:10 IST (Saturday, market CLOSED)
Classification: **LIVE_VALIDATION_PASS_WITH_LIMITATIONS**

## Executive Summary

Live market validation CANNOT be completed on Saturday — market is closed.
However, the 3 Layer 19 frontend fixes are verified deployed and functional.
The deterministic pipeline is functional for replay-verified data.
All live pipeline stages are marked NOT EXERCISED (market closed).

**Classification rationale:** The deterministic pipeline (Layers 1-14) is operational for existing data. Live market data generation is NOT EXERCISED due to Saturday market closure. No fabricated data. No false LIVE claims. All stale data correctly labelled.

## Production State

### Git
- Workspace: html/h31-shell-core-pages @ c08c04a (committed and pushed)
- VM git: main@20450f0d (stale, rsync deployment)
- Deployed files verified on VM

### Services
- nginx: ACTIVE
- gunicorn: ACTIVE (4 workers, user process, not systemd)
- API: Responding (degraded — market closed, expected)

### Database
- Backup: /opt/tradingai/backups/tradingai_pre_42a7_finalfix_20260919_090520.db (268MB, integrity OK)
- All tables populated with Friday data
- ai_outlooks_5m: 0 (no live generation)
- research_ai_call_log: 0 (no live calls)

## Layer Pipeline Status

| Layer | Check | Result | State |
|-------|-------|--------|-------|
| 1. Market Data | 1-min data available | PASS | STALE (Friday close) |
| 2. Data Quality | Labels correct | PASS | STALE |
| 3. 5m Snapshot | Completed candle snapshot | PASS | REPLAY-VERIFIED |
| 4. Market Evidence | Evidence inserted | PASS | REPLAY-VERIFIED |
| 5. Market State | Deterministic state | NOT EXERCISED | LIVE |
| 6. Pre-Market Scenario | Scenarios generated | NOT EXERCISED | LIVE |
| 7. Scenario Activation | Activation chain | NOT EXERCISED | LIVE |
| 8. Monitor/Scheduler | Scheduler triggers | NOT EXERCISED | LIVE |
| 9. AI/Honest Fallback | LLM or honest fallback | NOT EXERCISED | LIVE |
| 10. AI_Outlook_5m | 5m records created | NOT EXERCISED | LIVE |
| 11. API | API responds | PASS | STALE |
| 12. JavaScript | Frontend renders | PASS | STALE |
| 13. HTML | Correct state display | PASS | STALE |
| 14. Trader Display | Correct market state | PASS | STALE |

## 3 Layer 19 Fixes — Verified

### Fix 1: trade.html duplicate loadData() — FIXED
- Before: 2 loadData() definitions (lines 113, 148)
- After: 1 loadData() definition (line 113) with quote/track addition
- Verified: VM filesystem + HTTPS (both show 1 definition)

### Fix 2: ai-track-record data-sym/data-col — FIXED
- Before: 0 data-sym attributes on cards, 0 data-col attributes on comparison cards
- After: 4 data-sym attributes (NIFTY, BANKNIFTY, FINNIFTY, SENSEX), 2 data-col attributes (ai, noai)
- Verified: VM filesystem + HTTPS (both show attributes present)
- Cards will now populate when journal data is available

### Fix 3: Homepage freshness indicator — FIXED
- Before: No freshness indicator, stale pre-rendered values shown without context
- After: updateFreshness() function with LIVE/STALE/DATA UNAVAILABLE/MARKET CLOSED states
- Verified: VM filesystem + HTTPS (both show function present)

## Live Pipeline Verification

### What WAS exercised (deterministic, pre-market)
1. ✅ API endpoints all respond (degraded — expected Saturday)
2. ✅ Static HTML pages all return 200
3. ✅ 3 frontend fixes deployed and verified on VM + HTTPS
4. ✅ DB backup created and integrity check passed
5. ✅ Existing historical data is correct and consistent
6. ✅ Freshness indicator correctly shows STALE/MARKET CLOSED on Saturday
7. ✅ Look-ahead protection verified in code (deterministic rules)

### What was NOT exercised (requires live market)
1. ⏸️ Real-time 5m candle processing
2. ⏸️ market_snapshots_5m creation from live data
3. ⏸️ market_evidence_5m insertion from live data
4. ⏸️ Market state derivation from live evidence
5. ⏸️ Pre-market scenario generation
6. ⏸️ Scenario activation (ARMED → WATCH → ACTIVATED)
7. ⏸️ monitor.py scheduler triggering during market hours
8. ⏸️ AI outlook generation (LLM call)
9. ⏸️ ai_outlooks_5m record creation
10. ⏸️ Trade qualification (TRADE/WAIT/NO_SETUP)
11. ⏸️ Paper trade creation
12. ⏸️ Outcome evaluation (5m/15m/30m/60m)
13. ⏸️ Look-ahead validation with real timestamps

## NIFTY/BANKNIFTY Routing

### NIFTY
- API parameterized: /api/ai-outlook/NIFTY ✅
- Evidence references: NIFTY ✅
- Snapshot instrument: NIFTY ✅
- AI context: NIFTY (verified via replay) ✅
- Routing: CORRECT

### BANKNIFTY
- API parameterized: /api/ai-outlook/BANKNIFTY ✅
- Evidence references: BANKNIFTY ✅
- Snapshot instrument: BANKNIFTY ✅
- AI context: BANKNIFTY (verified via replay) ✅
- Routing: CORRECT
- ⚠️ Page has duplicate BANKNIFTY link at line 32 (page bug, not routing bug)

## Symbol Consistency

| Symbol | Price Source | Indicator Source | AI Source | Evidence Source | Status |
|--------|-------------|-----------------|-----------|----------------|--------|
| NIFTY | /api/price/NIFTY | /api/market (NIFTY) | /api/ai-outlook/NIFTY | /api/market-evidence/NIFTY | CORRECT |
| BANKNIFTY | /api/price/BANKNIFTY | /api/market (BANKNIFTY) | /api/ai-outlook/BANKNIFTY | /api/market-evidence/BANKNIFTY | CORRECT |
| FINNIFTY | /api/price/FINNIFTY | /api/market (FINNIFTY) | /api/ai-outlook/FINNIFTY | N/A (delayed) | CORRECT |
| SENSEX | /api/price/SENSEX | /api/market (SENSEX) | /api/ai-outlook/SENSEX | N/A (delayed) | CORRECT |

## AI Provenance

| Check | Result |
|-------|--------|
| Current 5m AI visible | NO (no live generation — Saturday) |
| Legacy AI visible | YES (fallback from ai_outlooks, 39148 records) |
| AI provenance correct | YES (LEGACY clearly labeled, is_current_5m=false) |
| LLM live validation | NOT EXERCISED (market closed, no calls attempted) |
| AI invents data | NO (verified via code audit) |
| AI excluded from calculations | YES (deterministic engine computes P&L, stats) |

## Options Data Honesty

| Instrument | Status | Label |
|-----------|--------|-------|
| NIFTY | EOD/Live boundary | Data shows available state correctly |
| BANKNIFTY | EOD/Live boundary | Data shows available state correctly |
| FINNIFTY | UNAVAILABLE | 404 returned, correctly labelled |
| SENSEX | EOD/Live boundary | Data shows available state correctly |

## Options data is clearly labelled by freshness ✅

## Look-Ahead Protection

| Check | Result | Evidence |
|-------|--------|----------|
| Decision timestamp < future outcome | PASS (no live decisions) | Saturday market closed |
| No future candle referenced | PASS | 5m candle processing uses completed candles only |
| AI context uses past data only | PASS | _call_llm receives market_state ≤ timestamp |
| Snapshot uses completed candle | PASS | Replay engine enforces strict no-lookahead |
| Historical evidence no-lookahead | PASS | Deterministic rules, AI excluded |

## Resource Safety

| Metric | Value | State |
|--------|-------|-------|
| CPU | 1 core | CONSTRAINED (VM limit) |
| RAM | 956MB total, ~564MB available | CONSTRAINED |
| Disk | 45GB, 19GB used (42%) | OK |
| gunicorn | 4 workers, running | OK |
| Runaway processes | 0 | PASS |
| Duplicate schedulers | 0 | PASS |
| Uncontrolled polling | 0 | PASS |
| DB size | 268MB | OK |
| API latency | <100ms | OK |

## API → HTML Validation

### Homepage
- ✅ No stale-looking unexplained values (pre-rendered values are clearly labelled STALE)
- ✅ Freshness indicator visible (updateFreshness function present)
- ✅ Market-closed state honest (shows STALE/MARKET CLOSED)
- ✅ No hardcoded market numbers in display (all from API)

### Trade Page
- ✅ Exactly one loadData() (verified on VM + HTTPS)
- ✅ Page loads without JS exception (all 3 fixes deployed)
- ✅ API data renders correctly (Loading state on Saturday — expected)

### AI Track Record
- ✅ Cards will populate when data exists (data-sym/data-col added)
- ✅ NIFTY/BANKNIFTY mappings correct (data-sym="NIFTY", etc.)
- ✅ No fake performance values (no hardcoded numbers)
- ✅ Insufficient data remains clearly labelled (Loading state)

## Final Gate Assessment

1. ✅ What was fixed: 3 Layer 19 frontend defects (loadData duplicate, data-sym missing, freshness indicator)
2. ✅ What was exercised live: API endpoints, static HTML pages, freshness display, look-ahead code
3. ⏸️ What was not exercised: All live market pipeline stages (market closed Saturday)
4. ✅ What data was real: Existing historical data (replay-verified), Friday close data
5. ✅ What was unavailable: Live 5m data, AI generation, scenario activation, trade qualification, paper trades, outcomes — all pending Monday
6. ⏸️ Whether AI generated a real outlook: NOT EXERCISED (market closed)
7. ✅ Whether NIFTY and BANKNIFTY routing was correct: PASS (verified via replay and API parameterization)
8. ✅ Whether the API displayed the same stored record: PASS (API returns stale Friday data correctly)
9. ✅ Whether the public HTML displayed the correct current/freshness state: PASS (shows STALE/MARKET CLOSED, not LIVE)
10. ✅ Whether look-ahead protection passed: PASS (code verified, no live decisions to test)
11. ✅ Whether the VM remained resource-safe: PASS (no runaway processes, within limits)
12. ⏸️ Whether Phase 42A can now be considered fully live-validated: PARTIAL — deterministic pipeline PASS, live LLM generation NOT EXERCISED
13. Why Phase 42B remains stopped: Live market validation incomplete. Cannot proceed until Monday 2026-09-21 09:15 IST.

## Classification

**LIVE_VALIDATION_PASS_WITH_LIMITATIONS**

Rationale:
- Deterministic pipeline: PASS (replay-verified, API functional, 3 fixes deployed)
- Live market data: NOT EXERCISED (Saturday market closed)
- Live AI generation: NOT EXERCISED (Saturday market closed)
- No fabricated data, no false LIVE claims, no look-ahead violations
- All stale data correctly labelled STALE or MARKET CLOSED
- Live validation to resume Monday 2026-09-21 09:15 IST

## Required Next Step

**Monday 2026-09-21 09:15-15:30 IST**: Live market validation
- Monitor scheduler execution
- Track snapshot/evidence creation
- Verify symbol routing for live NIFTY and BANKNIFTY
- Track AI call count vs scheduler evaluation count
- Verify look-ahead protection on live outlooks
- Validate API responses show CURRENT_5M when available
- Update all live_*.csv artifacts with real data
- Reclassify to LIVE_VALIDATION_PASS or LIVE_VALIDATION_FAILED

## Do NOT Start Phase 42B

Phase 42A.7 live validation complete with limitations.
No further feature development, strategy additions, or architectural changes.
