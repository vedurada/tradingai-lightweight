# TradingAI Phase 3.5 — Pre-Change Diagnosis: HLC Paper-Trade Latency

**Report:** PRECHANGE_DIAGNOSIS.md  
**Audit date:** 2026-10-29  
**Host:** webserver (Oracle VM)  
**Application root:** /opt/tradingai  
**Database:** /opt/tradingai/database/tradingai.db  
**Mode:** READ-ONLY diagnosis (no files modified yet)

---

## 1. Environment Verification

| Check | Value |
|-------|-------|
| Hostname | webserver |
| User | ubuntu |
| OS | Linux webserver 6.8.0-1060-oracle #63~22.04.1-Ubuntu SMP x86_64 |
| Application root | /opt/tradingai (confirmed) |
| Database | /opt/tradingai/database/tradingai.db (confirmed) |
| Diagnosis timestamp (IST) | 2026-10-29 08:05:00 IST |
| Running paper_scalp_live PID | 752009 (started Wed Oct 28 20:44:05 2026) |
| Running gunicorn PID | 745931 (started Wed Oct 28 19:42:16 2026) |

---

## 2. Problem Statement

The live HLC 3-bar paper-trading engine creates paper-trade records approximately 5–6 minutes after the intended entry candle opens. For all 10 sampled trades on 2026-10-28:

- Entry price = entry candle open (verified against `market_candles_5m`) — **no lookahead**
- `created_at` is ~5–6 minutes after `entry_time` (entry candle open)
- Telegram alert follows `created_at` by ~0–2 seconds

**Target:** Under 10 seconds from valid signal availability to committed paper-trade record.

---

## 3. Code Path Reconstruction (Read-Only)

### 3.1 Live loop execution order

**File:** `scripts/paper_scalp_live.py`

```
main()                                          line 234
  └── while True:
      ├── run_once(state); time.sleep(5)        line 235  [POLL_SECONDS = 5, line 41]
      └── run_once(state)                       line 216-244
          ├── now = datetime.now(_IST)          line 227  [NOW_1: used by guard]
          ├── allow_new = market_open_now() ... line 229-230
          ├── for inst in INSTRUMENTS:          line 232 (NIFTY, then BANKNIFTY)
          │   ├── c = latest_candle(inst)       line 238
          │   │   └── SELECT latest from market_candles_5m (line 80-84)
          │   ├── pc = prev_candle(inst)        line 239
          │   │   └── SELECT 2nd latest from market_candles_5m (line 88-94)
          │   ├── ok, reason = validate_candle(c, prev=pc)  line 240
          │   │   └── app/research/scalp_validation.py:19-76
          │   │       ├── freshness: <20 min stale (STALE_MIN=20, line 41)
          │   │       └── OHLC integrity checks
          │   ├── if ok and allow_new:          line 241
          │   │   ├── signals = today_signals(inst, variant="plain")  line 247
          │   │   │   └── app/research/scalp_engine.py:233 today_state()
          │   │   │       ├── _load_candles(inst) line 21-33
          │   │   │       │   └── SELECT ALL from market_candles_5m (line 24-26)
          │   │   │       ├── filter: c['timestamp'] <= now.isoformat() line 252
          │   │   │       │     [now captured at line 248: now = datetime.now(_IST)]
          │   │   │       ├── _scan_signals(candles) line 44-58
          │   │   │       │   ├── feats = _features(candles) line 36-41
          │   │   │       │   ├── scan triples for H/L/C alignment line 47-57
          │   │   │       │   └── if i + 1 >= len(candles): continue line 55-56
          │   │   │       │       [REQUIRES entry candle (i+1) in data!]
          │   │   │       └── _live_signal(candles, idx, ...) line 211-230
          │   │   │           ├── c = candles[idx]              line 212
          │   │   │           ├── nc = candles[idx + 1]         line 213
          │   │   │           ├── entry = float(nc['open'])     line 213
          │   │   │           ├── entry_time = nc['timestamp']  line 228
          │   │   │           ├── signal_time = c['timestamp']  line 227
          │   │   │           ├── stop = signal_candle.low ± 1  line 66/70
          │   │   │           └── target = entry ± 1.5×risk     line 68/72
          │   │   ├── for st in signals:                          line 250
          │   │   │   ├── entry_time_s = st.get("entry_time")   line 254
          │   │   │   ├── guard, why = _entry_time_guard(...)   line 257
          │   │   │   │   └── paper_scalp_live.py:168-186
          │   │   │   │       ├── if et <= now_dt: return 'expired' line 185
          │   │   │   │       └── return 'ok'                      line 186
          │   │   │   ├── if guard == "expired": mark_expired; continue  line 259-261
          │   │   │   ├── tid = try_create_trade(...)             line 263
          │   │   │   │   └── app/paper_trade/engine.py:66
          │   │   │   │       ├── INSERT INTO paper_trades        line 110-111
          │   │   │   │       ├── created_at = datetime.now(_IST) line 111
          │   │   │   │       └── conn.commit()                   line 112
          │   │   │   └── mark_traded(conn, sid, tid)             line 265
```

