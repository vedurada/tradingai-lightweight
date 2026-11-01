# TradingAI Phase 3.9 — Live HLC Signal and Latency Verification Report

**Report:** LIVE_VERIFICATION_REPORT.md  
**Audit date:** 2026-10-29  
**Host:** webserver (Oracle VM)  
**Application root:** /opt/tradingai  
**Database:** /opt/tradingai/database/tradingai.db  
**Mode:** READ-ONLY observation

---

## 1. Environment Verification

| Check | Value |
|-------|-------|
| Hostname | webserver |
| User | ubuntu |
| OS | Linux webserver 6.8.0-1060-oracle #63~22.04.1-Ubuntu SMP x86_64 |
| Application root | /opt/tradingai (confirmed) |
| Database | /opt/tradingai/database/tradingai.db (confirmed) |
| Audit start time (IST) | 2026-10-29 08:34:38 IST |
| Market status | CLOSED (pre-market; NSE opens 09:15 IST) |

---

## 2. Service Health and Deployed Code Verification

### 2.1 Running Processes

| Service | PID | Start Time | Status | Phase 3.5 Code Deployed |
|---------|-----|------------|--------|-------------------------|
| paper_scalp_live.py | 778264 | Thu Oct 29 08:19:00 2026 IST | Running | Yes |
| gunicorn master | 745931 | Oct 28 | Running | N/A |
| gunicorn worker | 745933 | Oct 28 | Running | N/A |
| gunicorn worker | 745934 | Oct 28 | Running | N/A |

### 2.2 Deployed Phase 3.5 Changes Verified

| File | Change | Line Reference | Verified |
|------|--------|----------------|----------|
| `app/research/scalp_engine.py` | Last-candle signal detection in `_scan_signals()` | line 56-65 | PASS |
| `app/research/scalp_engine.py` | `idx + 1 < len(candles) and` guard in `today_state()` | line 301 | PASS |
| `app/research/scalp_engine.py` | `_live_signal()` handles missing entry candle (entry=None) | line 215-253 | PASS |
| `scripts/paper_scalp_live.py` | `MarketDataProvider` import | line 16 | PASS |
| `scripts/paper_scalp_live.py` | `_entry_time_guard()` returns `entry_candle_closed` | line 211 | PASS |
| `scripts/paper_scalp_live.py` | `_get_entry_price_from_provider()` function | line 215-232 | PASS |
| `scripts/paper_scalp_live.py` | `run_once()` calls `_get_entry_price_from_provider()` when entry=None | line 273 | PASS |

### 2.3 Backups

| File | MD5 |
|------|-----|
| `scalp_engine.py.bak-20261029_080500` | c0ffd9401b0e8ffb8e16300306000313 |
| `paper_scalp_live.py.bak-20261029_080500` | a874be1e84e40c024c3aecc5703772ac |
| `paper_trade_engine.py.bak-20261029_080500` | b8da0ea1a8b2fee9cc4b736c39598a25 |

Stored in `/opt/tradingai/research/hlc_latency_fix_20261029_080500/backups/`.

### 2.4 Log Health

| Log | Status |
|-----|--------|
| `paper_scalp_live.out` | Only "another paper_scalp_live instance is already running" (2nd launch attempt exited; PID 778264 running normally) |
| `gunicorn-err.log` | Empty (no errors) |

---

## 3. Market Session Conditions

| Check | Value |
|-------|-------|
| Current time (IST) | 2026-10-29 08:34:38 IST |
| NSE market open | 09:15 IST |
| First completed candle | 09:20 IST |
| Market status | CLOSED (pre-market) |
| Candles ingested for 2026-10-29 | 0 (NIFTY: 0, BANKNIFTY: 0) |
| Latest candle timestamp in DB | 2026-10-28T15:25:00+05:30 (both instruments) |

**Market not open.** No 5-minute candles have been ingested for 2026-10-29. No HLC signal can form or be detected.

---

## 4. Naturally Occurring Signals Observed

