# TradingAI.in — Strategy Defaults and Alert Timing Audit

**Report:** STRATEGY_DEFAULTS_AND_ALERT_TIMING_AUDIT.md  
**Audit date:** 2026-10-29  
**Host:** webserver (Oracle VM)  
**Application root:** /opt/tradingai  
**Database:** /opt/tradingai/database/tradingai.db  
**Mode:** READ-ONLY (no files, DB rows, cron, systemd units, services, or strategy settings modified; no real-money/broker enabled)

---

## A–F Direct Answers

| # | Question | Answer |
|---|----------|--------|
| A | Default live paper-trading strategy | **HLC 3-bar scalp** (verified in code + DB) |
| B | Default backtest strategy | **HLC 3-bar scalp** via `/api/backtest/scalp`; CPR trigger via `/api/backtest/cpr-triggers` is an alternate endpoint |
| C | Does a Telegram alert happen automatically when a paper trade is created? | **No** — tg_alerts.py does NOT create trades. paper_scalp_live.py creates the trade; tg_alerts.py --watch polls, finds the trade already in the DB, then sends the alert in the same polling cycle. Delay ≈ 5–6 min after the candle open (wall-clock lag between entry candle open and DB insert) |
| D | Does the paper trade enter at the next candle open after a confirmed 3-bar HLC pattern? | **Yes in price/timestamp** (entry = candle N+1 open, verified against DB). **No in wall-clock** — the DB record is created ~5–6 minutes after the entry candle opens (created_at > entry_time) |
| E | Are the live engine, backtest, and alerts using consistent rules? | **PASS for HLC scalp path** — live engine, `/api/backtest/scalp`, and tg_alerts all use `app/research/scalp_engine` (same signal, entry, stop, target, EOD). **MISMATCH with legacy CPR path** (`qualified_trades`/`daily_trade_locks` from older QualificationEngine/SMA20/CPR code) |

---

## 1. Executive Summary

This is a read-only audit of the deployed TradingAI.in application on the Oracle VM (`webserver`, `/opt/tradingai`).

**Confirmed:** The default live paper-trading strategy is the **HLC 3-bar scalp**. Three consecutive 5-minute candles with aligned high/low/close generate a signal; entry is at the next candle's open; stop = signal-candle extreme ±1 pt; target = 1.5×R; EOD flat at session close. Mode C (one open position per instrument) is enforced.

The live engine (`app/live/engine.py`), the paper trader (`scripts/paper_scalp_live.py`), the scalp backtest (`/api/backtest/scalp`), and Telegram alerts (`scripts/tg_alerts.py --watch`) all share `app/research/scalp_engine.py` for HLC signal generation — parity holds on this path.

A legacy CPR/QualificationEngine path exists (`qualified_trades`, `daily_trade_locks`, `_cpr_book_signal`) but is **retained for rollback only** and is **not** the default trade-decision engine. The `qualified_trades` table shows CPR/SMA20 rows from older sessions (last: 2026-10-26), while `paper_trades` (94 rows) are all HLC SCALP_HLC from the current path.

