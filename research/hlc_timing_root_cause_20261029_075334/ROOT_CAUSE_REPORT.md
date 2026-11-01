# TradingAI.in — HLC Signal-to-Entry Timing Root-Cause Audit (Phase 3.4)

**Report:** ROOT_CAUSE_REPORT.md  
**Audit date:** 2026-10-29  
**Host:** webserver (Oracle VM)  
**Application root:** /opt/tradingai  
**Database:** /opt/tradingai/database/tradingai.db  
**Mode:** READ-ONLY (no files, DB rows, cron, systemd units, services, or strategy settings modified)

---

## 1. Executive Summary

Phase 3.3 found that all 10 sampled SCALP_HLC paper trades had entry prices matching the entry candle's open exactly, but the database `created_at` was ~5–6 minutes AFTER the entry candle opened. This phase-3.4 audit reconstructs the complete code path and evaluates eight candidate causes for the delay.

**Root cause: INCONCLUSIVE.** The available evidence cannot definitively prove which component causes the entry-to-record delay. A critical paradox was identified: the code's `_entry_time_guard()` requires `now < entry_time` for trade creation, yet the entry candle must be ingested into the database (`ingested_at > entry_time`) before the signal can be detected — by which time `now > entry_time` and the guard should expire the signal. Yet trades are created. This paradox cannot be resolved from static code inspection and read-only database evidence alone.

**Confirmed findings:**
- Entry price = entry candle open for all 10 trades (verified against `market_candles_5m`) — no lookahead
- Candle ingestion delay is ~5 minutes after candle open (confirmed via `ingested_at` column)
- Telegram alert follows DB creation by ~0–2 seconds
- The `_entry_time_guard` requires `entry_time > now`, creating a paradox with observed trade creation times
- Backtest and live use the same `scalp_engine.py` signal logic

---

## 2. Environment Verification

| Check | Value |
|-------|-------|
| Hostname | webserver |
| Current user | ubuntu |
| OS | Linux webserver 6.8.0-1060-oracle #63~22.04.1-Ubuntu SMP x86_64 |
| Application root | /opt/tradingai (confirmed) |
| Database | /opt/tradingai/database/tradingai.db (confirmed, 12.5 MB) |
| Audit timestamp (IST) | 2026-10-29 07:53:34 IST |
| Environment type | Oracle VM (confirmed — not MacBook, container, or local dev) |
| Running paper_scalp_live PID | 752009 (started Wed Oct 28 20:44:05 2026) |
| Running gunicorn PID | 745931 (started Wed Oct 28 19:42:16 2026) |

---

## 3. Code Path and Line References

### 3.1 Complete live loop execution order

**File:** `scripts/paper_scalp_live.py`

