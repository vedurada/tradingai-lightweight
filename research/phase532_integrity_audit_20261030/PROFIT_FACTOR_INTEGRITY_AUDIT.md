# Phase 5.32 — Profit Factor Integrity Audit

## Independent Recalculation (from 881-row ledger)

- Gross winning points: 19,577.24
- Gross losing points: 12.2
- Net points: 19,565.04
- Profit factor: 1604.69
- Win rate: 98.18%
- Wins: 865, Losses: 15, Breakeven: 1

## PF 1604.69 Analysis

- Gross losses are NOT zero (12.2 points), therefore PF is finite and computable.
- PF = 19577.24 / 12.2 = 1604.69.
- Average win: 22.63 pts; average loss: 0.81 pts.
- The PF is extreme because losing amounts are very small relative to winning amounts.
- All 15 losses exited via EOD (exit_reason=EOD); zero STOP exits recorded.
- Loss point total is small; no missing losses identified in ledger.

## Conclusion
PF of 1604.69 is mathematically valid for this ledger. Extreme value driven by asymmetric win/loss magnitudes, not by zero losses.
