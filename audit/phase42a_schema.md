# Phase 42A — Schema Documentation

**Date**: 2026-09-17
**Phase 41**: FROZEN

---

## New Research Tables

### research_setup_identity

**Purpose**: Records the identity of every trading setup for research analysis

| Field | Type | Description |
|-------|------|-------------|
| id | INTEGER | Auto-increment PK |
| setup_id | TEXT | Unique immutable setup identifier |
| setup_fingerprint | TEXT | Deterministic fingerprint for analysis |
| instrument | TEXT | NIFTY/BANKNIFTY/etc |
| candle_timestamp | TEXT | Exact decision timestamp |
| trading_date | TEXT | Trading date (IST) |
| direction | TEXT | BULLISH/BEARISH/NEUTRAL |
| regime | TEXT | Market regime at decision |
| trade_state | TEXT | TRADE/WAIT/NO_TRADE |
| strategy | TEXT | Selected strategy |
| evidence_summary | TEXT | JSON evidence state at decision |
| ai_outlook_id | TEXT | Associated AI outlook ID |
| qualification_id | TEXT | Associated qualification ID |
| setup_type | TEXT | NEW/CONTINUATION/REENTRY |
| is_duplicate_of | TEXT | If duplicate, ID of original |
| previous_setup_id | TEXT | Previous setup for same instrument |
| seconds_since_previous_same_direction | INTEGER | Time since last same-direction trade |
| regime_changed | INTEGER | 1 if regime changed from previous |
| direction_changed | INTEGER | 1 if direction changed from previous |
| evidence_changed | INTEGER | 1 if evidence state changed |
| outlook_changed | INTEGER | 1 if AI outlook changed |
| data_quality | TEXT | LIVE/STALE/MISSING/PARTIAL/UNAVAILABLE/INVALID |
| engine_version | TEXT | Code version that generated this |
| created_at | TEXT | Record creation timestamp (UTC) |

**Primary Key**: id
**Unique Constraints**: setup_id, (setup_fingerprint, candle_timestamp)
**Indexes**: instrument+candle_timestamp, setup_fingerprint
**DECISION_TIME fields**: candle_timestamp, trading_date, direction, regime, trade_state, strategy, evidence_summary, ai_outlook_id
**FUTURE_OUTCOME fields**: NONE
**Engine/Version**: engine_version
**Data Quality**: data_quality

### research_reentry_log

**Purpose**: Records re-entry relationships between trades

| Field | Type | Description |
|-------|------|-------------|
| id | INTEGER | Auto-increment PK |
| trade_id | TEXT | Current trade ID |
| instrument | TEXT | Instrument |
| candle_timestamp | TEXT | Decision timestamp |
| setup_id | TEXT | Associated setup ID |
| previous_trade_id | TEXT | Previous trade for same instrument |
| previous_exit_timestamp | TEXT | When previous trade exited |
| seconds_since_previous_exit | INTEGER | Time since previous exit |
| previous_direction | TEXT | Previous trade direction |
| current_direction | TEXT | Current trade direction |
| previous_regime | TEXT | Regime at previous trade |
| current_regime | TEXT | Regime at current trade |
| previous_setup_fingerprint | TEXT | Previous setup fingerprint |
| current_setup_fingerprint | TEXT | Current setup fingerprint |
| same_setup_fingerprint | INTEGER | 1 if same fingerprint |
| direction_changed | INTEGER | 1 if direction changed |
| regime_changed | INTEGER | 1 if regime changed |
| evidence_changed | INTEGER | 1 if evidence changed |
| outlook_changed | INTEGER | 1 if outlook changed |
| reentry_type | TEXT | SAME_SETUP/NEW_SETUP/UNKNOWN |
| data_quality | TEXT | Data quality status |
| engine_version | TEXT | Code version |
| created_at | TEXT | Record creation timestamp |

**Primary Key**: id
**Indexes**: instrument+candle_timestamp, trade_id
**DECISION_TIME fields**: candle_timestamp, direction, regime, setup_fingerprint
**FUTURE_OUTCOME fields**: NONE
**Engine/Version**: engine_version
**Data Quality**: data_quality

### research_ai_call_log

**Purpose**: Audit trail of every real AI API call

| Field | Type | Description |
|-------|------|-------------|
| id | INTEGER | Auto-increment PK |
| call_timestamp | TEXT | When AI call was made (UTC) |
| instrument | TEXT | Target instrument |
| candle_timestamp | TEXT | Associated candle timestamp |
| trigger | TEXT | What triggered the call |
| model | TEXT | AI model used |
| provider | TEXT | AI provider |
| prompt_version | TEXT | Prompt template version |
| success | INTEGER | 1=success, 0=failure |
| latency_ms | INTEGER | Response time in ms |
| token_usage | INTEGER | Token count (NULL if unavailable) |
| error | TEXT | Error message if failed |
| fallback_used | INTEGER | 1 if fallback was used |
| outlook_id | TEXT | Associated outlook ID |
| data_version | TEXT | Data version at call time |
| created_at | TEXT | Record creation timestamp |

