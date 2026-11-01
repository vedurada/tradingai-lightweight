# Phase 5.14 — Next-Candle Reproduction

## Method

Independently recomputed the next-candle entry scenario by:
1. Loading all candles chronologically
2. Detecting signals using _scan_signals (canonical)
3. Entering at candle i+2 (one candle later than baseline)
4. Computing exit using forward scan from entry candle
5. Applying Mode C (one open position per instrument)

## Results

| Metric | Baseline (S1) | Next-Candle (S2) | Change |
|--------|--------------|-------------------|--------|
| Trades | 729 | 974 | +245 (+33.6%) |
| Wins | 528 | 432 | -96 |
| Losses | 201 | 542 | +341 |
| Win rate | 72.43% | 44.35% | -28.08 pp |
| Total points | 19,210.95 | 7,167.92 | -62.7% |
| Profit factor | 3.47 | 1.25 | -64.0% |
| Expectancy (R) | 0.794 | 0.073 | -90.8% |
| Max drawdown | 442.40 | 3,097.22 | +599.9% |
| Max consec losses | 6 | 20 | +233.3% |

## Verification

- Reproduces Phase 5.13 reported values exactly: WR 44.35%, PF 1.25 ✓
- Entry convention: next candle's open (candles[i+2].open)
- Exit rules: same as baseline (forward scan, stop-first tie-break)
- Mode C enforced: one open position per instrument

## Explanation

The degradation is caused by:
1. Worse entry prices (market has moved one candle)
2. More trades created (245 additional, from signals that were blocked by Mode C in baseline)
3. Lower win rate on additional trades
4. Larger drawdowns due to worse entry timing

## Limitations

- Slippage not modeled in next-candle scenario
- Assumes next candle open is executable (may not be in live trading)
- No spread or liquidity considerations