### 3.2 `_entry_time_guard` — the paradox

**File:** `scripts/paper_scalp_live.py:168-186`

```python
if et <= now_dt:
    return 'expired', 'entry_candle_past_or_now'
return 'ok', None
```

The guard **requires** `entry_time > now`. If `entry_time <= now`, the signal is marked EXPIRED and trade creation is skipped.

**The paradox:** To detect the signal, the entry candle (N+1) must be in `market_candles_5m` (because `_scan_signals` requires `i + 1 < len(candles)` at line 55-56). The entry candle is ingested ~5 minutes after its open. By ingestion time, `now > entry_time`, so the guard returns `'expired'` and the signal should be skipped. Yet trades ARE created with `created_at > entry_time`. This contradiction cannot be resolved from static code + read-only DB evidence — the running code (PID 752009) may differ from the source file, or there is a timing nuance not observable without instrumentation.

### 3.3 `created_at` timestamp generation

**File:** `app/paper_trade/engine.py:110-111`

```python
conn.execute('''INSERT INTO paper_trades (... created_at, updated_at) VALUES (...,
    datetime.now(_IST).isoformat(), datetime.now(_IST).isoformat())''')
```

`created_at` = `datetime.now(_IST)` at INSERT time — actual wall-clock, not backdated.

---

## 4. Candle Ingestion Pipeline Analysis

### 4.1 How candles reach the database

**File:** `app/market/collector.py`

- `collect_instrument()` fetches 5m candles from yfinance via `_fetch_history()` (line 41-117)
- Only candles with `timestamp <= cutoff` are stored, where `cutoff = get_completed_cutoff(now_ist)` (line 41-51)
- `get_completed_cutoff()` returns the last completed 5m OPEN minus 5 minutes (line 30-41)
- Each row is inserted with `ingested_at = now_ist.isoformat()` (line 106-107)
- `phase11_artifacts.py:40` confirms: `'provider': 'yfinance on-demand (no collector daemon)'`

### 4.2 Measured ingestion delay (from `ingested_at` column)

| Candle timestamp | Candle close | Ingested at | Lag after open |
|-----------------|-------------|-------------|----------------|
| 10:55:00 | 11:00:00 | 11:00:04.629 | 304.6s (~5 min) |
| 11:00:00 | 11:05:00 | 11:05:02.007 | 302.0s (~5 min) |
| 11:05:00 | 11:10:00 | 11:10:04.429 | 304.4s (~5 min) |
| 11:10:00 | 11:15:00 | 11:15:00.696 | 300.7s (~5 min) |
| 14:40:00 | 14:45:00 | 14:45:04.996 | 299.0s (~5 min) |
| 14:45:00 | 14:50:00 | 14:50:05.513 | 305.5s (~5 min) |
| 14:50:00 | 14:55:00 | 14:55:22.958 | 323.0s (~5.4 min) |

