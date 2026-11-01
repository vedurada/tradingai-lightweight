# Phase 5.42 — Risk and Execution Findings (974 vs 881)

## Purpose
Assess delayed-entry sensitivity, one-candle-later entry, slippage assumptions, stop-vs-EOD exits, MAE/MFE, session-boundary risk.

## Findings
- MAE/MFE computed for all 881 trades; coverage COMPLETE (881/881).
- NIFTY MAE max 23.0, MFE max 92.35; BANKNIFTY MAE max 72.35, MFE max 308.45.
- Do not fabricate historical option premium or spread P&L where option data unavailable.

## Status
PENDING
