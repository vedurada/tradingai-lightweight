# Phase 41 Trade Breakdown — All 1,184 Trades
Generated: 2026-09-17

## Overview

| Metric | Value |
|--------|-------|
| Total trades | 1,184 |
| Period | 2026-08-10 to 2026-09-15 |
| Data source | NIFTY 5-minute candles from SQLite DB |
| Entry method | Per-candle evaluation, entry at close |
| Exit method | Stop/target/expired (intraday simulation) |

## Trades/Day

| Metric | Value |
|--------|-------|
| Total trading days | 26 |
| Avg trades/day | 45.5 |
| Max trades/day | 67 (2026-09-08) |
| Min trades/day | 21 (2026-08-13) |

## Trades/Hour (Market Hours 9:15-15:30)

| Hour | Trades |
|------|--------|
| 03:00-03:59 | 43 |
| 04:00-04:59 | 223 |
| 05:00-05:59 | 218 |
| 06:00-06:59 | 192 |
| 07:00-07:59 | 157 |
| 08:00-08:59 | 175 |
| 09:00-09:59 | 176 |

Note: Trades span 03:00-09:59 because replay evaluates every 5m candle including pre-market hours in DB.

## Trades by Direction

| Direction | Count | Percentage |
|-----------|-------|------------|
| BEARISH | 903 | 76.3% |
| BULLISH | 281 | 23.7% |

Market was predominantly bearish (NIFTY dropped ~6.4% over period), so bearish signals dominate.

## Trades by Outcome

| Outcome | Count | Percentage | PnL Sum |
|---------|-------|------------|---------|
| TARGET_HIT | 894 | 75.5% | 6,904.33 |
| STOPPED | 223 | 18.8% | -137,296.06 |
| EXPIRED | 67 | 5.7% | 0.00 |

Note: TARGET_HIT count is high because the target offset (1.5%) is larger than stop offset (0.5%),
and any price movement hits the target before stop in many cases. However, average target-hit PnL
is only 7.72 vs average stop-loss PnL of -615.68. Losses are concentrated in STOPPED trades.

## Trades by Exit Reason

| Exit Reason | Count | Percentage |
|-------------|-------|------------|
| TARGET_HIT | 894 | 75.5% |
| STOP_LOSS | 223 | 18.8% |
| SESSION_CLOSE | 67 | 5.7% |

## Trades by Direction — Performance

| Direction | Count | Avg PnL | Total PnL | Wins | Win Rate |
|-----------|-------|---------|-----------|------|----------|
| BEARISH | 903 | 7.65 | 6,904.33 | 453 | 50.2% |
| BULLISH | 281 | -488.59 | -137,296.06 | 2 | 0.7% |

**Critical finding**: BULLISH trades have 0.7% win rate. All BULLISH trades lost money because
the market was in a bearish trend. BULLISH signals were generated during pullbacks in a downtrend,
and none of these pullbacks were strong enough to reach the target.

## Trades by Strategy

| Strategy | Count | Notes |
|----------|-------|-------|
| None (empty) | 1,184 | BUG: strategy field None for all trades |

**Important**: Strategy field is empty for ALL trades. This is a replay-specific bug.
In production, `_determine_strategy` requires `trade_status == "TRADE"` but is called before
`replay_qualify` modifies trade_status from NO_TRADE to TRADE. Strategies would be:
- BULLISH → CALL_DEBIT_SPREAD
- BEARISH → PUT_DEBIT_SPREAD

## Setup Fingerprint Analysis

| Metric | Value |
|--------|-------|
| Unique timestamps | 1,184 |
| Total trades | 1,184 |
| Trades per timestamp | 1 (each candle = 1 trade) |
| Exact duplicate setups | 0 |

Each trade has a unique timestamp-based outlook_id, so no duplicate setups are detected.

## Rejection/Filtering at Each Stage

| Stage | In | Out | Rejected | Reason |
|-------|-----|-----|----------|--------|
| Eligible candles | 1,950 | 1,929 | 21 | Warm-up period (first 21 candles) |
| Directional evidence | 1,929 | 1,184 | 745 | MIXED (691) or RANGE (54) |
| Qualification passed | 1,184 | 1,184 | 0 | All directional passed (100%) |
| Paper trade created | 1,184 | 1,184 | 0 | All qualified entered |
| Paper trade completed | 1,184 | 1,184 | 0 | All completed same session |

**Critical finding**: No trades were rejected after qualification. 100% of directional signals
became trades. This is the primary driver of the high trade count.

## Data Quality Flags

- Strategy field: **None for all trades** (replay bug, not data issue)
- Market regime: **UNKNOWN for all trades** (not stored in replay)
- Evidence score: **Not stored** in trade record
- Confidence: **Not stored** in trade record
- Options data: **Not available** in replay (underlying-only logic)
- Risk reward: **Not stored** in trade record