**Finding:** Candles are ingested into `market_candles_5m` approximately 5 minutes after their open (essentially when they close). This is the primary contributor to the ~6-minute entry-to-record delay.

### 4.3 No collector daemon

`phase11_artifacts.py:40`: `'provider': 'yfinance on-demand (no collector daemon)'`. Data is fetched on-demand via `MarketDataProvider.get_5m_candles()` (app/market/provider.py:97-132), which calls `_fetch_history(symbol, '10d', '5m')` from yfinance. The provider caches results in `provider_cache` (app/market/cache.py) with 90s TTL.

---

## 5. Per-Trade Timeline Evidence (10 trades, 2026-10-28)

| # | Trade ID | Inst | Dir | Signal candle | Entry candle open | Entry price | Entry match? | Entry candle ingested | DB created_at | Entry→Create delay |
|---|----------|------|-----|---------------|-------------------|-------------|--------------|----------------------|---------------|--------------------|
| 1 | PT-0E1BB5B645 | NIFTY | BULL | 14:45 | 14:50:00 | 22704.6 | ✓ | 14:55:22.958 | 14:56:02.125 | 6m 2s |
| 2 | PT-A4D82F95DF | NIFTY | BEAR | 13:55 | 14:00:00 | 22706.5 | ✓ | 14:05:08.928 | 14:06:03.198 | 6m 3s |
| 3 | PT-86E7B96E9D | NIFTY | BULL | 12:50 | 12:55:00 | 22718.8 | ✓ | 12:55:00.407 | 13:00:03.318 | 5m 3s |
| 4 | PT-7F4FF31032 | NIFTY | BULL | 12:45 | 12:50:00 | 22705.75 | ✓ | 12:50:01.692 | 12:55:02.618 | 5m 2s |
| 5 | PT-F10674AE4A | NIFTY | BULL | 12:40 | 12:45:00 | 22696.25 | ✓ | 12:50:01.692 | 12:51:03.209 | 6m 3s |
| 6 | PT-58E0E20BA3 | NIFTY | BULL | 12:00 | 12:05:00 | 22642.3 | ✓ | ~12:10:xx | 12:11:02.836 | 6m 2s |
| 7 | PT-DF37AC2412 | NIFTY | BULL | 11:55 | 12:00:00 | 22634.3 | ✓ | ~12:05:xx | 12:06:02.708 | 6m 2s |
| 8 | PT-8D5F520972 | BANKNIFTY | BULL | 11:00 | 11:05:00 | 54004.3 | ✓ | 11:10:05.096 | 11:11:02.336 | 6m 2s |
| 9 | PT-F76F16D58C | BANKNIFTY | BULL | 10:55 | 11:00:00 | 53935.05 | ✓ | 11:05:03.297 | 11:06:04.397 | 6m 4s |
| 10 | PT-1AFB06CC01 | NIFTY | BULL | 10:55 | 11:00:00 | 22575.1 | ✓ | ~12:05:xx | 11:06:02.903 | 6m 2s |

**Entry price verification:** All 10 trades — entry price equals entry candle's open price exactly (verified by querying `market_candles_5m`).

**Median entry→create delay:** ~6 min 2s. **Maximum:** ~6 min 4s.

---

## 6. Evaluation of Eight Candidate Causes

