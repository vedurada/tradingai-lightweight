# Phase 42A.4 LIVE SESSION — Live Setup Analysis

**Date**: 2026-09-18
**Phase 41**: FROZEN
**Market State**: PRE-MARKET (07:14 IST)

---

## SETUP IDENTITY STATUS

| Metric | Value | Status |
|--------|-------|--------|
| Total setup events | 0 | PRE-MARKET |
| Unique setup fingerprints | 0 | PRE-MARKET |
| Repeated fingerprints | 0 | PRE-MARKET |
| Trades per fingerprint | N/A | No trades |
| Time between repeated | N/A | No trades |

## SETUP ID DEFINITIONS (NOT MODIFIED)

### setup_id
Event identity: `instrument + candle_timestamp + direction`
- SHA256: `SETUP-{SHA256(...)[:16].upper()}`
- Identifies EACH decision event separately

### setup_fingerprint
Decision/setup identity: `instrument + trading_date + direction + regime + trade_state + strategy + evidence_state + ai_outlook_id`
- SHA256: `[:24].upper()`
- For analysis of repeated setups

## VERIFICATION

| Check | Result |
|-------|--------|
| setup_id is event-based | VERIFIED ✅ |
| setup_id NOT interpreted as count | VERIFIED ✅ |
| setup_fingerprint available | VERIFIED ✅ |
| Neither definition modified | VERIFIED ✅ |
| No filtering of repeated setups | VERIFIED ✅ |

## INSUFFICIENT DATA

Setup analysis requires live market data.
Current state: PRE-MARKET (0 records).
