# Phase 5.26 — Replay Method

## Method

Chronological replay using canonical `_scan_signals()` and `_trade_for()` from `app/research/scalp_engine.py`.

## No-Lookahead Guarantees

1. Candles processed in timestamp order
2. Signal detection uses only completed candles available at decision time
3. Entry at next candle's open (not same candle)
4. Exit determined by forward scan (first hit)
5. Stop-first tie-break when both hit same candle
6. Session boundary: stop scanning when date changes
7. Mode C: one open position per instrument

## Replay Scope

- Instruments: NIFTY, BANKNIFTY
- Date range: 2026-07-06 to 2026-10-29 (81 sessions)
- Total replay trades: 729 (382 NIFTY + 347 BANKNIFTY)

## Comparison with Live Paper Trades

- 30 SCALP_HLC paper trades exist (Sep 25 - Oct 28)
- Replay covers Jul 6 - Oct 29
- Only overlapping period (Sep 25 - Oct 28) can be compared
- 29 scalp_signals exist (Oct 26 - Oct 29)
