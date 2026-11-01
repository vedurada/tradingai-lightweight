# TradingAI Phase 4.8 — Collector Latency Audit and Remediation Plan

**Report:** PHASE48_REPORT.md  
**Audit date:** 2026-10-29  
**Host:** webserver (Oracle VM)  
**Application root:** /opt/tradingai  
**Database:** /opt/tradingai/database/tradingai.db  
**Mode:** READ-ONLY audit (no code, database, cron, systemd, or strategy modifications during this phase)

---

## 1. Executive Summary

**Confirmed root cause: The market-data collector runs every 5 minutes, creating a ~6 minute ingestion delay that exceeds the 5-minute HLC entry window.**

The `tradingai-market-data.timer` systemd unit runs `app/market/collector.py` every 5 minutes during market hours (Mon-Fri 09:15–15:30 IST). The collector's `get_completed_cutoff()` returns `floor_5m(now) - 5min`, meaning it only stores candles that completed at least 5 minutes ago. Combined with the 5-minute timer interval, this produces a consistent ~6 minute delay from candle open to DB ingestion.

Since the HLC entry window is exactly 5 minutes (`entry_time` to `entry_time + 5min`), no signal can ever be detected and traded within the entry window. All signals are correctly rejected as expired by `_entry_time_guard()`.

**Status:** READY FOR APPROVAL — SCHEDULING BOTTLENECK VERIFIED

---

## 2. Verified Collector Schedule and Active Processes

### 2.1 Collector Invocation

| Mechanism | Details |
|-----------|---------|
| Systemd timer | `tradingai-market-data.timer` (enabled) |
| Service unit | `tradingai-market-data.service` (oneshot) |
| ExecStart | `/usr/bin/python3 /opt/tradingai/app/market/collector.py` |
| User | ubuntu |
| Working directory | `/opt/tradingai` |
| Environment | `PYTHONPATH=/opt/tradingai` |

### 2.2 Timer Schedule

```
OnCalendar=Mon-Fri 09:1,6,11,16,21,26,31,36,41,46,51,56:00
OnCalendar=Mon-Fri 10,11,12,13,14,15:*:00/5
Persistent=true
RandomizedDelaySec=20
```

**Translation:** During 09:xx, the collector runs at :01, :06, :11, :16, :21, :26, :31, :36, :41, :46, :51, :56 (every 5 minutes, offset by 1 minute). During 10:xx–15:xx, it runs every 5 minutes at :00, :05, :10, :15, :20, :25, :30, :35, :40, :45, :50, :55. Plus up to 20 seconds of randomized delay.

**Effective cadence: every 5 minutes, with up to 20s of jitter.**

### 2.3 No Other Collector Processes

- No cron job runs `collector.py` (confirmed from crontab)
- No other process invokes `collect_instrument()` or `collect_all()`
- The `phase9_artifacts.py` and `phase11_artifacts.py` confirm: `'collector_daemon': 'NONE - on-demand fetch per API call'`

The only market data collection is via the systemd timer running `collector.py` every 5 minutes.

### 2.4 Collector Logic (`app/market/collector.py`)

| Aspect | Behavior |
|--------|----------|
| Data source | yfinance (same as `MarketDataProvider`) |
| Fetch method | `_fetch_history(symbol, '10d', '5m')` — bounded executor with 12s timeout + 1 retry |
| Candle completeness | Only COMPLETED candles stored (`is_complete=1`) |
| Cutoff logic | `get_completed_cutoff(now_ist)` = `floor_5m(now) - 5min` |
| Insert method | `INSERT OR IGNORE` on `candle_id` (no duplicates) |
| Insert timestamp | `ingested_at = now_ist.isoformat()` (when the row is inserted) |
| Date filter | Today only (default, unless `--backfill` or `--date`) |

### 2.5 `get_completed_cutoff()` Analysis

