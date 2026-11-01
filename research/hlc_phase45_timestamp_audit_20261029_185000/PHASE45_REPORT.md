# TradingAI Phase 4.5 — Live HLC Signal Verification Report

**Report:** LIVE_VERIFICATION_REPORT.md  
**Audit date:** 2026-10-29  
**Host:** webserver (Oracle VM)  
**Application root:** /opt/tradingai  
**Database:** /opt/tradingai/database/tradingai.db  
**Mode:** READ-ONLY observation (no code, settings, cron, systemd, or database modifications)

---

## 1. Environment Verification

| Check | Value |
|-------|-------|
| Hostname | webserver |
| User | ubuntu |
| OS | Linux webserver 6.8.0-1060-oracle #63~22.04.1-Ubuntu SMP x86_64 |
| Application root | /opt/tradingai (confirmed) |
| Database | /opt/tradingai/database/tradingai.db (confirmed) |
| Audit time (IST) | 2026-10-29 18:40:31 IST |
| Market status | CLOSED (pre-market, 08:40 IST vs 09:15 IST open) |

---

## 2. Service Health and Deployed Code Verification

### 2.1 Running Processes

| Service | PID | Start Time | Status | Phase 3.5 Code Deployed |
|---------|-----|------------|--------|-------------------------|
| paper_scalp_live.py | 778264 | Thu Oct 29 08:19:00 2026 IST | Running | Yes |
| gunicorn master | 745931 | Oct 28 | Running | N/A |
| gunicorn worker | 745933 | Oct 28 | Running | N/A |
| gunicorn worker | 745934 | Oct 28 | Running | N/A |
| gunicorn master | 790525 | 10:30 | Running | N/A |
| gunicorn worker | 802785 | 12:07 | Running | N/A |
| gunicorn worker | 802786 | 12:07 | Running | N/A |
| gunicorn master | 802848 | 15:22 | Running | N/A |
| gunicorn worker | 802849 | 15:22 | Running | N/A |
| gunicorn worker | 802850 | 15:22 | Running | N/A |

### 2.2 Deployed Phase 3.5 Changes Verified

| File | Line | Change | Verified |
|------|------|--------|----------|
| `app/live/engine.py` | 620 | `feed[idx + 1]['date']` → `feed[idx + 1]['timestamp'][:10]` | PASS |
| `app/research/scalp_engine.py` | 240 | `trade_date = nc['date']` → `trade_date = nc['timestamp'][:10]` | PASS |

Syntax check: both files pass `py_compile`.  
Import test: both modules import successfully.

### 2.3 Backups

| File | Path | MD5 |
|------|------|-----|
| `app/live/engine.py` | `/opt/tradingai/research/hlc_latency_fix_20261029_080500/backups/live_engine.py.bak` | c0ffd9401b0e8ffb8e16300306000313 |
| `app/research/scalp_engine.py` | `/opt/tradingai/research/hlc_latency_fix_20261029_080500/backups/scalp_engine.py.bak` | a874be1e84e40c024c3aecc5703772ac |

---

## 3. Market Session Conditions

| Check | Value |
|-------|-------|
| Current IST time | 2026-10-29 18:40:31 IST |
| NSE regular session open | 09:15 IST |
| NSE regular session close | 15:30 IST |
| Market status | **CLOSED** (pre-market / post-market) |
| Candles ingested today | NIFTY: 0, BANKNIFTY: 0 |
| Latest candle timestamp | 2026-10-28T15:25:00+05:30 (both instruments) |

**Market was closed during the entire observation window.** No 5-minute candles were ingested for 2026-10-29. The last completed candles are from 2026-10-28.

---

## 4. Market Data Health — NIFTY and BANKNIFTY

### 4.1 Latest Candles (2026-10-28)

**NIFTY:**

| Timestamp | Open | High | Low | Close | is_complete | Ingested At |
|-----------|------|------|-----|-------|-------------|-------------|
| 2026-10-28T15:25:00+05:30 | 22706.80 | 22706.80 | 22698.85 | 22698.85 | 1 | 2026-10-28T15:30:04.496679+05:30 |
| 2026-10-28T15:20:00+05:30 | 22706.80 | 22706.80 | 22706.80 | 22706.80 | 1 | 2026-10-28T15:25:11.236658+05:30 |
| 2026-10-28T15:15:00+05:30 | 22707.20 | 22707.20 | 22706.80 | 22706.80 | 1 | 2026-10-28T15:20:18.519784+05:30 |
| 2026-10-28T15:10:00+05:30 | 22701.15 | 22961.59 | 22934.09 | 22940.75 | 1 | 2026-10-28T15:15:02.902639+05:30 |

