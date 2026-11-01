# Phase 5.19 — Historical Evidence Integrity

## Preserved Artifacts

| Artifact | Location | Status |
|----------|----------|--------|
| 729-trade backtest | phase512/TRADE_LEDGER_NIFTY.json + BANKNIFTY.json | Preserved |
| 723-trade expiry replay | phase515/HISTORICAL_EXPIRY_REPLAY.csv | Preserved |
| 161-trade OOS subset | Subset of 729 (test split) | Preserved |
| 245 extra CSV rows | phase512/TRADE_LEDGER.csv | Preserved |
| Timezone tests | phase516/ET10_TIMEZONE_TESTS.csv | Preserved |
| Production function tests | phase516/PRODUCTION_FUNCTION_TESTS.csv | Preserved |
| Expiry end-to-end tests | phase517/EXPIRY_END_TO_END_TESTS.csv | Preserved |
| Go/no-go report | phase518/PHASE518_REPORT.md | Preserved |

## Hash Verification

Source file hashes recorded in SOURCE_HASHES.txt. All match previous phases.

## Index-Point vs Option-Level

- All metrics in index points (NIFTY/BANKNIFTY)
- No option premium data
- No conversion to rupees
- Option-level profitability: NOT VERIFIED