### Signals during observation window

| Metric | Value |
|--------|-------|
| New SCALP_HLC paper trades | 0 |
| New scalp_signals records | 0 |
| New Telegram alerts | 0 |

### Last signals before market close (2026-10-28)

| Signal ID | Instrument | Direction | Source Candle TS | Status | Signal Created At |
|-----------|-----------|-----------|-------------------|--------|-------------------|
| SS-C820F08DF353 | NIFTY | BULL | 2026-10-27T14:30:00+05:30 | TRADED | 2026-10-27T14:40:10.593480+05:30 |
| SS-BFD43DF0C67D | BANKNIFTY | BEAR | 2026-10-27T13:05:00+05:30 | TRADED | 2026-10-27T13:15:43.434056+05:30 |
| SS-DC445383416B | NIFTY | BEAR | 2026-10-27T13:05:00+05:30 | TRADED | 2026-10-27T13:15:43.302507+05:30 |
| SS-F97511DC6058 | BANKNIFTY | BEAR | 2026-10-27T13:00:00+05:30 | TRADED | 2026-10-27T13:10:42.119822+05:30 |
| SS-5F5A9133FC11 | NIFTY | BEAR | 2026-10-27T13:00:00+05:30 | TRADED | 2026-10-27T13:10:41.925762+05:30 |

All signal records are from 2026-10-27. No signals on 2026-10-28 or 2026-10-29.

---

## 5. Latency Measurements

### Sample size

| Stage | Samples | Status |
|-------|---------|--------|
| Signal availability → detection | 0 | NO LIVE SAMPLE |
| Signal detection → trade commit | 0 | NO LIVE SAMPLE |
| Signal availability → trade commit | 0 | NO LIVE SAMPLE |
| Entry candle open → trade commit | 0 | NO LIVE SAMPLE |
| Trade commit → Telegram send | 0 | NO LIVE SAMPLE |

### Per-trade timestamps

No trades occurred during the observation window. No per-trade timestamps available.

### Statistical summary

| Metric | p50 | p95 | Max | Samples |
|--------|-----|-----|-----|---------|
| Valid signal → trade commit | N/A | N/A | N/A | 0 |

**Under-10-second target: NOT VERIFIED** — no naturally occurring HLC signal observed during live market hours.

---

## 6. Correctness Verification

### 6.1 Signal uses three completed candles only

| Check | Result | Evidence |
|-------|--------|----------|
| `_scan_signals()` iterates completed candle triples | PASS | `app/research/scalp_engine.py:47-55` |
| Last-candle detection uses only completed candles | PASS | `app/research/scalp_engine.py:58-65` |
| Entry candle not required for signal detection | PASS | `app/research/scalp_engine.py:301` |

### 6.2 Entry-price availability

| Check | Result | Evidence |
|-------|--------|----------|
| Entry price from live provider at trade creation time | PASS (code-level) | `scripts/paper_scalp_live.py:215-232` |
| Forming candle's open available at candle-open time | PASS (code-level) | `app/market/provider.py:97-132` |

**Note:** Cannot verify with live data since no signal occurred. Code-level verification confirms the mechanism exists, but no runtime evidence of a live entry-price retrieval exists.

### 6.3 Entry-time guard boundary cases

| Boundary Condition | Expected | Result | Evidence |
|-------------------|----------|--------|----------|
| now < entry_time | ok | PASS | `paper_scalp_live.py:206-211` |
| now == entry_time | ok | PASS | `>` comparison |
| now == entry_time + 5min | ok | PASS | Boundary inclusive |
| now > entry_time + 5min | expired | PASS | Entry candle closed |

### 6.4 Duplicate prevention, Mode C, stop/target, EOD

