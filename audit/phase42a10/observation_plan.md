# Phase 42A.10 Monday Observation Plan

## Observation Window: 09:15 — 10:00 IST

## Capture Points
| Time | IST | Capture |
|------|-----|---------|
| 09:15 | Market open | NIFTY/BANKNIFTY/SENSEX/FINNIFTY/VIX price, freshness, API response |
| 09:20 | 5m candle complete | market_snapshots_5m, market_evidence_5m for NIFTY/BANKNIFTY |
| 09:25 | 5m candle complete | Same + scenario state |
| 09:30 | Hourly | Full pipeline state, AI generation check |
| 09:40 | Continuous | Cache transition verification, AI provenance |
| 10:00 | Continuous | Full validation suite, resource check |

## Per-Capture Checklist (NIFTY + BANKNIFTY)
- [ ] Price from /api/price/{SYM}
- [ ] Price from /api/{SYM}
- [ ] 5m snapshot from market_snapshots_5m
- [ ] Evidence from market_evidence_5m
- [ ] Market state from /api/{SYM} (regime, trend, momentum)
- [ ] AI outlook from /api/ai-outlook/{SYM}
- [ ] Qualification from /api/{SYM} or /api/trade-qualification
- [ ] Options state from /api/options/state/{SYM}
- [ ] Scenario state from pre_market_scenarios
- [ ] Paper trade state from paper_trades
- [ ] Browser localStorage cache key state
- [ ] Browser visible price on page
- [ ] Freshness label (LIVE/LAST VALID/STALE)

## Resource Monitoring (every capture)
- [ ] RAM usage
- [ ] CPU load average
- [ ] Disk usage
- [ ] SQLite size
- [ ] gunicorn worker count
- [ ] monitor.py process running
- [ ] No runaway processes

## Defect Classification (if found)
A. Deployment defect
B. JavaScript defect
C. API defect
D. Data-source defect
E. Scheduler defect
F. Database defect
G. AI provider limitation
H. Expected market-closed/unavailable state

## If Defect Found
1. Backup database
2. Reproduce
3. Identify root cause
4. Minimal fix
5. Targeted test
6. Deploy
7. Revalidate