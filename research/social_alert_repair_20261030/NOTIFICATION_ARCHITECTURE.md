# Notification Architecture

## Date
2026-10-30

## Host
webserver / Linux / x86_64 / ubuntu / /opt/tradingai (Oracle VM)

## Overview
The live notification pipeline delivers TradingAI HLC 3-Bar signals to social-media channels (Telegram, Facebook) immediately after signal generation. The pipeline is implemented in `scripts/tg_alerts.py` and triggered by cron every minute during market hours.

## Components

### 1. Canonical HLC Engine (`app/research/scalp_engine.py`)
- `today_signals(instrument, variant='plain')` — generates HLC 3-bar alignment signals
- Returns signals with direction, entry, stop, target, entry_time, signal_time
- Signals with entry=None occur when the entry candle is not yet ingested (live signal on latest completed candle)

### 2. Signal Persistence (`scripts/paper_scalp_live.py`)
- `run_once()` — polls `today_signals()` for each instrument
- `record_signal()` — persists signal to `scalp_signals` SQLite table with status='NEW'
- `try_create_trade()` — creates paper trade in `paper_trades` table
- Signal and paper trade creation are independent paths

### 3. Notification Dispatcher (`scripts/tg_alerts.py`)
- `--watch` mode — polls `/api/strategy/scalp` API every minute (cron: `* 9-15 * * 1-5`)
- For each SIGNAL state: validates entry window, freshness, dedup
- Sends Telegram message via Bot API
- Logs to `data/tg_alerts_archive.jsonl` with delivered/message_id
- Best-effort Facebook post via `fb_post()` (never raises)

### 4. Notification Event Ledger (NEW)
- `notification_events` SQLite table — additive, no existing tables modified
- Tracks delivery status per signal_id + channel (PENDING, DELIVERED, FAILED)
- Stores external message_id on success, error description on failure

### 5. State Management (`data/tg_state.json`)
- `fired` — list of signal keys already alerted
- `open` — currently open trades awaiting exit
- `closed` — historical closed trades

### 6. Alerts Page (`scripts/build_alerts_page.py`)
- Regenerates `frontend/alerts.html` from the archive after each alert
- Also runs `build_rss.py` for RSS feed

## Data Flow

```
Live HLC signal (today_signals)
       ↓
Persist to scalp_signals (paper_scalp_live.py)
       ↓
Create paper trade (paper_scalp_live.py, independent path)
       ↓
--watch polls /api/strategy/scalp (tg_alerts.py, every 1 min)
       ↓
Validate: entry window, freshness, dedup via notification_events
       ↓
Persist PENDING notification_events record (NEW)
       ↓
Dispatch Telegram via Bot API sendMessage
       ↓
Becord DELIVERED with message_id, or FAILED with error
       ↓
Best-effort Facebook post (fb_post, never raises)
       ↓
Rebuild alerts.html + RSS
```

## Channels

| Channel | Secret File | API Endpoint | State File |
| --------|-------------|--------------|------------|
| Telegram | `.tg_env` (0600) | api.telegram.org/bot{token}/sendMessage | tg_state.json |
| Facebook | `.fb_env` (0600) | graph.facebook.com/v21.0/{page_id}/feed | fb_state.json |

## Safety Properties
- No broker order placement — paper trading only
- Telegram failures never crash the signal engine (try/except)
- Facebook failures never raise (best-effort, returns None)
- Duplicate suppression via notification_events UNIQUE(signal_id, channel)
- Service restart does not resend delivered signals (DELIVERED status check)
- Expired signals (>20 min) are not alerted
- Only SIGNAL state alerts; WATCH/NO_DATA states are ignored