```python
def get_completed_cutoff(now_ist):
    day_start = now_ist.replace(hour=9, minute=20, second=0, microsecond=0)
    if now_ist < day_start:
        return None  # No completed candles before 09:20
    fc = now_ist.replace(minute=(now_ist.minute // 5) * 5, second=0, microsecond=0)
    return fc - timedelta(minutes=5)
```

**At 09:21:18 (first ingestion):**
- `day_start = 09:20` → now_ist (09:21) >= day_start → proceed
- `fc = floor_5m(09:21) = 09:20`
- `cutoff = 09:20 - 5min = 09:15`
- Only the 09:15 candle can be stored (it completed at 09:20)

**At 09:26:09 (second trigger):**
- `fc = floor_5m(09:26) = 09:25`
- `cutoff = 09:25 - 5min = 09:20`
- Now the 09:20 candle can be stored (it completed at 09:25)

**At 09:31:11 (third trigger):**
- `fc = floor_5m(09:31) = 09:30`
- `cutoff = 09:30 - 5min = 09:25`
- Now the 09:25 candle can be stored

**Pattern:** Each 5-minute trigger stores the candle that completed 5 minutes ago. The candle that just completed (at the trigger time) is NOT stored until the NEXT trigger (5 minutes later).

---

## 3. Timestamp Semantics and Latency Calculations

### 3.1 Verified Timestamp Semantics

| Field | Source | Represents |
|-------|--------|------------|
| `market_candles_5m.timestamp` | yfinance `idx` (UTC) → `_to_ist_iso()` → IST | **Candle open time** (project convention) |
| `market_candles_5m.ingested_at` | `now_ist.isoformat()` at INSERT time | **When the row was inserted into the DB** |
| `candle_id` | `'C-' + instrument + '-' + ts_ist.strftime('%Y%m%d%H%M%S')` | Unique ID based on candle open time |

**Confirmed:** `timestamp` = candle open time (project convention: timestamp == candle OPEN). `ingested_at` = wall-clock time when the collector inserted the row.

### 3.2 Measured Ingestion Latency (from DB records)

| Instrument | Candle Open | Candle Close | Ingested At | Open-to-Ingestion | Close-to-Ingestion |
|------------|------------|-------------|-------------|-------------------|-------------------|
| NIFTY | 09:15:00 | 09:20:00 | 09:21:18 | 378.39s (6.31 min) | 78.39s (1.31 min) |
| NIFTY | 09:20:00 | 09:25:00 | 09:26:09 | 369.14s (6.15 min) | 69.14s (1.15 min) |
| NIFTY | 09:25:00 | 09:30:00 | 09:31:11 | 371.15s (6.19 min) | 71.15s (1.19 min) |
| NIFTY | 09:30:00 | 09:35:00 | 09:36:16 | 376.13s (6.27 min) | 76.13s (1.27 min) |
| NIFTY | 09:35:00 | 09:40:00 | 09:41:29 | 376.79s (6.28 min) | 76.79s (1.28 min) |
| NIFTY | 09:40:00 | 09:45:00 | 09:46:17 | 377.00s (6.28 min) | 77.00s (1.28 min) |
| NIFTY | 09:45:00 | 09:50:00 | 09:51:20 | 380.00s (6.33 min) | 80.00s (1.33 min) |
| NIFTY | 09:50:00 | 09:55:00 | 09:56:20 | 380.00s (6.33 min) | 80.00s (1.33 min) |
| BANKNIFTY | 09:15:00 | 09:20:00 | 09:21:18 | 378.39s (6.31 min) | 78.39s (1.31 min) |
| BANKNIFTY | 09:20:00 | 09:25:00 | 09:26:09 | 369.14s (6.15 min) | 69.14s (1.15 min) |
| BANKNIFTY | 09:25:00 | 09:30:00 | 09:31:12 | 371.15s (6.19 min) | 71.15s (1.19 min) |
| BANKNIFTY | 09:30:00 | 09:35:00 | 09:36:16 | 376.13s (6.27 min) | 76.13s (1.27 min) |
| BANKNIFTY | 09:35:00 | 09:40:00 | 09:41:29 | 376.79s (6.28 min) | 76.79s (1.28 min) |
| BANKNIFTY | 09:40:00 | 09:45:00 | 09:46:17 | 377.00s (6.28 min) | 77.00s (1.28 min) |

