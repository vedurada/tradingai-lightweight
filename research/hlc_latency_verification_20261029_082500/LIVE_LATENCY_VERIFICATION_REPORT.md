# TradingAI Phase 3.6 — Live HLC Latency Verification Report

**Report:** LIVE_LATENCY_VERIFICATION_REPORT.md  
**Audit date:** 2026-10-29  
**Host:** webserver (Oracle VM)  
**Application root:** /opt/tradingai  
**Database:** /opt/tradingai/database/tradingai.db  
**Mode:** READ-ONLY audit (no code, settings, cron, systemd, or database modifications)

---

## 1. Deployment Verification

### 1.1 Environment

| Check | Value |
|-------|-------|
| Hostname | webserver |
| User | ubuntu |
| OS | Linux webserver 6.8.0-1060-oracle #63~22.04.1-Ubuntu SMP x86_64 |
| Application root | /opt/tradingai (confirmed) |
| Database | /opt/tradingai/database/tradingai.db (confirmed) |
| Verification timestamp (IST) | 2026-10-29 08:25:31 IST |

### 1.2 Deployed File Changes Verified

The Phase 3.5 changes are present in the deployed files:

| File | Change | Line Reference | Verified |
|------|--------|----------------|----------|
| `app/research/scalp_engine.py` | Last-candle signal detection in `_scan_signals()` | line 56-65 | PASS |
| `app/research/scalp_engine.py` | `idx + 1 < len(candles) and` guard in `today_state()` | line 301 | PASS |
| `app/research/scalp_engine.py` | `_live_signal()` handles missing entry candle (entry=None) | line 215-253 | PASS |
| `scripts/paper_scalp_live.py` | `MarketDataProvider` import | line 16 | PASS |
| `scripts/paper_scalp_live.py` | `_entry_time_guard()` returns `entry_candle_closed` | line 211 | PASS |
| `scripts/paper_scalp_live.py` | `_get_entry_price_from_provider()` function | line 215-232 | PASS |
| `scripts/paper_scalp_live.py` | `run_once()` calls `_get_entry_price_from_provider()` when entry=None | line 273 | PASS |

### 1.3 Running Process Verification

| Check | Value | Verified |
|-------|-------|----------|
| Process PID | 778264 | PASS |
| Command | `/usr/bin/python3 /opt/tradingai/scripts/paper_scalp_live.py` | PASS |
| Start time | Thu Oct 29 08:19:00 2026 IST | PASS |
| Elapsed | ~2 minutes at verification time | PASS |
| File lock acquired | Yes (only one instance running) | PASS |
| Import check | `scalp_engine`, `paper_scalp_live` both import cleanly | PASS |
| Gunicorn API | 3 processes (PID 745931, 745933, 745934) running | PASS |

### 1.4 Service Health

| Check | Value | Verified |
|-------|-------|----------|
| Gunicorn errors | None in gunicorn-err.log | PASS |
| Paper scalper startup | "another instance already running" (2nd instance exited, 1st running) | PASS |
| Telegram log | No new entries since deployment (no signals fired) | PASS |
| Strategy rules unchanged | SCALP_HLC, Scalp HLC 3-bar, has_open_position, Mode C all present | PASS |

---

## 2. Naturally Occurring HLC Signals Observed

### 2.1 Market Status

| Item | Value |
|------|-------|
| Current time (IST) | 2026-10-29 08:25:31 IST |
| Market open | 09:15 IST |
| First completed candle | 09:20 IST |
| Market status | **CLOSED** (pre-market) |

### 2.2 Candles for Today (2026-10-29)

| Instrument | Count | Min Timestamp | Max Timestamp |
|------------|-------|---------------|---------------|
| NIFTY | 0 | — | — |
| BANKNIFTY | 0 | — | — |
| INDIA_VIX | 0 | — | — |

**No candles exist for today.** The market has not yet opened. No 5-minute candles have been ingested for 2026-10-29.

### 2.3 Trades Since Deployment (after 08:19 IST)

| Query | Result |
|-------|--------|
| `SELECT COUNT(*) FROM paper_trades WHERE scenario='SCALP_HLC' AND created_at > '2026-10-29T08:19:00+05:30'` | 0 |

### 2.4 Telegram Alerts Since Deployment

| Query | Result |
|-------|--------|
| New entries in `tg_alerts_archive.jsonl` after deployment | 0 |
| Last alert in archive | 2026-10-28T14:56:04+05:30 (message_id 141) |

### 2.5 Conclusion on Live Samples

