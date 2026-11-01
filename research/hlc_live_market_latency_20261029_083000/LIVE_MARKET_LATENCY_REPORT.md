# TradingAI Phase 3.7 — Live Market HLC Latency Verification Report

**Report:** LIVE_MARKET_LATENCY_REPORT.md  
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
| Audit start time (IST) | 2026-10-29 08:29:33 IST |

---

## 2. Services Observed

| Service | PID | Start Time | Status | Phase 3.5 Code Deployed |
|---------|-----|------------|--------|-------------------------|
| paper_scalp_live.py | 778264 | Thu Oct 29 08:19:00 2026 | Running | Yes |
| gunicorn master | 745931 | Oct 28 | Running | N/A (API only) |
| gunicorn worker | 745933 | Oct 28 | Running | N/A |
| gunicorn worker | 745934 | Oct 28 | Running | N/A |

### Process health

| Check | Result |
|-------|--------|
| Process running | PASS |
| Single instance (file lock held) | PASS |
| No errors in stdout | PASS (only "another instance already running" from a 2nd launch attempt) |
| No gunicorn errors | PASS (gunicorn-err.log empty) |
| Phase 3.5 fix confirmed deployed | PASS (grep confirmed `_get_entry_price_from_provider`, `entry_candle_closed`, last-candle detection present) |

### Market state

| Check | Value |
|-------|-------|
| Current time (IST) | 2026-10-29 08:29:33 IST |
| Market open | 09:15 IST |
| First completed candle | 09:20 IST |
| Market status | CLOSED (pre-market) |
| Candles for 2026-10-29 | 0 (none ingested yet) |
| Latest candle timestamp | 2026-10-28T15:25:00+05:30 (NIFTY and BANKNIFTY) |

---

## 3. Naturally Occurring HLC Signals Observed

### Signals since deployment (after 08:19 IST)

| Metric | Value |
|--------|-------|
| New SCALP_HLC paper trades | 0 |
| New scalp_signals records | 0 |
| New Telegram alerts | 0 |

The market was closed during the entire observation window. No 5-minute candles were ingested for 2026-10-29. No HLC 3-bar pattern could form or be detected.

### Last signals before market close (2026-10-28)

| Signal ID | Instrument | Direction | Source Candle TS | Status | Signal Created At |
|-----------|-----------|-----------|-------------------|--------|-------------------|
| SS-C820F08DF353 | NIFTY | BULL | 2026-10-27T14:30:00+05:30 | TRADED | 2026-10-27T14:40:10.593480+05:30 |
| SS-BFD43DF0C67D | BANKNIFTY | BEAR | 2026-10-27T13:05:00+05:30 | TRADED | 2026-10-27T13:15:43.434056+05:30 |
| SS-DC445383416B | NIFTY | BEAR | 2026-10-27T13:05:00+05:30 | TRADED | 2026-10-27T13:15:43.302507+05:30 |

All signal records are from 2026-10-27. No signals on 2026-10-28 or 2026-10-29.

---

## 4. Latency Measurements

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

**p95 < 10 seconds target: UNVERIFIED** — requires observation of naturally occurring HLC signals during live market hours.

---

## 5. Correctness Verification

### 5.1 Signal uses three completed candles only

| Check | Result | Evidence |
|-------|--------|----------|
| `_scan_signals()` iterates completed candle triples | PASS | `scalp_engine.py:47-55` — scans `feats[i-2:i+1]` from completed candle data |
| Last-candle detection uses only completed candles | PASS | `scalp_engine.py:58-65` — compares `candles[i-2], candles[i-1], candles[i]` |
| Entry candle not required for signal detection | PASS | `scalp_engine.py:301` — `idx + 1 < len(candles) and` guard |

### 5.2 No lookahead or future data

| Check | Result | Evidence |
|-------|--------|----------|
| Entry candle open obtained from live provider at trade creation time | PASS | `paper_scalp_live.py:215-232` — `_get_entry_price_from_provider()` queries `MarketDataProvider.get_5m_candles()` |
| Forming candle's open available at candle-open time | PASS | `provider.py:97-132` — `get_5m_candles()` returns forming candle with `is_complete=False` but `open` populated |
| No future candle data used | PASS | All candle timestamps are historical (past or current interval) |

### 5.3 Entry-time guard

| Boundary Condition | Expected | Result | Evidence |
|-------------------|----------|--------|----------|
| now < entry_time | ok | PASS | `paper_scalp_live.py:209-211` — `entry_close = et + timedelta(minutes=5); if now_dt > entry_close: return 'expired'` |
| now == entry_time | ok | PASS | `>` comparison, not `>=` |
| now == entry_time + 5min | ok | PASS | Boundary inclusive |
| now > entry_time + 5min | expired | PASS | Entry candle closed |

