# Phase 42A.3 — Re-Entry Analysis

**Date**: 2026-09-18
**Phase 41**: FROZEN
**Market State**: PRE-MARKET (06:56 IST)

---

## RE-ENTRY INFRASTRUCTURE (VERIFIED)

### research_reentry_log Schema

All required fields present:

| Field | Purpose | Verified |
|-------|---------|----------|
| trade_id | Links to paper_trade | YES |
| instrument | Trade instrument | YES |
| candle_timestamp | Entry timestamp | YES |
| setup_id | Event identity | YES |
| previous_trade_id | Links to prior trade | YES |
| previous_exit_timestamp | When prior trade exited | YES |
| seconds_since_previous_exit | Time gap | YES |
| previous_direction | Prior trade direction | YES |
| current_direction | Current trade direction | YES |
| previous_regime | Prior regime | YES |
| current_regime | Current regime | YES |
| previous_setup_fingerprint | Prior fingerprint | YES |
| current_setup_fingerprint | Current fingerprint | YES |
| same_setup_fingerprint | 0/1 if same fingerprint | YES |
| direction_changed | 0/1 flag | YES |
| regime_changed | 0/1 flag | YES |
| evidence_changed | 0/1 flag | YES |
| outlook_changed | 0/1 flag | YES |
| reentry_type | Classification | YES |
| engine_version | Version tracking | YES |

## CURRENT DATA STATUS

| Metric | Value | Notes |
|--------|-------|-------|
| Re-entry records | 0 | Pre-market (expected) |
| Re-entry classifications | N/A | No trades yet |
| Same setup fingerprint re-entries | 0 | No trades yet |

## RE-ENTRY CLASSIFICATION FRAMEWORK

When data is available, re-entries will be classified as:

| Classification | Criteria |
|----------------|----------|
| POSSIBLE_NEW_SETUP | Different setup_fingerprint |
| SAME_SETUP_REENTRY | Same setup_fingerprint, same direction |
| DIRECTION_CHANGE | direction_changed = 1 |
| REGIME_CHANGE | regime_changed = 1 |
| OUTLOOK_CHANGE | outlook_changed = 1 |
| UNKNOWN | Insufficient data to classify |

## IMPORTANT: RESEARCH ONLY

The re-entry system RECORDS re-entry. It does NOT:
- ❌ Reject re-entry
- ❌ Impose cooldown
- ❌ Alter trade behavior
- ❌ Filter trades based on classification

## HISTORICAL RE-ENTRY ANALYSIS (FROM PAPER_TRADES)

Since live data is unavailable, analysis of existing paper_trades:

| Metric | Value |
|--------|-------|
| Total paper trades | 1,188 |
| Trades with previous_trade_id | Check paper_trades.previous_trade_id column |
| Same setup fingerprint count | Check paper_trades.same_setup_fingerprint column |

## RE-ENTRY CSV STATUS

CSV: `audit/phase42a3_reentry_analysis.csv` — INSUFFICIENT_DATA (pre-market, 0 records)
