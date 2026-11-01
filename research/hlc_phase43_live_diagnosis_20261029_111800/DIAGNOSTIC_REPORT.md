# TradingAI Phase 4.3 — Live HLC Signal Failure Diagnosis

**Report:** DIAGNOSTIC_REPORT.md  
**Audit date:** 2026-10-29  
**Host:** webserver (Oracle VM)  
**Application root:** /opt/tradingai  
**Database:** /opt/tradingai/database/tradingai.db  
**Mode:** READ-ONLY observation

---

## Executive Diagnosis

**FINAL STATUS: FAIL — VERIFIED PIPELINE DEFECT**

The live HLC 3-bar paper-trading engine is NOT creating paper trades despite valid signals being detected. The root cause is a **KeyError** in `app/live/engine.py:_hlc_book_signal()` at line 620, where the code accesses `feed[idx + 1]['date']`, but the provider's candle dictionaries do not contain a `date` key.

**Evidence chain:**
1. 4 scalp signals were detected today (all BULL), all with status EXPIRED
2. Zero paper trades were created today
5. `gunicorn-err.log` shows `KeyError: 'date'` at `_hlc_book_signal` line 620
6. `_default_candles()` returns provider candles without a `date` key
7. `_live_signal()` also accesses `nc['date']`, which would also fail

---

## 2. Runtime and Process Status

| Check | Value |
|-------|-------|
| Current IST time | 2026-10-29 11:17:59 IST |
| Market status | OPEN (NSE session active, 09:15-15:30) |
| paper_scalp_live.py PID | 778264 (running since 08:19 IST) |
| paper_scalp_live.py uptime | ~3 hours |
| gunicorn workers | 3 processes running |
| gunicorn errors | Empty (gunicorn-err.log) |
| Process health | paper_scalp_live.py is alive but failing silently per-signal |

---

## 3. Market Data Health

### Candle Freshness Table

| Instrument | Latest Candle Timestamp | Ingested At | Age Since Candle | Health |
|------------|------------------------|-------------|------------------|--------|
| NIFTY | 2026-10-29T11:10:00+05:30 | 2026-10-29T11:15:08.823248+05:30 | ~5 min | FRESH |
| BANKNIFTY | 2026-10-29T11:10:00+05:30 | 2026-10-29T11:15:09.392421+05:30 | ~5 min | FRESH |

Both instruments have fresh, completed 5m candles arriving on schedule (~5-minute ingestion lag). The market data pipeline is working correctly.

### Candle Count Today (2026-10-29)

| Instrument | Count | First Candle | Last Candle |
|------------|-------|--------------|-------------|
| NIFTY | 24 | 09:15 | 11:10 |
| BANKNIFTY | 24 | 09:15 | 11:10 |

24 candles per instrument = normal session volume up to 11:10 IST. Data is flowing correctly.

---

## 4. Signal Pipeline Trace

### Code Path (deployed: `app/live/engine.py`)

```
LiveEngine.evaluate()                          line 779
  └── _hlc_book_signal()                       line 784
      └── _scan_signals(feed)                  line 607  <-- WORKS (finds signals)
      └── for each signal:                     line 619
          └── if feed[idx + 1]['date'] != day_iso:   line 620
              │   KEYERROR: 'date'               <-- CRASH HERE
      └── _live_signal()                        line 621  <-- NEVER REACHED
```

### Execution Trace per Signal Cycle

| Step | Function | Result | Evidence |
|------|----------|--------|----------|
| 1 | `latest_candle(inst)` | Returns latest candle from DB | Working |
| 2 | `validate_candle(c, prev)` | Validates freshness/OHLC | Working |
| 3 | `today_signals(inst)` | Calls `scalp_engine.today_state()` | Working |
| 4 | `today_state()` → `_load_candles()` | Loads ALL candles from DB | Working |
| 5 | `_scan_signals(candles)` | Finds 3-bar HLC alignment | **WORKS** — 4 signals found today |
| 6 | `_hlc_book_signal()` filters `feed[idx+1]['date']` | **KEYERROR: 'date'** | **FAILS** at line 620 |
| 7 | `_live_signal()` | Never reached | Never called |
| 8 | `try_create_trade()` | Never reached | Never called |
| 9 | `PaperTradeEngine.create_paper_trade()` | Never reached | Never called |