### 5.4 Duplicate prevention, Mode C, stop/target, EOD

| Check | Result | Evidence |
|-------|--------|----------|
| Deterministic trade ID (SHA-1 of link_key) | PASS | `paper_scalp_live.py:25-32` |
| `trade_id` is PRIMARY KEY | PASS | `schema.sql:81` |
| INSERT + IntegrityError catch prevents duplicates | PASS | `paper_trade/engine.py:105-123` |
| Mode C: `has_open_position()` blocks per instrument | PASS | `paper_scalp_live.py:122-131` |
| Stop = signal candle extreme ±1 pt | PASS | `scalp_engine.py:220-221` |
| Target = 1.5×R | PASS | `scalp_engine.py:242-244` |
| Stop-first tie-break | PASS | `scalp_engine.py:_trade_for()` |
| EOD flat at session close | PASS | `scalp_engine.py:_trade_for()` |

### 5.5 Telegram messages correspond to persisted trades

| Check | Result | Evidence |
|-------|--------|----------|
| `tg_alerts.py` checks DB before alerting | PASS | `tg_alerts.py:548-554` |
| Alert skipped if trade not in DB | PASS | `tg_alerts.py:555-558` |
| Alert sent after trade exists | PASS | `tg_alerts.py:584` |
| Dedup via `fired` key | PASS | `tg_alerts.py:399` |

### 5.6 No unexpected exceptions or anomalies

| Check | Result | Evidence |
|-------|--------|----------|
| Gunicorn errors | None | `gunicorn-err.log` empty |
| Paper scalper startup errors | None | `paper_scalp_live.out` shows only lock message |
| Missing trades | N/A (no signals) | N/A |
| Duplicate trades | 0 | 94/94 distinct trade_ids (from Phase 3.3 audit) |

---

## 6. Missing Instrumentation

| Missing Timestamp | Where to Instrument | Why Needed |
|-------------------|---------------------|------------|
| Signal detection timestamp (when `_scan_signals()` first identifies a signal) | `scripts/paper_scalp_live.py:run_once()` signal loop | To measure signal detection → trade commit latency |
| Candle first-available-at timestamp | `app/market/provider.py` `_fetch_candles()` | To measure candle ingestion → signal detection latency |
| Entry price observed-at timestamp | `scripts/paper_scalp_live.py:_get_entry_price_from_provider()` | To confirm entry price available at decision time |
| Trade insert start/commit timestamps | `app/paper_trade/engine.py:create_paper_trade()` | To measure persistence delay |
| Telegram send start/complete timestamps | `scripts/tg_alerts.py:do_watch()` | Already partially captured via `ts_ist` in archive |

---

## 7. PASS / FAIL / NOT VERIFIED per Acceptance Criterion

| # | Acceptance Criterion | Verdict | Evidence |
|---|---------------------|---------|----------|
| 1 | Under 10 seconds valid signal → trade commit (p95) | NOT VERIFIED | No live signal occurred; market closed during observation |
| 2 | No lookahead or retrospective price as actionable | PASS | Entry price from live provider; historical open preserved in `qualification_evidence` |
| 3 | No expired or duplicate trades | PASS | `_entry_time_guard()` + `trade_id` PRIMARY KEY; 94/94 distinct IDs |
| 4 | Telegram alert tied to persisted trade | PASS | `tg_alerts.py:548-554` checks DB before alerting |
| 5 | No strategy changes | PASS | All HLC rules unchanged in code |
| 6 | No real-money execution | PASS | No broker integration; paper-only |

---

## 8. Conclusion

**Deployment verification: PASS** — Phase 3.5 fix is deployed and running (PID 778264). All changes confirmed present. Strategy rules unchanged.

**Live signal observation: NO LIVE SAMPLE** — Market was closed during the entire observation window (08:29 IST vs 09:15 IST open). No candles ingested, no trades created, no alerts sent.

**Latency measurement: NOT VERIFIED** — The under-10-second p95 target (valid signal availability → committed trade) cannot be evaluated without live signal data.

**Recommendation:** Observe during the next live market session (market opens 09:15 IST on weekdays). Capture signal detection timestamps, entry price retrieval times, trade commit times, and Telegram send times for each naturally occurring HLC signal. Compute p95 valid-signal-availability → trade-commit latency and compare against the 10-second target.

**No production changes were made during this verification.**

---

## Report Path

`/opt/tradingai/research/hlc_live_market_latency_20261029_083000/LIVE_MARKET_LATENCY_REPORT.md`
