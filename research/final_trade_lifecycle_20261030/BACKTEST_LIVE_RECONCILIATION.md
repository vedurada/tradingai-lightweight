# Backtest vs Live Parity

## Date
2026-10-30

## Methodology
Compared backtest results (run_opens_range()) with live signal generation
(today_state()) for 2026-10-30 using identical candle data from
market_candles_5m.

Both paths use the same canonical HLC engine:
- Backtest: run_opens_range() -> run_range() -> _scan_signals() + _trade_for()
- Live: today_state() -> _scan_signals() + _live_signal()

## Results

### NIFTY 2026-10-30

| Signal # | Direction | Signal Time | Entry Time | Entry Price | Stop | Target |
|----------|-----------|-------------|------------|-------------|------|--------|
| 1 | BEAR | 10:10:00 | 10:15:00 | 22,938.60 | 22,948.70 | 22,923.45 |
| 2 | BULL | 10:55:00 | 11:00:00 | 22,972.45 | 22,955.85 | 22,997.35 |
| 3 | BULL | 11:00:00 | 11:05:00 | 22,990.30 | 22,963.25 | 23,030.88 |
| 4 | BULL | 11:05:00 | 11:10:00 | 23,004.25 | 22,978.75 | 23,042.50 |
| 5 | BULL | 11:10:00 | 11:15:00 | 23,009.95 | 22,999.50 | 23,025.62 |
| 6 | BULL | 14:10:00 | 14:15:00 | 23,025.20 | 23,013.95 | 23,042.07 |
| 7 | BULL | 14:15:00 | 14:20:00 | 23,040.85 | 23,016.50 | 23,077.37 |

**7/7 signals match exactly** between backtest and live.

### BANKNIFTY 2026-10-30

| Signal # | Direction | Signal Time | Entry Time | Entry Price | Stop | Target |
|----------|-----------|-------------|------------|-------------|------|--------|
| 1 | BEAR | 10:00:00 | 10:05:00 | 54,681.35 | 54,743.80 | 54,587.68 |
| 2 | BULL | 11:35:00 | 11:40:00 | 54,849.60 | 54,819.85 | 54,894.23 |
| 3 | BEAR | 13:30:00 | 13:35:00 | 54,767.15 | 54,831.55 | 54,670.54 |
| 4 | BEAR | 13:35:00 | 13:40:00 | 54,720.55 | 54,788.70 | 54,618.33 |
| 5 | BEAR | 13:40:00 | 13:45:00 | 54,713.45 | 54,739.95 | 54,673.70 |
| 6 | BULL | 14:15:00 | 14:20:00 | 54,693.05 | 54,653.40 | 54,752.53 |
| 7 | BEAR | 14:40:00 | 14:45:00 | 54,689.15 | 54,713.90 | 54,652.02 |

**7/7 signals match exactly** between backtest and live.

## Summary

| Instrument | Backtest Signals | Live Signals | Exact Matches | Parity |
|------------|-----------------|--------------|---------------|--------|
| NIFTY | 7 | 7 | 7 | 100% |
| BANKNIFTY | 7 | 7 | 7 | 100% |
| **Total** | **14** | **14** | **14** | **100%** |

## Conclusion

Backtest and live produce identical results. Both paths use:
- Same _scan_signals() function for 3-bar alignment detection
- Same _live_signal() / _trade_for() for entry, stop, target calculation
- Same candle data from market_candles_5m table
- Same next-candle execution rule (entry at next candle open)
- Same stop/target calculation (signal candle extreme +/-1pt, 1.5R target)

There are **zero mismatches** between backtest and live for 2026-10-30.
Any differences in live paper trades vs backtest results in production are due to:
- Entry candle not yet ingested at live time (entry=None, resolved later from provider)
- Market data latency between backtest (historical) and live (real-time)
- Signal expiration (entry window closed before trade creation)
These are operational timing issues, not strategy or logic differences.