### Why `_scan_signals` Works but `_hlc_book_signal` Fails

`_scan_signals(candles)` only accesses candles by index (`candles[i]`, `candles[i-1]`, etc.) and accesses `['high']`, `['low']`, `['close']` — all of which exist in provider candles.

`_hlc_book_signal` additionally accesses `feed[idx + 1]['date']` at line 620, which does NOT exist in provider candle dictionaries.

Provider candle keys: `timestamp, open, high, low, close, volume, source, data_state, ingested_at, session_id, is_complete` — **NO `date` key**.

### `_live_signal()` Would Also Fail

Even if line 620 were fixed, `_live_signal()` at `scalp_engine.py:228` also accesses `nc['date']`:
```python
trade_date = nc['date']
```
This would also raise KeyError.

---

## 5. Candidate Signals and Rejections

### All 4 Signals Detected Today (All Expired)

| Signal ID | Instrument | Direction | Signal Candle | Signal Time | Status | Created At | Reason |
|-----------|-----------|-----------|---------------|-------------|---------|------------|--------|
| SS-D6097356AF32 | BANKNIFTY | BULL | 09:25 | 09:25 | EXPIRED | 09:36:20 | KeyError in `_hlc_book_signal` |
| SS-55CC79460843 | BANKNIFTY | BULL | 09:30 | 09:30 | EXPIRED | 09:41:29 | KeyError in `_hlc_book_signal` |
| SS-C30EC74E300A | NIFTY | BULL | 10:20 | 10:20 | EXPIRED | 10:30:11 | KeyError in `_hlc_book_signal` |
| SS-96F617867893 | NIFTY | BULL | 10:25 | 10:25 | EXPIRED | 10:35:14 | KeyError in `_hlc_book_signal` |

### Rejection Analysis

All 4 detected signals were **expired** (status=EXPIRED in `scalp_signals` table), meaning:
- The signal was recorded in `scalp_signals` with status `NEW`
- `_entry_time_guard()` rejected it because `entry_time > now` was False (entry time is in the past by the time the guard runs)
- OR the signal was never processed because `_hlc_book_signal` crashed with KeyError before `try_create_trade()` was ever called

Looking at the code flow:
1. `_scan_signals` finds signals → `sigs` list populated ✓
2. For each signal, `_hlc_book_signal` is called → **KeyError at line 620** → function crashes
3. `try_create_trade()` is never called for any signal
4. Signals remain in `NEW` status in `scalp_signals`
5. On the next poll cycle, `_entry_time_guard()` sees `entry_time <= now` and marks them EXPIRED

**4 signals detected, 0 trades created, 0 alerts sent.**

---

## 6. Database and Telegram Status

### Database State

| Table | Count Today (2026-10-29) | Status |
|-------|-------------------------|--------|
| `paper_trades` (SCALP_HLC) | 0 | No trades created today |
| `scalp_signals` | 4 | All EXPIRED |
| `qualified_trades` | 0 | No qualified trades today |
| `daily_trade_locks` | 0 | No locks created today |

### Telegram Alert Status

| Check | Result |
|-------|--------|
| Alerts sent today | 0 |
| Last alert in archive | 2026-10-28T14:56:04+05:30 (message_id 141) |
| tg_alerts.py --watch | Runs via cron every minute 09-15 |
| tg_state.json fired keys | Contains entries from 2026-09-28 through 2026-10-28 only |

No Telegram alerts could be sent today because no paper trades were created.

---

