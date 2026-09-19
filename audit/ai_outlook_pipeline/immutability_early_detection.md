# Data Immutability & Early Detection Audit

Date: 2026-09-18

## Data Immutability

### ai_outlooks (Legacy)
| Protection | Status |
|-----------|--------|
| UPDATE allowed | YES — no triggers or constraints preventing updates |
| DELETE allowed | YES — no protections |
| INSERT OR REPLACE | YES — used in data_fetcher_db.py (can overwrite) |
| Audit trail | NO — no change log |
| Updated_at | NO — no timestamp on updates |

**Finding**: ai_outlooks rows CAN be overwritten by data_fetcher_db.py (INSERT OR REPLACE). The twice-daily outlook.py also uses INSERT OR REPLACE. This means outlooks can be silently overwritten.

### ai_outlooks_5m (Intraday)
| Protection | Status |
|-----------|--------|
| UPDATE allowed | YES |
| DELETE allowed | YES |
| INSERT OR REPLACE | YES — used by scheduler's _store_outlook() |
| UNIQUE constraint | outlook_id — prevents exact duplicates |
| Audit trail | NO |

**Finding**: If the scheduler were enabled, it would INSERT OR REPLACE outlooks, potentially overwriting previous values without notice.

### market_outlooks (Daily)
| Protection | Status |
|-----------|--------|
| UPDATE allowed | YES |
| DELETE allowed | YES |
| UNIQUE(date, symbol) | Prevents duplicate daily entries |
| Audit trail | NO |

### Other Tables (Trade Journal, etc.)
Per AGENTS.md: Trade journal is immutable (planned entry, actual entry, stop, target, risk never changed). Only notes, mistake, user_action, user_reason can be updated (creates audit events).

## Early Detection Mechanisms

### 1. outlook_change_detector.evaluate()
**Purpose**: Detect material changes in market state that might require AI outlook regeneration
**Status**: WORKING (verified via /api/outlook/5m/changes/<symbol>)
**Limitation**: Only detects changes in:
- Regime change
- Confidence swing (>15 points)
- VIX move (>5 points)
- Price move (>1%)
- Bias reversal
**Does NOT detect**:
- Data quality degradation
- Missing data feeds
- Stale indicators
- Options data unavailability

### 2. needs_ai_outlook()
**Purpose**: Check if AI outlook needs regeneration based on age and material changes
**Status**: WORKING
**Limitation**: Uses MAX_OUTLOOK_AGE_MINUTES=30, OUTLOOK_AGE_WARN_MINUTES=15 — but these apply to ai_outlooks table age, not ai_outlooks_5m (which is empty)

### 3. Data Freshness (Live API)
**Purpose**: Track how stale data is via age_minutes/age_status
**Status**: WORKING for ai_outlooks (FRESH/AGING/STALE)
**Not working for**: 5m pipeline (no data to check)

### 4. Missing Early Detection
| Gap | Description |
|-----|-------------|
| No pipeline health check | No monitoring of ai_outlooks_5m population rate |
| No data coverage alert | No alert when 5m tables are empty |
| No generation failure alert | No alert when AI generation fails |
| No scheduler monitoring | No alert when outlook_scheduler hasn't run |
| No quality degradation alert | No alert when data_quality drops |

## Findings

1. **No immutability protection** on any AI outlook table — all can be overwritten
2. **No audit trail** for AI outlook changes — cannot tell when/what changed
3. **Early detection is partial** — material change detection works, but pipeline health monitoring is absent
4. **No data coverage alerting** — if 5m tables are empty, nobody is notified
5. **The twice-daily overwrite** of ai_outlooks by data_fetcher_db.py is a silent operation

## Recommendations

1. Add audit triggers or updated_at columns to AI outlook tables
2. Add pipeline health monitoring (scheduler run check, table population rate)
3. Add alerts when ai_outlooks_5m is empty during market hours
4. Consider making ai_outlooks append-only (separate table or soft delete)
5. Add data quality degradation detection