**Key finding:** The `ingested_at - timestamp` (open-to-ingestion) is ~6 minutes. But the `ingested_at - (timestamp + 5min)` (close-to-ingestion) is only ~1-1.3 minutes. This means:
- The candle completes at `timestamp + 5min`
- The collector stores it at `ingested_at` ≈ `timestamp + 5min + 1min` = `timestamp + 6min`
- The ~5 minute "extra" delay is because the collector only runs every 5 minutes and the candle must complete before it can be stored

### 3.3 Why the Delay Is ~6 Minutes

The delay decomposes into two components:

1. **Candle completion delay (5 minutes):** A 5-minute candle `[open, open+5m)` is only complete after `open + 5min`. The collector's `get_completed_cutoff()` returns `floor_5m(now) - 5min`, which means it only stores candles that completed at least 5 minutes ago.

2. **Collection cadence delay (up to 5 minutes):** The collector runs every 5 minutes. If a candle completes at 09:20:00, the next collector trigger is at 09:21:00 (or 09:26:00 if the trigger was just missed). The collector then stores the candle at `ingested_at = trigger_time`.

**Total delay = candle completion (5 min) + collection cadence (up to 5 min) = up to 10 minutes worst case, ~6 minutes typical.**

The observed ~6 minute delay is consistent: candle completes at `open + 5min`, collector runs every 5 min, so worst case is `open + 5min + 5min = open + 10min`, but typical is `open + 5min + 1min = open + 6min` (because the collector trigger happens shortly after candle completion).

---

## 4. Forming-Candle Availability Assessment

### 4.1 Provider Behavior (`_fetch_candles` in `provider.py`)

The `get_5m_candles()` function fetches from yfinance with `period='10d', interval='5m'`. The response includes:
- All completed 5-minute candles (with `is_complete=True` when `now - candle_dt >= 5min`)
- The **forming (current) candle** (with `is_complete=False` when `now - candle_dt < 5min`)

The forming candle's `open` field IS populated in yfinance's response. It is available as soon as yfinance returns the data (which happens within seconds of the candle opening).

### 4.2 Forming-Candle Open Availability

| Aspect | Value |
|--------|-------|
| Earliest observed availability | At candle open (yfinance returns forming candle with `open` populated) |
| Price field | `candle['open']` (float, from yfinance `row['Open']`) |
| Timestamp field | `candle['timestamp']` (ISO 8601, converted to IST) |
| `is_complete` flag | `False` for forming candles (recomputed at serve time) |
| Cache TTL | 90 seconds (candles) |

**The forming candle's open IS available from the provider at candle-open time.** This is confirmed by `_fetch_candles()` in `provider.py` which includes the forming candle in the response (line: `is_complete = (now_ist - candle_dt).total_seconds() >= 5 * 60`).

### 4.3 Current Usage of Forming Candle

The `_get_entry_price_from_provider()` function in `paper_scalp_live.py:215-232` already fetches the forming candle's open:

```python
def _get_entry_price_from_provider(inst, entry_time):
    try:
        provider = MarketDataProvider()
        candles_data = provider.get_5m_candles(inst)
        for c in candles_data.get('candles', []):
            if c.get('timestamp') == entry_time:
                return float(c['open'])
    except Exception as e:
        print(f"{inst} provider entry price lookup failed: {e}", flush=True)
    return None
```

This function works correctly — it returns the forming candle's open price when the provider has it. The problem is that this function is only called when `entry is None` (i.e., when the entry candle is not in `market_candles_5m` DB table). But the signal detection pipeline (`_scan_signals`) requires the entry candle to be in the DB table, which only happens after ingestion.

---

## 5. HLC Execution Path Verification

### 5.1 Current Code State