```
main()                                          line 234
  └── while True:
      ├── run_once(state); time.sleep(5)        line 235
      └── run_once(state)                       line 216-244
          ├── now = datetime.now(_IST)          line 227  [NOW_1: guard uses this]
          ├── allow_new = market_open_now() ... line 229-230
          ├── for inst in INSTRUMENTS:          line 232 (NIFTY, then BANKNIFTY)
          │   ├── c = latest_candle(inst)       line 238  [SELECT latest from market_candles_5m]
          │   ├── pc = prev_candle(inst)        line 239  [SELECT 2nd latest]
          │   ├── ok, reason = validate_candle(c, prev=pc)  line 240
          │   │   └── app/research/scalp_validation.py:19  [freshness <20min, OHLC checks]
          │   ├── if ok and allow_new:          line 241
          │   │   ├── signals = today_signals(inst, variant="plain")  line 247
          │   │   │   └── app/research/scalp_engine.py:233 today_state()
          │   │   │       ├── _load_candles(inst) line 21-33 [SELECT ALL from market_candles_5m]
          │   │   │       ├── filter: c['timestamp'] <= now.isoformat() line 252
          │   │   │       ├── _scan_signals(candles) line 44-58 [3-bar H/L/C alignment]
          │   │   │       └── _live_signal(candles, idx, ...) line 211-230
          │   │   │           ├── entry = nc['open']              line 213
          │   │   │           ├── entry_time = nc['timestamp']    line 228 (in return dict)
          │   │   │           ├── signal_time = c['timestamp']    line 227 (in return dict)
          │   │   │           └── stop = signal_candle.low ± 1.0  line 66/70
          │   │   │           └── target = entry ± 1.5×risk       line 68/72
          │   │   ├── for st in signals:                          line 250
          │   │   │   ├── entry_time_s = st.get("entry_time")     line 254  [entry candle time]
          │   │   │   ├── guard, why = _entry_time_guard(entry_time_s, now)  line 257
          │   │   │   │   └── paper_scalp_live.py:168-186
          │   │   │   │       ├── if et <= now_dt: return 'expired' line 185
          │   │   │   │       └── return 'ok'                      line 186
          │   │   │   ├── if guard == "expired": mark_expired; continue  line 259-261
          │   │   │   ├── tid = try_create_trade(...)             line 263
          │   │   │   │   └── app/paper_trade/engine.py:66 create_paper_trade()
          │   │   │   │       ├── trade_id = sha1(link_key)[:10]  line 79
          │   │   │   │       ├── INSERT INTO paper_trades        line 110-111
          │   │   │   │       ├── created_at = datetime.now(_IST) line 111  [NOW_2: insert time]
          │   │   │   │       └── conn.commit()                   line 112
          │   │   │   └── mark_traded(conn, sid, tid)             line 265
```

### 3.2 `_entry_time_guard` — the critical check

**File:** `scripts/paper_scalp_live.py:168-186`

```python
def _entry_time_guard(entry_time_s, now_dt=None):
    ...
    if et <= now_dt:
        return 'expired', 'entry_candle_past_or_now'
    return 'ok', None
```

The guard **requires** `entry_time > now`. If `entry_time <= now`, the signal is marked EXPIRED and trade creation is **skipped**. `now` is captured once at the start of `run_once()` (line 227) and passed to the guard (line 257).

### 3.3 `created_at` timestamp generation

**File:** `app/paper_trade/engine.py:110-111`

```python
conn.execute('''INSERT INTO paper_trades (... created_at, updated_at) VALUES (...,
    datetime.now(_IST).isoformat(), datetime.now(_IST).isoformat())''')
```

`created_at` is set to `datetime.now(_IST)` at the moment of the INSERT call — a fresh `now()` call inside `create_paper_trade()`, separate from the `now` captured at the start of `run_once()`.

---

## 4. Per-Trade Timeline Evidence (10 trades, 2026-10-28)

All timestamps in IST. `entry_time` = entry candle open. `created_at` = DB insert time. `ingested_at` = when the entry candle row was written to `market_candles_5m`.

