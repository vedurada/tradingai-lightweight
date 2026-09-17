# 30-Day NIFTY 5-Minute Backtest Report
Generated: 2026-09-17T12:25:05.524440+00:00

## Summary
- **Period**: 2026-08-08 to 2026-09-15
- **Instrument**: NIFTY
- **Timeframe**: 5-minute candles (09:15–15:30 IST)
- **Trading Days**: 27
- **Candles Analyzed**: 1875
- **Strategy**: EMA CROSS (9/21) — deterministic intraday

## Metrics
| Metric | Value |
|--------|-------|
| Total Trades | 12 |
| Wins | 2 |
| Losses | 10 |
| Win Rate | 16.7% |
| Avg Win | ₹14832.90 |
| Avg Loss | ₹-12024.20 |
| Profit Factor | 0.25 |
| Net P&L | ₹-90576.15 |
| Max Drawdown | ₹-96186.11 |
| Average R | -0.63 |
| Largest Win | ₹24055.85 |
| Largest Loss | ₹-12303.17 |
| Best R | 2.00 |
| Worst R | -1.00 |
| No-Trade Days | 15 |

## Data Quality
- Good days: 25
- Partial days: 0
- Poor/No-data days: 2

## Look-Ahead Bias Check
PASS — strict chronological processing, no future data accessed

## Methodology
At each 5-minute candle, the strategy checks if EMA(9) crosses above EMA(21).
If so, enters LONG at the close price with:
- Stop loss: 0.5% below entry
- Target: 1.0% above entry
- Exit at stop, target, or EOD close (15:30 IST)

No future data is used. All indicators are calculated from candles up to and including the current timestamp.

## Trade Ledger
See: /opt/tradingai/data/backtest/nifty_30d_5m_trades.csv
