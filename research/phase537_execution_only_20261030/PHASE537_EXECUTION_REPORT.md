# Phase 5.37 — Direct Execution of Outstanding HLC Sensitivity Scenarios

## Environment
- Host: `webserver` (Oracle VM)
- Project root: `/opt/tradingai`
- Sources: Phase 5.34, 5.35, 5.36.

## Step 1 — Locate Inputs
- 881-trade ledger: `/opt/tradingai/research/phase534_risk_validation_20261030/ALL_881_TRADES_MAE_MFE.csv`
- Historical candles: via `app.research.scalp_engine._load_candles`.
- Entry/exit timestamps/prices: present in ledger.

## Step 2 — Verify Baseline
- Expected: 881 trades, 865 wins, 15 losses, 1 flat, Net +19,565.04, PF 1604.69.
- Verified in Phase 5.32–5.34 recalculation.

## Step 3 — Scenario B: Delayed Entry
- Execution: attempted; prior run did not complete cleanly.

## Step 4 — Entry / Exit Slippage
- Scenarios C1–C3, D1–D3 defined.

## Step 5 — Combined Stress
- Scenarios E, F defined.

## Step 6 — Calculate Results
- Baseline metrics recorded.

## Step 7 — Trade-Level Reconciliation
- Pending.

## Step 8 — Execution Failure Handling
- Prior execution run encountered IndexError on empty candle window; classified as calculation/data-handling issue.

## Final Status
PARTIAL
