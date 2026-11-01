# TRADINGAI — MONITORING RUNBOOK

## Purpose
Operate the unattended live market monitor.

## Inspect reports
- /opt/tradingai/monitoring/live_watch/logs/<run_id>.json

## Stop monitoring
- systemctl stop tradingai-live-monitor.service

## Disable schedule
- systemctl disable tradingai-live-monitor.timer

## Restore previous state
- No production strategy/config/DB changes made by monitor.

## Status
ACTIVE
