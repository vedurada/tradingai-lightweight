# Phase 42A.5 Scheduler Validation

## Crontab State (After Fix)
- Lines: 34 (was 39 with duplicates)
- Syntax: Valid ✅
- Duplicate cleanup.sh entries: Removed ✅
- aggregate.py syntax error: Fixed ✅

## Job Schedule

| Component | Schedule | Command | Log | Status |
|---|---|---|---|---|
| data_fetcher_db.py | Every 1 min, 9-15 IST | `cd /opt/tradingai/backend && SKIP_LLM=1 python3 data_fetcher_db.py` | /opt/tradingai/logs/data.log | READY |
| aggregate.py | Every 15 min, 9-15 IST | `cd /opt/tradingai/backend && python3 aggregate.py sweep` | /opt/tradingai/logs/aggregate.log | READY |
| monitor.py | Every 5 min, 9-15 IST | `cd /opt/tradingai/backend && python3 monitor.py` | /opt/tradingai/logs/monitor.log | READY |
| generate_json.py | Every 15 min, 9-15 IST | `cd /opt/tradingai/backend && SKIP_LLM=1 python3 generate_json.py` | /opt/tradingai/logs/json.log | READY |
| self-heal.sh | Every 2 min | `/opt/tradingai/ops/self-heal.sh` | /opt/tradingai/logs/self-heal.log | ACTIVE (130KB) |
| nse_live_chain.py | Every 15 min, 9-15 IST | `cd /opt/tradingai/backend && python3 nse_live_chain.py poll` | /opt/tradingai/logs/livechain.log | READY |
| pnl_tracker.py | Every 5 min + close 15:20 | `cd /opt/tradingai/backend && python3 pnl_tracker.py` | /opt/tradingai/logs/pnl.log | READY |
| outlook.py | 09:30 + 19:00 IST | Multi-symbol with groq.env | /opt/tradingai/logs/outlook.log | READY |
| daily_page.py | 09:35 + 15:35 IST | Morning/close with webroot | /opt/tradingai/logs/daily.log | READY |
| bhavcopy.py | 18:35 + 08:30 IST | daily/holidays | /opt/tradingai/logs/bhav.log | READY |

## Systemd Services

| Service | Type | Status | Purpose |
|---|---|---|---|
| tradingai-api.service | simple | ACTIVE | Gunicorn API server |
| monitor.service | oneshot | INACTIVE (ran once, exit 0/1) | Health check + research collection |
| data-fetcher.service | oneshot | INACTIVE (not yet triggered) | Market data fetch |

## No Duplicate Schedulers
- One cron trigger per function ✅
- No duplicate market fetchers ✅
- No duplicate collectors ✅

## Last Execution Verification
- self-heal.sh: Running (130KB log) ✅
- Other services: Not yet triggered (pre-market, will run at 09:15 IST) ✅
