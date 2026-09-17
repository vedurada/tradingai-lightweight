# Phase 41 Trade Frequency Diagnostic
Generated: 2026-09-17

## Executive Summary

The Phase 41 replay produces **1,184 trades over 26 trading days** (45.5 trades/day).
This frequency is **unexpectedly high** and requires investigation.

**Primary cause**: The evidence engine classifies 61.4% of eligible candles as directional (BULLISH/BEARISH),
and the qualification pipeline enters a trade on EVERY directional signal without deduplication or throttling.

## Frequency Breakdown

| Metric | Value | Notes |
|--------|-------|-------|
| Total trades | 1184 | Simulated through qualification + paper trade |
| Trading days | 26 | 2026-08-10 to 2026-09-15 |
| Trades/day (avg) | 45.5 | 45.5 |
| Trades/day (max) | 67 | 2026-09-08 |
| Trades/day (min) | 21 | 2026-08-26 |
| Trades/hour (market) | 74.0 | ~16 active hours |
| Trades per 5m candle | 0.61 | 1184/1929 eligible |

## Signal Funnel → Trade Conversion

| Stage | Count | Conversion | Reason |
|-------|-------|------------|--------|
| 5m candles | 1950 | 100% | Raw data |
| Eligible (after warm-up) | 1929 | 98.9% | Excluded first 21 candles |
| Directional evidence | 1184 | 61.4% | BULLISH/BEARISH |
| Qualified setups | 1184 | 61.4% | All directional passed |
| Paper trades created | 1184 | 100.0% | All qualified entered |
| Paper trades completed | 1184 | 100.0% | All completed same session |
| **Skipped** | 745 | - | MIXED=691, RANGE=54 |

**Critical finding**: 100% of directional candles became trades. No deduplication, no throttling.

## Root Cause Analysis

### Why ~45 trades/day?

The system produces ~45 trades/day because:

1. **Evidence classification is too permissive**: 61.4% of eligible candles are classified BULLISH/BEARISH
   - This is because the evidence engine uses short-term indicators (EMA, RSI, VWAP proximity) that change frequently
   - On a 5-minute timeframe, directional conditions change rapidly

2. **Qualification passes every directional signal**: The 6-layer qualification checks are designed for live AI outlook context, not for replaying every candle
   - AI bias valid: BULLISH/BEARISH always valid → PASS
   - AI trade_state valid: TRADE always valid in outlook → PASS
   - Risk calculable: Stop/target always calculable → PASS
   - Risk reward ≥ 1.0: Target offset (1.5%) / Stop offset (0.5%) = 3.0 → PASS
   - All other checks pass because they're boolean validations, not thresholds

3. **No effective deduplication in replay**: Each candle gets a unique timestamp-based outlook_id,
   so the setup fingerprint differs for every candle, even if the underlying market state is identical

4. **No active trade blocking in replay**: Each trade completes (hits stop or target) within the same session,
   so the next candle can immediately enter a new trade

5. **Stop losses are hit quickly**: Stop is at 0.5% from entry (~115 points on NIFTY at 23000).
   On a 5-minute chart, a 0.5% move happens within minutes, so most trades complete quickly.
   This allows rapid-fire re-entry.

### Is this intentional?

**No.** In a production system:
- AI outlook refresh frequency is ~30 minutes to 1 hour, not every 5 minutes
- Active trade protection would block new entries while one is OPEN
- Setup deduplication would block re-entry within a time window (e.g., 30 minutes)
- The qualification engine is designed for AI context, not per-candle evaluation

### Classification

This is a **REPLAY METHODOLOGY ARTIFACT**, not a production behavior.
However, it reveals a real design gap: the qualification engine lacks frequency controls.

## Trade Distribution

### By Direction
| BEARISH | 903 | 76.3% |
| BULLISH | 281 | 23.7% |

### By Outcome
| TARGET_HIT | 894 | 75.5% |
| STOPPED | 223 | 18.8% |
| EXPIRED | 67 | 5.7% |

### By Exit Reason
| TARGET_HIT | 894 | 75.5% |
| STOP_LOSS | 223 | 18.8% |
| SESSION_CLOSE | 67 | 5.7% |

### By Trading Day
| 2026-08-10 | 33 |
| 2026-08-11 | 47 |
| 2026-08-12 | 53 |
| 2026-08-13 | 24 |
| 2026-08-14 | 39 |
| 2026-08-17 | 45 |
| 2026-08-18 | 57 |
| 2026-08-19 | 56 |
| 2026-08-20 | 30 |
| 2026-08-21 | 39 |
| 2026-08-24 | 54 |
| 2026-08-25 | 50 |
| 2026-08-26 | 21 |
| 2026-08-27 | 58 |
| 2026-08-28 | 34 |
| 2026-08-31 | 33 |
| 2026-09-01 | 49 |
| 2026-09-02 | 54 |
| 2026-09-03 | 46 |
| 2026-09-04 | 39 |
| 2026-09-07 | 59 |
| 2026-09-08 | 67 |
| 2026-09-09 | 50 |
| 2026-09-10 | 44 |
| 2026-09-11 | 41 |
| 2026-09-15 | 62 |

## Re-entry Analysis Summary

| Metric | Count | % | Classification |
|--------|-------|---|----------------|
| Re-entry ≤5 minutes | 1,031 | 87.2% | OVERLY SENSITIVE |
| Re-entry ≤15 minutes | 1,090 | 92.1% | OVERLY SENSITIVE |
| Re-entry ≤30 minutes | 1,111 | 94.0% | OVERLY SENSITIVE |
| Re-entry ≤60 minutes | 1,115 | 94.2% | OVERLY SENSITIVE |
| Same direction consecutive | 1,136 | 96.0% | SEQUENTIAL |
| Exact duplicate setups | 0 | 0.0% | None (unique timestamps) |

**Verdict**: 87% of consecutive trades are re-entries within 5 minutes of the previous trade's exit.
These are NOT legitimate new setups - they are sequential re-entries driven by the per-candle evaluation.

## Why This Matters

1. **Not comparable to Phase 37 baseline**: Phase 37 had 12 trades (conservative, rules-based)
   Phase 41 has 1,184 trades (aggressive, evidence-permissive)

2. **Economically impractical**: 45 trades/day = ~225 trades/week = ~900 trades/month
   At ₹500/trade commission = ₹450,000/month in commissions alone

3. **Strategy credibility**: A strategy trading every 5 minutes when conditions are directional
   is not a viable production strategy

4. **Phase 42 implications**: Before Phase 42, frequency must be controlled
   Options: time-based dedup, minimum hold period, AI outlook refresh throttling

## Files Generated

- `audit/phase41_trade_frequency_diagnostic.md` — This document
- `audit/phase41_trade_frequency_diagnostic.csv` — Machine-readable frequency data
- `audit/phase41_reentry_analysis.csv` — Re-entry timing analysis