| # | Candidate | Classification | Evidence |
|---|-----------|---------------|----------|
| 1 | **Candle ingestion delay** | **CONFIRMED** (primary factor) | `ingested_at` shows candles enter DB ~5 min after open (300-323s). Signal cannot be detected until entry candle is in DB because `_scan_signals` requires `i + 1 < len(candles)` (scalp_engine.py:55-56). |
| 2 | **Polling delay** | **RULED OUT** | `POLL_SECONDS = 5` (paper_scalp_live.py:41). 5-second poll cannot explain 5-6 min delay. |
| 3 | **Signal detection delay** | **INCONCLUSIVE** | No separate timestamp for "signal first detected" vs "candle available." `scalp_signals.created_at` is when signal is recorded, not first detected. |
| 4 | **Entry-time guard** | **PARADOX — INCONCLUSIVE** | Guard requires `entry_time > now` (line 185), but entry candle must be ingested first (`ingested_at > entry_time`). By ingestion time, `now > entry_time`, so guard should expire all signals. Yet trades are created. Running code may differ from source. |
| 5 | **Loop ordering** | **RULED OUT** | No sleep/delay between guard pass and `try_create_trade()` (lines 257-263 consecutive). No queue/batching. |
| 6 | **Persistence delay** | **RULED OUT** | `INSERT ... commit()` immediate (paper_trade/engine.py:110-112). No DB queue evidence. |
| 7 | **Timestamp semantics** | **PARTIAL** | `created_at` = `datetime.now(_IST)` at INSERT (paper_trade/engine.py:111). Actual wall-clock, not backdated. |
| 8 | **Timezone/rounding** | **RULED OUT** | All timestamps use `Asia/Kolkata` via `_IST = ZoneInfo('Asia/Kolkata')`. No conversion issues. |

---

## 6. Root Cause Summary

**Primary confirmed cause:** Candle ingestion delay (~5 minutes after candle open). The live engine cannot detect the HLC signal until the entry candle is in `market_candles_5m` because `_scan_signals()` requires `i + 1 < len(candles)` (scalp_engine.py:55-56). By the time the entry candle is ingested, ~5 minutes have elapsed since its open.

**Unresolved paradox:** `_entry_time_guard()` requires `entry_time > now`, but by the time the entry candle is ingested, `now > entry_time`. The guard should expire all signals, yet trades are created. This cannot be resolved without runtime instrumentation.

**Key insight:** The entry candle's OPEN price IS known at the moment the candle opens (it is the first price of the interval). yfinance provides this via `get_5m_candles()` which returns ALL bars including the forming one, with `is_complete = False` but with the `open` value populated (provider.py:97-132). The engine does NOT need to wait for the entry candle to be ingested as completed data to know its open price.

---

## 7. Entry-Price Realism Assessment

### 7.1 Three distinct timestamps

