# Data quality report

Generated: 2026-10-19T20:04:28.306686+05:30
Range: 2026-07-06 .. 2026-10-19
**Status: PASS_WITH_LIMITATIONS**

## Structure

- duplicate candles: 0
- OHLC violations: 0
- timezone offsets: {'+05:30': 15361}
- rows not marked complete: 0

## Coverage

### NIFTY
- sessions with data: 74 (2026-07-06 .. 2026-10-19)
- sessions with != 75 candles: {'2026-09-21': 73, '2026-10-15': 73}
- session days without data: none
- data on non-session days: none
- candle span: 2026-07-06T09:15:00+05:30 .. 2026-10-19T15:25:00+05:30

### BANKNIFTY
- sessions with data: 74 (2026-07-06 .. 2026-10-19)
- sessions with != 75 candles: {'2026-09-21': 73, '2026-10-15': 73}
- session days without data: none
- data on non-session days: none
- candle span: 2026-07-06T09:15:00+05:30 .. 2026-10-19T15:25:00+05:30

## Point-in-time level check

- levels for day D recomputed after truncating the feed to days < D
- checked: 146, mismatches: 0
- verdict: **PASS**

## Option history (required for credit-spread P&L)

- option_snapshots: {'rows': 0, 'min': None, 'max': None}
- option_contracts: {'rows': 0, 'min': None, 'max': None}
- historical_option_premiums_available: False
- consequence: UNAVAILABLE -> this run is an UNDERLYING (spot) signal study only; credit-spread P&L cannot be claimed from these inputs

## Sources

- yfinance / LIVE: 6663 rows (2026-07-29T09:25:00+05:30 .. 2026-10-19T15:25:00+05:30)
- yfinance-backfill / LIVE: 8698 rows (2026-07-06T09:15:00+05:30 .. 2026-09-25T09:15:00+05:30)

## Issues

- NIFTY: short sessions {'2026-09-21': 73, '2026-10-15': 73}
- BANKNIFTY: short sessions {'2026-09-21': 73, '2026-10-15': 73}
- NO historical option premiums -> credit-spread P&L test not executable (labelled limitation)
