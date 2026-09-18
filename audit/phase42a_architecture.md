# Phase 42A — Architecture

**Date**: 2026-09-17
**Phase 41**: FROZEN
**Phase 42A**: INSTRUMENTATION ONLY

---

## Architecture Overview

```
Production Pipeline (UNCHANGED)
    │
    ▼
DATA → MARKET SNAPSHOT → EVIDENCE → MARKET STATE → AI OUTLOOK → TRADE QUALIFICATION → STRATEGY → PAPER TRADE → OUTCOME
    │
    ▼
Research Instrumentation Layer (NEW)
    │
    ▼
┌─────────────────────────────────────────────────┐
│             Research Data Collection              │
│                                                   │
│  ┌──────────────┐ ┌───────────────┐ ┌──────────┐│
│  │ Setup        │ │ Re-entry      │ │ AI Call  ││
│  │ Identity     │ │ Log           │ │ Log      ││
│  └──────────────┘ └───────────────┘ └──────────┘│
│  ┌──────────────┐ ┌───────────────┐ ┌──────────┐│
│  │ Outcome      │ │ Data Health   │ │ Manifest ││
│  │ Tracking     │ │               │ │          ││
│  └──────────────┘ └───────────────┘ └──────────┘│
└─────────────────────────────────────────────────┘
    │
    ▼
SQLite Research Tables (IMMMUTABLE, APPEND-ONLY)
    │
    ▼
Research Export API (READ-ONLY)
    │
    ▼
CSV/SQLite Export for Analysis
```

## Design Principles

| Principle | Implementation |
|-----------|---------------|
| **Immutable** | All research tables are append-only. UPDATE only allowed on `research_data_health` (status changes). No DELETE. |
| **Timestamped** | Every record has `created_at` (UTC) and event-specific timestamp (`candle_timestamp`, `check_timestamp`, etc.) |
| **Versioned** | Every record has `engine_version` field |
| **Reproducible** | Setup IDs are deterministic hashes of input fields |
| **Look-ahead safe** | Outcome tracking uses separate table from decision records |
| **Production-safe** | Research collection is best-effort. Failures are logged, never crash production |

## Database Schema

### New Research Tables (6)

| Table | Purpose | Key Fields |
|-------|---------|-----------|
| `research_setup_identity` | Records every setup identity | setup_id, setup_fingerprint, instrument, candle_timestamp, direction, regime, trade_state, strategy |
| `research_reentry_log` | Records re-entry relationships | trade_id, previous_trade_id, seconds_since_previous_exit, same_setup_fingerprint, direction_changed |
| `research_ai_call_log` | Records every AI call | call_timestamp, instrument, trigger, model, success, latency, token_usage, error |
| `research_outcome_tracking` | Future outcomes (5m/15m/30m/60m) | outlook_id, outcome_5m-60m, evaluated_at (FUTURE fields separate from decision) |
| `research_data_health` | Data quality checks | check_type, status, instrument, detail |
| `research_manifest` | Dataset manifest | dataset_name, schema_version, row_count, earliest/latest, instruments, missingness |

### Modified Existing Tables (3)

| Table | New Columns | Purpose |
|-------|------------|---------|
| `market_snapshots_5m` | `setup_id` | Link snapshot to setup identity |
| `market_evidence_5m` | `setup_id` | Link evidence to setup identity |
| `ai_outlooks_5m` | `generated_success` | Track AI generation success/failure |
| `paper_trades` | `previous_trade_id`, `seconds_since_previous_exit`, `same_setup_fingerprint` | Re-entry tracking |

## Integration Points

### Where Research Data Is Collected

1. **Setup Identity**: At each paper trade qualification (TRADE status)
2. **Re-entry**: At each paper trade entry (new record)
3. **AI Call**: At each AI outlook generation (real call)
4. **Outcome**: At each 5m/15m/30m/60m candle close for active outlook
5. **Data Health**: At scheduled health check intervals

### What Does NOT Change

- Trading qualification logic
- Evidence calculation
- Strategy selection
- AI outlook generation logic
- Trade entry/exit rules
- Stop/target determination
- All frozen model files

## Research Tables vs Production Tables

| Aspect | Production Tables | Research Tables |
|--------|------------------|----------------|
| Purpose | Trading decisions | Research analysis |
| Access | API, Frontend | Internal/research export only |
| Retention | Current state + history | Append-only |
| Update | UPDATE allowed | UPDATE restricted |
| Deletion | N/A | Never |
| Public access | Yes (API) | No (read-only export) |

## Performance Design

| Concern | Mitigation |
|---------|-----------|
| DB writes on every trade | Async insert if needed (current: sync, low volume) |
| DB size growth | Estimated 1-5 MB/day at current trade frequency |
| Query performance | Indexes on all timestamp and instrument fields |
| Memory impact | Minimal (connection pool shared) |
| CPU impact | Negligible (hashing, string operations) |