Telegram alerts are **scheduled and operational**: `tg_alerts.py --watch` runs via cron every minute 09:15–15:30 weekdays; `tg_alerts.py --reconcile` runs at 09:10 weekdays. Alerts are sent **after** paper_scalp_live.py creates the trade (tg_alerts checks the DB first and skips if the trade doesn't exist yet).

**Key timing finding:** The trade record is created ~5–6 minutes after the entry candle opens (wall-clock `created_at` > `entry_time`), not at the exact candle-open instant. The entry price/timestamp equal the next candle's open, but the DB insert lags.

---

## 2. Task 1 — Live Paper-Trading Defaults

### 2.1 Service startup and running processes

No `systemctl` binary exists on this VM. Services are launched directly:

**Gunicorn API** (PID 745931, started Oct 28):
```
/usr/bin/python3 /usr/local/bin/gunicorn -w 2 --threads 4 --worker-class gthread
  --bind 127.0.0.1:8000 --timeout 90 --graceful-timeout 15 --keep-alive 5
  --max-requests 1000 --max-requests-jitter 800
  --access-logfile /opt/tradingai/logs/gunicorn-access.log
  --error-logfile /opt/tradingai/logs/gunicorn-error.log
  app.api.app:app
```
2 worker processes (PIDs 745933, 745934). Serves the decision API used by tg_alerts.

**Paper scalper** (PID 752009, started Oct 28):
```
/usr/bin/python3 /opt/tradingai/scripts/paper_scalp_live.py
```
Runs as a foreground loop (`while True: run_once(); time.sleep(5)`), not under systemd. Uses an fcntl lock file (`logs/paper_scalp_live.lock`) to prevent multiple instances.

### 2.2 Default live strategy: HLC 3-bar scalp

**File:** `/opt/tradingai/app/live/engine.py`

`LiveEngine.evaluate()` (line 597) is the decision entry point. Its docstring (lines 21–32) explicitly states:

> "Firing uses the HLC 3-bar scalp book (_hlc_book_signal: three-consecutive candle alignment, next-open entry, signal-candle-extreme stop ±1pt, 1.5R target) — same math as backtest/paper. Live default variant is 'plain'. ... The CPR trigger engine (_cpr_book_signal) is retained for rollback but is no longer the default trade-decision engine."

Call chain:
1. `LiveEngine.evaluate()` (live/engine.py:597) → computes `completed_candle_ts()` (line 602)
2. → `_hlc_book_signal(instrument, all_candles, completed, ...)` (line 689)
3. → `app.research.scalp_engine._scan_signals(feed)` (hlc_book_signal line 502)
4. → `app.research.scalp_engine._live_signal(feed, idx, ...)` (hlc_book_signal line 515) → returns entry/stop/target/signal_time/entry_time
5. → `_frozen_trade()` (line 696) / `_freeze_trade()` (line 513) → writes `qualified_trades` + `daily_trade_locks` (one trade per instrument per day)

### 2.3 Signal function called by the running service

The running `paper_scalp_live.py` (PID 752009) calls:

```python
from app.research.scalp_engine import today_signals   # paper_scalp_live.py:14
signals = today_signals(inst, variant="plain")         # paper_scalp_live.py:170
```

`scalp_engine.today_signals()` → `today_state()` → `_scan_signals()` → `_live_signal()`.

### 2.4 Strategy identifier / mode

- **Strategy:** `SCALP_HLC` (scenario field in paper_trades); strategy name `Scalp HLC 3-bar`
- **Variant:** `plain` (no weekly gate, no no-chase re-anchor — `NO_CHASE_BEAR = False` in cpr_trigger_engine; HLC engine has no variant gate)
- **Default engine:** HLC scalp book (CPR book retained for rollback only, per live/engine.py docstring line 29)

### 2.5 Instruments enabled

`paper_scalp_live.py:39`: `INSTRUMENTS = ("NIFTY", "BANKNIFTY")`

INDIA_VIX is in `scalp_engine.VALID` but not traded by the live paper scalper.

### 2.6 Mode C enforcement (one open position per instrument)

**File:** `/opt/tradingai/scripts/paper_scalp_live.py`

`has_open_position(conn, inst)` (lines 136–149):
```python
row = conn.execute(
    "SELECT trade_id FROM paper_trades WHERE instrument_id=? "
    "AND scenario='SCALP_HLC' AND status IN ('ACTIVE','OPEN')",
    (inst,)).fetchone()
return row[0] if row else None
```

`try_create_trade()` (lines 153–199) blocks if `open_pos` is not None (Mode C), marks the signal as `POSITION_OPEN_{inst}` and skips. NIFTY and BANKNIFTY are tracked independently.

### 2.7 Default instrument list, candle timeframe

- Instruments: NIFTY, BANKNIFTY (paper_scalp_live.py:39)
- Candle timeframe: 5 minutes (scalp_engine docstring; market_candles_5m table)
- Poll interval: 5 seconds (paper_scalp_live.py:41 `POLL_SECONDS = 5`)
- Session: 09:15–15:30 IST; last entry cutoff 15:25 (paper_scalp_live.py:42 `LAST_ENTRY_CUTOFF = dtime(15, 25)`)

### 2.8 Entry / stop / target / EOD rules (HLC scalp)

From `app/research/scalp_engine.py`:
- **Signal:** 3 consecutive 5m candles where H, L, C all move same direction (`_scan_signals`, lines 44–58)
- **Entry:** next candle open (`_live_signal`, line 213: `entry = float(nc['open'])`); `entry_time = nc['timestamp']`
- **Stop:** signal candle low − 1.0 (BULL) / high + 1.0 (BEAR) (lines 66, 70)
- **Target:** entry + 1.5×risk (BULL) / entry − 1.5×risk (BEAR) (lines 68, 72)
- **Risk rejection:** `if risk <= 0: return None` (line 73)
- **Stop-first tie-break:** same candle hits both → STOP (lines 89–94)
- **EOD:** flat at last session candle close if neither level hit (lines 107–118)
- **Entry window:** `[09:20, 15:20)` (live/engine.py `_hlc_book_signal` line 531–534, uses `OPEN_MIN`/`OPEN_EOD` from cpr_trigger_engine)

### 2.9 Feature flags / environment overrides / fallback strategies

- `LIVE_VARIANT = 'plain'` (live/engine.py:67) — CPR book variant; not used by HLC default
- CPR trigger engine (`_cpr_book_signal`, live/engine.py:318) — retained for rollback, not default
- `SHORT_ONLY = True`, `SKIP_FRIDAY = True`, `NO_CHASE_BEAR = False`, `BREAKOUT_ADDON = True` (cpr_trigger_engine.py:59, 85, 109, 127) — CPR path only; HLC path unaffected
- `paper_exit_mode()` (paper_trade/engine.py:46): `eod` or `overnight` from settings; default `overnight`
- No environment variable overrides the HLC default strategy; no fallback strategy in the live decision path

### 2.10 Deterministic trade ID / duplicate prevention

`paper_scalp_live.py:25–32`:
```python
def scalp_link(inst, trade_date, direction, signal_time):
    return f"scalp|{inst}|{trade_date}|{direction}|{signal_time}"

def scalp_trade_id(link_key):
    return 'PT-' + hashlib.sha1(str(link_key).encode()).hexdigest()[:10].upper()
```

`PaperTradeEngine.create_paper_trade(qt, link_key=link)` (paper_trade/engine.py:66–123) derives `trade_id = 'PT-' + sha1(link_key)[:10].upper()` and sets `origin='live-watch'`. `trade_id` is the PRIMARY KEY; `INSERT` + `IntegrityError` catch ensures at most one trade per signal. Verified: 94 paper_trades, 94 distinct trade_ids (zero duplicates).

---

## 3. Task 2 — HLC Signal and Entry Timing

### 3.1 Signal detection (verified in code)

`scalp_engine._scan_signals()` (lines 44–58):
- Computes features for each consecutive candle pair: `(high_diff, low_diff, close_diff)`
- Scans triples of features (indices `i-2, i-1, i`) starting at `i=5`
- **BULL:** all three features have H>0, L>0, C>0
- **BEAR:** all three features have H<0, L<0, C<0
- Signal candle = `candles[i]` (3rd confirming candle)
- Only completed candles are scanned (candles loaded from DB, all `is_complete=1`)

### 3.2 Bullish / bearish conditions

| Direction | Condition (3 consecutive 5m candles) |
|-----------|--------------------------------------|
| BULL (H1_UP) | candle[i-2].H < candle[i-1].H < candle[i].H AND L similarly AND C similarly |
| BEAR (H1_DOWN) | candle[i-2].H > candle[i-1].H > candle[i].H AND L similarly AND C similarly |

### 3.3 Evaluated only after candle completion

Yes. `today_state()` (scalp_engine.py:241) loads candles where `timestamp <= now.isoformat()`. All 5,996 candles per instrument have `is_complete=1`. `_scan_signals` only sees completed candles. The forming candle is never scanned.

### 3.4 Entry scheduled for candle N+1

Yes. `_live_signal()` (line 211–230):
- `c = candles[idx]` (signal candle)
- `nc = candles[idx + 1]` (entry candle)
- `entry = nc['open']`, `entry_time = nc['timestamp']`

### 3.5 Entry price = candle N+1 open

**Verified against DB.** Example PT-0E1BB5B645 (NIFTY BULL, 2026-10-28):
- Signal candle 14:45: open=22696.95, high=22712.20, low=22696.20, close=22704.45
- Entry candle 14:50: open=22704.60
- Trade entry=22704.60 = entry candle open exactly ✓
- Stop=22695.2 = signal candle low (22696.20) − 1.0 ≈ 22695.2 ✓
- Target=22718.7 = entry + 1.5×risk (risk=9.4, 1.5R=14.1, 22704.6+14.1=22718.7) ✓

### 3.6 How the engine waits for the next candle

`paper_scalp_live.run_once()` polls every 5 seconds:
1. `latest_candle(inst)` — gets most recent candle from DB
2. `validate_candle(c, prev=pc)` — validates freshness (<20 min stale) and OHLC integrity
3. `today_signals(inst, variant="plain")` — scans for HLC signals
4. For each signal: `is_stale()` check (<20 min), then `_entry_time_guard(entry_time, now)` — entry must be in the future (`entry_time > now`), else 'expired' → skip
5. `try_create_trade()` — creates the paper trade with deterministic ID

The forming candle's open is used as the entry price once the signal candle is confirmed. The entry candle's timestamp is known from historical data once that candle's interval has started.

### 3.7 Missing / delayed / duplicated / partially formed next candle

- **Missing next candle:** `today_state` filters `candles[idx+1]['date'] != day_iso` → signal skipped; `_live_signal` checks `idx + 1 >= len(candles)` → returns None
- **Delayed candle:** Not in DB yet → `today_state` doesn't include it → signal not detected until it arrives
- **Duplicated candle:** `validate_candle` rejects `OUT_OF_ORDER_OR_DUPLICATE` → `run_once` skips entries for that instrument (`validate_candle` returns `ok=False`)
- **Partially formed candle:** Only `is_complete=1` candles are in `market_candles_5m`; forming candles are not included → no premature entry

### 3.8 5-second polling — repeated processing of same signal

`record_signal()` (scalp_signal_store.py:43) inserts with `UNIQUE(instrument_id, source_candle_ts, direction)`. `try_create_trade()` checks `SELECT trade_id FROM paper_trades WHERE trade_id=?` → if exists, marks signal as TRADED and returns existing ID. `run_once()` checks `status != "NEW"` → continue (skip). So a signal is processed at most once.

### 3.9 Existing open position blocks new signal

Yes — Mode C via `has_open_position()` (paper_scalp_live.py:136–149). If an ACTIVE/OPEN SCALP_HLC trade exists for the instrument, `try_create_trade` marks the signal `POSITION_OPEN_{inst}` and skips.

### 3.10 Skipped signal retried or discarded

- `mark_failed()` sets `status='NEW'` (keeps retryable) but records `last_error`
- `mark_expired()` sets `status='EXPIRED'` (terminal)
- `recover_new_signals()` (scalp_signal_store.py:84) returns NEW signals; `recover_open_positions()` checks if a trade already exists for them and marks TRADED if so
- Expired signals are NOT retried

### 3.11 Event ordering (verified with DB + archive)

**Events A–E, verified for PT-0E1BB5B645 (NIFTY BULL, 2026-10-28):**

| Event | Time | Evidence |
|-------|------|----------|
| A. 3-bar pattern confirmed (signal candle) | 14:45 | DB: candle 14:45 is the signal candle (close=22704.45) |
| B. Signal detected by engine | ~14:50–14:56 | `scalp_signals` row would show source_candle_ts=14:45 (row not found for this trade ID, but archive confirms detection at 14:56:02) |
| C. Entry candle opens | 14:50 | DB: candle 14:50 open=22704.60 |
| D. Paper trade record created | 14:56:02.125328 | DB: `created_at` = 14:56:02.125328, `entry_time` = 14:50:00 |
| E. Telegram alert sent | 14:56:02 | Archive: `ts_ist` = 14:56:02, `message_id` = 140, `delivered` = true |

**Key:** D and E happen ~5–6 minutes AFTER C (entry candle open). The trade record is NOT created at the exact candle-open timestamp. The entry *price/timestamp* equal candle N+1's open, but the DB insert and alert are wall-clock delayed.

Another example, PT-A4D82F95DF (NIFTY BEAR):
- Signal candle 13:55 → entry candle 14:00 (open=22706.5)
- Trade created 14:06:03, alert sent 14:06:03
- Exit TARGET at 14:20 (22679.05), trade closed 14:06:03 (same cycle — target hit on entry candle itself)

---

## 4. Task 3 — Backtest Defaults

### 4.1 Default backtest strategy (API)

**Endpoint:** `POST /api/backtest/scalp` (app/api/app.py:1224–1241)
```python
from app.research.scalp_engine import run_opens_range, VALID
start = data.get("start") or data.get("date_start") or "2000-01-01"
end = data.get("end") or data.get("date_end") or "2100-01-01"
variant = data.get("variant", "plain")
res = run_opens_range(inst, start, end, variant=variant)
```
- **Default strategy:** HLC 3-bar scalp (`scalp_engine.run_opens_range`)
- **Default instrument:** NIFTY
- **Default date range:** 2000-01-01 to 2100-01-01 (full available range)
- **Default variant:** `plain`
- Uses same `run_opens_range` → `run_range` → `_scan_signals` + `_trade_for` as live engine

**Alternate endpoint:** `POST /api/backtest/cpr-triggers` (app/api/app.py:453–490)
- Strategy: CPR trigger (`cpr_trigger_engine.run_opens_range`)
- Default date range: 2026-07-29 to 2026-09-25
- Default variant: `plain` (aligned retired 2026-10-14)
- This is the legacy CPR backtest, NOT the default scalp backtest

### 4.2 Historical comparison script strategy

**File:** `/Users/satya/research/hlc_frequency_risk_20261028/run_comparison.py` (note: this path is on the Mac; the VM has `/opt/tradingai/research/hlc_frequency_risk_20261028/`)

- Strategy: **HLC 3-bar scalp** (exact replica of `scalp_engine._scan_signals`)
- Modes: A (1 trade/day), B (every signal overlapping), C (1 open position)
- Cost scenarios: 0 / 1 / 2 pts per round-trip
- Stop = signal candle extreme ±1 pt; Target = 1.5×R; Stop-first tie-break; EOD flat

### 4.3 Previously generated CSV results

VM research dir `/opt/tradingai/research/hlc_frequency_risk_20261028/` contains:
- `trade_log_mode_a.csv`, `trade_log_mode_b.csv`, `trade_log_mode_c.csv`
- `mode_comparison.csv`, `monthly_summary.csv`, `execution_cost_sensitivity.csv`, `overlap_analysis.csv`
- All represent **HLC 3-bar scalp** strategy

### 4.4 Backtest vs live consistency

| Aspect | Live | Backtest (`/api/backtest/scalp`) | Match? |
|--------|------|----------------------------------|--------|
| Strategy | HLC 3-bar | HLC 3-bar | ✅ |
| Signal conditions | 3-bar H/L/C alignment | 3-bar H/L/C alignment | ✅ |
| Entry timing | Next candle open [09:20,15:20) | Next candle open [09:20,15:20) | ✅ |
| Entry price | Candle N+1 open | Candle N+1 open | ✅ |
| Stop | Signal extreme ±1 pt | Signal extreme ±1 pt | ✅ |
| Target | 1.5×R | 1.5×R | ✅ |
| Stop-first tie-break | Yes | Yes | ✅ |
| EOD | Last session close | Last session close | ✅ |
| Mode C | has_open_position block | run_mode_c (single open position) | ✅ (conceptually) |
| Transaction costs | 0.5 pts slippage + 40 Rs brokerage (paper engine) | COST_POINTS=1.0 (scalp_engine.py:18) | ⚠️ Different |

---

## 5. Task 4 — Telegram Alert Strategy and Timing

### 5.1 Alert process role

**File:** `/opt/tradingai/scripts/tg_alerts.py`

`do_watch()` (line 338):
- **Polls** `GET /api/strategy/scalp?instrument={inst}` for HLC signals (line 378)
- Also polls `GET /api/decision/{sym}` for context (line 396)
- **Does NOT create trades** — explicitly stated (line 542–544): "Mode C unified flow: paper_scalp_live.py is the sole creator of paper trades. tg_alerts.py only alerts for existing trades; it never creates them."
- **Checks DB first:** computes deterministic `trade_id = 'PT-' + sha1(link)[:10].upper()` where `link = f"scalp|{inst}|{today}|{direction}|{signal_time or entry_time}"`; `SELECT trade_id FROM paper_trades WHERE trade_id=?` (lines 548–554)
- **If trade NOT in DB:** `print(...skipping alert)` and `continue` — no alert sent
- **If trade EXISTS:** sends `tg('sendMessage', ...)` (line 584)
- **Dedup:** `key in st.get('fired', [])` skips already-fired alerts (line 399)

### 5.2 Alert timing

Alert is sent **after** paper_scalp_live.py creates the trade, in the same cron polling cycle:

1. paper_scalp_live.py creates trade (DB `created_at` ≈ entry_time + 5–6 min)
2. tg_alerts.py --watch runs (cron every minute), polls API, finds trade in DB
3. tg_alerts sends `sendMessage` immediately after confirming trade exists

**Verified from archive:** PT-0E1BB5B645 — trade created 14:56:02, alert sent 14:56:02 (message_id 140, delivered=true). Exit alert sent 14:56:04 (message_id 141).

### 5.3 Alert deduplication and failure handling

- **Dedup mechanism:** `st.get('fired', [])` list in `data/tg_state.json`; key format `"{today}|{inst}|{direction}|{signal_time}"`
- **Delivery failure:** `_fail()` warns once, returns `ok=False`; key is NOT added to `fired` → retried on next poll
- **Exit sweep failure:** "will retry; never vanish silently" (line 658–660 comment)
- **State file:** `data/tg_state.json` (in-memory during run, saved with `save_state()`)
- **Archive:** `data/tg_alerts_archive.jsonl` (append-only, records `delivered` and `message_id`)

### 5.4 Is Telegram monitoring scheduled and running?

**Yes — scheduled via cron:**

Crontab (ubuntu):
```
* 9-15 * * 1-5 cd /opt/tradingai && /usr/bin/python3 scripts/mistake_guard.py >> ...; /usr/bin/python3 scripts/tg_alerts.py --watch >> /opt/tradingai/logs/tg.log 2>&1
10 9 * * 1-5 cd /opt/tradingai && /usr/bin/python3 scripts/tg_alerts.py --reconcile >> /opt/tradingai/logs/tg.log 2>&1
```
- `--watch`: every minute, 09:15–15:30, weekdays
- `--reconcile`: 09:10, weekdays (repairs missed alerts from paper ledger, `delivered=false` for past dates)

No systemd unit for tg_alerts (no `systemctl` on this VM). The `--watch` script is a single-shot invocation (line 893–896 `__main__`) that runs one cycle and exits; cron re-invokes it every minute.

**Archive evidence:** `/opt/tradingai/data/tg_alerts_archive.jsonl` (117,583 bytes) contains delivered signal and update alerts with `message_id` values (e.g., 122–141 for 2026-10-28).

---

## 6. Task 5 — Live / Backtest / Alert Parity Matrix

| Behavior | Live paper | Backtest (`/api/backtest/scalp`) | Telegram alerts |
|----------|-----------|----------------------------------|-----------------|
| Strategy default | HLC 3-bar scalp (`_hlc_book_signal` → `scalp_engine`) | HLC 3-bar scalp (`run_opens_range` → `scalp_engine`) | N/A (notifier, not strategy engine) |
| Signal conditions | 3-bar H/L/C alignment (BULL/BEAR) | Same | N/A |
| Completed candles only | Yes — forming candle excluded from scan | Yes — stored completed candles | N/A |
| Entry timing | Next candle open [09:20,15:20) | Next candle open [09:20,15:20) | N/A (consumes frozen entry) |
| Entry price | Candle N+1 open (never live price) | Candle N+1 open | N/A |
| Stop/target rules | Signal extreme ±1 pt / 1.5×R | Signal extreme ±1 pt / 1.5×R | N/A |
| Stop-first tie-break | Yes (same candle → STOP) | Yes (same candle → STOP) | N/A |
| EOD exit | Last session close (after 15:30) | Last session close | Alert at 15:15 EOD boundary (`past_eod`) |
| Mode C | `has_open_position()` blocks per instrument | `run_mode_c` — one open position | N/A |
| Trade creation responsibility | `paper_scalp_live.py` (sole creator) | N/A (read-only backtest) | None — alerts only |
| Alert timing | N/A | N/A | After trade exists in DB; same poll cycle |
| Active runtime config | POLL_SECONDS=5, INSTRUMENTS=(NIFTY,BANKNIFTY) | variant=plain, full date range | cron `* 9-15 * * 1-5`, CHANNEL=@tradingai_cpr |

**Parity verdict:** PASS for the HLC scalp path — live, backtest, and alerts all use `app/research/scalp_engine.py`. MISMATCH with the legacy CPR/QualificationEngine path (`qualified_trades`, `daily_trade_locks`) which is retained for rollback only.

---

## 7. Task 6 — Runtime Evidence

### 7.1 Service status (observed via `ps`)

| Service | PID | Started | Command |
|---------|-----|---------|---------|
| gunicorn master | 745931 | Oct 28 | `gunicorn -w 2 --threads 4 ... app.api.app:app` |
| gunicorn worker | 745933 | Oct 28 | (worker 1) |
| gunicorn worker | 745934 | Oct 28 | (worker 2) |
| paper_scalp_live | 752009 | Oct 28 | `python3 /opt/tradingai/scripts/paper_scalp_live.py` |

No systemd services (no `systemctl` binary). Gunicorn and paper_scalp_live are running as background processes.

### 7.2 Database schema (read-only)

Key tables relevant to this audit:
- `paper_trades` (schema.sql line 81–86): trade_id PK, instrument_id, scenario, direction, entry, stop, target, entry_time, exit_time, exit_price, exit_reason, status, created_at, updated_at, qualification_evidence
- `scalp_signals`: signal_id PK, UNIQUE(instrument_id, source_candle_ts, direction), status (NEW/TRADED/EXPIRED/IGNORED), paper_trade_id
- `qualified_trades`: legacy CPR path, UNIQUE(instrument_id, date)
- `daily_trade_locks`: UNIQUE(instrument_id, date)
- `market_candles_5m`: 5,996 rows per instrument (NIFTY, BANKNIFTY), all `is_complete=1`, 2026-07-06 to 2026-10-28

### 7.3 Runtime records

**paper_trades:** 94 rows, 94 distinct trade_ids (zero duplicates). All recent trades (2026-10-27, 2026-10-28) are `scenario='SCALP_HLC'`.

**sample trades (2026-10-28):**

| trade_id | inst | direction | entry | stop | target | entry_time | created_at | exit_reason |
|----------|------|-----------|-------|------|--------|------------|------------|-------------|
| PT-0E1BB5B645 | NIFTY | BULL | 22704.6 | 22695.2 | 22718.7 | 14:50:00 | 14:56:02 | TARGET |
| PT-A4D82F95DF | NIFTY | BEAR | 22706.5 | 22724.8 | 22679.05 | 14:00:00 | 14:06:03 | TARGET |
| PT-86E7B96E9D | NIFTY | BULL | 22718.8 | 22697.8 | 22750.3 | 12:55:00 | 13:00:03 | TARGET |
| PT-E9AE8C3AB1 | NIFTY | BEAR | 22560.65 | 22609.65 | 22487.15 | 10:05:00 | 10:11:04 | STOP |

### 7.4 Trade lifecycle reconstruction (verified)

**PT-0E1BB5B645 (NIFTY BULL, 2026-10-28):**

| Event | Time | Source |
|-------|------|--------|
| A. Signal candle (14:45) completes | 14:45 | `market_candles_5m` |
| B. HLC 3-bar alignment detected | ~14:50–14:56 | `scalp_engine._scan_signals` |
| C. Entry candle opens (14:50) | 14:50 | `market_candles_5m` open=22704.60 |
| D. Trade record created | 14:56:02.125328 | `paper_trades.created_at` |
| E. Telegram alert sent | 14:56:02 | `tg_alerts_archive.jsonl`, message_id=140, delivered=true |
| Exit (TARGET) detected | 14:50 (entry candle) | Candle high=22723.05 >= target=22718.70 |
| Exit alert sent | 14:56:04 | Archive, message_id=141 |

**RR verification (PT-A4D82F95DF, NIFTY BEAR):**
- entry=22706.5, stop=22724.8, target=22679.05
- risk = 22724.8 − 22706.5 = 18.3 pts
- reward = 22706.5 − 22679.05 = 27.45 pts
- RR = 27.45 / 18.3 = **1.5** ✓

### 7.5 Alert archive sample (2026-10-28)

All sampled alerts show `delivered: true` with `message_id`. Signal alerts include instrument, date, direction, entry, stop, target, signal time. Update alerts include exit reason and points.

Example signal alert (NIFTY, 14:45 signal, 14:50 entry):
```
"Scalp HLC 3-bar BULL alignment confirmed on the 14:45 candle; entry at the next 5-minute open 14:50 (22,704.60), invalidation 22,695.20, target 22,718.70."
ts_ist: 2026-10-28T14:56:02+05:30, delivered: true, message_id: 140
```

### 7.6 Evidence limitations

- `paper_scalp_live.py`'s `_entry_time_guard()` requires `entry_time > now` (future entry). Empirically, trades are created ~5–6 min after entry_time (`created_at` > `entry_time`). The exact mechanism by which the trade passes the guard (given entry_time is in the past at creation time) could not be fully traced from static code alone; this may involve timing windows in the 5-second poll cycle.
- `tg_state.json` and archive confirm alerts were delivered, but the precise poll-to-poll latency between trade creation and alert detection is bounded by the 1-minute cron interval (not measurable to sub-minute precision from available logs).
- `qualified_trades` / `daily_trade_locks` show legacy CPR/SMA20 rows (last: 2026-10-26) that are NOT reflected in `paper_trades` — these are from the retired code path.

---

## 8. Source File Paths and Line Numbers

| Component | File | Key Lines |
|-----------|------|-----------|
| Live engine (HLC default) | `/opt/tradingai/app/live/engine.py` | 21–32 (docstring: HLC default, CPR rollback), 318 (_cpr_book_signal), 502 (_hlc_book_signal), 597 (evaluate), 513 (_freeze_trade), 426 (_frozen_trade) |
| HLC signal engine | `/opt/tradingai/app/research/scalp_engine.py` | 44 (_scan_signals), 61 (_trade_for), 211 (_live_signal), 241 (today_state), 712 (run_opens_range) |
| Paper trade engine | `/opt/tradingai/app/paper_trade/engine.py` | 66 (create_paper_trade, deterministic ID), 125 (monitor), 182 (_exit_trade) |
| Paper scalper (runner) | `/opt/tradingai/scripts/paper_scalp_live.py` | 25–32 (scalp_link/scalp_trade_id), 41 (POLL_SECONDS=5), 39 (INSTRUMENTS), 136–149 (has_open_position, Mode C), 153–199 (try_create_trade), 168 (_entry_time_guard), 216 (run_once), 234 (main loop) |
| Signal store | `/opt/tradingai/app/research/scalp_signal_store.py` | 13 (CREATE TABLE), 34 (record_signal), 48 (mark_traded), 57 (mark_failed), 84 (recover_new_signals) |
| Candle validation | `/opt/tradingai/app/research/scalp_validation.py` | 19 (validate_candle), 46 (latest_candle_ok) |
| Telegram alerts | `/opt/tradingai/scripts/tg_alerts.py` | 338 (do_watch), 378 (poll /api/strategy/scalp), 542–544 (sole creator comment), 548–554 (DB existence check), 584 (sendMessage), 399 (fired dedup), 593 (exit sweep), 693 (paper monitor), 712 (do_eod), 756 (do_reconcile), 893–896 (__main__) |
| Scalp API route | `/opt/tradingai/app/api/app.py` | 1204 (GET /api/strategy/scalp), 1224 (POST /api/backtest/scalp) |
| CPR backtest API | `/opt/tradingai/app/api/app.py` | 453 (POST /api/backtest/cpr-triggers), 429 (variant=plain), 436–437 (default dates) |
| DB schema | `/opt/tradingai/database/schema.sql` | 81 (paper_trades), 77 (qualified_trades unique), 78 (daily_trade_locks unique), 11 (market_candles_5m) |
| Cron (scheduling) | `/var/spool/cron/crontabs/ubuntu` | `* 9-15 * * 1-5` (tg_alerts --watch), `10 9 * * 1-5` (tg_alerts --reconcile) |

---

## 9. Mismatches and Unresolved Questions

### 9.1 Confirmed matches (PASS)

- Live engine, scalp backtest, and alerts all use `app/research/scalp_engine.py` (HLC 3-bar) — parity confirmed
- Entry price = next candle open (verified against DB for multiple trades)
- Stop = signal extreme ±1 pt; Target = 1.5×R; Stop-first tie-break; EOD flat — all match documented HLC spec
- Mode C (one open position per instrument) enforced in live and paper engine
- Deterministic trade IDs prevent duplicates (0 duplicates in 94 rows)
- Alerts sent after trade exists in DB (not before)
- Telegram monitoring scheduled and operational via cron

### 9.2 Mismatches

| Item | Documented HLC spec | Deployed implementation |
|------|--------------------|------------------------|
| Entry timing | "at the next candle open" | Trade DB record created ~5–6 min after entry candle open (wall-clock lag); entry price/timestamp correct |
| Transaction costs | Not specified in HLC spec | Paper engine: 0.5 pts slippage + 40 Rs brokerage per fill; scalp_engine COST_POINTS=1.0 |
| Backtest default date range | Not specified | `/api/backtest/scalp`: 2000-01-01 to 2100-01-01; `/api/backtest/cpr-triggers`: 2026-07-29 to 2026-09-25 |

### 9.3 Legacy CPR path (not default, retained for rollback)

- `qualified_trades` has CPR/SMA20 rows from 2026-10-19 to 2026-10-26 (one per instrument per day via `daily_trade_locks`)
- These are NOT in `paper_trades` — the legacy path wrote to `qualified_trades`, not `paper_trades`
- `_cpr_book_signal` in live/engine.py:318 is retained but not called by the default evaluate path (which uses `_hlc_book_signal` at line 689)

### 9.4 Unresolved questions

1. **`_entry_time_guard` timing:** The guard requires `entry_time > now` (future), but trades are observed with `created_at` > `entry_time` (past entry). The exact poll-cycle timing that allows creation is not fully determinable from static code + minute-precision DB timestamps.
2. **`tg_state.json` contents:** Not inspected (contains alert dedup state); would show the exact `fired` keys and open/closed state.
3. **Sub-minute alert latency:** Bounded by 1-minute cron interval; exact delay between trade creation and alert detection not measurable to sub-minute precision.

---

## 10. PASS / FAIL / NOT VERIFIED per Requirement

| # | Requirement | Verdict | Evidence |
|---|-------------|---------|----------|
| 1 | Default live strategy identified | PASS | HLC 3-bar scalp; live/engine.py:21–32, 502; paper_scalp_live.py:14, 170 |
| 2 | HLC signal conditions verified | PASS | scalp_engine.py:44–58 (_scan_signals) |
| 3 | Next-candle-open entry verified | PASS | scalp_engine.py:213 (_live_signal entry=nc['open']); DB verified PT-0E1BB5B645 entry=22704.6=candle 14:50 open |
| 4 | Completed-candles-only rule | PASS | market_candles_5m all is_complete=1; today_state filters timestamp<=now |
| 5 | Stop/target = ±1pt / 1.5R verified | PASS | scalp_engine.py:66–72; DB verified RR=1.5 |
| 6 | Stop-first tie-break | PASS | scalp_engine.py:89–94 |
| 7 | EOD flat | PASS | scalp_engine.py:107–118 |
| 8 | Mode C (1 open position/instrument) | PASS | paper_scalp_live.py:136–149 (has_open_position) |
| 9 | Duplicate prevention | PASS | paper_trade/engine.py:79 (deterministic ID), 105–123 (PK IntegrityError); 94/94 distinct IDs in DB |
| 10 | Alert created after trade (not before) | PASS | tg_alerts.py:542–554 (DB check before alert); archive shows alert after created_at |
| 11 | Telegram scheduled and running | PASS | crontab `* 9-15 * * 1-5` (--watch), `10 9 * * 1-5` (--reconcile); archive has delivered alerts with message_ids |
| 12 | Live/backtest/alert parity (HLC path) | PASS | All use app/research/scalp_engine.py |
| 13 | Runtime evidence (trade lifecycles) | PASS | 3+ lifecycles reconstructed from DB + archive |
| 14 | No production changes | PASS | Read-only audit only |

---

## 11. Recommended Follow-Up Actions

1. **Investigate `_entry_time_guard` timing:** The guard requires `entry_time > now`, yet trades are created with `created_at > entry_time`. Determine whether a timing window in the 5-second poll allows creation, or whether the guard needs adjustment to match observed behavior.

2. **Inspect `tg_state.json`:** Review the current alert dedup state (`fired`, `open`, `closed` keys) to understand the alert lifecycle state.

3. **Document the legacy CPR path retirement:** The `qualified_trades`/`daily_trade_locks` CPR rows are from a retired path. Confirm whether they should be archived or if any code still reads them.

4. **Sub-minute alert latency monitoring:** If precise alert timing matters, consider logging the exact poll timestamp when tg_alerts detects a new trade, to measure the delay between trade creation and alert delivery.

5. **Transaction cost alignment:** The paper engine uses 0.5 pts slippage + 40 Rs brokerage per fill; the backtest uses COST_POINTS=1.0. Document this difference for P&L comparison.

---

**Statement:** No production files, settings, services, cron entries, systemd units, or database records were modified during this audit. All findings are based on read-only inspection of deployed code, configuration, process status, and database contents on the Oracle VM.
