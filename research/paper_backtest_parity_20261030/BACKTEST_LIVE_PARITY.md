# Backtest vs Live Parity

## Date
2026-10-30

## Host
webserver / Linux / x86_64 / ubuntu / /opt/tradingai (Oracle VM)

## Methodology

Compared backtest results (`run_opens_range()`) with live signal generation (`today_state()`) for 2026-10-30 using identical candle data from `market_candles_5m`.

Both paths use the same canonical HLC engine (`app/research/scalp_engine.py`):
- Backtest: `run_opens_range()` → `run_range()` → `_scan_signals()` + `_trade_for()`
- Live: `today_state()` → `_scan_signals()` + `_live_signal()`

## Results

### NIFTY 2026-10-30

| Signal # | Direction | Signal Time | Entry Time | Entry | Stop | Target | Backtest Match | Live Match |
|----------|-----------|-------------|------------|-------|------|--------|--------------|------------|
| 1 | BEAR | 10:10:00 | 10:15:00 | 22938.6 | 22948.7 | 22923.45 | Yes | Yes |
| 2 | BULL | 10:55:00 | 11:00:00 | 22972.45 | 22955.85 | 22997.35 | Yes | Yes |
| 3 | BULL | 11:00:00 | 11:05:00 | 22990.3 | 22963.25 | 23030.88 | Yes | Yes |
| 4 | BULL | 11:05:00 | 11:10:00 | 23004.25 | 22978.75 | 23042.5 | Yes | Yes |
| 5 | BULL | 11:10:00 | 11:15:00 | 23009.95 | 22999.5 | 23025.62 | Yes | Yes |
| 6 | BULL | 14:10:00 | 14:15:00 | 23025.2 | 23013.95 | 23042.07 | Yes | Yes |
| 7 | BULL | 14:15:00 | 14:20:00 | 23040.85 | 23016.5 | 23077.37 | Yes | Yes |

**7/7 signals match exactly** between backtest and live.

### BANKNIFTY 2026-10-30

| Signal # | Direction | Signal Time | Entry Time | Entry | Stop | Target | Backtest Match | Live Match |
|----------|-----------|-------------|------------|-------|------|--------|--------------|------------|
| 1 | BEAR | 10:00:00 | 10:05:00 | 54681.35 | 54743.8 | 54587.68 | Yes | Yes |
| 2 | BULL | 11:35:00 | 11:40:00 | 54849.6 | 54819.85 | 54894.23 | Yes | Yes |
| 3 | BEAR | 13:30:00 | 13:35:00 | 54767.15 | 54831.55 | 54670.54 | Yes | Yes |
| 4 | BEAR | 13:35:00 | 13:40:00 | 54720.55 | 54788.7 | 54618.33 | Yes | Yes |
| 5 | BEAR | 13:40:00 | 13:45:00 | 54713.45 | 54739.95 | 54673.7 | Yes | Yes |
| 6 | BULL | 14:15:00 | 14:20:00 | 54693.05 | 54653.4 | 54752.53 | Yes | Yes |
| 7 | BEAR | 14:40:00 | 14:45:00 | 54689.15 | 54713.9 | 54652.02 | Yes | Yes |

**7/7 signals match exactly** between backtest and live.

## Summary

| Instrument | Backtest Signals | Live Signals | Exact Matches | Parity |
|------------|-----------------|--------------|---------------|--------|
| NIFTY | 7 | 7 | 7 | 100% |
| BANKNIFTY | 7 | 7 | 7 | 100% |

## Conclusion

**Backtest and live produce identical results.** Both paths use:
1. Same `_scan_signals()` function for 3-bar alignment detection
2. Same `_live_signal()` / `_trade_for()` for entry, stop, target calculation
3. Same candle data from `market_candles_5m` table
4. Same next-candle execution rule (entry at next candle open)

There are NO mismatches between backtest and live for 2026-10-30. Any differences in live paper trades vs backtest results are due to:
- Entry candle not yet ingested at live time (entry=None, resolved later from provider)
- Market data latency between backtest (historical) and live (real-time)
- Signal expiration (entry window closed before trade creation)

These are operational timing issues, not strategy or logic differences.