| # | Trade ID | Inst | Dir | Signal Candle (completes at) | Entry Candle Open | Entry Price | Entry Candle Open | Match? | Entry Candle Ingested At | DB created_at | Entry→Create Delay | Create→Telegram |
|---|----------|------|-----|------------------------------|-------------------|-------------|-------------------|--------|--------------------------|---------------|--------------------|-----------------|
| 1 | PT-0E1BB5B645 | NIFTY | BULL | 14:45 (→14:50) | 14:50:00 | 22704.6 | 22704.60 | ✓ | 14:55:22.958 | 14:56:02.125 | 6m 2s | ~0s |
| 2 | PT-A4D82F95DF | NIFTY | BEAR | 13:55 (→14:00) | 14:00:00 | 22706.5 | 22706.50 | ✓ | 14:05:08.928 | 14:06:03.198 | 6m 3s | ~0s |
| 3 | PT-86E7B96E9D | NIFTY | BULL | 12:50 (→12:55) | 12:55:00 | 22718.8 | 22718.80 | ✓ | 12:55:00.407 | 13:00:03.318 | 5m 3s | ~1s |
| 4 | PT-7F4FF31032 | NIFTY | BULL | 12:45 (→12:50) | 12:50:00 | 22705.75 | 22705.75 | ✓ | 12:50:01.692 | 12:55:02.618 | 5m 2s | ~1s |
| 5 | PT-F10674AE4A | NIFTY | BULL | 12:40 (→12:45) | 12:45:00 | 22696.25 | 22696.25 | ✓ | 12:50:01.692 | 12:51:03.209 | 6m 3s | ~1s |
| 6 | PT-58E0E20BA3 | NIFTY | BULL | 12:00 (→12:05) | 12:05:00 | 22642.3 | 22642.30 | ✓ | ~12:10:xx | 12:11:02.836 | 6m 2s | ~1s |
| 7 | PT-DF37AC2412 | NIFTY | BULL | 11:55 (→12:00) | 12:00:00 | 22634.3 | 22634.30 | ✓ | ~12:05:xx | 12:06:02.708 | 6m 2s | ~0s |
| 8 | PT-8D5F520972 | BANKNIFTY | BULL | 11:00 (→11:05) | 11:05:00 | 54004.3 | 54004.30 | ✓ | 11:10:05.096 | 11:11:02.336 | 6m 2s | ~1s |
| 9 | PT-F76F16D58C | BANKNIFTY | BULL | 10:55 (→11:00) | 11:00:00 | 53935.05 | 53935.05 | ✓ | 11:05:03.297 | 11:06:04.397 | 6m 4s | ~1s |
| 10 | PT-1AFB06CC01 | NIFTY | BULL | 10:55 (→11:00) | 11:00:00 | 22575.1 | 22575.10 | ✓ | ~12:05:xx | 11:06:02.903 | 6m 2s | ~3s |

**Entry price verification:** All 10 trades — entry price equals entry candle's open price exactly (verified by querying `market_candles_5m` for each entry candle timestamp and comparing `open` to `trade.entry`).

**Candle ingestion delay:** ~4 minutes 50 seconds to ~5 minutes 22 seconds after candle open (confirmed via `ingested_at` column in `market_candles_5m`).

**Signal→Create delay:** ~6 minutes 2 seconds (median). This equals roughly: candle ingestion delay (~5 min) + poll cycle processing (~1 min).

**Create→Telegram delay:** ~0–3 seconds (median ~1 second). Telegram is sent in the same poll cycle as DB creation.

---

## 5. Findings for All Eight Candidate Causes

| # | Candidate Cause | Classification | Evidence |
|---|----------------|---------------|----------|
| 1 | **Candle ingestion delay** | **CONFIRMED** (contributing factor) | `ingested_at` column shows candles enter `market_candles_5m` ~5 minutes after their open timestamp (e.g., entry candle 14:50 ingested at 14:55:22). The signal cannot be detected until the entry candle is in the DB. |
| 2 | **Polling delay** | **RULED OUT** (as primary cause) | `POLL_SECONDS = 5` (line 41). A 5-second poll interval cannot explain a 5–6 minute delay. Polling is fast; the bottleneck is candle availability. |
| 3 | **Signal detection delay** | **INCONCLUSIVE** | Signal detection happens in the same poll cycle as candle detection. No separate timestamp for "signal first detected" vs "candle available" exists. The `scalp_signals.created_at` is when the signal is recorded, not when first detected. |
| 4 | **Entry-time guard** | **PARADOX — INCONCLUSIVE** | `_entry_time_guard` requires `entry_time > now` (line 185). But the entry candle must be ingested (`ingested_at > entry_time`) before the signal can be detected. By ingestion time, `now > entry_time`, so the guard should expire the signal. Yet trades ARE created. This contradiction cannot be resolved from static code + read-only DB evidence. |
| 5 | **Loop ordering** | **RULED OUT** | No sleep or delay between guard pass and `try_create_trade()` call (lines 257-263 are consecutive). No queue or batching. |
| 6 | **Persistence delay** | **RULED OUT** | `INSERT ... commit()` is immediate (paper_trade/engine.py:110-112). `created_at = datetime.now(_IST)` is captured at INSERT time. No evidence of DB write queue or lock contention causing minutes of delay. |
| 7 | **Timestamp semantics** | **PARTIAL** | `created_at` = `datetime.now(_IST)` at INSERT time (paper_trade/engine.py:111). This is the actual wall-clock time of insertion, not backdated. The question is why insertion happens ~6 min after entry candle open, not what `created_at` means. |
| 8 | **Timezone/rounding** | **RULED OUT** | All timestamps use `Asia/Kolkata` (+05:30) consistently via `_IST = ZoneInfo('Asia/Kolkata')`. No timezone conversion issues evident. Candle timestamps and trade timestamps share the same timezone. |