| Check | Result | Evidence |
|-------|--------|----------|
| Deterministic trade ID (SHA-1 of link_key) | PASS | `paper_scalp_live.py:25-32` |
| `trade_id` is PRIMARY KEY | PASS | `schema.sql:81` |
| INSERT + IntegrityError catch prevents duplicates | PASS | `app/paper_trade/engine.py:105-123` |
| Mode C: `has_open_position()` blocks per instrument | PASS | `paper_scalp_live.py:122-131` |
| Stop = signal candle extreme ±1 pt | PASS | `scalp_engine.py:220-221` |
| Target = 1.5×R | PASS | `scalp_engine.py:242-244` |
| Stop-first tie-break | PASS | `scalp_engine.py:_trade_for()` |
| EOD flat at session close | PASS | `scalp_engine.py:_trade_for()` |

### 6.5 Telegram messages correspond to persisted trades

| Check | Result | Evidence |
|-------|--------|----------|
| `tg_alerts.py` checks DB before alerting | PASS | `tg_alerts.py:548-554` |
| Alert skipped if trade not in DB | PASS | `tg_alerts.py:555-558` |
| Dedup via `fired` key | PASS | `tg_alerts.py:399` |

### 6.6 No unexpected exceptions or anomalies

| Check | Result | Evidence |
|-------|--------|----------|
| Gunicorn errors | None | `gunicorn-err.log` empty |
| Paper scalper errors | None | `paper_scalp_live.out` shows only lock message |
| Missing trades | N/A (no signals) | N/A |
| Duplicate trades | 0 | 94/94 distinct trade_ids |

---

## 7. Missing Instrumentation

| Missing Timestamp | Where to Instrument | Why Needed |
|-------------------|---------------------|------------|
| Signal detection timestamp | `scripts/paper_scalp_live.py:run_once()` signal loop | To measure signal detection → trade commit latency |
| Candle first-available-at timestamp | `app/market/provider.py` `_fetch_candles()` | To measure candle ingestion → signal detection latency |
| Entry price observed-at timestamp | `scripts/paper_scalp_live.py:_get_entry_price_from_provider()` | To confirm entry price available at decision time |
| Trade insert start/commit timestamps | `app/paper_trade/engine.py:create_paper_trade()` | To measure persistence delay |
| Telegram send start/complete timestamps | `scripts/tg_alerts.py:do_watch()` | Partially captured via `ts_ist` in archive |

Without these, latency calculations must rely on `created_at` (DB insert time) and `ts_ist` (Telegram archive time), which are minute-precision at best.

---

## 8. PASS / FAIL / NOT VERIFIED per Acceptance Criterion

| # | Acceptance Criterion | Verdict | Evidence |
|---|---------------------|---------|----------|
| Under 10 seconds valid signal → trade commit (p95) | NOT VERIFIED | No live signal; market closed |
| No lookahead or retrospective price as actionable | PASS (code-level) | Entry price from live provider |
| No expired or duplicate trades | PASS | Guard + PRIMARY KEY; 94/94 distinct IDs |
| Telegram alert tied to persisted trade | PASS | `tg_alerts.py:548-554` DB check |
| No strategy changes | PASS | All HLC rules unchanged |
| No real-money execution | PASS | Paper-only |

---

## 9. Conclusion

**Deployment verification: PASS** — Phase 3.5 fix deployed and running (PID 778264).

**Live signal observation: NO LIVE SAMPLE** — Market closed during observation window. No candles ingested, no trades created, no alerts sent for 2026-10-29.

**Latency measurement: NOT VERIFIED** — Requires live signal data during market hours.

**Final status: INCONCLUSIVE — NO LIVE SAMPLE**

No naturally occurring HLC signal was observed during the observation window because the NSE market was not open. The under-10-second latency target cannot be measured without live signal data.

**Recommendation:** Observe during the next live market session (market opens 09:15 IST on weekdays) and capture signal detection, entry-price retrieval, trade commit, and Telegram delivery timestamps for each naturally occurring HLC signal.

**No production changes were made during this verification.**

---

## Report Path

`/opt/tradingai/research/hlc_phase39_live_verification_20261029_083500/LIVE_VERIFICATION_REPORT.md`
