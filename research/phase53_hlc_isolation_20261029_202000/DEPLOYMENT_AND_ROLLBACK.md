# Phase 5.3 — Deployment and Rollback Procedures

## Pre-Deployment Status

| Item | Status |
|------|--------|
| HLC isolated in scalp_engine.py | YES (already isolated) |
| Unrelated strategies retired | NO (deferred due to dependencies) |
| Backup created | YES (timestamped directory) |
| Tests passed | YES (9/9 look-ahead tests) |
| Database integrity | OK |
| Broker execution disabled | YES |
| Rollback procedure documented | YES |

## Deployment Status

No deployment performed. This phase is a read-only audit. No code changes were made. No services were restarted.

## Rollback Status

No rollback needed. No changes were made that require rollback.

## If Deployment Were Needed

1. Commit or stash the dirty working tree before making changes
2. Add systemd unit for paper_scalp_live.py if live paper trading is desired
3. Add daily trade limit enforcement (1 trade/day per instrument) to scalp paper path
4. Document the backtest/live exit discrepancy (entry candle exclusion)
5. Keep CPR trigger engine as live trade decision engine unless owner approves switching
6. Verify all tests pass before deploying
7. Restart only the affected service after recording its current state
