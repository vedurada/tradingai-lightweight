# Phase 5.8 — Service and Lifecycle Design

## Current Invocation

`paper_scalp_live.py` currently runs as a background process:
- PID 806096, 806158 (2 instances)
- Started manually (no systemd unit enabled)
- Lock file: `/opt/tradingai/logs/paper_scalp_live.lock` (fcntl)
- Poll interval: 5 seconds
- State file: `/opt/tradingai/logs/paper_scalp_live.state.json`

## Proposed Service Lifecycle (Design Only, Not Implemented)

### Systemd Unit (Proposed)

```ini
[Unit]
Description=TradingAI HLC Paper Trade Live Service
After=network-online.target tradingai-market-data.service
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=/opt/tradingai
ExecStart=/usr/bin/python3 /opt/tradingai/scripts/paper_scalp_live.py
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=tradingai-paper-scalp-live
Environment=PYTHONPATH=/opt/tradingai

[Install]
WantedBy=multi-user.target
```

### Duplicate-Process Prevention

- Current: `fcntl.flock(LOCK_EX | LOCK_NB)` on lock file
- Proposed: Same mechanism, retained in systemd unit
- If a second instance starts, it exits immediately with message "another paper_scalp_live instance is already running"

### Startup Behavior

1. Acquire file lock
2. Print startup message
3. `recover_open_positions()` — load open trades from DB
4. `recover_new_signals()` — mark signals with existing trades as TRADED
5. Load state from state file
6. Enter main loop (poll every 5s during market hours)

### Shutdown Behavior

1. SIGTERM → Python default handler → process exits
2. Lock file released automatically
3. State file saved on last successful cycle
4. Open positions remain in DB (managed on next startup)

### Restart and Retry Behavior

- On crash: systemd restarts after 10s (RestartSec=10)
- On DB lock: retry on next poll cycle (5s)
- On provider failure: skip entry, retry next cycle
- On stale data: skip entries, log warning

### Database-Path Protection

- `get_conn()` returns production DB by default
- No database-path override in current code
- Test isolation requires monkeypatching (as done in Phase 5.7)
- Proposed: add `TRADINGAI_DB_PATH` env var for test isolation (not implemented)

### Idempotent Signal Processing

- `scalp_signals` table has UNIQUE constraint on `(instrument_id, source_candle_ts, direction)`
- `record_signal()` returns existing signal_id on duplicate
- `create_paper_trade()` uses deterministic trade_id (SHA-1 of link_key)
- `trade_id` is PRIMARY KEY in `paper_trades`

### Existing Open-Position Monitoring

- `PaperTradeEngine.monitor(inst)` called every cycle
- Handles both scalp and CPR branches based on `scenario` field
- Scalp: 1.5% stop / 3% target
- CPR: 0.5% stop / 2% target
- Exit evaluation uses market_candles_5m data

### Safe Handling of Stale Market Data

- `validate_candle()` rejects stale candles (>20 min)
- `is_stale()` checks timestamp age
- Entry-time guard rejects expired signals
- No trades created from stale data

### Interaction with Collector Timer

- Collector runs every 5 minutes (timer)
- paper_scalp_live polls every 5 seconds
- On new candle: signal scan → entry resolution → guard → trade creation
- No direct dependency between collector and paper_scalp_live

### Notification Behavior When Telegram Unavailable

- `tg_alerts.py` runs via cron (every minute)
- If Telegram API unavailable: alert queued in `tg_state.json` (fired key not set)
- Retry on next cron run
- Trade creation is independent of alert delivery
- No trade is lost if alert fails