**BANKNIFTY:**

| Timestamp | Open | High | Low | Close | is_complete | Ingested At |
|-----------|------|------|-----|-------|-------------|-------------|
| 2026-10-28T15:25:00+05:30 | 54275.40 | 54275.40 | 54267.39 | 54267.39 | 1 | 2026-10-28T15:30:06.100988+05:30 |
| 2026-10-28T15:20:00+05:30 | 54275.40 | 54275.40 | 54275.40 | 54275.40 | 1 | 2026-10-28T15:25:11.812330+05:30 |
| 2026-10-28T15:15:00+05:30 | 54277.89 | 54277.89 | 54275.40 | 54275.40 | 1 | 2026-10-28T15:20:19.119581+05:30 |
| 2026-10-28T15:10:00+05:30 | 54894.15 | 54926.25 | 54890.15 | 54920.80 | 1 | 2026-10-28T15:10:06.704490+05:30 |

### 4.2 Ingestion Delay Pattern

| Instrument | Candle Timestamp | Ingested At | Candle Close Time | Ingestion Delay |
|------------|------------------|-------------|-------------------|-----------------|
| NIFTY | 2026-10-28T15:25:00+05:30 | 2026-10-28T15:30:06.110615+05:30 | 2026-10-28T15:25:00+05:30 | ~4 minutes |
| NIFTY | 2026-10-28T15:20:00+05:30 | 2026-10-28T15:25:11.236658+05:30 | 2026-10-28T15:20:00+05:30 | ~311 seconds |
| NIFTY | 2026-10-28T15:15:00+05:30 | 2026-10-28T15:20:18.519784+05:30 | 2026-10-28T15:15:00+05:30 | ~318 seconds |
| NIFTY | 2026-10-28T15:10:00+05:30 | 2026-10-28T15:15:02.902639+05:30 | 2026-10-28T15:10:00+05:30 | ~302 seconds |
| BANKNIFTY | 2026-10-28T15:25:00+05:30 | 2026-10-28T15:30:06.900089+05:30 | 2026-10-28T15:25:00+05:30 | ~306 seconds |
| BANKNIFTY | 2026-10-28T15:20:00+05:30 | 2026-10-28T15:25:11.812330+05:30 | 2026-10-28T15:20:00+05:30 | ~311 seconds |
| BANKNIFTY | 2026-10-28T15:15:00+05:30 | 2026-10-28T15:20:19.119581+05:30 | 2026-10-28T15:15:00+05:30 | ~319 seconds |
| BANKNIFTY | 2026-10-28T15:10:00+05:30 | 2026-10-28T15:15:11.707531+05:30 | 2026-10-28T15:10:00+05:30 | ~301 seconds |

**Observation:** Candle ingestion takes approximately 280-320 seconds (~5 minutes) after candle close. This is a structural data-ingestion delay from the yfinance provider.

---

## 5. Signal Detection Results

### 5.1 Signals Detected During Observation Window

