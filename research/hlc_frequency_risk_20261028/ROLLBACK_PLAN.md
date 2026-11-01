# HLC 3-Bar Scalp — Phase 2 Rollback Plan

**Repository:** /opt/tradingai (VM: ubuntu@129.159.224.81)
**Branch:** production-2026-10-01
**Commit:** 7da4b216960c257fef61760c66e5abd97e40086a
**Date:** 2026-10-28

## Files Modified

| File | Change |
|------|--------|
| app/live/engine.py | Added _hlc_book_signal(); evaluate() now calls _hlc_book_signal as default trigger; updated _frozen_trade_passes_gate() to skip CPR gates for HLC trades |
| app/research/scalp_engine.py | (Pre-existing dirty change) _trade_for returns stop/target keys; run_opens_range accepts stop_pct/target_pct; today_state returns all signals; _live_signal added |
| scripts/paper_scalp_live.py | Added has_open_position(); try_create_trade() checks for existing open position before creating (Mode C) |
| scripts/tg_alerts.py | --watch mode no longer creates paper trades; checks paper_trades table for existing trade by trade_id before alerting; added import hashlib |

## Files Created

| File | Purpose |
|------|---------|
| /etc/systemd/system/tradingai-paper-scalp-live.service | systemd service unit for paper_scalp_live.py |
| /opt/tradingai/research/hlc_frequency_risk_20261028/ | Research directory with backtest results, tests, reports |

## Rollback Steps

### Step 1: Stop and disable the paper_scalp_live service

bash
sudo systemctl stop tradingai-paper-scalp-live.service
sudo systemctl disable tradingai-paper-scalp-live.service
sudo rm /etc/systemd/system/tradingai-paper-scalp-live.service
sudo systemctl daemon-reload

### Step 2: Restore tg_alerts.py to original (re-enables trade creation in watch mode)

bash
cp /tmp/tg_alerts.py.orig /opt/tradingai/scripts/tg_alerts.py

### Step 3: Restore paper_scalp_live.py to original (removes Mode C position check)

bash
cp /tmp/paper_scalp_live.py.orig /opt/tradingai/scripts/paper_scalp_live.py

### Step 4: Restore app/live/engine.py to original (restores CPR as default trigger)

bash
git checkout -- app/live/engine.py

### Step 5: Restore app/research/scalp_engine.py to original

bash
git checkout -- app/research/scalp_engine.py

### Step 6: Verify rollback

bash
# Verify services
systemctl is-active tradingai-api.service
systemctl is-active tradingai-paper-scalp-live.service  # Should be inactive/failed

# Verify API is serving
curl -s https://tradingai.in/api/decision/nifty | head -c 200

# Verify git status shows only pre-existing dirty files
git status --short

## What Was NOT Modified (Preserved)

- All pre-existing dirty/untracked files in the working tree
- All existing trade records in paper_trades, qualified_trades, daily_trade_locks, scalp_signals
- All existing market data in market_candles_5m
- CPR trigger engine code (cpr_trigger_engine.py) - retained for rollback
- Legacy decision engine paths - preserved in code but not called by default
- No broker order placement, no real-money execution, no credential changes
- No database schema changes

## Verification After Rollback

1. tradingai-api.service should be active and serving /api/decision/nifty
2. tradingai-paper-scalp-live.service should be inactive
3. git status should show only pre-existing dirty files (no new changes from Phase 2)
4. No new rows in paper_trades with scenario=SCALP_HLC created by the new service
5. No new systemd services or cron jobs beyond what existed before Phase 2

## If Rollback Is Incomplete

If any files were not properly restored, manually edit them to remove the Phase 2 changes:

- app/live/engine.py: Change _hlc_book_signal call back to _cpr_book_signal in evaluate()
- scripts/paper_scalp_live.py: Remove has_open_position() function and its call in try_create_trade()
- scripts/tg_alerts.py: Re-add the PaperTradeEngine().create_paper_trade() call in do_watch()

