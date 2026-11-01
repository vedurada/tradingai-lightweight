# HLC Scalp 3-Bar Backtest — Research Report (NO Daily Trade Limit)

Generated: 2026-10-28T20:08:19.208386+05:30
Source DB: /opt/tradingai/database/tradingai.db

## Methodology
- Strategy: 3-bar HLC alignment (BULL: higher H/L/C x3; BEAR: lower H/L/C x3)
- Signal detection: exact replica of app/research/scalp_engine._scan_signals
- Entry: next candle open (no look-ahead)
- Stop: signal candle low - 1 (BULL) / high + 1 (BEAR)
- Target: entry + 1.5x risk (BULL) / entry - 1.5x risk (BEAR)
- NO DAILY TRADE LIMIT — every qualifying signal is executed
- Convention A (primary): exit checked from entry candle onward (live-faithful)
- Convention B (comparison): exit checked strictly after entry candle (research)
- Results are index points, not rupee P&L or options returns

## NIFTY

### Convention A (Live-Faithful, Primary)
- Total signals: 512
- Executed trades: 505
- Skipped (invalid risk/entry window): 7
- Skipped (daily limit): 0 (NONE — no limit)
- Wins: 368 | Losses: 137 | Flats: 0
- Win rate: 72.87%
- Net points: 6444.38
- Avg points per trade: 12.76
- Avg win: 24.16 pts | Avg loss: -17.86 pts
- Total R: 414.13 | Avg R: 0.82
- Max drawdown (pts): 105.66
- Max drawdown (R): 5.0
- Stop exits: 130 | Target exits: 361 | EOD exits: 14
- Entry-candle exits: 151
- Same-candle ambiguities: 0
- Max trades per day: 14
- Days with multiple trades: 78

### Direction Breakdown (Convention A)
- BEAR: 258 trades, 195 wins, 75.6% WR, 3891.79 pts
- BULL: 247 trades, 173 wins, 70.0% WR, 2552.59 pts

### Monthly Summary (Convention A)
- 2026-07: 125 trades, 72.8% WR, 1693.65 pts, 100.618 R
- 2026-08: 116 trades, 68.1% WR, 819.92 pts, 81.597 R
- 2026-09: 138 trades, 70.3% WR, 1239.07 pts, 106.481 R
- 2026-10: 126 trades, 80.2% WR, 2691.74 pts, 125.434 R

## BANKNIFTY

### Convention A (Live-Faithful, Primary)
- Total signals: 452
- Executed trades: 441
- Skipped (invalid risk/entry window): 11
- Skipped (daily limit): 0 (NONE — no limit)
- Wins: 316 | Losses: 125 | Flats: 0
- Win rate: 71.66%
- Net points: 15730.49
- Avg points per trade: 35.67
- Avg win: 72.99 pts | Avg loss: -58.68 pts
- Total R: 345.02 | Avg R: 0.782
- Max drawdown (pts): 414.55
- Max drawdown (R): 4.0
- Stop exits: 121 | Target exits: 310 | EOD exits: 9
- Entry-candle exits: 150
- Same-candle ambiguities: 1
- Max trades per day: 15
- Days with multiple trades: 77

### Direction Breakdown (Convention A)
- BEAR: 236 trades, 172 wins, 72.9% WR, 9819.59 pts
- BULL: 205 trades, 144 wins, 70.2% WR, 5910.9 pts

### Monthly Summary (Convention A)
- 2026-07: 125 trades, 75.2% WR, 5787.42 pts, 107.37 R
- 2026-08: 103 trades, 70.9% WR, 2543.84 pts, 78.346 R
- 2026-09: 114 trades, 68.4% WR, 2633.81 pts, 79.022 R
- 2026-10: 99 trades, 71.7% WR, 4765.42 pts, 80.282 R