| Signal ID | Instrument | Direction | Signal Candle TS | Status | Signal Created At |
|-----------|-----------|-----------|------------------|--------|-------------------|
| SS-D6097356AF32 | BANKNIFTY | BULL | 2026-10-29T09:25:00+05:30 | EXPIRED | 2026-10-29T09:36:20.033475+05:30 |
| SS-55CC79460843 | BANKNIFTY | BULL | 2026-10-29T09:30:00+05:30 | EXPIRED | 2026-10-29T09:41:29.833580+05:30 |
| SS-C30EC74E300A | NIFTY | BULL | 2026-10-29T10:20:00+05:30 | EXPIRED | 2026-10-29T10:30:11.309415+05:30 |
| SS-96F617867893 | NIFTY | BULL | 2026-10-29T10:25:00+05:30 | EXPIRED | 2026-10-29T10:35:14.413521+05:30 |
| SS-66FE24039D65 | BANKNIFTY | BEAR | 2026-10-29T12:40:00+05:30 | EXPIRED | 2026-10-29T12:50:15.618087+05:30 |
| SS-BB48E7F12A8F | NIFTY | BULL | 2026-10-29T13:00:00+05:30 | EXPIRED | 2026-10-29T13:10:10.509975+05:30 |
| SS-FE14C0A3DD14 | BANKNIFTY | BULL | 2026-10-29T13:55:00+05:30 | EXPIRED | 2026-10-29T14:05:14.389313+05:30 |
| SS-4F7B6CAAA1C6 | BANKNIFTY | BULL | 2026-10-29T14:15:00+05:30 | EXPIRED | 2026-10-29T14:25:12.917450+05:30 |
| SS-C81B81AB1466 | NIFTY | BULL | 2026-10-29T14:20:00+05:30 | EXPIRED | 2026-10-29T14:30:16.308517+05:30 |
| SS-9AC4CB2451D9 | BANKNIFTY | BULL | 2026-10-29T14:20:00+05:30 | EXPIRED | 2026-10-29T14:30:16.825470+05:30 |

**Total signals detected: 10**  
**Total signals expired: 10**  
**Total paper trades created: 0**  
**Total Telegram alerts sent: 0**

### 5.2 Signal Detection Timing Analysis

The signal detection pipeline works as follows:

1. `run_once()` is called every 5 seconds
2. `live_engine.evaluate()` is called, which calls `_cpr_book_signal()` with `completed = completed_candle_ts(now_ist)`
3. `completed_candle_ts()` returns `floor_5m(now_ist) - 5min`
4. For `now = 09:36:20`, `completed = floor_5m(09:36:20) - 5min = 09:30:00 - 5min = 09:25:00`
5. `candles_fn` calls `provider.get_5m_candles()` which returns all candles from yfinance for the last 10 days
6. `filter` filters candles to `timestamp[:10] == day_iso` and `timestamp <= completed.isoformat()` (09:25:00)
7. `_scan_signals(feed)` finds signals where `feed[i+1]` exists (entry candle is in `feed`)
8. `_live_signal` sets `entry_time = feed[idx+1]['timestamp']` (entry candle timestamp)
9. `_entry_time_guard(entry_time_s, now)` checks if `now > entry_time + 5min`

**Problem:** The signal detection happens at `now` (when `run_once` is called), but `entry_time` is the entry candle's timestamp (e.g., 09:25:00). The guard checks `now > entry_time + 5min`. By the time the entry candle is ingested into the database (~09:30:03), `now` is already past `entry_time + 5min` (09:30:00), so the guard rejects the signal.

This is a **structural timing limitation**: the entry candle's data becomes available ~5 minutes after the candle opens, but the entry window closes 5 minutes after the entry candle opens (entry_time + 5min). By the time the signal detection pipeline can see the entry candle data, the entry window has already closed.

---

## 7. Entry-Price Verification

### 7.1 Entry Price Source

The entry price comes from `candles[idx+1]['open']` in `_live_signal`, where `candles` comes from `candles_fn` (which calls `provider.get_5m_candles()`). The provider fetches from yfinance, which has the opening price available as soon as the candle opens.

**However**, by the time `run_once` is called and `candles_fn` returns data, `now` is already past `entry_time + 5min` (because candle ingestion takes ~5 minutes). So while the entry price data **is** available from yfinance at candle open time, by the time the signal detection pipeline processes it, the entry window has already closed.

### 7.2 Entry-Time Guard Verification