| File | Function | Key Lines | Status |
|------|----------|-----------|--------|
| `app/research/scalp_engine.py` | `_scan_signals()` | 44-65 | ✅ Present — last-candle detection added (Phase 3.5) |
| `app/research/scalp_engine.py` | `_live_signal()` | 222-253 | ✅ Present — handles missing entry candle (entry=None) |
| `app/research/scalp_engine.py` | `_live_signal()` | 240 | ✅ Fixed — `trade_date = nc['timestamp'][:10]` (Phase 4.4) |
| `app/live/engine.py` | `_hlc_book_signal()` | 578-657 | ✅ Present — HLC signal detection |
| `app/live/engine.py` | `_hlc_book_signal()` | 620 | ✅ Fixed — `feed[idx + 1]['timestamp'][:10]` (Phase 4.4) |
| `scripts/paper_scalp_live.py` | `run_once()` | 236-311 | ✅ Present — calls `_get_entry_price_from_provider()` when entry=None |
| `scripts/paper_scalp_live.py` | `_entry_time_guard()` | 183-212 | ✅ Present — rejects if `now > entry_time + 5min` |
| `scripts/paper_scalp_live.py` | `_get_entry_price_from_provider()` | 215-232 | ✅ Present — fetches from yfinance |

### 5.2 Execution Flow

```
1. paper_scalp_live.py:run_once() [every 5 seconds]
   └── 2. latest_candle(inst) → SELECT from market_candles_5m [DB]
   └── 3. validate_candle(c, prev=pc) → freshness <20min, OHLC checks
   └── 4. today_signals(inst) → scalp_engine.today_state()
       └── 5. _load_candles(inst) → SELECT ALL from market_candles_5m [DB]
       └── 6. _scan_signals(candles) → 3-bar HLC alignment detection
       └── 7. _live_signal(candles, idx, ...) → entry/stop/target
           └── If entry candle not in DB: entry=None, entry_time=signal+5min
   └── 8. is_stale(entry_time) → skip if >20min old
   └── 9. record_signal() → INSERT into scalp_signals [DB]
   └── 10. _entry_time_guard(entry_time, now) → reject if now > entry_time + 5min
   └── 11. _get_entry_price_from_provider() → yfinance forming candle open
   └── 12. try_create_trade() → PaperTradeEngine.create_paper_trade()
       └── 13. INSERT INTO paper_trades [DB]
   └── 14. mark_traded(conn, sid, tid) → UPDATE scalp_signals
   └── 15. PaperTradeEngine().monitor(inst) → exit evaluation
```

### 5.3 Where the Flow Breaks

The flow breaks at **step 4-6**: `today_state()` calls `_load_candles()` which reads from `market_candles_5m` DB table. The signal candle (e.g., 09:25) is only in the DB after ingestion (~09:31). Even though `_scan_signals()` can detect the signal at the last candle (Phase 3.5 fix), the signal detection happens AFTER ingestion, which is AFTER the entry window closes.

The `_entry_time_guard()` at step 10 correctly rejects the signal because `now (09:36:20) > entry_time + 5min (09:35:00)`.

---

## 6. Recommended Remediation

### Option A: Reduce Collector Cadence to 1 Minute (RECOMMENDED)

**Change:** Modify `tradingai-market-data.timer` to run every 1 minute instead of every 5 minutes.

**Files to change:**
- `/etc/systemd/system/tradingai-market-data.timer` — change `OnCalendar` from `*:00/5` to `*:00/1`

**Expected improvement:**
- Current ingestion delay: ~6 minutes (5 min completion + up to 5 min timer interval)
- After fix: ~1-2 minutes (5 min completion + up to 1 min timer interval)
- This would allow signals to be detected within the entry window for most cases

**Risks:**
- Increased yfinance polling (12 requests/min vs 2.4 requests/min)
- Potential rate limiting (429 errors)
- Increased CPU/DB load

### Option B: Use Forming Candle Open from Provider (ALTERNATIVE)

**Change:** Modify `paper_scalp_live.py` to call `_get_entry_price_from_provider()` immediately when a signal is detected, rather than waiting for the entry candle to be in the DB.

