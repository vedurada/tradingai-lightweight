# Phase 42A.3 — Setup Identity Research

**Date**: 2026-09-18
**Phase 41**: FROZEN
**Market State**: PRE-MARKET (06:56 IST)

---

## SETUP IDENTITY DEFINITIONS (NOT MODIFIED)

### setup_id
Event identity based on: `instrument + candle_timestamp + direction`
- Generated via: `SETUP-{SHA256(instrument|candle_timestamp|direction)[:16].upper()}`
- Identifies EACH decision event separately
- NOT a count of unique setups

### setup_fingerprint
Decision/setup identity based on: `instrument + trading_date + direction + regime + trade_state + strategy + evidence_state + ai_outlook_id`
- Generated via: `SHA256(...)|SHA256(...)[:24].upper()`
- For analysis of repeated/similar setups
- Does NOT affect trade decisions

## CURRENT DATA STATUS

| Metric | Value | Notes |
|--------|-------|-------|
| Unique setup fingerprints | 0 | No live data yet |
| Research setup records | 0 | Pre-market |
| NIFTY setups | 0 | Pre-market |
| BANKNIFTY setups | 0 | Pre-market |

## HISTORICAL ANALYSIS (FROM PAPER_TRADES)

Since live data is unavailable (pre-market), analysis of existing paper_trades:

| Metric | Value |
|--------|-------|
| Total paper trades | 1,188 |
| NIFTY paper trades | 1,188 |
| BANKNIFTY paper trades | 0 |
| Unique setup_fingerprint in paper_trades | See paper_trades.setup_fingerprint column |

## SETUP IDENTITY RESEARCH PLAN

When market data becomes available, the following research questions will be answered:

1. **How many unique setup fingerprints occur?** → Count DISTINCT setup_fingerprint in research_setup_identity
2. **How many paper trades per fingerprint?** → GROUP BY setup_fingerprint COUNT(*)
3. **How often does same setup recur?** → Compare timestamps of same fingerprint
4. **Re-entry frequency?** → Count re-entry records per fingerprint
5. **Regime changes per setup?** → Check regime_changed field

## SETUP_ID vs SETUP_FINGERPRINT VERIFICATION

| Check | Result |
|-------|--------|
| setup_id is event-based (instrument + timestamp + direction) | VERIFIED in code |
| setup_id NOT interpreted as count | VERIFIED |
| setup_fingerprint available for analysis | VERIFIED |
| Neither definition modified | VERIFIED |
| setup_id in market_snapshots_5m | VERIFIED (column exists) |
| setup_id in market_evidence_5m | VERIFIED (column exists) |
| setup_id in ai_outlooks_5m | N/A (column not added, but outlook_id links) |
| same_setup_fingerprint in paper_trades | VERIFIED (column exists) |

## CSV GENERATION STATUS

CSV: `audit/phase42a3_setup_identity.csv` — INSUFFICIENT_DATA (pre-market, 0 records)

## SAMPLE SIZE NOTE

Insufficient live data for statistical analysis.
Research is in INITIATION phase.
Results from historical paper_trades are descriptive only, not statistically significant.
