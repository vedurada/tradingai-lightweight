# Phase 5.28 — Backtest Ledger Root-Cause Audit

## Environment

- Host: `webserver` (Oracle VM)
- Application root: `/opt/tradingai`
- Database: `/opt/tradingai/database/tradingai.db` (read-only)
- Phase 5.27: `/opt/tradingai/research/phase527_reconciliation_20261029_222500/`
- Report directory: `/opt/tradingai/research/phase528_rootcause_20261029_223000/`

## Phase A — Evidence Verification

- TRADE_LEDGER.csv: 974 rows (975 lines including header)
- TRADE_LEDGER_NIFTY.json: 382 trades
- TRADE_LEDGER_BANKNIFTY.json: 347 trades
- Total JSON trades: 729
- All 729 JSON trades present in CSV (0 JSON-only)
- 245 extra CSV rows (all unique by instrument+entry_time+direction)

## Phase B — Classification of 245 Extra Rows

See `ALL_245_ROWS_ROOT_CAUSE.csv`.

- 729 MATCHED (present in authoritative JSON)
- 245 CLOSE_ENTRY_TIME (all extra rows have JSON trades on same day/instrument)
- 0 NEW_SIGNAL_NOT_IN_JSON (reclassified — all have same-day JSON trades)

### Root Cause

The first backtest script (`phase512_backtest.py`) processed candle-by-candle and used `_scan_signals` with last-candle detection. For each candle, it scanned ALL available candles and found signals whose entry candle was the current candle. The last-candle detection appended an additional signal at the last position of the available candle array.

When the current candle was NOT the last candle in the available array (because more candles were added later), the last-candle signal was at a position whose entry candle was a FUTURE candle. The filter `idx + 1 == ci` should have excluded these, but the last-candle detection's signal index calculation was off by one, causing spurious signals to be processed.

The second script (`phase512_backtest2.py`) processed day-by-day and filtered by `entry_candle['date'] == day`, which correctly excluded these spurious signals.

### Confirmed Root Cause

The 245 extra rows are caused by the first script's candle-by-candle processing combined with `_scan_signals`'s last-candle detection. The last-candle detection generates signals at intermediate positions that are not valid in a day-by-day processing model.

## Phase C — Root Cause Test

See `DUPLICATE_AND_EVENT_LIFECYCLE_AUDIT.csv` and `FINAL_CANDLE_AND_SESSION_BOUNDARY_TESTS.md`.

- Last-candle detection: confirmed generates extra signals at intermediate positions
- Candle-by-candle processing: confirmed processes every candle, not just day boundaries
- Different eligibility rules: confirmed (idx+1==ci vs entry_date==day)
- Mode C blocking: first script tracks open_trade across all candles

## Phase D — Metrics Reproduction

See `AUTHORITATIVE_METRICS_REPRODUCTION.md` (from metrics_reproduction.json).

| Metric | Value |
|--------|-------|
| Total trades | 729 |
| NIFTY | 382 |
| BANKNIFTY | 347 |
| Wins | 528 |
| Losses | 201 |
| Win rate | 72.43% |
| Total points | 19,210.95 |
| Profit factor | 3.47 |

All metrics reproduce exactly from JSON files.

## Phase E — Unmatched Records

### 2 Unmatched Scalp Signals

From Phase 5.27: 2 of 29 scalp signals unmatched in replay. These are signals from Oct 29 (the most recent session) that may not have corresponding replay trades because the replay's last-candle detection doesn't generate signals for the final day's last candles.

### 4 Probable HLC Matches

4 of 30 HLC paper trades are PROBABLE_MATCH (same day/instrument/direction but no exact entry time match). These may be signals that fired on intermediate candles and were not captured by the replay's day-by-day processing.

## Final Classification

**PARTIAL — EVIDENCE IS AUDITABLE BUT SOME ROWS REMAIN UNRESOLVED**

Reasons:
1. Root cause identified: candle-by-candle processing + last-candle detection
2. 245 extra rows all classified as CLOSE_ENTRY_TIME (not NEW_SIGNAL_NOT_IN_JSON as earlier)
3. 729-trade metrics reproduce exactly
4. 2 unmatched scalp signals remain unexplained
5. 4 probable HLC matches not exact
