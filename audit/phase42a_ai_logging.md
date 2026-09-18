# Phase 42A — AI Logging Design

**Date**: 2026-09-17
**Phase 41**: FROZEN
**Priority**: HIGH — AI attribution requires this data

---

## Design Requirements

1. Every actual production AI outlook must be stored
2. Every AI API call must be logged (success or failure)
3. No fabricated historical AI data
4. AI prompts are NOT stored (privacy)
5. No secrets in AI call log
6. Model/version information recorded
7. AI call data separated from trade decision data

## What Is Logged

### AI Call Log (research_ai_call_log)

| Field | Stored | Notes |
|-------|--------|-------|
| call_timestamp | YES | UTC timestamp of API call |
| instrument | YES | Target instrument |
| candle_timestamp | YES | Associated candle |
| trigger | YES | What triggered the call |
| model | YES | Model name (groq, etc.) |
| provider | YES | Provider name |
| prompt_version | YES | Template version (NOT content) |
| success | YES | 1 or 0 |
| latency_ms | YES | NULL if unavailable |
| token_usage | YES | NULL if unavailable |
| error | YES | NULL if success |
| fallback_used | YES | 1 if fallback was used |
| outlook_id | YES | Associated outlook ID |
| data_version | YES | Data version at call time |

### What Is NOT Logged

- API keys or credentials
- Full prompt text (only version reference)
- Full response text (stored in ai_outlooks_5m)
- User data or PII
- Internal system details

## AI Outlook Storage

AI outlooks are stored in existing `ai_outheads_5m` table with added `generated_success` field.

## AI Call vs Trade Decision

AI calls are logged independently of trade decisions:
- An AI call may happen without a trade (NO_TRADE)
- A trade may happen with stale AI data
- An AI call may fail (fallback used)

All scenarios are recorded separately.

## Historical Data

**NO** historical AI calls will be fabricated or recreated.

Only AI calls that occur AFTER Phase 42A deployment are logged.

Future researchers will need sufficient prospective AI data before performing AI attribution analysis.

## Research Questions This Enables

1. How often does AI generate outlooks?
2. What is AI success/failure rate?
3. What is AI latency?
4. How often does AI suggest TRADE vs NO_TRADE?
5. When does AI fail and what happens to trades?
6. What is the relationship between AI confidence and outcomes?
7. Does AI add value beyond deterministic evidence?

## Production Safety

- AI call logging does NOT affect AI call behavior
- No change to minimum AI interval
- No change to maximum session calls
- No change to material-change trigger
- No change to timeout or retry policy
- Logging is best-effort: if logging fails, AI call still proceeds
