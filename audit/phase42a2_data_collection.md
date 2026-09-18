# Phase 42A.2 — Data Collection

**Date**: 2026-09-18
**Phase 41**: FROZEN

---

## DATA COLLECTION OVERVIEW

| Item | Status |
|------|--------|
| Market state | PRE-MARKET |
| Live data collection | IDLE (awaiting 09:15 IST) |
| Historical data | Available (see below) |
| Research tables | 0 records (expected) |
| Cross-instrument isolation | VERIFIED |
| Data freshness | STALE (pre-market, expected) |
| Fabricated data | NONE |

## INSTRUMENT DATA STATUS

### NIFTY

| Metric | Value |
|--------|-------|
| Historical 5m candles | Available in price_5m |
| Historical snapshots | Available in market_change_snapshots |
| Latest price | STALE (586m ago) |
| Current session data | PENDING (market not open) |
| Data quality | STALE (expected pre-market) |
| Cross-contamination | NONE — NIFTY records contain only NIFTY context |

### BANKNIFTY

| Metric | Value |
|--------|-------|
| Historical 5m candles | Available in price_5m (4,350 candles) |
| Historical snapshots | No data in market_change_snapshots |
| Latest price | STALE (586m ago) |
| Current session data | PENDING (market not open) |
| Paper trades | 0 (pre-existing: all 1,188 paper trades are NIFTY) |
| Cross-contamination | NONE — BANKNIFTY records contain only BANKNIFTY context |
| Data quality | STALE (expected pre-market) |

### FINNIFTY

| Metric | Value |
|--------|-------|
| Historical 5m candles | Available in price_5m (4,350 candles) |
| Current status | DATA UNAVAILABLE per existing policy |
| Cross-contamination | NONE — FINNIFTY records contain only FINNIFTY context |

### SENSEX

| Metric | Value |
|--------|-------|
| Historical 5m candles | Available in price_5m (4,350 candles) |
| Latest price | STALE (918m ago) |
| Cross-contamination | NONE |

## 5-MINUTE CANDLE PIPELINE

Conceptual flow:
```
5m market data → market snapshot → market evidence → market state → AI trigger evaluation → AI outlook IF triggered → trade qualification → paper trade IF qualified → future outcome tracking
```

### Current Status

| Pipeline Stage | Status | Reason |
|----------------|--------|--------|
| 5m market data | STALE | Last session Sept 15-17 |
| Market snapshot | IDLE | No completed candles today |
| Market evidence | IDLE | No completed candles today |
| Market state | STALE | Last known state available |
| AI trigger evaluation | IDLE | No new candles |
| AI outlook | IDLE | No trigger conditions met |
| Trade qualification | IDLE | No new candles |
| Paper trade | IDLE | No qualification |
| Outcome tracking | IDLE | No trades |

## CROSS-INSTRUMENT CONTAMINATION TEST

### price_5m Table
| Symbol | Records | Isolated |
|--------|---------|----------|
| NIFTY | 4,350 | ✅ NIFTY-only data |
| BANKNIFTY | 4,350 | ✅ BANKNIFTY-only data |
| FINNIFTY | 4,350 | ✅ FINNIFTY-only data |
| SENSEX | 4,350 | ✅ SENSEX-only data |

### market_change_snapshots Table
| Symbol | Records | Isolated |
|--------|---------|----------|
| NIFTY | 32,033 | ✅ NIFTY-only data |

### Evidence Records
| Check | Result |
|-------|--------|
| NIFTY evidence contains NIFTY data | VERIFIED |
| BANKNIFTY evidence contains BANKNIFTY data | VERIFIED |
| No NIFTY prices in BANKNIFTY records | VERIFIED |
| No BANKNIFTY prices in NIFTY records | VERIFIED |

## DATA FRESHNESS

| Category | Status | Details |
|----------|--------|---------|
| Price data | STALE | 586-918 minutes old (last session) |
| VIX data | STALE | 586 minutes old |
| AI outlooks | STALE | 1519 minutes old |
| Research data | UNAVAILABLE | 0 records (pre-market) |

## DATA UNAVAILABLE COMPONENTS

| Component | Status | Notes |
|-----------|--------|-------|
| Options chain | UNAVAILABLE | External source unreliable |
| PCR | UNAVAILABLE | Depends on options data |
| Max Pain | UNAVAILABLE | Depends on options data |
| Expected move | UNAVAILABLE | Depends on options data |
| FINNIFTY | CONSTRAINED | Per existing policy — DATA UNAVAILABLE |
| AI service | NOT CALLED | No trigger conditions met |

## EVIDENCE GROUPS STATUS

| Group | Status | Notes |
|-------|--------|-------|
| Trend | UNAVAILABLE | No fresh data |
| Momentum | UNAVAILABLE | No fresh data |
| Market Structure | UNAVAILABLE | No fresh data |
| Volatility | UNAVAILABLE | No fresh data |
| Options Positioning | UNAVAILABLE | No options data |
| Market Confirmation | UNAVAILABLE | No fresh data |

## LOOK-AHEAD SAFETY

All research tables at 0 records → no look-ahead contamination possible.

Decision records will only contain DECISION_TIME fields.
Outcome records will be stored separately in research_outcome_tracking.

## IDEMPOTENCY

All research collection uses CREATE TABLE IF NOT EXISTS and idempotent processing.
No duplicate processing risk during single-collection pipeline.

## DATA GROWTH PROJECTION (Session)

| Metric | Estimate (Full Session) |
|--------|------------------------|
| 5m candles/day | ~156 (during market hours) |
| research_setup_identity | ~78 (50% of candles with trades) |
| research_ai_call_log | 0-5 (trigger-dependent) |
| research_data_health | ~24 (periodic checks) |
| research_outcome_tracking | 0 (pending maturation) |
| research_reentry_log | 0 (pending trades) |

These estimates are for a FULL market session (09:15-15:30 IST).
