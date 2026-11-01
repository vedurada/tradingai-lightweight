# Phase 5.26 — Database Schema and Counts

## paper_trades (94 rows)

| Column | Type | Notes |
|--------|------|-------|
| trade_id | TEXT PK | Deterministic (SHA-1 of link_key) |
| instrument_id | TEXT NOT NULL | NIFTY (80), BANKNIFTY (14) |
| scenario | TEXT | SCALP_HLC (30), BREAKOUT (55), etc. |
| strategy | TEXT | Scalp HLC 3-bar (30), Bull/Bear spreads (64) |
| direction | TEXT | BULL/BEAR |
| entry | REAL | Entry price |
| stop | REAL | Stop level |
| target | REAL | Target level |
| entry_time | TEXT | ISO 8601 +05:30 |
| exit_time | TEXT | ISO 8601 +05:30 |
| exit_price | REAL | Exit price |
| exit_reason | TEXT | TARGET/STOP/EOD/VOID |
| paper_pnl | REAL | P&L in points |
| status | TEXT | CLOSED (86), VOID (8) |

## scalp_signals (29 rows)

| Column | Type | Notes |
|--------|------|-------|
| signal_id | TEXT PK | SS- + SHA-1 |
| trade_date | TEXT | Signal date |
| instrument_id | TEXT | NIFTY (15), BANKNIFTY (14) |
| strategy | TEXT | Scalp HLC 3-bar (all 29) |
| direction | TEXT | BULL/BEAR |
| signal_type | TEXT | H1_UP/H1_DOWN |
| source_candle_ts | TEXT | Signal candle timestamp |
| status | TEXT | TRADED (18), EXPIRED (10), IGNORED (1) |
| paper_trade_id | TEXT | FK to paper_trades (when TRADED) |

## Strategy Distribution

| Scenario | Count | Strategy Type |
|----------|-------|---------------|
| SCALP_HLC | 30 | HLC 3-bar scalp |
| BREAKOUT | 55 | CPR breakout |
| BRK_TC | 1 | CPR breakout |
| BELOW_CPR | 4 | CPR |
| PDH | 1 | CPR |
| R1 | 2 | CPR |
| SMA20_CLOSE_BELOW | 1 | CPR |

## HLC-Specific Records

- 30 paper_trades with scenario=SCALP_HLC
- 29 scalp_signals (all Scalp HLC 3-bar)
- 18 TRADED signals (linked to paper_trades)
- 10 EXPIRED signals
- 1 IGNORED signal

## Date Range

- paper_trades: 2026-09-25 to 2026-10-28
- scalp_signals: 2026-10-26 to 2026-10-29
