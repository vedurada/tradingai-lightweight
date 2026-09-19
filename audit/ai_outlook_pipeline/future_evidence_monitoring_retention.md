# Future Evidence, Monitoring & Audit Trail

Date: 2026-09-18

## Future Evidence (Section 26)

### Planned Enhancements (from user spec)

1. **Walk-forward validation** for AI outlooks (Phase 8 style)
2. **Historical evidence** linking AI outlooks to market outcomes
3. **Cross-validation** across symbols and timeframes
4. **A/B testing** framework for different AI models
5. **Performance attribution** (which market factors contributed to prediction accuracy)

### Prerequisites

- ai_outlooks_5m must have data
- ai_outcome_predictions must be populated
- research_ai_call_log must be populated
- outlook_changes table must exist

## AI Outlook Monitoring (Section 27)

### Current Monitoring

**Existing checks** (via /api/health):
- Database connectivity: OK
- Disk space: OK
- Health file: OK
- Freshness: check_data_freshness()

**data_fetcher_db.py freshness check**: Monitors last_fetch timestamps per data source.

### Missing Monitoring for AI Outlook Pipeline

| What | Current | Needed |
|------|---------|--------|
| ai_outlooks_5m row count | Not monitored | Alert if 0 during market hours |
| LLM call success rate | Not tracked | Track via research_ai_call_log |
| LLM latency | Not tracked | Track via research_ai_call_log |
| AI outlook freshness | Implicit (age_minutes) | Explicit monitoring/alerting |
| Scheduler execution | No monitoring | Alert if scheduler doesn't run |
| Material change frequency | Not tracked | Track via outlook_changes |
| AI prediction accuracy | Not tracked | Track via ai_outcome_predictions |

### Recommended Monitoring

1. Cron job to check ai_outlooks_5m row count every 5 min during market
2. Alert if ai_outlooks_5m has 0 rows between 9:30-15:30 IST
3. Dashboard showing AI outlook generation statistics
4. Alert if LLM call fails >3 times in a row
5. Monitor data_fetcher_db.py error count (already in health check)

## Audit Trail & Data Lineage (Section 28)

### Current Audit Trail

**For AI outlooks**: NONE
- No log of when ai_outlooks were generated
- No log of which model/version generated each outlook
- No log of prompt/response for LLM calls
- No log of template version used for rule-based outlooks

**For database**: 
- No change tracking (no audit tables)
- No data lineage (can't trace data from source to final output)

**For research_ai_call_log**: EXISTS but EMPTY — would provide audit trail if populated.

### What Needs to Be Auditable

1. **Generation event**: When, which symbol, which model, which prompt version, success/failure
2. **Storage event**: When stored, which table, row ID, data hash
3. **API access**: When endpoints called, by whom, what data returned
4. **Data source**: Where input data came from, freshness, quality
5. **Change detection**: What changed, when, trigger for regeneration

### Recommended Implementation

1. Populate research_ai_call_log for every AI call
2. Add generation_log table: timestamp, symbol, model, prompt_version, success, latency
3. Add data_lineage table: source_table, target_table, sync_timestamp, row_count
4. Log all scheduler runs (success/failure) to a scheduler_log table

## Data Retention, Backfill, Recovery (Section 29)

### Data Retention

| Table | Retention Policy | Status |
|-------|-----------------|--------|
| ai_outlooks | No explicit policy — grows forever | 39,148 rows |
| ai_outlooks_5m | No explicit policy — N/A | 0 rows |
| market_outcomes | No explicit policy — 206 rows | Growing at ~260/yr |
| market_change_snapshots | No explicit policy | Unknown |
| research_outcome_tracking | No explicit policy | 61,672 rows |
| research_data_health | No explicit policy | 219 rows |

**VM disk**: 45GB total, data is ~264MB — plenty of space currently.

### Backfill Capability

**Existing backfill scripts**:
- backfill_yearly.py: Yearly historical data backfill (runs weekly on Sundays)
- backfill_indices_10y.py: 10-year index data backfill
- backfill_outlooks.py: Outlook backfill (3650 days, overwrite)

**Note from AGENTS.md**: backfill_outlooks.py --days 3650 --overwrite can regenerate outlook history.

### Recovery Procedures

**From backup**:
1. Stop gunicorn: systemctl stop tradingai-api
2. Restore database: cp backup.db /opt/tradingai/database/tradingai.db
3. Start gunicorn: systemctl start tradingai-api
4. Verify: curl https://tradingai.in/api/health

**From VM snapshot**: VM-level backup at /opt/tradingai/ops/vm-backup.sh (daily at 18:00)

## Cross-Page AI Outlook Workflow Validation

### Current Workflow

1. User visits /today → loads /api/ai-outlook/NIFTY → renders AI outlook section
2. User visits /indices/nifty.html → loads /api/NIFTY → renders ai_outlook narrative
3. User visits / → loads /api/market-outlook?symbol=NIFTY → renders daily outlook

### Validation Status

| Workflow | Status | Issue |
|----------|--------|-------|
| Today → AI outlook | WORKING (after fix) | Was broken (regimeText missing) |
| Index pages → AI outlook | WORKING | Uses template-based data |
| Home → daily outlook | WORKING | Cached 1 hour |
| Options → AI outlook | N/A | Options separate from outlook |
| Journal → AI outlook | N/A | Trade comparison uses journal data |

### Known Cross-Page Issues (from PHASE 29)

1. `/home.html` publicly reachable despite 301 config
2. `/today/index.html` calls 3 nonexistent endpoints
3. `/api/market-outlook` returns raw object; /today expects `{outlook: ...}` wrapper
4. `/` vs `/index.html` canonical relationship unverified
