# Data Inventory — Historical Backtest (2026-10-30)
Source: /opt/tradingai/database/tradingai.db (existing production DB — read-only, untouched)
Table: market_candles_5m
- Instrument: NIFTY, BANKNIFTY
- Timeframe: 5-minute
- Total records: 17161
- Columns: candle_id, instrument_id, timestamp, open, high, low, close, volume, source, data_state, ingested_at, session_id, is_complete
- Timezone: IST (+05:30)
- Data state: LIVE (historical records)
- Complete candles: is_complete=1
Quality: Genuine historical market data from existing pipeline; not synthetic.
Option premium data: Not found locally. No historical CE/PE OHLC available.
