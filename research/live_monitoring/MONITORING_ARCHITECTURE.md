# TRADINGAI — UNATTENDED LIVE MARKET MONITORING AND PAPER-TRADE VALIDATION

## Phase
#TRADINGAI — UNATTENDED LIVE MARKET MONITORING AND PAPER-TRADE VALIDATION

## Objective
Set up persistent monitoring of TradingAI on the Oracle VM (paper-monitoring only).

## Monitor location
- Script: /opt/tradingai/monitoring/live_watch/live_monitor.py
- Logs: /opt/tradingai/monitoring/live_watch/logs/<run_id>.json
- Lock: /opt/tradingai/monitoring/live_watch/monitor.lock

## Schedule
- Interval: every 15 minutes
- Timezone: Asia/Kolkata
- Window: 09:15 IST - 15:30 IST, Mon-Fri, exchange holidays respected
- Mechanism: systemd timer (/etc/systemd/system/tradingai-live-monitor.timer) + service (/etc/systemd/system/tradingai-live-monitor.service)

## Status
INSTALLED