**Primary Key**: id
**Unique Constraints**: (call_timestamp, instrument)
**Indexes**: instrument+call_timestamp
**DECISION_TIME fields**: call_timestamp, instrument, candle_timestamp
**FUTURE_OUTCOME fields**: NONE
**Engine/Version**: prompt_version
**Data Quality**: N/A (separate from decision records)

**Security**: No credentials stored. No API keys. No prompts stored.

### research_outcome_tracking

**Purpose**: Future market outcomes for AI outlook evaluation (separate from decision records)

| Field | Type | Description |
|-------|------|-------------|
| id | INTEGER | Auto-increment PK |
| outlook_id | TEXT | Associated AI outlook ID |
| setup_id | TEXT | Associated setup ID |
| instrument | TEXT | Instrument |
| candle_timestamp | TEXT | Decision timestamp |
| outcome_5m | TEXT | PENDING/WIN/LOSS/BREAKEVEN/INVALIDATED |
| outcome_5m_timestamp | TEXT | When 5m outcome was evaluated |
| outcome_5m_price | REAL | Price at 5m evaluation |
| outcome_5m_return_pct | REAL | Return percentage |
| outcome_5m_direction | TEXT | Direction of move |
| outcome_15m | TEXT | 15-minute outcome |
| ... | ... | Same pattern for 15m, 30m, 60m |
| evaluated_at | TEXT | Last evaluation timestamp |
| data_quality | TEXT | Data quality status |
| created_at | TEXT | Record creation timestamp |

**Primary Key**: id
**Unique Constraints**: (outlook_id, candle_timestamp)
**Indexes**: instrument+candle_timestamp, outlook_id
**DECISION_TIME fields**: candle_timestamp, instrument
**FUTURE_OUTCOME fields**: ALL outcome_* fields (5m/15m/30m/60m)
**Engine/Version**: N/A
**Data Quality**: data_quality

**Critical**: Outcome fields contain future information. They are stored SEPARATELY from the original AI outlook record. The original outlook record remains unchanged.

### research_data_health

**Purpose**: Periodic data quality health checks

| Field | Type | Description |
|-------|------|-------------|
| id | INTEGER | Auto-increment PK |
| check_timestamp | TEXT | When check was performed |
| instrument | TEXT | Target instrument (optional) |
| check_type | TEXT | Type of check |
| status | TEXT | VALID/STALE/MISSING/PARTIAL/UNAVAILABLE/INVALID |
| detail | TEXT | Human-readable detail |
| details_json | TEXT | JSON detail object |
| created_at | TEXT | Record creation timestamp |

**Primary Key**: id
**Indexes**: check_timestamp, instrument+check_timestamp
**DECISION_TIME fields**: check_timestamp
**FUTURE_OUTCOME fields**: NONE
**Engine/Version**: N/A
**Data Quality**: status

### research_manifest

**Purpose**: Dataset manifest for reproducibility

| Field | Type | Description |
|-------|------|-------------|
| id | INTEGER | Auto-increment PK |
| dataset_name | TEXT | Name of dataset |
| schema_version | TEXT | Schema version |
| source_tables | TEXT | Source table names |
| row_count | INTEGER | Total rows |
| earliest_timestamp | TEXT | Earliest data timestamp |
| latest_timestamp | TEXT | Latest data timestamp |
| instruments | TEXT | JSON array of instruments |
| missingness | TEXT | JSON object of missingness |
| generated_timestamp | TEXT | When manifest was generated |
| engine_version | TEXT | Code version |
| data_quality | TEXT | Data quality |
| created_at | TEXT | Record creation timestamp |

**Primary Key**: id
**Unique Constraints**: dataset_name

## Modified Existing Tables

### market_snapshots_5m (added column)

| New Column | Type | Description |
|------------|------|-------------|
| setup_id | TEXT | Link to research setup identity |

### market_evidence_5m (added column)

| New Column | Type | Description |
|------------|------|-------------|
| setup_id | TEXT | Link to research setup identity |

### ai_outlooks_5m (added column)

| New Column | Type | Description |
|------------|------|-------------|
| generated_success | INTEGER | 1=success, 0=failure |

### paper_trades (added columns)

| New Column | Type | Description |
|------------|------|-------------|
| previous_trade_id | TEXT | Previous trade for same instrument |
| seconds_since_previous_exit | INTEGER | Time since previous exit |
| same_setup_fingerprint | INTEGER | 1 if same fingerprint |
