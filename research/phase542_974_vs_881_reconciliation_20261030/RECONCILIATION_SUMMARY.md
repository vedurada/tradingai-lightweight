# Phase 5.42 — 974 vs 881 Trade Reconciliation

## Objective
Reconcile deterministic 974-trade historical replay against earlier 881-trade candle-by-candle ledger.

## Inputs
- New 974-trade ledger: `/opt/tradingai/research/phase541_stage3a_20261030/REPLAY_TRADE_LEDGER.csv` (RUN1 974 + RUN2 974 rows; unique 974 trades).
- Prior 881-trade ledger: `/opt/tradingai/research/phase534_risk_validation_20261030/ALL_881_TRADES_MAE_MFE.csv`.

## Method
- Stable key: (instrument, direction, entry_time).
- Classification: EXACT_MATCH / SAME_SIGNAL_DIFF_ENTRY / SAME_SIGNAL_DIFF_EXIT / DIFFERENT_SIGNAL / MISSING_FROM_974 / MISSING_FROM_881 / DUPLICATE / AMBIGUOUS.

## Findings
- Trades in 974: 974. Trades in 881: 881.
- Trades missing from 974: 0.
- Trades missing from 881: 93.
- Comparable pairs: 881; all classified as differing under strict field alignment (field/units semantics differ: `points` vs `mfe_pts`; excursion vs realised P&L).
- No duplicate trade keys within either ledger.

## Deliverables
- TRADE_LEVEL_RECONCILIATION.csv
- UNMATCHED_TRADES.csv
- METRICS_COMPARISON.csv
- METHODOLOGY_DIFFERENCES.md
- RISK_AND_EXECUTION_FINDINGS.md
- FINAL_DECISION.md

## Status
IN_PROGRESS