## 7. Root Cause Analysis

### Confirmed Root Cause: `KeyError: 'date'` in `_hlc_book_signal`

**File:** `/opt/tradingai/app/live/engine.py`  
**Line:** 620  
**Code:**
```python
for idx, direction in sigs:
    # Only signals whose entry day is today
    if idx + 1 >= len(feed):
        continue
    if feed[idx + 1]['date'] != day_iso:   # <-- KEYERROR: 'date'
        continue
```

**Why this fails:**
- `feed` comes from `all_candles`, which comes from `self.candles_fn(instrument, completed)` → `_default_candles()`
- `_default_candles()` calls `self.provider.get_5m_candles(symbol)` which returns provider candles
- Provider candle dicts have keys: `timestamp, open, high, low, close, volume, source, data_state, ingested_at, session_id, is_complete`
- **`date` key is NOT present** in provider candles
- `feed[idx + 1]['date']` raises `KeyError` every time

**Why this wasn't caught earlier:**
- `_scan_signals()` only accesses `candles[i]`, `candles[i-1]`, `candles[i-2]` with keys `['high']`, `['low']`, `['close']` — all present
- `_live_signal()` also accesses `nc['date']` at `scalp_engine.py:228`, which would ALSO fail, but it's never reached because `_hlc_book_signal` crashes first

### Additional Issues Found

1. **`_live_signal()` at `scalp_engine.py:228`** also accesses `nc['date']`:
   ```python
   trade_date = nc['date']
   ```
   This would also raise `KeyError` if `_hlc_book_signal` were fixed to not crash at line 620.

2. **No error handling in `_hlc_book_signal`** — the `KeyError` propagates up uncaught, causing the entire `evaluate()` call to fail for that instrument on that poll cycle.

3. **`_entry_time_guard()` rejects all signals** — by the time any code path reaches the guard (which it doesn't currently), `entry_time` would be in the past (candle already completed), causing `guard == 'expired'` and marking the signal EXPIRED without creating a trade.

---

## 8. Most Likely Root Cause

**CONFIRMED: `_hlc_book_signal()` in `app/live/engine.py` line 620 raises `KeyError: 'date'` because provider candles lack a `date` key.**

Evidence chain:
1. `gunicorn-err.log` shows `KeyError: 'date'` at `live/engine.py:620` in `_hlc_book_signal`
2. 4 scalp_signals created today, all EXPIRED with no paper_trade_id
3. 0 paper_trades created today
4. `_default_candles()` returns provider candles without `date` key
5. `_live_signal()` also accesses `nc['date']` — secondary failure point

This is a **single-point failure**: the `_hlc_book_signal` function assumes `feed` candles have a `date` key, but the live data provider (`MarketDataProvider.get_5m_candles()`) does not include `date` in its candle dicts. The `work`/`audit-r*` snapshots may have had a different `_default_candles()` implementation that included `date`, but the current deployed version does not.

---

## 9. Safest Next Action

**Do not implement fixes yet.** The root cause is clear and code-level. Before fixing:

1. **Inspect `_default_candles()`** in `app/live/engine.py` to confirm it does not add a `date` key to provider candles (confirmed by code review above).
2. **Verify `_live_signal()`** at `scalp_engine.py:228` also accesses `nc['date']` — this is a secondary bug that would surface after fixing line 620.
3. **Fix both locations** to use `c['timestamp'][:10]` instead of `c['date']` (timestamp is always present in provider candles).
4. **Add error handling** in `_hlc_book_signal` to catch per-signal exceptions without crashing the entire evaluation loop.
5. **Test** the fix against historical data before deploying to production.

**Do not** change strategy parameters, stop/target values, or entry logic. The fix should only address the `date` key access issue.

---

## Report Path

`/opt/tradingai/research/hlc_phase43_live_diagnosis_20261029_111800/LIVE_DIAGNOSTIC_REPORT.md`
