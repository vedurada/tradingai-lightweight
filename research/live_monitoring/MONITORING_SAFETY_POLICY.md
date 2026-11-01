# TRADINGAI — MONITORING SAFETY POLICY

## Purpose
Unattended monitoring must fail safe; must not change production trading behavior.

## Allowed recovery
- retry transient market-data requests
- retry failed API reads
- recover monitor's own stale lock after proving no active process owns it
- restart monitor's own worker if safely configured
- rotate monitor logs
- suppress new paper entries when data/validation unhealthy
- resume observation after health checks recover

## Not allowed without human approval
- edit live strategy source
- change signal-generation rules
- change stop-loss/exit rules
- change HLC/CPR mode
- modify production DB schemas
- delete/reset trades
- change systemd production service config
- restart tradingai-api or Nginx
- change Telegram destinations
- deploy code
- place broker orders

## Defect handling
Capture error/logs; locate source; reproduce isolated; propose patch in staging; back up source; run tests on staged patch; record results/rollback; keep production unchanged; notify owner for approval.

## Status
ACTIVE
