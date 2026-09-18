# Phase 42A.4B — Scheduler

**Date**: 2026-09-18
**Phase 41**: FROZEN

---

## Existing Schedulers (VM Crontab)

| Job | Schedule | Purpose | Status |
|-----|----------|---------|--------|
| data_fetcher_db.py | * 9-15 * * 1-5 | Market data fetch | EXISTING |
| aggregate.py sweep | */15 9-15 * * 1-5 | 5m candle rollup | EXISTING |
| monitor.py | */5 9-15 * * 1-5 | Health checks | EXISTING → NOW INCLUDES RESEARCH |
| outlook.py | 30 9,35 9,0 19 * * 1-5 | AI outlook generation | EXISTING |
| pnl_tracker.py evaluate | */5 9-15 * * 1-5 | PnL tracking | EXISTING |
| pnl_tracker.py close | 20 15 * * 1-5 | Session close | EXISTING |
| self_heal.sh | */2 * * * * | Self-heal | EXISTING |
| nse_live_chain.py poll | */15 9-15 * * 1-5 | Options chain | EXISTING |
| cleanup.sh | 0 3 * * * | Cleanup | EXISTING |
| vm-backup.sh | 30 18 * * * | Backup | EXISTING |

## Research Collection Scheduler

**Trigger**: monitor.py (runs every 5 minutes during market hours)
**Mechanism**: run_research_collection() called at end of check_health()
**Market guard**: _is_market_hours() check (09:15-15:30 IST)
**No duplicate**: Only one trigger mechanism (monitor.py)
**No overlap**: Single process per cron trigger

## Duplicate Scheduler Check

Verified: No duplicate research collection triggers exist.
- No research-specific cron job
- No systemd timer for research
- monitor.py is the single authoritative trigger

## Bounded Execution

collect() is bounded:
- Time-bounded: Market hours only
- Resource-bounded: Single call per monitor run
- Failure isolation: Exception caught, logged, does not stop monitor
