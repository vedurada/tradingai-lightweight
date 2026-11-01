# Phase 5.14 — Unresolved Discrepancies

## 1. TRADE_LEDGER.csv vs JSON (245 extra rows)

**Status: UNRESOLVED**

The CSV has 974 rows while the JSON has 729 trades. All 729 JSON trades are present in the CSV. The 245 extra CSV rows are classified as:
- 197 CLOSE_ENTRY_TIME (entry within 1 hour of a JSON trade on same day/instrument)
- 48 NEW_SIGNAL_NOT_IN_JSON (no close JSON trade on that day/instrument)

**Root cause:** The first backtest script (phase512_backtest.py) processed candle-by-candle and used _scan_signals with last-candle detection, generating additional signals that the second script (day-by-day) filtered out.

**Impact:** CSV-derived analysis (monthly performance, instrument comparison) is unreliable. JSON files are authoritative.

**Resolution:** Use JSON files as the authoritative trade ledger. Regenerate any CSV-based analysis from JSON.

## 2. Overnight Signal Carry

**Status: UNRESOLVED**

Some signals fire on the last candle of a trading day (15:25) and enter on the first candle of the next day (09:15). This is a 17-hour delay. In live trading, the entry guard would pass (entry_time = today 09:15, now = 09:15, within 5-min window), but the signal is 17 hours old.

**Impact:** Overnight signals can create trades in live trading that may not be desirable. The is_stale check uses entry_time, not signal_time.

**Resolution:** Consider adding signal-age validation to the entry guard or paper_scalp_live.py.

## 3. S3 Slippage Approximation

**Status: UNRESOLVED**

The slippage scenario (S3) used risk ratio scaling instead of adjusting entry prices directly. This produced slightly better points than baseline, which is counterintuitive. The approximation is incorrect.

**Impact:** S3 results are unreliable. Need proper slippage simulation with adjusted entry prices.

**Resolution:** Re-run with correct slippage model (entry price ± slippage, recompute stop/target/risk).

## 4. Options-Level Profitability

**Status: NOT TESTED**

No historical option quote data available. Index-point returns cannot be converted to rupee returns without contract specifications.

**Impact:** Cannot determine if the strategy is profitable in options terms.

**Resolution:** Requires historical option premium data and contract specifications.
