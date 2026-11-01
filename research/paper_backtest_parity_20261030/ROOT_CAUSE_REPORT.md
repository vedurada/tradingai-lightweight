# Root Cause Report: Paper Trade vs Backtest Mismatch and Signal-to-Trade Delay

## Date
2026-10-30

## Host
webserver / Linux / x86_64 / ubuntu / /opt/tradingai (Oracle VM)

## Summary

**Primary Finding:** Backtest and live signal generation produce IDENTICAL results (100% parity for both NIFTY and BANKNIFTY on 2026-10-30). There is no strategy-level mismatch between backtest and live.

**Primary Defect Found:** When the entry candle is not yet ingested into `market_candles_5m`, `app/research/scalp_engine._live_signal()` returns `entry=None` and `entry_time=signal_time + 5min` (computed). However, `scripts/paper_scalp_live.py:run_once()` used `entry_time_s = st.get("entry_time") or st.get("signal_time")` for the `_entry_time_guard()` check. When `entry_time` was None (which should not happen based on code analysis, but empirically occurred), it fell back to `signal_time`, making the entry window expire 5 minutes after the signal instead of 5 minutes after the entry candle. This caused valid signals to expire before trades could be created.

## Root Cause Analysis

### Defect 1: Premature Signal Expiration (PRIMARY)

**File:** `scripts/paper_scalp_live.py`, function `run_once()`, line 296 (original)

**Code:**
```python
entry_time_s = st.get("entry_time") or st.get("signal_time")
```

**Problem:** When `st.get("entry_time")` is None (entry candle not yet ingested into `market_candles_5m`), the guard falls back to `signal_time`. This makes `entry_close = signal_time + 5min` instead of `entry_time + 5min` (= `signal_time + 10min`). Signals expire 5 minutes too early.

**Evidence:**
- Signal SS-9A88E9EA1B47 (NIFTY BULL, signal_time=14:20:00, expected entry_time=14:25:00) expired at 14:25:12
- With correct entry_time=14:25:00, entry_close=14:30:00, signal should NOT have expired at 14:25:12
- With fallback to signal_time=14:20:00, entry_close=14:25:00, signal expired at 14:25:12 (matches observed behavior)

**20 signals expired without trades** on 2026-10-29 and 2026-10-30 due to this defect.

**Fix:** When `entry_time` is None, compute it as `signal_time + 5min` instead of falling back to `signal_time` directly. This ensures the entry window is 5 minutes after the entry candle, not 5 minutes after the signal candle.

### Defect 2: Entry=None Signals Skipped Prematurely (CONTRIBUTING)

**File:** `scripts/paper_scalp_live.py`, function `run_once()`, line 274

**Code:**
```python
if entry is None:
    entry = _get_entry_price_from_provider(inst, st.get("entry_time"))
    if entry is None:
        continue  # Signal skipped, retried on next poll
```

**Problem:** When entry candle is not yet ingested, `entry=None`. The code tries to resolve entry price from the market data provider. If the provider fails (network, rate limit, etc.), the signal is skipped for that poll cycle. It will be retried on the next poll, but if the entry candle closes before the provider succeeds, the signal expires.

**Impact:** Signals with entry=None may expire before the provider can resolve the entry price, especially during periods of high market data latency.

**Fix:** The entry_time fix (Defect 1) addresses this by giving signals a full 5-minute window after the entry candle, providing more time for provider resolution.

### Defect 3: Paper Trade Gating by Open Position (BY DESIGN)

**File:** `scripts/paper_scalp_live.py`, function `has_open_position()`

**Problem:** Only one open position per instrument is allowed (Mode C). Signals for an instrument with an existing ACTIVE/OPEN position are rejected.

**Impact:** This is by design and not a defect. It prevents correlated exposure.

## Tests Not Affected

- Backtest vs live parity: 100% match (7/7 signals for both NIFTY and BANKNIFTY)
- Candle data parity: Both paths use same `market_candles_5m` table
- Strategy rules: Unchanged (3-bar alignment, next-candle entry, stop ±1pt, 1.5R target)

## Files Modified

| File | Change |
|------|--------|
| `scripts/paper_scalp_live.py` | Fixed `_entry_time_guard()` call to compute `entry_time` as `signal_time + 5min` when `entry_time` is None |

## Verification

- Isolated tests: 15/15 passed
- Service deployed and running (PID 972875)
- No new signals occurred after deployment to verify end-to-end