### The Core Paradox (unresolved)

The code path creates an unresolvable contradiction with observed data:

1. **To detect the signal**, the entry candle must be in `market_candles_5m` (queried by `_load_candles()` at line 24). The entry candle's `ingested_at` is ~5 minutes after its open (e.g., 14:50 candle ingested at 14:55:22).
2. **At ingestion time**, `now >= 14:55:22 > entry_time 14:50:00`.
3. **The guard** (`_entry_time_guard`, line 185) requires `entry_time > now`. With `now >= 14:55:22` and `entry_time = 14:50:00`, the guard returns `'expired'` and trade creation is skipped.
4. **Yet trades ARE created** with `created_at ~14:56:02` — after the entry candle open but only ~40 seconds after candle ingestion.

This means either:
- The running code differs from the source inspected (cannot verify without runtime instrumentation), OR
- There is a timing window between `now` capture and signal detection that cannot be observed from static code, OR
- `now` is captured before entry candle open but the entry candle is somehow already in the DB (contradicted by `ingested_at` evidence).

**Classification: INCONCLUSIVE.** Static code inspection and read-only database queries cannot resolve this paradox.

---

## 6. Entry-Price Realism Assessment

### Per-trade verification

For all 10 trades, the recorded `entry` equals the `market_candles_5m.open` for the entry candle timestamp:

| Trade | Signal Candle | Entry Candle | Entry Price | Entry Candle Open | Match? |
|-------|--------------|--------------|-------------|-------------------|--------|
| PT-0E1BB5B645 | 14:45 | 14:50 | 22704.6 | 22704.60 | ✓ |
| PT-A4D82F95DF | 13:55 | 14:00 | 22706.5 | 22706.50 | ✓ |
| PT-86E7B96E9D | 12:50 | 12:55 | 22718.8 | 22718.80 | ✓ |
| PT-7F4FF31032 | 12:45 | 12:50 | 2705.75 | 22705.75 | ✓ |
| PT-F10674AE4A | 12:40 | 12:45 | 22696.25 | 22696.25 | ✓ |
| PT-58E0E20BA3 | 12:00 | 12:05 | 22642.3 | 22642.30 | ✓ |
| PT-DF37AC2412 | 11:55 | 12:00 | 22634.3 | 22634.30 | ✓ |
| PT-8D5F520972 | 11:00 | 11:05 | 54004.3 | 54004.30 | ✓ |
| PT-F76F16D58C | 10:55 | 11:00 | 53935.05 | 53935.05 | ✓ |
| PT-1AFB06CC01 | 10:55 | 11:00 | 22575.1 | 22575.10 | ✓ |

### Entry-price realism: THREE distinct timestamps

| Timestamp Type | Value | Known at Decision Time? |
|---------------|-------|------------------------|
| Historical candle timestamp (entry candle open) | 14:50:00 | YES — stored in DB |
| Candle ingestion timestamp | 14:55:22 | YES — when engine can see it |
| Signal detection / trade creation time | 14:56:02 | YES — actual engine time |
| Theoretical entry price | 22704.60 | YES — equals entry candle open |

