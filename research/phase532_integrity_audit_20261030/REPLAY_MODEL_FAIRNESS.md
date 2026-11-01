# Phase 5.32 — Replay Model Fairness

## Comparison Basis
- Identical historical date coverage: 2026-07-06 to 2026-10-29.
- Identical instruments: NIFTY, BANKNIFTY.
- Identical strategy rules: HLC 3-bar alignment.
- Identical risk and exit assumptions: stop = signal low -1 / high +1, target = entry ± 1.5R, EOD flat.

## Differences
- Day-by-day: patterns evaluated per day; cross-session patterns excluded.
- Candle-by-candle: patterns evaluated incrementally per day feed; final-candle triggers resolved via +5min.
- Trade count difference: 729 (day-by-day) vs 881 (candle-by-candle) — attributable to final-candle/extra triggers.

## Verdict
Differences are attributable to intentional model semantics (session boundaries, final-candle handling) and require further review.