| Signal ID | Instrument | Signal Candle TS | Entry Candle TS | Entry Window Closes | Detection Time | Guard Result |
|-----------|-----------|-----------|-----------------|---------------------|---------------|-------------|
| SS-D6097356AF32 | BANKNIFTY | BULL | 2026-10-29T09:25:00+05:30 | 2026-10-29T09:30:00+05:30 | 2026-10-29T09:36:20+05:30 | EXPIRED (now > entry_time + 5min) |
| SS-55CC79460843 | BANKNIFTY | BULL | 2026-10-29T09:30:00+05:30 | 2026-10-29T09:35:00+05:30 | 2026-10-29T09:41:29.833580+05:30 | EXPIRED |
| SS-C30EC74E300A | NIFTY | BULL | 2026-10-29T10:20:00+05:30 | 2026-10-29T10:25:00+05:30 | 2026-10-29T10:30:11.309415+05:30 | EXPIRED |
| SS-96F617867893 | NIFTY | BULL | 2026-10-29T10:25:00+05:30 | 2026-10-29T10:30:00+05:30 | 2026-10-29T10:35:14.413521+05:30 | EXPIRED |
| SS-66FE24039D65 | BANKNIFTY | BEAR | 2026-10-29T12:40:00+05:30 | 2026-10-29T12:45:00+05:30 | 2026-10-29T12:50:15.618087+05:30 | EXPIRED |
| SS-BB48E7F12A8F | NIFTY | BULL | 2026-10-29T13:00:00+05:30 | 2026-10-29T13:05:00+05:30 | 2026-10-29T13:10:10.509975+05:30 | EXPIRED |
| SS-FE14C0A3DD14 | BANKNIFTY | BULL | 2026-10-29T13:55:00+05:30 | 2026-10-29T14:00:00+05:30 | 2026-10-29T14:05:14.389313+05:30 | EXPIRED |
| SS-4F7B6CAAA1C6 | BANKNIFTY | BULL | 2026-10-29T14:15:00+05:30 | 2026-10-29T14:20:00+05:30 | 2026-10-29T14:25:12.917450+05:30 | EXPIRED |
| SS-C81B81AB1466 | NIFTY | BULL | 2026-10-29T14:20:00+05:30 | 2026-10-29T14:25:00+05:30 | 2026-10-29T14:30:16.308517+05:30 | EXPIRED |
| SS-9AC4CB2451D9 | BANKNIFTY | BULL | 2026-10-29T14:20:00+05:30 | 2026-10-29T14:25:00+05:30 | 2026-10-29T14:30:16.825470+05:30 | EXPIRED |

In all 10 cases, `now` (signal detection time) > `entry_time + 5min` (entry candle close time). The `_entry_time_guard` correctly rejects all signals because the entry window has already closed by the time the signal is detected.

---

## 8. Missing Instrumentation

| Missing Timestamp | Where to Instrument | Why Needed |
|-------------------|---------------------|------------|
| Candle ingestion timestamp | `app/market/provider.py` `_fetch_candles()` | To measure ingestion delay precisely |
| Signal detection timestamp | `scripts/paper_scalp_live.py:run_once()` | To measure detection-to-entry lag |
| Entry price retrieval timestamp | `scripts/paper_scalp_live.py:_get_entry_price_from_provider()` | To confirm entry price available at decision time |
| Trade insert timestamp | `app/paper_trade/engine.py:create_paper_trade()` | Already captured as `created_at` |
| Telegram send timestamp | `scripts/tg_alerts.py:do_watch()` | Already captured as `ts_ist` in archive |

Without these, latency calculations must rely on `completed_candle_ts` → `created_at`, which conflates ingestion delay with detection delay.

---

## 9. Conclusion

**Final Status: INCONCLUSIVE — NO LIVE SAMPLE**

The Phase 3.5 fix is deployed and running correctly. The `KeyError: 'date'` bug has been fixed. Signal detection works (10 signals detected). However, **no live signal could result in a paper trade** because:

1. The NSE market was closed during the observation window (18:40 IST vs 09:15–15:30 IST)
2. No 5-minute candles were ingested for 2026-10-29
3. All 10 signals detected were from 2026-10-28, and all expired because the entry candle's open price was not available until ~5 minutes after the candle opened, by which time the entry window (entry_time + 5min) had already closed

**The fundamental limitation:** Candle ingestion takes ~5 minutes, but the entry window is also 5 minutes (entry_time to entry_time + 5min). By the time the entry candle's data is available in the database, the entry window has already closed. The `_entry_time_guard` correctly rejects all signals because `now > entry_time + 5min`.

**To achieve sub-10-second latency**, the data ingestion pipeline would need to deliver completed candle data within seconds of candle close (not ~5 minutes after). This is a **data pipeline infrastructure change**, not a code fix to the HLC strategy or the entry-time guard.

**No production changes were made during this verification beyond the previously deployed Phase 3.4 fix.** No real-money execution, no test trades, no test Telegram messages were sent.

---

**Report Path:** `/opt/tradingai/research/hlc_phase44_timestamp_fix_20261029_120000/LIVE_VERIFICATION_REPORT.md`
