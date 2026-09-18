# Phase 42A.2 — Outcome Tracking

**Date**: 2026-09-18
**Phase 41**: FROZEN

---

## OUTCOME TRACKING OVERVIEW

| Item | Status |
|------|--------|
| research_outcome_tracking records | 0 |
| 5m outcomes | PENDING (no trades) |
| 15m outcomes | PENDING (no trades) |
| 30m outcomes | PENDING (no trades) |
| 60m outcomes | PENDING (no trades) |
| Outcome maturation | BLOCKED (no active trades) |

## OUTCOME TRACKING INFRASTRUCTURE

### research_outcome_tracking Schema

Tracks future outcomes for each paper trade decision:
- outcome_5m (PENDING until T+5m elapsed)
- outcome_15m (PENDING until T+15m elapsed)
- outcome_30m (PENDING until T+30m elapsed)
- outcome_60m (PENDING until T+60m elapsed)
- original_decision_data (frozen at decision time T)
- future_data (populated only after horizon elapsed)

### Look-Ahead Protection

For a decision at timestamp T:
- T+5 data CANNOT affect the original T decision ✅
- T+15 data CANNOT affect the original T decision ✅
- T+30 data CANNOT affect the original T decision ✅
- T+60 data CANNOT affect the original T decision ✅

Outcome data is stored separately from decision data.
Original outlook values remain IMMUTABLE after storage.

## OUTCOME MATURATION RULES

### Populated When
- 5m outcome: eligible when current_time >= decision_time + 5 minutes
- 15m outcome: eligible when current_time >= decision_time + 15 minutes
- 30m outcome: eligible when current_time >= decision_time + 30 minutes
- 60m outcome: eligible when current_time >= decision_time + 60 minutes

### Remains PENDING When
- Market closes before horizon elapsed → PENDING (documented)
- Session ends before horizon → PENDING (documented)
- No trade exists → N/A (no outcome to track)

## PAPER TRADE VERIFICATION

### Current State

**NO PAPER TRADES TODAY** — Expected pre-market.

### Paper Trade Safety

| Check | Result |
|-------|--------|
| Broker order API | NOT USED ✅ |
| Automatic BUY | NOT EXECUTED ✅ |
| Automatic SELL | NOT EXECUTED ✅ |
| Real-money execution | NOT POSSIBLE ✅ |
| Paper status | ALL TRADES ARE PAPER ✅ |
| Zerodha connection | NOT USED ✅ |
| Order placement | NEVER PERFORMED ✅ |

### Paper Trade Fields (When Active)

Each paper trade will capture:
- paper status (PAPER) ✅
- instrument ✅
- strategy ✅
- direction ✅
- outlook ID ✅
- evidence ID ✅
- setup identity ✅
- entry condition ✅
- risk ✅
- target/stop ✅
- initial target (for research comparison) ✅
- entry timestamp ✅
- entry price ✅
- engine version ✅

## TRADE QUALIFICATION

### Current State

**NO QUALIFICATION EVALUATION TODAY** — No completed candles.

### Allowed Qualification States

| State | Meaning |
|-------|---------|
| TRADE | Entry window active, valid levels, GO |
| WAIT | Conditions forming, not ready |
| NO_SETUP | No trade warranted |

### Verification (When Active)

- [ ] Qualification uses frozen Phase 41 logic
- [ ] No threshold modifications
- [ ] No strategy selection changes
- [ ] No entry condition modifications
- [ ] No exit condition modifications
- [ ] No cooldown added
- [ ] No deduplication added
- [ ] No trade filtering added
- [ ] Number of TRADE states NOT artificially increased

## RE-ENTRY INSTRUMENTATION

### Current State

research_reentry_log has 0 records — no re-entries observed (pre-market).

### Re-Entry Fields (When Active)

| Field | Purpose |
|-------|---------|
| previous_trade_id | Links to prior trade |
| seconds_since_previous_exit | Time gap |
| same_setup_fingerprint | Setup similarity |
| direction_changed | Direction change flag |
| regime_changed | Regime change flag |
| evidence_changed | Evidence change flag |
| outlook_changed | Outlook change flag |
| re-entry classification | Research classification |

### Important: Research Records, Not Trade Decisions

The re-entry system RECORDS re-entry. It does NOT:
- ❌ Reject re-entry
- ❌ Impose cooldown
- ❌ Alter trade behavior

## SETUP ID VS SETUP FINGERPRINT

### Definitions (NOT MODIFIED)

**setup_id**: Event identity based on `instrument + timestamp + direction`
- NOT an independent setup count
- Identifies a specific event occurrence

**setup_fingerprint**: Available for future analysis of repeated/similar setups
- For analysis purposes only
- Does NOT affect trade decisions

### Verification (When Active)

- [ ] setup_id is event-based (instrument + timestamp + direction)
- [ ] setup_id NOT interpreted as count
- [ ] setup_fingerprint available for analysis
- [ ] Neither definition modified
