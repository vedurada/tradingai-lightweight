# 30-Day NIFTY 5-Minute Backtest Results — Phase 36
Generated: 2026-09-17

## Period
- **Date range**: 2026-08-08 to 2026-09-15
- **Trading days**: 27
- **Candles analyzed**: 1,875 (5-minute, 09:15-15:30 IST)
- **Strategy**: EMA CROSS (9/21) — deterministic intraday LONG only

## Metrics

| Metric | Value |
|--------|-------|
| Period | 2026-08-08 to 2026-09-15 |
| Trading days | 27 |
| Timeframe | 5-minute |
| Total trades | 12 |
| Signals (entries) | 12 |
| Wins | 2 |
| Losses | 10 |
| Win rate | 16.67% |
| Average win | ₹14,832.90 |
| Average loss | ₹-12,024.20 |
| Profit factor | 0.25 |
| Net P&L | ₹-90,576.15 |
| Max drawdown | ₹-96,186.11 |
| Average R | -0.63 |
| Largest win | ₹24,055.85 |
| Largest loss | ₹-12,303.17 |
| Best R | 2.0 |
| Worst R | -1.0 |
| No-trade days | 15 |

## Trade Ledger Summary
All 12 trades:
- Entry: LONG at EMA(9) cross above EMA(21) on 5m close
- Stop: 0.5% below entry
- Target: 1.0% above entry
- Exit: Stop hit (10), Target hit (1), EOD close (1)
- All exits occur AFTER entries (verified in CSV)
- No overlapping positions (one trade at a time)

## Data Quality
- Good days: 25
- Partial days: 0
- Poor/No-data days: 2 (Sep 14-15, incomplete data)

## Verification
- JSON metrics match CSV ledger: PASS
- Win count: 2 = 2 ✓
- Loss count: 10 = 10 ✓
- Net P&L: -90576.15 = -90576.15 ✓
- All entries after signals: PASS
- All exits after entries: PASS
- No overlapping positions: PASS
