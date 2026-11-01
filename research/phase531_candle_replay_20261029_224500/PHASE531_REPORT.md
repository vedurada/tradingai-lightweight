# Phase 5.31 — Isolated Candle-by-Candle Replay Parity

## Environment

- Host: `webserver` (Oracle VM)
- Project root: `/opt/tradingai`
- Database: `/opt/tradingai/database/tradingai.db` (read-only)
- Phase 5.30 reference: `/opt/tradingai/research/phase530_final_20261029_224000/`
- Phase 5.31 report dir: `/opt/tradingai/research/phase531_candle_replay_20261029_224500/`
- Live engine: `/opt/tradingai/app/live/engine.py`
- Canonical HLC engine: `/opt/tradingai/app/research/scalp_engine.py`
- HLC adapter: `/opt/tradingai/app/strategies/scalp.py`
- Replay outputs: `/opt/tradingai/research/phase531_candle_replay_20261029_224500/`

## Objective

Build an isolated research replay that processes historical candles in
chronological order, reproducing the live engine's decision timing as closely as
the available historical data permits. Determine whether this processing model
explains the two unmatched scalp signals, the four probable HLC paper-trade
matches, and the 245 extra CSV rows found in earlier audits.

This is a research experiment only. No production behavior was changed.

## Phase A — Live Processing Contract (verified from source)

### Candle input format
- Source: `market_candles_5m` table, columns `timestamp, open, high, low, close`.
- Timestamps are ISO-8601 with `+05:30` (Asia/Kolkata) offset.

### Timestamp convention
- Candle timestamp = completed bar close time.
- Entry candle = next candle open (5-minute bar boundary).
- Signal candle = candle whose high/low/close completes the 3-bar alignment.

### Signal-generation call sequence
- Live: `LiveEngine.evaluate` -> `_hlc_book_signal(instrument, candles, completed, ...)`.
- `_hlc_book_signal` filters feed to today's completed candles with
  `timestamp <= completed`, applies warmup gate (first completed candle at
  `09:15` must be present), calls `_scan_signals(feed)`.

### Final-candle detection
- `_scan_signals` performs global 3-bar alignment over consecutive candles
  (high/low/close all moving same direction).
- Additionally detects a final-candle trigger on the last candle of the feed.

### Session boundaries
- Market session candles from `09:15` (warmup) through entry window end
  (`OPEN_EOD` = `15:20`).

### Entry timing
- Entry at next candle open. Entry window check: `09:20 <= entry_time[11:16] < 15:20`.

### Expiry behaviour
- EOD flat at last session close if stop/target not hit.

### Duplicate-prevention rules
- Not re-evaluated as a new trade within the same decision epoch.

## Phase B — Isolated Candle-by-Candle Replay

Implemented in `/tmp/phase531_candle_replay3.py` (research-only, imported from
production modules without modification).

Design:
- Candles grouped by day, days processed in chronological order.
- Within a day, candles appended in timestamp order; after each append, signal
  candidates evaluated incrementally (pattern at `idx = e-1`, final candle at
  `idx = e`).
- Entry candle resolved from next candle open, or `signal_ts + 5min` for final-candle triggers.
- Entry window and risk gates applied identically.

## Phase C — Deterministic Tests

Tests 1-10 executed. See `DETERMINISTIC_TEST_RESULTS.csv`.

## Phase D — Six-Case Reconciliation

See `SIX_CASE_RECONCILIATION.csv`.

## Phase E — 245-Row Reassessment

See `245_ROW_REASSESSMENT.csv`.

## Phase F — Performance Comparison

See `PERFORMANCE_COMPARISON.csv`.

## Final Classification

`PARTIAL` — the candle-by-candle replay was implemented and executed, but the
final reconciliation of all six cases and the 245-row reassessment require the
comparison outputs from this run to be fully incorporated.

The isolated candle-by-candle replay produced 881 trades
(478 NIFTY + 403 BANKNIFTY) versus the reference 729-trade replay, with materially
different win rate and profit factor. The source of the difference is under
investigation (cross-session pattern alignment, final-candle entry resolution).

No production files, database records, services, configuration or trading behavior
were modified during this phase.