**NO LIVE SAMPLE.** No naturally occurring HLC signals have fired since the fix was deployed because:
1. The market is not yet open (08:25 IST vs 09:15 IST open)
2. No candles have been ingested for 2026-10-29
3. No paper trades have been created since deployment
4. No Telegram alerts have been sent since deployment

**End-to-end latency: UNVERIFIED** — the under-10-second target cannot be measured without a live signal.

---

## 3. Latency Calculations

| Latency Stage | Measurement | Sample Size | Status |
|--------------|-------------|-------------|--------|
| Completed signal data → signal detection | No live signal | 0 | NO LIVE SAMPLE |
| Signal detection → database commit | No live signal | 0 | NO LIVE SAMPLE |
| Valid signal availability → database commit | No live signal | 0 | NO LIVE SAMPLE |
| Entry candle open → database commit | No live signal | 0 | NO LIVE SAMPLE |
| Database commit → Telegram send | No live signal | 0 | NO LIVE SAMPLE |

**p50 / p95 / maximum:** Not computable (zero samples).

**Primary operational target (p95 < 10 seconds valid signal → trade commit):** UNVERIFIED — requires observation of a naturally occurring HLC signal during live market hours.

---

## 4. Correctness Checks

### 4.1 Signal Uses Three Completed Candles Only

| Check | Result | Evidence |
|-------|--------|----------|
| `_scan_signals()` scans triples of completed candles | PASS | `scalp_engine.py:47-55` — iterates `feats[i-2:i+1]` which requires 3 consecutive completed candles |
| Last-candle detection uses only completed candles | PASS | `scalp_engine.py:58-65` — uses `candles[i-2], candles[i-1], candles[i]` all from completed data |
| Entry candle not required for signal detection | PASS | `scalp_engine.py:301` — `idx + 1 < len(candles) and` guard prevents accessing missing entry candle |

### 4.2 Entry Price from Genuinely Available Provider Observation

| Check | Result | Evidence |
|-------|--------|----------|
| `_get_entry_price_from_provider()` fetches from `MarketDataProvider.get_5m_candles()` | PASS | `paper_scalp_live.py:215-232` |
| Provider returns forming candle's open (available at candle-open time) | PASS | `provider.py:97-132` — `get_5m_candles()` returns all bars including forming candle with `is_complete` flag |
| Entry price not backdated | PASS | Price obtained from live provider at trade creation time |

### 4.3 Entry-Time Guard Boundary Cases

| Check | Result | Evidence |
|-------|--------|----------|
| `_entry_time_guard()` rejects when `now > entry_time + 5min` | PASS | `paper_scalp_live.py:209-211` — `entry_close = et + timedelta(minutes=5); if now_dt > entry_close: return 'expired'` |
| `_entry_time_guard()` allows when `now <= entry_time + 5min` | PASS | `paper_scalp_live.py:212` — `return 'ok', None` |
| Boundary: `now == entry_time + 5min` returns 'ok' | PASS | Uses `>` not `>=`, so exactly at boundary is allowed |
| Boundary: `now == entry_time` returns 'ok' | PASS | `now_dt > entry_close` is False when `now_dt == et` |

### 4.4 Duplicate Prevention, Mode C, Stop/Target, EOD

| Check | Result | Evidence |
|-------|--------|----------|
| Deterministic trade ID (SHA-1 of link_key) | PASS | `paper_scalp_live.py:25-32` — `scalp_trade_id()` |
| `trade_id` is PRIMARY KEY | PASS | `schema.sql:81` — `trade_id TEXT PRIMARY KEY` |
| `INSERT` + `IntegrityError` catch prevents duplicates | PASS | `paper_trade/engine.py:105-123` |
| Mode C: `has_open_position()` blocks per instrument | PASS | `paper_scalp_live.py:122-131` — `has_open_position()` |
| Stop = signal candle extreme ±1 pt | PASS | `scalp_engine.py:220-221` — unchanged |
| Target = 1.5×R | PASS | `scalp_engine.py:242-244` — unchanged |
| Stop-first tie-break | PASS | `scalp_engine.py:_trade_for()` — unchanged (backtest path) |
| EOD flat at session close | PASS | `scalp_engine.py:_trade_for()` — unchanged |

### 4.5 Telegram Messages Correspond to Persisted Trades

| Check | Result | Evidence |
|-------|--------|----------|
| `tg_alerts.py` checks DB before alerting | PASS | `tg_alerts.py:548-554` — `SELECT trade_id FROM paper_trades WHERE trade_id=?` |
| Alert skipped if trade not in DB | PASS | `tg_alerts.py:555-558` — `if not row: print(...skipping alert); continue` |
| Alert sent after trade exists | PASS | `tg_alerts.py:584` — `tg('sendMessage', ...)` after DB check |
| Dedup via `fired` key | PASS | `tg_alerts.py:399` — `key in st.get('fired', [])` |

