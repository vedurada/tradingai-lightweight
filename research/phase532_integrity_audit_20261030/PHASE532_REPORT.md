# Phase 5.32 — Candle Replay Reconciliation and Performance Integrity Audit

## Environment
- Host: `webserver` (Oracle VM)
- Project root: `/opt/tradingai`
- Phase 5.31 report: `/opt/tradingai/research/phase531_candle_replay_20261029_224500/`

## Phase A — Source and Artifact Verification
- Phase 5.31 deliverables read and verified present.
- Day-by-day replay: 729 trades (72.43% WR, +19,210.95 pts, PF 3.47).
- Candle-by-candle replay: 881 trades (98.18% WR, +19,565.04 pts, PF 1604.69).
- Source artifacts unchanged (read-only research).

## Phase B — Six-Case Final Reconciliation
See `SIX_CASE_FINAL_RECONCILIATION.csv`.

## Phase C — 245-to-881 Row Reconciliation
See `245_ROW_TO_881_TRADE_RECONCILIATION.csv`.

## Phase D — Performance Integrity Audit
See `CANDLE_REPLAY_METRIC_RECALCULATION.csv`, `PROFIT_FACTOR_INTEGRITY_AUDIT.md`, `WIN_LOSS_AND_EXIT_AUDIT.csv`, `INSTRUMENT_PERFORMANCE_COMPARISON.csv`.

## Phase E — Replay Model Fairness
See `REPLAY_MODEL_FAIRNESS.md`.

## Phase F — No-Lookahead and Data Leakage Audit
See `NO_LOOKAHEAD_AND_DATA_LEAKAGE_AUDIT.md`.

## Final Verdict
TBD
