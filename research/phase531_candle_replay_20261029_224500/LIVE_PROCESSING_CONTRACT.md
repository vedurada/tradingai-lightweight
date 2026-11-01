# Phase 5.31 — Live Processing Contract

Source files inspected (read-only):
- `/opt/tradingai/app/live/engine.py`
- `/opt/tradingai/app/research/scalp_engine.py`
- `/opt/tradingai/app/strategies/scalp.py`
- `/opt/tradingai/app/paper_trade/engine.py`
- `/opt/tradingai/scripts/paper_scalp_live.py`

## Candle input format
- `market_candles_5m` rows: `timestamp, open, high, low, close`.
- Timestamps ISO-8601 with `+05:30`.

## Timestamp convention
- Candle timestamp = bar close time.
- Entry = next completed candle open.
- Final-candle trigger entry = signal timestamp + 5 minutes.

## Signal-generation call sequence
1. `LiveEngine.evaluate(instrument, now, ...)`
2. candles fetched up to `completed` timestamp.
3. feed filtered to today's candles with `timestamp <= completed`.
4. warmup gate: first completed candle (09:15) required.
5. `_scan_signals(feed)` -> signal list `(idx, direction)`.
6. For each signal: entry candle = `feed[idx+1]` or `signal_ts + 5min`.
7. Entry window check: `09:20 <= HH:MM < 15:20`.

## Final-candle detection
- `_scan_signals` checks last candle of feed for 3-bar alignment.
- Signal index = last candle index; entry resolved via +5min.

## Session boundaries
- Session candles: from first completed candle of day (09:15) through entry window end (15:20).

## Entry timing
- Entry at next candle open (past price, no lookahead).
- Stop = signal candle low - 1 (BULL) / high + 1 (BEAR).
- Target = entry ± 1.5R.

## Expiry behaviour
- EOD flat at last session close if stop/target not hit.

## Duplicate-prevention rules
- One signal evaluated per decision epoch; entry window and risk gates applied.