### 4.6 Service/Log Anomalies

| Check | Result | Evidence |
|-------|--------|----------|
| Gunicorn errors | None | `gunicorn-err.log` empty |
| Paper scalper startup errors | None (only lock message from 2nd instance) | `paper_scalp_live.out` shows "another paper_scalp_live instance is already running; exiting" |
| Unexpected exceptions in logs | None observed | No traceback or error messages in logs |
| Missing trades | N/A (no signals fired) | N/A |
| Duplicate trades | 0 duplicates | 94 total, 94 distinct (from Phase 3.3 audit) |

---

## 5. Strategy Integrity

| Strategy Element | Status | Evidence |
|-----------------|--------|----------|
| HLC 3-bar pattern (3 consecutive completed candles) | UNCHANGED | `scalp_engine.py:47-55` |
| Completed-candle confirmation | UNCHANGED | `scalp_validation.py:19-76` + `scalp_engine.py:58-65` |
| Entry at next candle open | UNCHANGED | `scalp_engine.py:223` (when entry candle available) |
| Stop = signal extreme ±1 pt | UNCHANGED | `scalp_engine.py:220-221` |
| Target = 1.5×R | UNCHANGED | `scalp_engine.py:242-244` |
| Stop-first tie-break | UNCHANGED | `scalp_engine.py:_trade_for()` |
| EOD flat at session close | UNCHANGED | `scalp_engine.py:_trade_for()` |
| Mode C (one open position per instrument) | UNCHANGED | `paper_scalp_live.py:122-131` |
| Deterministic trade IDs | UNCHANGED | `paper_scalp_live.py:25-32` |
| No real-money execution | UNCHANGED | No broker integration in code |

---

## 6. Missing Instrumentation

The following timestamps are **not** currently logged and would be needed for precise end-to-end latency measurement:

| Missing Timestamp | Where to Instrument | Why Needed |
|-------------------|---------------------|------------|
| Signal detection timestamp (when `_scan_signals()` first identifies a signal) | `scripts/paper_scalp_live.py:run_once()` signal loop | To measure signal detection → trade commit latency separately from candle availability |
| Candle first-available-at timestamp | `app/market/provider.py` `_fetch_candles()` | To measure candle ingestion → signal detection latency |
| Entry price observed-at timestamp | `scripts/paper_scalp_live.py:_get_entry_price_from_provider()` | To confirm entry price was available at decision time |
| Trade insert start/commit timestamps | `app/paper_trade/engine.py:create_paper_trade()` | To measure any persistence delay |
| Telegram send start/complete timestamps | `scripts/tg_alerts.py:do_watch()` | Already partially captured via `ts_ist` in archive |

Without these, latency calculations must rely on `created_at` (DB insert time) and `ts_ist` (Telegram archive time), which are minute-precision at best.

---

## 7. PASS / FAIL / NOT VERIFIED per Acceptance Criterion

| # | Acceptance Criterion | Verdict | Evidence |
|---|---------------------|---------|----------|
| 1 | Under 10 seconds valid signal → trade commit (p95) | NOT VERIFIED | No live signal occurred since deployment; market not yet open |
| 2 | No lookahead or retrospective price as actionable | PASS | Entry price from live provider; historical open preserved in `qualification_evidence` |
| 3 | No expired or duplicate trades | PASS | `_entry_time_guard()` + `trade_id` PRIMARY KEY; 94/94 distinct IDs |
| 4 | Telegram alert tied to persisted trade | PASS | `tg_alerts.py:548-554` checks DB before alerting |
| 5 | No strategy changes | PASS | All HLC rules unchanged in code |
| 6 | No real-money execution | PASS | No broker integration; paper-only |

---

## 8. Conclusion

**Deployment: PASS** — All Phase 3.5 changes are deployed and running. The `paper_scalp_live.py` process (PID 778264) is healthy and using the updated code. Strategy rules are unchanged.

**End-to-end latency: NOT VERIFIED** — No naturally occurring HLC signal has fired since deployment because the market is not yet open (08:25 IST vs 09:15 IST open). No candles, no trades, no Telegram alerts exist for 2026-10-29.

**Recommendation:** Wait for the next live market session (market opens 09:15 IST) and observe naturally occurring HLC signals. Measure the valid-signal-availability → trade-commit latency for each signal. The under-10-second target can only be confirmed with live signal data.

**No production changes were made during this verification.**

---

## Report Path

`/opt/tradingai/research/hlc_latency_verification_20261029_082500/LIVE_LATENCY_VERIFICATION_REPORT.md`
