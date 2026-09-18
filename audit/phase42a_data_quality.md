# Phase 42A — Data Quality Design

**Date**: 2026-09-17
**Phase 41**: FROZEN

---

## Standard Data Quality States

| State | Definition | Example |
|-------|-----------|---------|
| VALID | Data is complete and fresh | Recent candle with all indicators |
| STALE | Data is old but available | Candle older than 5 minutes |
| MISSING | Data is absent but expected | No VIX reading available |
| PARTIAL | Some fields missing | EMA available but RSI missing |
| UNAVAILABLE | Data source unavailable | Options chain not fetched |
| INVALID | Data is clearly wrong | Negative price, impossible value |

## Application Points

Every research event records its data quality:
- Snapshot: data_state field
- Evidence: data_quality field
- Setup identity: data_quality field
- Re-entry: data_quality field
- Outcome: data_quality field
- AI call: success/failure status

## Data Quality Rules

1. Missing values remain NULL — NEVER inferred
2. Stale data is labeled, not hidden
3. Unavailable states are explicit, not empty
4. Invalid data is flagged, not corrected
5. Research events without quality flags are considered INVALID

## Source Tracking

Where available, source is recorded:
- yfinance → price data
- internal database → cached data
- calculated → derived indicator
- API → external API
- unavailable → no source available

If source timestamp differs from candle timestamp, both are recorded.

## Data Quality vs Trading Decision

Data quality does NOT affect trading decisions in Phase 42A. It is recorded for research analysis only.

Future research can analyze:
- How often does STALE data lead to trades?
- What is the impact of UNAVAILABLE options on qualification?
- Does data quality correlate with trade outcomes?

## Validation Rules

1. Every candle has a data_state (LIVE/STALE/DELAYED/EOD/HISTORICAL/UNAVAILABLE)
2. Every evidence evaluation has data_quality (LIVE/STALE/PARTIAL/UNAVAILABLE/INVALID)
3. Every setup identity has data_quality (LIVE/STALE/PARTIAL/UNAVAILABLE/INVALID)
4. Every outcome tracking has data_quality (LIVE/STALE/PARTIAL/UNAVAILABLE/INVALID)
