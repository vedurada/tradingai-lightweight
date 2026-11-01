# Architecture and Data Flow

## Date
2026-10-30

## Host
webserver / Linux / x86_64 / ubuntu / /opt/tradingai (Oracle VM)

## Overview

The TradingAI HLC 3-Bar scalp trading pipeline consists of four main components that work together to generate signals, persist them, create paper trades, and send notifications.

## Components

### 1. Canonical HLC Engine (`app/research/scalp_engine.py`)

**Function:** `today_signals()` / `today_state()`

**Role:** Generates HLC 3-bar alignment signals from 5-minute candle data.

**Data flow:**
1. `_load_candles()` - Loads all completed 5-minute candles from `market_candles_5m` table for the given instrument
2. `_scan_signals()` - Detects 3-consecutive-bar alignment patterns (all H/L/C moving same direction)
3. `_live_signal()` - For each signal, computes entry from the NEXT candle (next-open execution)
   - If entry candle is ingested: `entry_time = entry_candle.timestamp`, `entry = entry_candle.open`
   - If entry candle NOT ingested: `entry_time = signal_time + 5min`, `entry = None`
4. Returns signal dict with: `signal_time`, `entry_time`, `entry`, `stop`, `target`, `direction`, `level`

**Key timestamp semantics:**
- `signal_time`: Signal candle timestamp (when strategy identifies the signal)
- `entry_time`: Entry candle timestamp (next candle open, 5 min after signal)
- These are NEVER the same - entry is always next-candle execution (strategy rule)

### 2. Signal Persistence (`scripts/paper_scalp_live.py`)

**Function:** `run_once()` → `record_signal()`

**Role:** Persists signals to `scalp_signals` table and creates paper trades.

**Data flow (per poll cycle, every 5 seconds):**
1. `latest_candle()` - Get latest candle for each instrument
2. `validate_candle()` - Validate candle integrity
3. `today_signals()` - Get all HLC signals from scalp engine
4. For each signal:
   a. If `entry` is None, resolve from market data provider
   b. `record_signal()` - Insert into `scalp_signals` table
   c. `_entry_time_guard()` - Check if entry candle still open
   d. `try_create_trade()` - Create paper trade in `paper_trades` table

**Signal-to-trade relationship:**
- `signal_id` = SHA1 hash of `instrument|date|direction|signal_time`
- `trade_id` = SHA1 hash of `instrument|date|direction|signal_time` (same as signal_id prefix)
- UNIQUE constraint on `paper_trades.trade_id` prevents duplicates
- UNIQUE constraint on `scalp_signals(instrument_id, source_candle_ts, direction)` prevents duplicate signals

### 3. Paper Trade Engine (`app/paper_trade/engine.py`)

**Function:** `PaperTradeEngine.create_paper_trade()`

**Role:** Persists paper trades with deterministic trade IDs.

**Trade ID generation:**
- `link_key = f"scalp|{inst}|{trade_date}|{direction}|{signal_time}"`
- `trade_id = 'PT-' + SHA1(link_key)[:10].upper()`

**Entry time persistence:**
- `entry_time = st.get("entry_time") or st.get("signal_time")`
- When entry candle is ingested: `entry_time` = entry candle timestamp
- When entry candle not ingested: `entry_time` = computed as signal_time + 5min (after fix)

### 4. Notification Dispatcher (`scripts/tg_alerts.py`)

**Function:** `do_watch()` (5-second polling loop)

**Role:** Sends Telegram and Facebook notifications for signals and trade exits.

**Data flow:**
1. Poll `/api/strategy/scalp` API for each instrument
2. For each signal: check if already delivered via `notification_events`
3. If not delivered: send Telegram message, record delivery
4. For exit: monitor open trades via `PaperTradeEngine.monitor()`, send exit notifications

## Sequence Diagram

```
Market Data Collector
       |
       v (stores completed 5m candles)
market_candles_5m table
       |
       v (reads completed candles)
paper_scalp_live.py (run_once, 5s poll)
       |
       v (today_signals -> _scan_signals -> _live_signal)
scalp_signals table (signal persisted)
       |
       v (try_create_trade)
paper_trades table (trade created with entry_time)
       |
       v (tg_alerts.py --watch, 5s poll)
notification_events table (ENTRY/EXIT, PENDING/DELIVERED/FAILED)
       |
       v (Telegram Bot API / Facebook Graph API)
Social Media Channels (@tradingai_cpr, Facebook Page)
```

## Timestamps

| Field | Source | Meaning |
|-------|--------|---------|
| `signal_time` | `scalp_engine._live_signal()` | Signal candle timestamp (strategy identification time) |
| `entry_time` | `scalp_engine._live_signal()` | Entry candle timestamp (next candle open, 5 min after signal) |
| `created_at` (scalp_signals) | `paper_scalp_live.run_once()` | Signal persistence time (IST) |
| `created_at` (paper_trades) | `paper_trade.engine.create_paper_trade()` | Trade creation time (IST) |
| `source_candle_ts` | `scalp_signals.source_candle_ts` | Same as `signal_time` |

**Important:** `entry_time` is ALWAYS 5 minutes after `signal_time` due to next-candle execution strategy rule. This is NOT a delay - it's the strategy design.
