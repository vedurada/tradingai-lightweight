# Phase 42A.4 — Setup Analysis

**Date**: 2026-09-18
**Phase 41**: FROZEN
**Market State**: PRE-MARKET (06:56 IST)

---

## SETUP IDENTITY DEFINITIONS (NOT MODIFIED)

### setup_id
Event identity: `instrument + candle_timestamp + direction`
- SHA256 hash: `SETUP-{SHA256(instrument|candle_timestamp|direction)[:16].upper()}`
- Identifies EACH decision event separately
- NOT a count of unique setups

### setup_fingerprint
Decision/setup identity: `instrument + trading_date + direction + regime + trade_state + strategy + evidence_state + ai_outlook_id`
- SHA256 hash: `[:24].upper()`
- For analysis of repeated/similar setups
- Does NOT affect trade decisions

## CURRENT DATA STATUS

| Metric | Value | Notes |
|--------|-------|-------|
| Unique setup fingerprints | 0 | PRE-MARKET |
| research_setup_identity records | 0 | PRE-MARKET |
| Repeated fingerprints | 0 | PRE-MARKET |
| Trades per fingerprint | N/A | No trades yet |
| Time between repeated fingerprints | N/A | No trades yet |

## VERIFICATION (INFRASTRUCTURE)

| Check | Result |
|-------|--------|
| setup_id is event-based | VERIFIED ✅ |
| setup_id NOT interpreted as count | VERIFIED ✅ |
| setup_fingerprint available | VERIFIED ✅ |
| Neither definition modified | VERIFIED ✅ |
| setup_id in market_snapshots_5m | VERIFIED ✅ |
| setup_id in market_evidence_5m | VERIFIED ✅ |
| same_setup_fingerprint in paper_trades | VERIFIED ✅ |

## RESEARCH READINESS

When market data becomes available, analysis will answer:
1. How many unique setup fingerprints? → COUNT DISTINCT
2. How many paper trades per fingerprint? → GROUP BY COUNT
3. How often does same setup recur? → TIMESTAMP comparison
4. Re-entry frequency? → reentry_log analysis
5. Regime changes per setup? → regime_changed field

## INSUFFICIENT DATA

Setup fingerprint analysis requires live market data.
Current state: PRE-MARKET (0 records).
