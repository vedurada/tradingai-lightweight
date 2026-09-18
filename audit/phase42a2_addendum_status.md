# Phase 42A.2 — Addendum Status: Exit-Lifecycle Instrumentation

**Date**: 2026-09-18
**Phase 41**: FROZEN

---

## ADDENDUM REFERENCE

The Phase 42A.2 prompt includes an ADDENDUM for paper trade / backtest position management (EXIT-LIFECYCLE INSTRUMENTATION).

## CURRENT STATUS

### NOT IMPLEMENTED

The exit-lifecycle instrumentation has NOT been implemented during Phase 42A.2.

### Reason

Phase 42A.2 is a PRODUCTION OBSERVATION + VALIDATION task. Its purpose is to verify deployed research infrastructure, not implement new features.

### Addendum Requirements Summary

| Category | Count | Status |
|----------|-------|--------|
| Exit lifecycle management | 16 sections | PENDING |
| Bullish/Bearish management rules | 2 | PENDING |
| Exit reason tracking | 1 | PENDING |
| MFE/MAE measurement | 2 | PENDING |
| Tests required | 22 | PENDING |
| Safety rules | Multiple | TO BE VERIFIED |

### What the Addendum Requires (NOT Implemented)

1. Position monitoring on each completed 5m candle
2. Bullish trade management (HOLD/RIDE logic)
3. Bearish trade management (HOLD/RIDE logic)
4. Thesis reversal detection (BULLISH→BEARISH, BEARISH→BULLISH)
5. Exit priority framework (DATA_INVALIDATION > STOP > TARGET > REVERSAL > SESSION)
6. Same-candle ambiguity handling (INTRABAR_AMBIGUOUS)
7. MFE/MAE calculation
8. Exit reason persistence (7 allowed values)
9. Exit event log (ENTRY, TARGET_OBSERVED, STATE_CHANGED, REVERSAL, EXIT, etc.)
10. Initial target persistence (for research comparison)
11. AI vs deterministic exit separation
12. Backtest/replay compatibility
13. 22 required tests

### What the Addendum PROHIBITS

- ❌ No entry logic changes
- ❌ No trade qualification changes
- ❌ No evidence threshold changes
- ❌ No AI prompt changes
- ❌ No AI trigger changes
- ❌ No strategy selection changes
- ❌ No signal generation changes
- ❌ No setup identity changes
- ❌ No Phase 41 frozen logic changes
- ❌ No target percentage changes
- ❌ No stop percentage changes
- ❌ No threshold tuning
- ❌ No trailing stops
- ❌ No cooldowns
- ❌ No optimization
- ❌ No Phase 42B

### Addendum Not Authorized By

The Phase 42A.2 task does NOT authorize Phase 42B implementation.
The addendum requires separate authorization before implementation.

### Addendum Classification

POSITION-MANAGEMENT INSTRUMENTATION (NOT strategy optimization)

This is compatible with Phase 42A scope IF separately authorized, because:
- It does NOT change entry logic
- It does NOT change qualification rules
- It does NOT change AI prompts
- It does NOT change strategy selection
- It records exit behavior, does not influence it
- It adds measurement, does not add optimization

### Required Before Implementation

1. Separate authorization decision
2. Phase 41 frozen verification (ensure no frozen logic affected)
3. Schema design review
4. Exit priority methodology documentation
5. 22 required tests written and passing
6. Look-ahead protection verification
7. Backtest compatibility verification

### Current Research Comparison Capability

| Model | Status |
|-------|--------|
| Model A (Fixed target/stop) | EXISTS (current Phase 41 behavior) |
| Model B (Target + thesis-reversal) | NOT YET IMPLEMENTED |
| Model C (Target + thesis-reversal + trailing) | NOT YET IMPLEMENTED |

Model A data exists from paper_trades table (initial target, exit price, exit reason, exit timestamp).

## ADDENDUM ACTION REQUIRED

Separate task required: **PHASE 42 EXIT-LIFECYCLE INSTRUMENTATION**

This is NOT Phase 42B (no optimization, no strategy selection).
This requires explicit authorization before implementation begins.
