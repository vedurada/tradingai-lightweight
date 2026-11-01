# Phase 5.16 — Timestamp Semantics, Production-Path Expiry Validation, and Evidence Reconciliation

## Environment

- Host: `webserver` (Oracle VM)
- Application root: `/opt/tradingai`
- Database: `/opt/tradingai/database/tradingai.db` (read-only)
- Phase 5.15: `/opt/tradingai/research/phase515_expiry_20261029_214000/`
- Report directory: `/opt/tradingai/research/phase516_timestamp_20261029_215000/`

## Workstream A — Phase 5.15 Evidence Verification

All Phase 5.15 claims verified against actual files:
- 6 overnight-carry trades ✓
- 723/729 accepted, 6 rejected ✓
- 161/161 OOS trades accepted ✓
- ET10: 1 of 15 tests (timezone mismatch — design question) ✓
- 245-row CSV discrepancy ✓
- 14/15 expiry tests PASS ✓

No disagreements found.

## Workstream B — ET10 Resolution

See `TIMESTAMP_SEMANTICS.md` and `ET10_TIMEZONE_TESTS.csv`.

### Canonical Policy

Timestamps in the system use ISO 8601 with +05:30 offset (Asia/Kolkata). Signal time, entry time, and now are all in IST. The comparison policy:

1. Parse all timestamps as timezone-aware (assume IST if naive)
2. Compare instants (not labels) — UTC and IST representations of the same instant produce identical decisions
3. Fail closed on ambiguous/naive inputs where instant cannot be established
4. Session date derived from IST date (not UTC)

### ET10 Test Results

See `ET10_TIMEZONE_TESTS.csv`. 8/8 tests PASS.

## Workstream C — Production Function Tests

See `PRODUCTION_FUNCTION_TESTS.csv`.

### Tests Executed

14 tests using actual production functions (`_entry_time_guard` from `scripts/paper_scalp_live.py`):
- 14/14 PASS

### Code-Inspection Checks (Not Executed)

3 checks via code inspection (no test execution):
- Signal persistence in scalp_signals table
- Mode C enforcement in try_create_trade
- monitor() independence from entry guard

## Workstream D — Expiry Replay Reconciliation

See `EXPIRY_REPLAY_RECONCILIATION.csv` and `SIX_EXCLUDED_TRADES_AUDIT.csv`.

### Results

| Metric | Original (729) | With Expiry (723) | Change |
|--------|----------------|-------------------|--------|
| Trades | 729 | 723 | -6 |
| Win rate | 72.43% | 72.20% | -0.23 pp |
| Total points | 19,210.95 | 17,857.91 | -1,353.04 |
| Profit factor | 3.47 | 3.30 | -0.17 |
| Max drawdown | 442.40 | 442.40 | 0 |

### Six Excluded Trades

All 6 were overnight carries (signal on day D, entry on day D+1). All 6 were winners (+1,353.04 points). Excluding them slightly reduces performance.

### Out-of-Sample

161 test trades: UNCHANGED (all accepted). No cross-session trades in test period.

## Workstream E — 245-Row Discrepancy

See `LEDGER_245_ROW_DISCREPANCY.md`.

### Results

- CSV: 974 rows, JSON: 729 trades
- All 729 JSON trades present in CSV
- 245 extra CSV rows: 197 CLOSE_ENTRY_TIME, 48 NEW_SIGNAL_NOT_IN_JSON
- Root cause: first backtest script's candle-by-candle processing with last-candle detection
- Status: UNRESOLVED

## Final Classification

**PARTIAL — SOME EVIDENCE/TESTS REMAIN INCOMPLETE OR UNRESOLVED**

Reasons:
1. ET10 resolved (timezone policy documented, 8/8 tests pass)
2. Production function tests: 14/14 PASS (using actual _entry_time_guard)
3. Expiry replay reconciled (723/729 accepted)
4. 245-row discrepancy remains UNRESOLVED
5. No production changes made
