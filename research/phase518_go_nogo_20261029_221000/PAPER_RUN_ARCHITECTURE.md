# Phase 5.18 — Paper-Run Architecture (Design Only, Not Implemented)

## Process Isolation

- Separate process: paper_scalp_live.py (already runs independently)
- Separate systemd unit (proposed, not installed)
- Separate log files: paper_scalp_live.log
- Lock file prevents duplicate instances

## Data Isolation

- Read-only access to market_candles_5m (collector writes, paper reader)
- paper_trades table shared (both CPR and HLC trades)
- Separate scenario tag: SCALP_HLC vs CPR scenarios
- No separate database required

## Startup/Shutdown

- Startup: recover_open_positions(), recover_new_signals(), load_state()
- Shutdown: SIGTERM → process exits, lock released, state saved
- Restart: systemd Restart=on-failure, RestartSec=10

## Stale Data Handling

- validate_candle() rejects stale (>20 min)
- is_stale() checks timestamp age
- Entry guard rejects expired signals
- No trades from stale data

## Signal Expiry

- _entry_time_guard: 5-min window
- Cross-session rejection (proposed, not implemented)
- Duplicate prevention via UNIQUE constraint

## Max Trades Per Day

- Configurable via settings.json or env var
- Default: disabled (current behavior)
- Requires explicit opt-in

## API/Dashboard/Telegram

- All use same paper_trades table
- API endpoints read from same DB
- Telegram alerts tied to persisted trades
- No mode-specific changes needed

## Evidence Capture

- Save API responses as JSON
- Save logs
- Record DB row counts before/after
- Save signal/trade snapshots
