# Phase 5.28 — Authoritative Metrics Reproduction

## Source: JSON files (382 + 347 = 729 trades)

| Metric | Value |
|--------|-------|
| Total trades | 729 |
| NIFTY trades | 382 |
| BANKNIFTY trades | 347 |
| Wins | 528 |
| Losses | 201 |
| Win rate | 72.43% |
| Total points | 19,210.95 |
| Profit factor | 3.47 |
| Max drawdown | 442.40 |
| Expectancy (R) | 0.794 |
| Max consec losses | 6 |

## Reproduction Status: REPRODUCED

All metrics reproduced from JSON files without modification. Values match Phase 5.12 report exactly.

## Sensitivity: 245 Extra Rows

If the 245 extra rows were valid trades:
- Total would be 974 trades
- But these rows cannot be validated as independent trades
- They are likely spurious (from candle-by-candle processing)

## Expiry-Policy Replay (723 trades)

- Accepted: 723 (6 cross-session rejected)
- Win rate: 72.20%
- Total points: 17,857.91
- Profit factor: 3.30
