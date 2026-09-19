# Data Provenance & Freshness Audit

Date: 2026-09-18

## Provenance Tracking

### ai_outlooks (Legacy — Twice-Daily)
| Field | Status |
|-------|--------|
| timestamp | YES — ISO 8601 UTC timestamp per row |
| data_quality | YES — GOOD/STALE/UNAVAILABLE per row |
| source/generator | IMPLICIT — ai_outlooks from outlook.py or data_fetcher_db.py (cannot distinguish) |
| model_version | NO — not stored in ai_outlooks schema |
| prompt_version | NO — not stored in ai_outlooks schema |
| LLM vs template | IMPLICIT — LLM from outlook.py, template from data_fetcher_db.py |
| created_at | NO — only timestamp field |

### ai_outlooks_5m (Intraday — 5-Minute)
| Field | Status |
|-------|--------|
| outlook_id | YES — unique ID format: OUTLOOK-{SYMBOL}-{timestamp} |
| generated_at | YES — ISO 8601 UTC |
| candle_timestamp | YES — the 5m candle time |
| model | YES — "groq" |
| model_version | YES — "v1" |
| prompt_version | YES — "5m-v1" |
| data_state | YES — LIVE/DELAYED/UNAVAILABLE |
| generated_success | YES — column exists but always 0 (not set by _store_outlook) |
| data_snapshot_id | Column exists but always NULL (not set by _store_outlook) |
| engine_version | NO — not stored in ai_outlooks_5m schema |
| created_at | YES — same as generated_at |

### market_outlooks (Daily)
| Field | Status |
|-------|--------|
| date | YES — YYYY-MM-DD |
| created_at | YES — timestamp of creation |
| UNIQUE(date, symbol) | YES — prevents duplicates |
| payload version | NO — schema not versioned |
| LLM vs template | IMPLICIT — from outlook.py LLM path |

### market_snapshots_5m
| Field | Status |
|-------|--------|
| candle_timestamp | YES |
| snapshot_time | YES |
| created_at | YES |
| data_quality | YES — LIVE/UNAVAILABLE |
| engine_version | YES — ENGINE_VERSION from snapshot.py |
| setup_id | YES (nullable) |

### market_evidence_5m
| Field | Status |
|-------|--------|
| evidence_id | YES |
| candle_timestamp | YES |
| generated_at | YES |
| engine_version | YES |
| created_at | YES |
| data_quality | YES — GOOD/UNAVAILABLE |
| data_state | YES — LIVE/UNAVAILABLE |

## Freshness Tracking

### AI Outlook Age (Live API)
| Metric | Value |
|--------|-------|
| Current outlook age | 14 minutes (as of audit time) |
| Max fresh age | 30 minutes (MAX_OUTLOOK_AGE_MINUTES) |
| Warn threshold | 15 minutes (OUTLOOK_AGE_WARN_MINUTES) |
| Current status | FRESH (14 < 15) |
| Last update | 2026-09-18T16:40:20Z (NIFTY) |

### How Age is Computed
In api_ai_outlook():
```python
generated_dt = datetime.fromisoformat(current["generated_at"].replace("Z", "+00:00"))
age_seconds = (datetime.now(timezone.utc) - generated_dt).total_seconds()
current["age_seconds"] = round(age_seconds)
current["age_minutes"] = round(age_seconds / 60)
if age_seconds > MAX_OUTLOOK_AGE_MINUTES * 60:
    current["age_status"] = "STALE"
elif age_seconds > OUTLOOK_AGE_WARN_MINUTES * 60:
    current["age_status"] = "AGING"
else:
    current["age_status"] = "FRESH"
```

### Data Timestamps (Latest)
| Table | Latest Timestamp | Age at Audit |
|-------|-----------------|--------------|
| ai_outlooks (NIFTY) | 2026-09-18T16:40:20Z | ~18 min |
| ai_outlooks_5m | N/A | N/A — 0 rows |
| market_snapshots_5m | N/A | N/A — 0 rows |
| market_evidence_5m | N/A | N/A — 0 rows |
| market_outlooks (NIFTY) | 2026-09-18 | Today |
| price_5m (NIFTY) | 2026-09-18T04:25:00Z | 17h 29m (market closed) |
| indicators (NIFTY) | Recent | Fresh |
| market_regime (NIFTY) | Recent | Fresh |
| vix_data | Recent | Fresh |
| price_1m (NIFTY) | Recent | Fresh |

## Key Findings

1. **ai_outlooks_5m schema has versioning fields** (model_version, prompt_version) but **no engine_version** — unlike other tables
2. **generated_success column** exists but is never set to 1 (default 0)
3. **data_snapshot_id** column exists but is never populated
4. **ai_outlooks schema doesn't distinguish LLM vs template** — cannot tell which generator produced a row
5. **market_outlooks has NO versioning** — no schema version, no prompt version, no model version
6. **Freshness tracking works** for ai_outlooks (age_minutes, age_status) but NOT for 5m pipeline (no data to check)
7. **No audit trail** for outlook modifications — no updated_at, no modifier, no change log
8. **market_change table** provides some temporal tracking (is_material_change compares current vs previous)

## Schema Version Field
db_schema.py line 1016-1019 adds `generated_success INTEGER DEFAULT 0` to ai_outlooks_5m. This was likely added after initial creation but never populated.