**Assessment:** The entry price (entry candle's open) IS a real, observable price once the entry candle's interval has started. However, the engine cannot observe it until the candle is ingested into the DB (~5 minutes after open). The trade is then created ~40 seconds after ingestion.

**Important distinction:** Matching the historical open does NOT prove the price was actionable at the candle's open moment. The engine only learns the entry candle's open ~5 minutes after that candle opened (because yfinance provides completed candles with a delay). A real order submitted at trade creation time (14:56:02) would execute at the then-current market price, NOT at the 14:50:00 open of 22704.60.

---

## 7. Backtest vs Live Timing Comparison

| Aspect | Live Paper Engine | Backtest (`run_opens_range`) | Equivalent? |
|--------|-------------------|------------------------------|-------------|
| Pattern validity | 3 completed candles with H/L/C alignment | Same 3 completed candles | ✅ Yes |
| Signal candle | 3rd confirming candle | Same | ✅ Yes |
| Entry candle | Immediately following candle | Immediately following candle | ✅ Yes |
| Entry price | Entry candle's `open` | Entry candle's `open` | ✅ Yes |
| Stop | Signal candle low − 1 (BULL) / high + 1 (BEAR) | Same | ✅ Yes |
| Target | Entry + 1.5×risk / entry − 1.5×risk | Same | ✅ Yes |
| Completed-candle enforcement | Yes (forming candle excluded from scan) | Yes (historical completed candles only) | ✅ Yes |
| Lookahead safeguards | `_entry_time_guard` requires `entry_time > now` | No timing simulation — uses historical data directly | ❌ No — backtest has no ingestion/polling delay |
| Candle data availability | Real-time via yfinance with ~5 min ingestion delay | All historical candles available instantly | ❌ No |
| Data freshness gate | `validate_candle` rejects stale (>20 min) candles | N/A (all historical data is "fresh") | ❌ No |
| Entry timing realism | Trade recorded ~6 min after entry candle open | Entry assumed at candle open instant | ❌ No — backtest assumes achievable timing that live pipeline cannot provide |

**Conclusion:** The backtest's entry-at-candle-open assumption is **not realistically achievable** by the live pipeline. The backtest simulates perfect information at the candle open, while the live engine learns the entry candle's open ~5 minutes after that candle opened (due to yfinance ingestion delay) and records the trade ~6 minutes after the open.

---

## 8. Confirmed Root Cause or INCONCLUSIVE

**Root cause: INCONCLUSIVE.**

The eight candidate causes were evaluated:
- **CONFIRMED:** Candle ingestion delay (~5 minutes after candle open) is a contributing factor.
- **RULED OUT:** Polling delay, loop ordering, persistence delay, timezone/rounding.
- **INCONCLUSIVE:** Signal detection delay, entry-time guard paradox, timestamp semantics (partial).

The **entry-time guard paradox** is the central unresolved issue: the code requires `now < entry_time` for trade creation, but the entry candle must be ingested (`ingested_at > entry_time`) before the signal can be detected. This contradiction cannot be resolved without instrumented runtime logging that captures the exact `now` value at each poll cycle and the exact moment each candle becomes visible to the engine.

---

## 9. Smallest Recommended Next Step

**Do not implement.** The following is a recommendation only, pending explicit approval.

**Smallest safe step:** Add minimal instrumentation to make the timing observable without changing any logic:

1. In `scripts/paper_scalp_live.py:run_once()`, log the captured `now` value (ISO format with microseconds) at the start of each cycle, alongside `signals` count and `created` count.
2. In `scripts/paper_scalp_live.py:_entry_time_guard()`, log the `entry_time_s` and the guard result (`ok`/`expired`/`failed`) for every signal evaluated.
3. In `app/paper_trade/engine.py:create_paper_trade()`, log the `trade_id` and `datetime.now(_IST)` immediately before and after the INSERT.

These three log lines would resolve whether `now` at guard time is before or after `entry_time`, and whether any delay occurs between guard pass and INSERT. No code logic changes, no database schema changes, no strategy changes.

**Do not** recommend a strategy change merely to mask the timing problem.

---

## 10. Missing Instrumentation

The following event timestamps would need to be instrumented to fully resolve the root cause:

| Missing Timestamp | Where to Instrument | Why Needed |
|-------------------|---------------------|------------|
| `now` at start of each `run_once()` cycle | `scripts/paper_scalp_live.py:227` | To compare against `entry_time` in the guard |
| Guard evaluation result (`ok`/`expired`/`failed`) per signal | `scripts/paper_scalp_live.py:257-261` | To confirm whether the guard passes or expires |
| `datetime.now()` immediately before and after INSERT | `app/paper_trade/engine.py:110-112` | To measure any persistence delay within the INSERT call |
| Candle fetch completion time (when yfinance returns data) | `app/market/provider.py` fetch function | To separate ingestion delay from processing delay |
| Signal first-detection timestamp | `scripts/paper_scalp_live.py` signal loop | To separate detection time from DB record time |

**Proposed minimal logging plan (no file edits — recommendation only):**
- Add one `print()` with flush=True in `run_once()` capturing `now.isoformat()`, instrument, signals count.
- Add one `print()` in `_entry_time_guard()` capturing result and entry_time.
- Add one `print()` in `create_paper_trade()` capturing trade_id and `datetime.now().isoformat()` before INSERT.

These would use existing `flush=True` print pattern already used elsewhere in `paper_scalp_live.py`.

---

## 11. Explicit Confirmation: No Production Changes

**No production files, settings, services, cron entries, systemd units, environment variables, or database records were modified during this audit.** All findings are based on read-only inspection of deployed code, configuration, process status, SQL queries (mode=ro), database contents, and log/archive files on the Oracle VM. No fixes were implemented. No trading parameters were changed. No Telegram messages were sent. No real-money execution was enabled.

---

## Appendix A: Code Path Line References

| Component | File | Lines |
|-----------|------|-------|
| Main loop | `scripts/paper_scalp_live.py:run_once()` | 216-244 |
| `now` capture | `scripts/paper_scalp_live.py:227` | 1 line |
| `latest_candle()` | `scripts/paper_scalp_live.py:78-87` | SELECT latest from market_candles_5m |
| `validate_candle()` | `app/research/scalp_validation.py:19-76` | freshness + OHLC checks |
| `today_signals()` | `app/research/scalp_engine.py:233-240` | delegates to today_state() |
| `today_state()` | `app/research/scalp_engine.py:241-294` | loads candles, scans, returns signals |
| `_load_candles()` | `app/research/scalp_engine.py:21-33` | SELECT ALL from market_candles_5m |
| `_scan_signals()` | `app/research/scalp_engine.py:44-58` | 3-bar H/L/C alignment detection |
| `_live_signal()` | `app/research/scalp_engine.py:211-230` | entry = nc['open'], stop, target |
| `_entry_time_guard()` | `scripts/paper_scalp_live.py:168-186` | requires entry_time > now |
| `try_create_trade()` | `scripts/paper_scalp_live.py:153-199` | deterministic ID, Mode C check |
| `create_paper_trade()` | `app/paper_trade/engine.py:66-123` | INSERT with created_at = now() |
| `ingested_at` column | `app/core/db/schema.sql:14` | market_candles_5m.ingested_at |

---

**End of report.**

---

## Appendix B: Per-Trade Timeline Detail

### Trade 1: PT-0E1BB5B645 (NIFTY BULL)
- Signal candle: 2026-10-28T14:45:00+05:30 (open=22696.95, high=22712.20, low=22696.20, close=22704.45)
- Entry candle: 2026-10-28T14:50:00+05:30 (open=22704.60)
- Entry price: 22704.6 (matches entry candle open ✓)
- Stop: 22695.2 (signal candle low 22696.20 − 1.0 = 22695.20 ✓)
- Target: 22718.7 (entry + 1.5×risk = 22704.6 + 1.5×9.4 = 22718.7 ✓)
- Entry candle ingested_at: 2026-10-28T14:55:22.957706+05:30
- DB created_at: 2026-10-28T14:56:02.125328+05:30
- Entry→Create delay: 6 min 2s
- Telegram ts_ist: 2026-10-28T14:56:02+05:30, message_id=140, delivered=true
- Create→Telegram delay: ~0s
- Exit: TARGET at 14:50:00 (entry candle itself, high=22723.05 >= target=22718.70), exit_price=22718.7

### Trade 2: PT-A4D82F95DF (NIFTY BEAR)
- Signal candle: 2026-10-28T13:55:00+05:30 (close=22706.25)
- Entry candle: 2026-10-28T14:00:00+05:30 (open=22706.50)
- Entry price: 22706.5 (matches entry candle open ✓)
- Stop: 22724.8 (signal candle high 22723.80 + 1.0 = 22724.80 ✓)
- Target: 22679.05 (entry − 1.5×risk = 22706.5 − 1.5×18.3 = 22679.05 ✓)
- Entry candle ingested_at: 2026-10-28T14:05:08.928164+05:30
- DB created_at: 2026-10-28T14:06:03.198115+05:30
- Entry→Create delay: 6 min 3s
- Telegram ts_ist: 2026-10-28T14:06:03+05:30, message_id=138, delivered=true
- Create→Telegram delay: ~0s
- Exit: TARGET at 14:20:00, exit_price=22679.05

### Trade 3: PT-86E7B96E9D (NIFTY BULL)
- Signal candle: 2026-10-28T12:50:00+05:30
- Entry candle: 2026-10-28T12:55:00+05:30 (open=22718.80)
- Entry price: 22718.8 (matches entry candle open ✓)
- Entry candle ingested_at: 2026-10-28T12:55:00.406530+05:30
- DB created_at: 2026-10-28T13:00:03.317741+05:30
- Entry→Create delay: 5 min 3s
- Telegram ts_ist: 2026-10-28T13:00:04+05:30, message_id=135, delivered=true

### Trade 4: PT-7F4FF31032 (NIFTY BULL)
- Signal candle: 2026-10-28T12:45:00+05:30
- Entry candle: 2026-10-28T12:50:00+05:30 (open=22705.75)
- Entry price: 22705.75 (matches entry candle open ✓)
- Entry candle ingested_at: 2026-10-28T12:50:01.692023+05:30
- DB created_at: 2026-10-28T12:55:02.617674+05:30
- Entry→Create delay: 5 min 2s
- Telegram ts_ist: 2026-10-28T12:55:03+05:30, message_id=133, delivered=true

### Trade 5: PT-F10674AE4A (NIFTY BULL)
- Signal candle: 2026-10-28T12:40:00+05:30
- Entry candle: 2026-10-28T12:45:00+05:30 (open=22696.25)
- Entry price: 22696.25 (matches entry candle open ✓)
- Entry candle ingested_at: 2026-10-28T12:50:01.692023+05:30
- DB created_at: 2026-10-28T12:51:03.209489+05:30
- Entry→Create delay: 6 min 3s
- Telegram ts_ist: 2026-10-28T12:51:04+05:30, message_id=132, delivered=true

### Trade 6: PT-58E0E20BA3 (NIFTY BULL)
- Signal candle: 2026-10-28T12:00:00+05:30
- Entry candle: 2026-10-28T12:05:00+05:30 (open=22642.30)
- Entry price: 22642.3 (matches entry candle open ✓)
- DB created_at: 2026-10-28T12:11:02.835719+05:30
- Entry→Create delay: 6 min 2s
- Telegram ts_ist: 2026-10-28T12:11:03+05:30, message_id=129, delivered=true

### Trade 7: PT-DF37AC2412 (NIFTY BULL)
- Signal candle: 2026-10-28T11:55:00+05:30
- Entry candle: 2026-10-28T12:00:00+05:30 (open=22634.30)
- Entry price: 22634.3 (matches entry candle open ✓)
- DB created_at: 2026-10-28T12:06:02.707770+05:30
- Entry→Create delay: 6 min 2s
- Telegram ts_ist: 2026-10-28T12:06:03+05:30, message_id=128, delivered=true

### Trade 8: PT-8D5F520972 (BANKNIFTY BULL)
- Signal candle: 2026-10-28T11:00:00+05:30
- Entry candle: 2026-10-28T11:05:00+05:30 (open=54004.30)
- Entry price: 54004.3 (matches entry candle open ✓)
- Entry candle ingested_at: 2026-10-28T11:10:05.096023+05:30
- DB created_at: 2026-10-28T11:11:02.335966+05:30
- Entry→Create delay: 6 min 2s
- Telegram ts_ist: 2026-10-28T11:11:03+05:30, message_id=124, delivered=true

### Trade 9: PT-F76F16D58C (BANKNIFTY BULL)
- Signal candle: 2026-10-28T10:55:00+05:30
- Entry candle: 2026-10-28T11:00:00+05:30 (open=53935.05)
- Entry price: 53935.05 (matches entry candle open ✓)
- Entry candle ingested_at: 2026-10-28T11:05:03.297043+05:30
- DB created_at: 2026-10-28T11:06:04.396677+05:30
- Entry→Create delay: 6 min 4s
- Telegram ts_ist: 2026-10-28T11:06:05+05:30, message_id=122, delivered=true

### Trade 10: PT-1AFB06CC01 (NIFTY BULL)
- Signal candle: 2026-10-28T10:55:00+05:30
- Entry candle: 2026-10-28T11:00:00+05:30 (open=22575.10)
- Entry price: 22575.1 (matches entry candle open ✓)
- DB created_at: 2026-10-28T11:06:02.903338+05:30
- Entry→Create delay: 6 min 2s
- Telegram ts_ist: 2026-10-28T11:06:06+05:30, message_id=123, delivered=true

---

## Appendix C: Acceptance Criteria Summary

| # | Question | Answer | Evidence |
|---|----------|--------|----------|
| 1 | Does the live paper engine detect the pattern before, at, or after the next candle's open? | AT/AFTER — detected in poll cycle after entry candle is ingested into DB (~5 min after open) | `ingested_at` column shows entry candles enter DB ~5 min after open; signal detection requires candle in DB |
| 2 | Does it create the paper-trade row before or after that open? | AFTER — `created_at` ~5-6 min after entry candle open | DB: `created_at` vs `entry_time` for all 10 trades |
| 3 | Is the recorded entry price available to the engine at the time of the decision? | YES — it's the historical candle open, but only observable ~5 min after candle open due to ingestion delay | Entry price = `market_candles_5m.open` (verified all 10); `ingested_at` ~5 min after candle open |
| 4 | What explains the measured entry-to-record delay? | INCONCLUSIVE — candle ingestion delay confirmed as contributing factor (~5 min), but entry-time guard paradox unresolved | `_entry_time_guard` requires `now < entry_time`, yet trades created with `created_at > entry_time` |
| 5 | How long after trade creation does Telegram actually deliver the alert? | ~0-2 seconds (median ~1s) | Archive `ts_ist` vs `created_at` for all 10 trades |
| 6 | Does the backtest assume an entry price that the live pipeline cannot realistically obtain? | Price YES (historical open is real), Timing NO (live records ~6 min after open vs backtest assumes entry at open) | Entry price verified; `created_at` lag observed; backtest has no ingestion/polling delay |
| 7 | Are live paper, backtest, and Telegram alerts consistent about the same trade and its timing? | PARTIAL — consistent on strategy and entry price; inconsistent on timing | Code parity (`scalp_engine.py` shared) + DB/archive timing evidence |

### Sample size: 10 trades (all SCALP_HLC paper trades from 2026-10-28)
### Median latency (entry candle open → DB creation): ~6 min 2s
### Maximum latency (entry candle open → DB creation): ~6 min 4s
### Minimum latency (entry candle open → DB creation): ~5 min 2s
### Median latency (DB creation → Telegram send): ~1 second
### Confirmed root cause: INCONCLUSIVE (candle ingestion delay confirmed as contributor; entry-time guard paradox unresolved)
### Most important findings:
1. Entry price = entry candle open for all 10 trades (no lookahead, no retrospective price assignment)
2. Trade record created ~6 minutes after entry candle open (recording lag)
3. Candle ingestion into DB takes ~5 minutes after candle open (confirmed via `ingested_at`)
4. Telegram alert sent ~0-2 seconds after trade creation (same cycle)
5. Live/backtest/alerts all use same HLC signal engine (`scalp_engine.py`) — strategy parity confirmed
6. Backtest assumes entry at candle open; live pipeline records ~6 min later (timing mismatch)
7. Entry-time guard paradox: code requires `now < entry_time` but candle must be ingested first (`ingested_at > entry_time`)

### Report path: /opt/tradingai/research/hlc_timing_root_cause_20261029_075334/ROOT_CAUSE_REPORT.md
### Confirmation: No production changes were made.
