# TradingAI Phase 4.0 — Market-Hours Readiness and Live HLC Verification Report

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
| Audit start time (IST) | 2026-10-29 08:37:52 IST |

---

## 2. Session Timing Verification

| Item | Value |
|------|-------|
| Current IST time | 2026-10-29 08:37:52 IST |
| NSE regular session open | 09:15 IST |
| NSE regular session close | 15:30 IST |
| First completed 5m candle | 09:20 IST |
| Market status during observation | **CLOSED** (pre-market) |
| Is today an NSE trading day? | Thursday — yes, regular weekday |
| Is regular session open? | **No** — pre-market, before 09:15 IST |

**Session status: CLOSED** — The NSE regular session has not yet opened. No 5-minute candles can be forming or completing before 09:15 IST.

---

## 3. Live Data Ingestion Check

### 3.1 Running paper trader process and deployed code

| Service | PID | Start Time | Status | Phase 3.5 Code Deployed |
|---------|-----|------------|--------|-------------------------|
| paper_scalp_live.py | 778264 | Thu Oct 29 08:19:00 2026 IST | Running | Yes |
| gunicorn master | 745931 | Oct 28 | Running | N/A |
| gunicorn worker | 745933 | Oct 28 | Running | N/A |
| gunicorn worker | 745934 | Oct 28 | Running | N/A |

### 3.2 Latest market-candle timestamps and ingestion

**NIFTY:**

| Timestamp | Open | High | Low | Close | is_complete | Ingested At |
|-----------|------|------|-----|-------|-------------|-------------|
| 2026-10-28T15:25:00+05:30 | 22706.80 | 22706.80 | 22698.85 | 22698.85 | 1 | 2026-10-28T15:30:04.496679+05:30 |
| 2026-10-28T15:20:00+05:30 | 22706.80 | 22706.80 | 22706.80 | 22706.80 | 1 | 2026-10-28T15:25:11.014381+05:30 |
| 2026-10-28T15:15:00+05:30 | 22707.20 | 22707.20 | 22706.80 | 22706.80 | 1 | 2026-10-28T15:20:06.594072+05:30 |

**BANKNIFTY:**

| Timestamp | Open | High | Low | Close | is_complete | Ingested At |
|-----------|------|------|-----|-------|-------------|-------------|
| 2026-10-28T15:25:00+05:30 | 54275.40 | 54275.40 | 54267.38 | 54267.38 | 1 | 2026-10-28T15:30:06.100988+05:30 |
| 2026-10-28T15:20:00+05:30 | 54275.40 | 54275.40 | 54275.40 | 54275.40 | 1 | 2026-10-28T15:25:11.635059+05:30 |
| 2026-10-28T15:15:00+05:30 | 54277.90 | 54277.90 | 54275.40 | 54275.40 | 1 | 2026-10-28T15:20:07.203814+05:30 |

### 3.3 Market data health table

| Instrument | Latest Candle Timestamp | Ingested At | Age Since Candle | Health |
|------------|------------------------|-------------|------------------|--------|
| NIFTY | 2026-10-28T15:25:00+05:30 | 2026-10-28T15:30:04.496679+05:30 | ~23 hours | STALE (prior session) |
| BANKNIFTY | 2026-10-28T15:25:00+05:30 | 2026-10-28T15:30:06.100988+05:30 | ~23 hours | STALE (prior session) |

**Neither instrument has fresh candles for today.** The latest data is from the previous session's close (2026-10-28T15:25 IST). No new candles have arrived for 2026-10-29.

---

## 4. HLC Pipeline Observation

### 4.1 Signals observed during observation window

| Metric | Value |
|--------|-------|
| New SCALP_HLC paper trades | 0 |
| New scalp_signals records | 0 |
| New Telegram alerts | 0 |

### 4.2 Last signals before market close (2026-10-28)

| Signal ID | Instrument | Direction | Source Candle TS | Status | Signal Created At |
|-----------|-----------|-----------|-------------------|--------|-------------------|
| SS-C820F08DF353 | NIFTY | BULL | 2026-10-27T14:30:00+05:30 | TRADED | 2026-10-27T14:40:10.593480+05:30 |
| SS-BFD43DF0C67D | BANKNIFTY | BEAR | 2026-10-27T13:05:00+05:30 | TRADED | 2026-10-27T13:15:43.434056+05:30 |
| SS-DC445383416B | NIFTY | BEAR | 2026-10-27T13:05:00+05:30 | TRADED | 2026-10-27T13:15:43.302507+05:30 |
| SS-F97511DC6058 | BANKNIFTY | BEAR | 2026-10-27T13:00:00+05:30 | TRADED | 2026-10-27T13:10:42.119822+05:30 |
| SS-5F5A9133FC11 | NIFTY | BEAR | 2026-10-27T13:00:00+05:30 | TRADED | 2026-10-27T13:10:41.925762+05:30 |

All signal records are from 2026-10-27. No signals on 2026-10-28 or 2026-10-29.

---

## 5. Latency Assessment

### Sample size

| Stage | Samples | Status |
|-------|---------|--------|
| Actionable signal → detection | 0 | NO LIVE SAMPLE |
| Signal detection → trade commit | 0 | NO LIVE SAMPLE |
| Signal availability → trade commit | 0 | NO LIVE SAMPLE |
| Trade commit → Telegram send | 0 | NO LIVE SAMPLE |

### Per-signal timestamps

No signals occurred during the observation window. No per-signal timestamps available.

### Statistical summary

| Metric | p50 | p95 | Max | Samples |
|--------|-----|-----|-----|---------|
| Actionable signal → trade commit | N/A | N/A | N/A | 0 |

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

**Deployment verification: PASS** — Phase 3.5 fix is deployed and running (PID 778264). All changes confirmed present. Strategy rules unchanged.

**Live signal observation: NO LIVE SAMPLE** — Market closed during observation window. No candles ingested for 2026-10-29. No HLC signal could form or be detected.

**Latency measurement: NOT VERIFIED** — Requires live signal data during market hours.

**Final status: WAITING FOR MARKET OPEN**

The NSE regular session has not yet opened (08:37 IST vs 09:15 IST). No 5-minute candles have been ingested for 2026-10-29. No HLC signal can form or be detected until the session opens and candles begin arriving.

**Recommendation:** Observe during the next live market session (market opens 09:15 IST on weekdays). Capture signal detection, entry-price retrieval, trade commit, and Telegram delivery timestamps for each naturally occurring HLC signal. Compute p95 valid-signal-availability → trade-commit latency and compare against the 10-second target.

**No production changes were made during this verification.**

---

## Report Path

`/opt/tradingai/research/hlc_phase40_20261029_083800/LIVE_VERIFICATION_REPORT.md`
