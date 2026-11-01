# Historical HLC Backtest Report — NIFTY (2026-10-30)
Source: /opt/tradingai/database/tradingai.db (market_candles_5m, existing production DB — read-only)
Instrument: NIFTY (only, as requested)
Timeframe: 5-minute candles, complete (is_complete=1)
Record count: 6146 candles
Period: 2026-07-06 to 2026-10-30 (from first/last signal timestamps)
Strategy: Canonical HLC 3-bar (scalp_engine.py) — unchanged
Method: Chronological, completed candles only, no future data, entry at next candle open
Signals: 523 (BULL/BEAR distributed across period)
Data quality: Genuine historical; no synthetic data used; no look-ahead
Option premium data: NOT AVAILABLE locally — historical option OHLC/strike data not present
Options backtest: NOT POSSIBLE with current data (documented per requirements)
No broker orders; MODE=SHADOW; production untouched; branch feature/zerodha-paper-trading
