# Outcome Linkage & Resource Usage Audit

Date: 2026-09-18

## AI Outlook Outcome Tracking

### ai_outcome_predictions Table
| Metric | Value |
|--------|-------|
| Total rows | **0** |
| Schema | (id, outlook_id, symbol, entry_price, reference_price, horizon_minutes, future_return_pct, correct, mfe_pct, mae_pct, bias, recorded_at, evaluated_at, status, created_at) |
| Purpose | Track whether AI outlook predictions were correct |
| Status | **EXISTS BUT EMPTY** |
| Expected population | When trades from AI outlook positions are evaluated |

### Why Empty
1. AI outlook predictions require a trade to be taken based on the outlook
2. The 5-minute AI outlook pipeline is broken → no 5m outlooks → no predictions
3. The twice-daily outlook.py doesn't track outcomes
4. No code path connects ai_outlooks → ai_outcome_predictions

### Research Outcome Tracking (Existing)
| Table | Rows | Notes |
|-------|------|-------|
| research_outcome_tracking | 61,672 | POPULATED — tracks paper trade outcomes |
| research_data_health | 219 | POPULATED |
| research_setup_identity | 0 | EMPTY — needs paper_trades |
| research_reentry_log | 0 | EMPTY — depends on setups |

### outcome_linkage Gap
The ai_outcome_predictions table is designed to track outcomes of AI outlook predictions, but:
1. No code populates it
2. The twice-daily outlook doesn't track which trades were based on it
3. The 5-minute pipeline is broken
4. research_outcome_tracking tracks paper trade outcomes but doesn't link to AI outlooks

### Evidence Linkage (what_ai_knew vs what_ai_didnt)
Per Phase 5 architecture:
- Replay snapshots preserve: timestamp, indicators version, data quality, evidence
- Strict no-lookahead: only data ≤ timestamp is used
- Every snapshot preserves what AI knew vs didn't know

**Status**: This is a design principle, not a database field. Implementation exists in replay_engine.py but not in production outlook generation.

## Resource Usage

### LLM API Costs
| Metric | Value | Notes |
|--------|-------|-------|
| Twice-daily LLM calls | ~2/day/symbol × 4 symbols = 8 calls/day | At 9AM and 7PM IST |
| 5-minute LLM calls | **0** | Scheduler never runs |
| Total LLM calls (daily) | ~8 | Very low frequency |
| research_ai_call_log | 0 rows | Never populated |
| Token tracking | NONE | No token usage recorded anywhere |
| Latency tracking | NONE | No latency recorded |
| Cost per day | Unknown | Cannot calculate without token data |

### Database Size
| Component | Size |
|-----------|------|
| Total database | 264MB |
| ai_outlooks | ~15MB (estimated, 39K rows of JSON) |
| market_outlooks | ~100KB |
| market_snapshots_5m | 0 |
| ai_outlooks_5m | 0 |
| research_outcome_tracking | ~200MB (estimated, 61K rows) |
| Other tables | ~60MB (estimated) |

### CPU/Memory
| Component | Usage |
|-----------|-------|
| Gunicorn (3 workers) | ~5-6% each |
| AI generation (LLM) | Occasional spikes during twice-daily runs |
| Nginx | Minimal |
| Database | 264MB on disk |

### Cron Jobs (AI Outlook Related)
| Schedule | Job | Status |
|----------|-----|--------|
| 0 9 * * 1-5 | outlook.py (LLM outlook) | WORKING |
| 0 19 * * 1-5 | outlook.py (LLM outlook) | WORKING |
| * 9-15 * * 1-5 | data_fetcher_db.py (rule-based) | WORKING |
| */5 9-15 * * 1-5 | monitor.py (research collection) | WORKING (but 5m data empty) |
| NEVER | outlook_scheduler.py | NOT TRIGGERED |

## Findings

1. **AI outcome tracking is completely non-functional** — ai_outcome_predictions has 0 rows and no population path
2. **No cost tracking** — LLM usage is untracked
3. **No latency tracking** — cannot measure AI generation speed
4. **research_setup_identity is empty** — dependent on paper_trades which may be empty
5. **Resource usage is minimal** — only 8 LLM calls per day, very lightweight
6. **The 5-minute pipeline resource savings** are actually a problem — no AI calls means no cost savings from caching/deduplication

## Recommendations

1. Create a population path for ai_outcome_predictions (link from trades to outlooks)
2. Add token usage and latency tracking to all LLM calls
3. Connect research_outcome_tracking to AI outlook IDs
4. Monitor resource usage when 5-minute pipeline is enabled (could be 12 LLM calls/hour during market = significant cost increase)
5. Consider cost capping for the 5-minute AI outlook generation
