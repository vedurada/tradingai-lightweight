# Layer Architecture Compliance — Phase 42A.7 Audit Cross-Reference

Date: 2026-09-19
Reference: TradingAI 19-layer architecture (user-provided)
Purpose: Verify audit findings are consistent with intended layer model

## Architecture Compliance Summary

| Architecture Principle | Status | Evidence |
|----------------------|--------|----------|
| AI not at foundation (layer 11) | ✅ COMPLIANT | AI outlook at layer 11, after 10 deterministic layers |
| Deterministic data before AI | ✅ COMPLIANT | price_5m → evidence → market state → scenario → AI |
| Two feedback loops defined | ✅ COMPLIANT | Loop 1 (intraday) pending live validation; Loop 2 (research) depends on paper trades |
| Frontend = display only | ⚠️ PARTIALLY COMPLIANT | ai-track-record cards can't display backend-computed values (data-sym missing) |
| Frontend doesn't decide | ✅ COMPLIANT | No AI/bullish decisions in HTML; all intelligence from backend |
| Storage connects everything | ✅ COMPLIANT | SQLite stores all layer outputs with timestamps |
| AI doesn't invent data | ✅ COMPLIANT | _call_llm fix ensures AI receives actual symbol + market_state |
| API/Service is layer 18 | ✅ COMPLIANT | REST APIs serve JSON to frontend |
| Every layer has timestamp | ⚠️ PARTIALLY COMPLIANT | Homepage pre-rendered values lack live timestamps |

## Audit Findings → Layer Mapping

### Findings that violate or stress the layer model

1. **ai-track-record cards NEVER populate** (Layer 19 → Layer 11/16 disconnect)
   - Layer 16 (Research) computes accuracy stats via /api/journal/stats
   - Layer 19 (Frontend) queries for data-sym/data-col attributes that don't exist
   - Result: Research layer output is invisible to trader experience layer
   - **Layer violation**: Frontend cannot display research results

2. **trade.html duplicate loadData()** (Layer 19 internal bug)
   - Second definition overwrites first, removing error/empty states
   - **Layer violation**: Frontend layer has inconsistent internal logic

3. **Homepage pre-rendered stale data** (Layer 19 → Layer 1 gap)
   - Layer 1 (Market Data) has stale price_5m (18 Sep)
   - Layer 19 displays stale values with no freshness indicator for pre-rendered data
   - **Layer violation**: Display layer doesn't distinguish stale pre-rendered from live data

4. **BANKNIFTY page duplicate index link** (Layer 19 navigation bug)
   - Duplicate link creates navigation confusion
   - **Layer violation**: Frontend navigation doesn't correctly represent available layers

5. **FINNIFTY stale-price magic number** (Layer 2 → Layer 19 gap)
   - Layer 2 (Data Quality) should classify FINNIFTY as STALE/DELAYED
   - Layer 19 shows stale data without clear quality label (magic number hack)
   - **Layer violation**: Data quality layer output not properly propagated to display

### Findings that CONFIRM architecture integrity

1. **NIFTY/BANKNIFTY symbol routing** ✅ — Layer 10 (Scenario) and Layer 11 (AI) receive correct symbol from Layer 1 (Data Ingestion). No cross-symbol contamination.

2. **AI outlook provenance** ✅ — LEGACY vs CURRENT_5M labels correctly maintained. Layer 11 (AI) properly labeled as explanation layer, not data source.

3. **Options data honesty** ✅ — Layer 13 (Options Strategy) shows UNAVAILABLE for FINNIFTY (404), not fabricated data. Matches architecture: "No qualified setup → NO TRADE".

4. **Research methodology section** ✅ — Layer 16 (Research) correctly separates static methodology from dynamic computed statistics. No fabricated research data.

5. **Backtest rules-based** ✅ — Layer 7 (Deterministic Backtest) clearly separated from Layer 11 (AI). Page title says "Deterministic Strategy Performance".

6. **Evidence deterministic** ✅ — Layer 4 (Market Evidence) uses deterministic rules, AI excluded. Matches "AI EXCLUDED from all calculations" principle.

## Layer Integrity Assessment

```
Layer  1  Market Data Ingestion      ✅ COMPLIANT — real data, no fabrication
Layer  2  Data Normalization         ⚠️ STRESSED — FINNIFTY stale not cleanly labeled
Layer  3  5m Snapshot                ✅ COMPLIANT — REPLAY-VERIFIED for NIFTY+BANKNIFTY
Layer  4  Market Evidence            ✅ COMPLIANT — deterministic, AI excluded
Layer  5  Positioning Engine         ✅ COMPLIANT — inference from data
Layer  6  Liquidity/Structure        ✅ COMPLIANT — levels, VWAP, CPR, OI
Layer  7  Market State               ✅ COMPLIANT — multiple states defined
Layer  8  Pre-Market Scenario        ✅ COMPLIANT — max 3 scenarios, pending live
Layer  9  Expected Movement          ✅ COMPLIANT — historical only, calibrated
Layer 10  Scenario Activation        ✅ COMPLIANT — ARMED/WATCH/ACTIVATED/CONFIRMED
Layer 11  AI Outlook                 ✅ COMPLIANT — explanation only, receives structured evidence
Layer 12  Trade Qualification        ⚠️ STRESSED — Loading on static load (not broken, but unavailable)
Layer 13  Options Strategy           ⚠️ STRESSED — FINNIFTY unavailable (correct), others Loading
Layer 14  Risk/Position Sizing       ⚠️ STRESSED — Loading (depends on qualification)
Layer 15  Paper Trade/Outcome        ⚠️ STRESSED — Loading (no qualified setups on Saturday)
Layer 16  Research/Learning          ⚠️ STRESSED — 4 cards invisible (data-sym), otherwise OK
Layer 17  Storage Layer              ✅ COMPLIANT — SQLite, immutable records
Layer 18  API/Service Layer          ✅ COMPLIANT — all endpoints responding
Layer 19  Frontend/Trader Experience ⚠️ STRESSED — 3 bugs (duplicate loadData, data-sym, stale display)
```

## Key Insight

Most "stressed" layers (12-16) are in Loading state because:
- Market is CLOSED (Saturday) — expected
- Pre-market state — no live data generation
- Not violations of the architecture, just the current operating mode

The 3 actual frontend bugs (Layer 19) are:
1. trade.html duplicate loadData() — code bug
2. ai-track-record data-sym missing — HTML/JS contract bug
3. Homepage stale display — data freshness UX bug

All 3 are correctable without layer redesign.

## Architecture Principle Verified

The audit confirms the fundamental principle:

> **Every layer should know what information came before it, what it is allowed to infer, and what it is not allowed to claim.**

- AI (Layer 11) receives structured evidence, NOT market data directly → ✅
- AI does NOT compute walk-forward, evidence, or qualification metrics → ✅
- Frontend does NOT make trading decisions → ✅
- Storage layer preserves all intermediate states for reconstruction → ✅
- No fabricated data at any layer → ✅
