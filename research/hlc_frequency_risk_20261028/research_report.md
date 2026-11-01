# HLC 3-Bar Scalp — Trade Frequency, Overlap & Risk Validation

## Overview

Read-only comparative backtest of the canonical HLC 3-bar scalp strategy.

### Data Source
- Database: `/opt/tradingai/database/tradingai.db`
- Date range: 2026-07-06 to 2026-10-28
- Instruments: NIFTY, BANKNIFTY

### Signal Rules (Exact, from `app/research/scalp_engine.py`)
- BULL: 3 consecutive completed 5m candles with higher H, higher L, higher C
- BEAR: 3 consecutive completed 5m candles with lower H, lower L, lower C
- Signal candle = 3rd confirming candle
- Entry = next candle's open (historical reference fill)
- Stop = signal candle low − 1 (BULL) / high + 1 (BEAR)
- Target = entry + 1.5×risk (BULL) / entry − 1.5×risk (BEAR)
- Reject if risk <= 0
- Exit evaluated from entry candle onward; stop-first tie-break on same candle
- EOD flat at last session candle close if neither level hit
- No look-ahead: only completed candles used for signal detection

### Execution Modes

**Mode A — One trade per day per instrument**
- Take the first eligible signal of each session.
- No additional trades that day, even if the first exits early.
- Matches current production daily-limit behavior (`MAX_TRADES_PER_DAY = 1`).

**Mode B — Every signal, overlapping allowed**
- Execute every eligible signal.
- Multiple positions on the same instrument may be open simultaneously.
- Each position tracked independently.

**Mode C — Every signal, one open position per instrument**
- Execute first eligible signal when instrument has no open position.
- Ignore new signals while position is open.
- Resume after position closes.
- No positions carried across sessions.

### Exit Conventions
- Convention A (primary): exit check starts at entry candle (live-faithful)
- Convention B (sensitivity): exit check starts strictly after entry candle

### Cost Scenarios (per trade round-trip, index points)
- Zero cost: 0.0 pts
- Modest cost: 1.0 pts
- Adverse cost: 2.0 pts

## Results by Instrument and Mode (Convention A, Zero Cost)

### NIFTY

| Mode | Trades | Win Rate | Net Points | Avg R | Max DD (pts) | Max Simul Pos | Max Agg Risk |
|------|--------|----------|------------|-------|--------------|---------------|--------------|
| A_one_trade_per_day | 80 | 67.5% | 818.74 | 0.688 | 75.35 | 1 | 47.4 |
| B_every_signal_overlapping | 505 | 72.87% | 6444.38 | 0.82 | 105.66 | 4 | 147.55 |
| C_one_open_position | 388 | 72.42% | 5065.89 | 0.808 | 105.13 | 1 | 94.65 |

### BANKNIFTY

| Mode | Trades | Win Rate | Net Points | Avg R | Max DD (pts) | Max Simul Pos | Max Agg Risk |
|------|--------|----------|------------|-------|--------------|---------------|--------------|
| A_one_trade_per_day | 78 | 71.79% | 2946.3 | 0.783 | 323.73 | 1 | 275.3 |
| B_every_signal_overlapping | 441 | 71.66% | 15730.49 | 0.782 | 414.55 | 3 | 376.7 |
| C_one_open_position | 345 | 71.3% | 13067.99 | 0.771 | 412.5 | 1 | 275.3 |

## Key Findings

### Mode A (1 trade/day)
- Simple, matches current production behavior
- Lowest trade count, lowest drawdown

### Mode B (Every signal, overlapping)
- Highest gross points but highest drawdown and aggregate risk
- Multiple concurrent positions increase risk exposure

### Mode C (1 open position)
- Middle ground between A and B
- Avoids overlapping risk while capturing more signals than Mode A

## Limitations
- Results are index points, not rupee P&L or options returns
- Next-candle open is a reference fill, not a guaranteed live fill
- OHLC data cannot determine exact intrabar order of stop/target touches
- Cost scenarios are illustrative assumptions

## Output Files
- `mode_comparison.csv` — All modes, all instruments, all cost scenarios
- `trade_log_mode_a.csv`, `trade_log_mode_b.csv`, `trade_log_mode_c.csv`
- `daily_equity_mode_a.csv`, `daily_equity_mode_b.csv`, `daily_equity_mode_c.csv`
- `monthly_summary.csv`
- `execution_cost_sensitivity.csv`
- `overlap_analysis.csv`
- `run_comparison.py` — This script
- `test_hlc_frequency.py` — Automated tests