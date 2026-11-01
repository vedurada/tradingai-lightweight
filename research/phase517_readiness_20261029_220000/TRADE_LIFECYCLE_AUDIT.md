# Phase 5.17 — Trade Lifecycle and Storage Integrity Audit

## Authoritative Table: paper_trades

`paper_trades` is the authoritative store for active HLC paper trades. `paper_scalp` serves EOD backtest comparison only.

## Backtest vs Active Trades

- `paper_scalp` contains EOD backtest results (session_date, instrument_id PK)
- `paper_trades` contains live paper trades (trade_id PK)
- `scalp_reconcile.py` matches live vs EOD trades
- No confusion: different tables, different PKs, different purposes

## Stable Identifiers

- `trade_id` = 'PT-' + SHA-1(link_key)[:10] (deterministic)
- `signal_id` = 'SS-' + SHA-1(instrument|candle_ts|direction|level)[:12]
- `scalp_signals` has UNIQUE(instrument_id, source_candle_ts, direction)
- `paper_trades.trade_id` is PRIMARY KEY

## Duplicate Prevention

- Deterministic trade_id ensures idempotency
- IntegrityError caught on duplicate INSERT
- Signal UNIQUE constraint prevents duplicate signals
- tg_alerts checks DB before alerting (dedup via fired key)

## Restart Recovery

- `recover_open_positions()` loads open trades from DB
- `recover_new_signals()` marks signals with existing trades as TRADED
- Open positions remain in DB across restarts

## Rejected Signal Side Effects

- Rejected signals: no trade created, no position opened, no alert sent
- `mark_failed()` records error in scalp_signals (status stays NEW for retry)
- `mark_expired()` sets status to EXPIRED

## Live vs EOD Exit Discrepancy

- Live monitor uses market_candles_5m data (may lag ingestion)
- EOD backtest uses all candles (instant access)
- Minor timing differences possible but exit logic is identical