| Timestamp type | When known | Source |
|---------------|-----------|--------|
| Historical candle timestamp (entry candle open) | ~5 min after open | `market_candles_5m` (ingested_at) |
| Candle ingestion timestamp | ~5 min after open | `market_candles_5m.ingested_at` |
| Entry candle open price | AT candle open | yfinance 5m data (forming candle's Open field) |
| Trade creation time | ~6 min after open | `paper_trades.created_at` |

### 7.2 Is the entry price actionable?

**YES for price, NO for timing:**
- The entry price (entry candle's open) IS a real, observable price at the moment the entry candle opens (e.g., 14:50:00)
- yfinance provides this via `get_5m_candles()` which returns the forming candle's Open
- The engine currently does NOT use this — it waits for the DB insertion (~5 min later)
- A real order submitted at trade creation time (~6 min after open) would execute at the then-current market price, NOT at the historical open

### 7.3 Matching historical open ≠ actionable at open time

The fact that `entry == market_candles_5m.open` for all 10 trades confirms the strategy uses the candle open as entry price. But it does NOT prove the price was actionable at the candle's open moment — the engine only learns it ~5 minutes later due to ingestion delay.

---

## 8. Backtest vs Live Timing Comparison

| Aspect | Live paper engine | Backtest (`run_opens_range`) | Equivalent? |
|--------|-------------------|------------------------------|-------------|
| Signal detection | After entry candle ingested (~5 min after open) | Instant (all historical data available) | ❌ No |
| Entry price | Entry candle open (from DB) | Entry candle open (from historical data) | ✅ Yes |
| Entry timing | Recorded ~6 min after open | Assumed at candle open instant | ❌ No |
| Lookahead safeguards | `_entry_time_guard` requires `entry_time > now` | None (historical data) | ❌ No |
| Candle availability | yfinance ~5 min delay | Instant | ❌ No |

**Conclusion:** The backtest's entry-at-candle-open assumption is NOT realistically achievable by the current live pipeline. The backtest simulates perfect information at candle open; the live engine learns the entry candle's open ~5 minutes after it opened.

---

## 9. Recommended Fix Approach

**Do not implement yet — diagnosis only.**

**Concept:** Detect the HLC signal as soon as the SIGNAL candle (candle N) is completed and ingested (~5 seconds after its close, which is when the entry candle N+1 opens). Use the entry candle's OPEN price from yfinance live data (available at open time) instead of waiting for the entry candle to be ingested into `market_candles_5m` (~5 minutes after its open).

**Expected latency reduction:** ~6 minutes → under 10 seconds:
- Signal candle N completes at 14:45, ingested ~14:50:05
- Signal detected at ~14:50:05 (same poll cycle)
- Entry candle N+1 opened at 14:50:00, open available from yfinance immediately
- Trade created at ~14:50:10 (within 10 seconds of signal detection)

**Files likely to change:**
1. `app/research/scalp_engine.py` — `_scan_signals()` (remove `i + 1 >= len(candles)` check at line 55-56), `_live_signal()` (handle missing entry candle at line 211-230)
2. `scripts/paper_scalp_live.py` — `run_once()` (get entry price from provider when entry candle not in DB), `_entry_time_guard()` (fix `entry_time > now` logic which is incompatible with next-candle-open strategy)

**Constraints to preserve:**
- HLC pattern rules (3 consecutive completed candles with aligned H/L/C)
- Completed-candle confirmation for signal detection
- Entry at next candle open (price from live quote at open time)
- Stop = signal candle extreme ±1 pt, Target = 1.5×R
- Stop-first tie-break, EOD flat
- Mode C (one open position per instrument)
- Deterministic trade IDs, duplicate prevention
- `entry_time` and `created_at` semantics unchanged
- No broker, no real-money execution

---

## 10. Missing Instrumentation

The following timestamps would be needed to fully resolve the guard paradox and measure latency precisely:

| Missing timestamp | Where to instrument | Purpose |
|-------------------|--------------------|---------|
| `now` at start of each `run_once()` cycle | `paper_scalp_live.py:227` | Compare against `entry_time` in guard |
| Guard evaluation result per signal | `paper_scalp_live.py:257-261` | Confirm pass/expire decision |
| `datetime.now()` before and after INSERT | `paper_trade/engine.py:110-112` | Measure persistence delay |
| Candle fetch completion time | `app/market/provider.py` | Separate ingestion delay from processing |
| Signal first-detection timestamp | `paper_scalp_live.py` signal loop | Separate detection from DB record |

None of these exist in the current code. Static analysis cannot resolve the guard paradox.

---

## 11. Diagnosis Conclusion

**Confirmed root cause (partial):** Candle ingestion delay (~5 minutes after candle open) is the primary contributor to the 5-6 minute entry-to-record delay. The engine waits for the entry candle to be ingested into `market_candles_5m` before detecting the signal.

**Unresolved paradox:** `_entry_time_guard()` requires `entry_time > now`, but the entry candle must be ingested before the signal can be detected, making `now > entry_time` at detection time. Yet trades are created. Requires runtime instrumentation to resolve.

**Fix viability:** HIGH. The entry candle's OPEN price is available from yfinance at candle-open time via `get_5m_candles()`. The engine can detect the signal when the signal candle completes and use the live quote for entry price, eliminating the ~5-minute ingestion wait.

**No production changes made during this diagnosis.**
