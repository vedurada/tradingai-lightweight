# AI Scheduler Validation

## Expected Scheduler Configuration
```text
Outlook scheduler (cron):
30 9 * * 1-5: outlook.py --symbol NIFTY/BANKNIFTY/FINNIFTY/SENSEX at 09:30 IST
35 19 * * 1-5: outlook.py --symbol NIFTY/BANKNIFTY/FINNIFTY/SENSEX at 19:35 IST
```

## Key Validation Points
- [ ] AI calls originate from backend scheduler (NOT browser)
- [ ] AI calls originate from backend scheduler (NOT API)
- [ ] NIFTY → NIFTY data (no hardcoded routing)
- [ ] BANKNIFTY → BANKNIFTY data
- [ ] FINNIFTY → FINNIFTY data
- [ ] SENSEX → SENSEX data

## AI Call Protection
- [ ] Minimum call interval respected
- [ ] Maximum session calls enforced
- [ ] Timeout configured
- [ ] Retry/backoff implemented
- [ ] Failure isolation working
- [ ] Material-change detector working (NOT called every refresh)

## Monitoring During Monday
- Check research_ai_call_log count increases during market hours
- Verify calls are NOT every page refresh
- Verify calls are NOT every 5m candle (only material changes)
- Check logs at /opt/tradingai/logs/outlook.log

## Current State
```text
research_ai_call_log: 0 rows (expected before Monday)
ai_outlooks_5m: 0 rows (expected before Monday live session)
ai_outlooks: 39148 rows (historical)
```

## Outlook Generator Log Path
/var/www/tradingai.in/html
