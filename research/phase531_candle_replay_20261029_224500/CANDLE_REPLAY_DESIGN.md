# Phase 5.31 — Candle Replay Design

## Approach
- Research-only harness importing canonical primitives from
  `app.research.scalp_engine` (no code modification).
- Candles grouped by trading day; days processed in chronological order.
- Within each day, candles appended in timestamp order.
- After each append at index `e`, evaluate signal candidates:
  - pattern trigger at index `e - 1` (entry at `e`),
  - final-candle trigger at index `e` (entry at `e + 1` via +5min).

## No-lookahead
- Only candles with timestamp <= decision timestamp are in the feed.
- Future candles never influence earlier decisions.

## Determinism
- Run1/Run2 outputs compared at trade level (0 differences target).

## Missing dependencies
- Historical live-provider entry resolution (for final-candle triggers) approximated
  by arithmetic (signal_ts + 5min). Documented as approximation.

## Limitations
- Cross-session pattern alignment not exercised in per-day design (documented).
- Historical live entry price resolution approximated by next-open.
