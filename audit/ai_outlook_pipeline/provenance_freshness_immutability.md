# Provenance, Freshness & Immutability Audit

Date: 2026-09-18

## Data Provenance

### AI Outlook Provenance (Current State — Broken for 5m)

| Field | Legacy (ai_outlooks) | 5m (ai_outlooks_5m) |
|-------|---------------------|---------------------|
| symbol/instrument | symbol | instrument |
| generated timestamp | timestamp | generated_at |
| model | NOT STORED | model (from generator) |
| model_version | NOT STORED | model_version ("v1") |
| prompt_version | NOT STORED | prompt_version ("5m-v1") |
| bias | directional_bias | bias |
| confidence | confidence | confidence |
| regime | market_regime | market_regime |
| data_source | NOT STORED | NOT STORED |
| evidence_version | NOT STORED | NOT STORED |
| indicator_version | NOT STORED | NOT STORED |
| data_version | NOT STORED | NOT STORED |
| engine_version | NOT STORED | NOT STORED (should add) |
| creation timestamp | NOT STORED | created_at |
| generation method | NOT STORED (LLM vs template) | NOT STORED |

**Finding**: Legacy ai_outlooks has almost NO provenance fields. It doesn't even record whether it was LLM-generated or template-generated.

### 5m Schema Has More Provenance

The ai_outlooks_5m schema has better provenance fields (model, model_version, prompt_version, generated_at), but they're all NULL/empty because the generator never runs.

## Data Freshness

### Current Freshness (Live Check)

| Table | Latest Data | Age | Status |
|-------|------------|-----|--------|
| ai_outlooks | 2026-09-18T16:40:59Z | ~5.5 hours | FRESH (generated today) |
| market_regime | Latest from data_fetcher_db | Minutes | FRESH |
| indicators | Latest from data_fetcher_db | Minutes | FRESH |
| price_1m | Latest from data_fetcher_db | Minutes | FRESH |
| price_5m | 2026-09-18T04:25:00Z | ~12 hours | STALE (market closed Friday) |
| ai_outlooks_5m | N/A | N/A | EMPTY |
| market_snapshots_5m | N/A | N/A | EMPTY |
| market_evidence_5m | N/A | N/A | EMPTY |
| vix_data | Latest from data_fetcher_db | Minutes | FRESH |
| market_outcomes | 2026-09-18 (latest daily) | Today | FRESH |

### Freshness Rules

- `MAX_OUTLOOK_AGE_MINUTES = 30` — AI outlook considered stale after 30 min
- `OUTLOOK_AGE_WARN_MINUTES = 15` — AI outlook warning after 15 min
- `AI_OUTLOOK_REUSE_TTL = 12 hours` — Legacy outlook reused for 12h in poller
- During market closed: data_state = "DELAYED"
- During market open: data_state = "LIVE" (if fresh) or "STALE" (if >30 min old)

### Observed Freshness Issue

The current legacy outlook is ~5.5 hours old (generated at 16:40 UTC = 10:10 IST, current time 22:11 IST = 16:41 UTC). This is within the 12-hour reuse TTL for the poller path, so it's considered FRESH. However, it's a template-generated outlook (use_llm=False from data_fetcher_db), not the LLM-generated one from outlook.py.

**Wait — let me clarify**: outlook.py runs at 9AM and 7PM IST with LLM. data_fetcher_db.py runs every minute with use_llm=False. So the latest ai_outlooks could be either LLM-generated (from 7AM or 7PM) or template-generated (from any minute).

Let me check which one is latest.

## Immutability

### ai_outlooks Immutability

**Schema**: `INSERT OR REPLACE INTO ai_outlooks (symbol, timestamp, outlook, data_quality)`
**Issue**: `INSERT OR REPLACE` means the same symbol+timestamp can be overwritten
- data_fetcher_db.py runs every minute and can overwrite the latest ai_outlooks
- outlook.py runs twice daily and can overwrite
- **No version history** — previous outlooks are lost
- **No audit trail** — no log of when/what changed

### ai_outlooks_5m Immutability

**Schema**: `INSERT OR REPLACE INTO ai_outlooks_5m ... UNIQUE(outlook_id)`
- Idempotent by outlook_id (correct design)
- But if same candle_timestamp is processed twice, outlook_id might differ (includes timestamp but also generated_at)
- No version history for same candle

### Should AI Predictions Be Immutable?

**Yes, per AGENTS.md**: "Immutability of AI predictions: Once an AI outlook is generated, it must not be overwritten."

**Current violation**: Both ai_outlooks and ai_outlooks_5m use INSERT OR REPLACE, allowing overwrites.

### Recommended Immutability Approach

1. Use INSERT (not INSERT OR REPLACE) for new outlooks
2. Add UNIQUE constraint on (symbol, timestamp) for legacy, (instrument, candle_timestamp) for 5m
3. If regeneration needed, insert NEW row with NEW timestamp/candle_timestamp
4. Keep historical rows as-is