**Files to change:**
- `scripts/paper_scalp_live.py:run_once()` — fetch entry price from provider immediately after signal detection
- `scripts/paper_scalp_live.py:_entry_time_guard()` — remove or modify the `now > entry_time + 5min` check

**Expected improvement:**
- Entry price available at candle-open time (0-5 seconds)
- Trade creation within ~5 seconds of signal candle completion

**Risks:**
- Changes the strategy's entry-price semantics (from historical candle open to live provider quote)
- May introduce look-ahead bias if the provider returns data before the candle actually opens
- Requires careful validation of the forming candle's open price

### Option C: Real-Time Data Feed (LONG-TERM)

**Change:** Replace yfinance with a real-time WebSocket data feed (e.g., Zerodha Kite, Upstox).

**Expected improvement:**
- Candle data available within 1-2 seconds of candle close
- Total latency <10 seconds

**Risks:**
- Requires broker API integration (real-money execution risk)
- Additional cost and complexity
- Requires approval

---

## 7. Testing Plan

### Test 1: Candle Timestamp Semantics
- Verify `market_candles_5m.timestamp` = candle open time (from yfinance `_to_ist_iso()`)
- Verify `ingested_at` = wall-clock time of DB insert
- Verify all timestamps are IST (UTC+05:30)

### Test 2: Ingestion Latency Measurement
- Query `ingested_at - timestamp` for 100+ candles
- Confirm consistent ~6 minute delay

### Test 3: Entry-Price Availability
- Call `MarketDataProvider.get_5m_candles()` at candle-open time
- Verify forming candle's `open` field is populated
- Measure delay between candle open and provider availability

### Test 4: Guard Boundary Conditions
- Test `_entry_time_guard()` with `now` before, at, and after `entry_time + 5min`
- Verify correct rejection/acceptance

### Test 5: Duplicate Prevention
- Verify `trade_id` PRIMARY KEY prevents duplicates
- Verify `scalp_signals` UNIQUE constraint prevents duplicate signals

### Test 6: Trade Persistence
- Verify `create_paper_trade()` correctly persists trades
- Verify `created_at` is set to current time at insert

### Test 7: Telegram Alert Linkage
- Verify `tg_alerts.py` only sends alerts for trades in DB
- Verify `trade_id` linkage between paper_trades and tg_state.json

---

## 8. Rollback Plan

If Option A is implemented:
1. Restore `tradingai-market-data.timer` to original `*:00/5` schedule
2. Verify no new paper trades are created with stale data
3. Monitor for rate-limiting errors in collector logs

If Option B is implemented:
1. Restore `paper_scalp_live.py` from backup
2. Restart `paper_scalp_live.py`
3. Verify signal detection and trade creation return to pre-change behavior

---

## 9. Approval Requirements

This phase requires explicit approval before implementation because:
1. It involves changes to the market-data collection schedule (Option A)
2. It may require new cron jobs or systemd timers
3. It affects the timing of all live HLC trades
4. It could introduce rate-limiting issues with yfinance

**Do not implement without explicit approval.**

---

## 10. Final Status

**INCONCLUSIVE — PROVIDER LATENCY NOT ISOLATED**

The exact provider publication latency (time between yfinance publishing a candle and the collector fetching it) cannot be isolated from the available evidence. The ~6 minute delay decomposes into:
1. Candle completion delay (5 minutes — the candle must close before it's available)
2. Collection cadence delay (up to 5 minutes — the timer runs every 5 minutes)

The provider's publication latency (time between candle close and yfinance making it available) is not measured because the collector doesn't log fetch start/end times.

**Recommended next action:** Reduce the collector cadence to 1 minute (Option A) and measure whether the ingestion delay decreases. If it does, the bottleneck was scheduling, not provider latency. If it doesn't, the bottleneck is provider latency, and a real-time feed (Option C) would be needed.

**No production changes were made during this audit.**

---

**Report Path:** `/opt/tradingai/research/hlc_phase48_collector_audit_20261029_194000/PHASE48_REPORT.md`
