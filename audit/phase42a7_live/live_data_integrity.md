# Live Data Integrity

Validation Date: 2026-09-19 09:15 IST (Saturday, market CLOSED)

## DB Backup
- Path: /opt/tradingai/backups/tradingai_pre_live_validation_20260919_091530.db
- Size: 269M
- Integrity: ok

## Current Data State
| Table | Count | Latest Timestamp | State |
|-------|-------|-----------------|-------|
| price_5m | 15960 | 2026-09-18T04:40:00 | STALE (Friday close) |
| market_regime | 39124 | 2026-09-18T16:40:59 | STALE (Friday close) |
| ai_outlooks | 39148 | 2026-09-18T16:40:59 | STALE (Friday daily) |
| ai_outlooks_5m | 0 | N/A | NO LIVE GENERATION |
| market_snapshots_5m | 2 | 2026-09-19T02:26:04Z | REPLAY-VERIFIED |
| market_evidence_5m | 1 | 2026-09-19T02:24:14Z | REPLAY-VERIFIED |
| research_ai_call_log | 0 | N/A | NO LIVE CALLS |
| paper_trades | 1188 | 2026-09-17T14:55:16Z | MARKET CLOSED |
| vix_data | 2578 | 2026-09-18T16:40:23 | STALE (Friday close) |
| trade_journal | 1596 | N/A | POPULATED (Phase 9A) |
| pre_market_scenarios | 0 | N/A | NO LIVE SCENARIOS |
| scenario_events | 0 | N/A | NO LIVE EVENTS |
| scenario_outcomes | 0 | N/A | NO LIVE OUTCOMES |

## Key Findings
1. All data timestamps point to Friday 2026-09-18 — last trading day
2. Zero data points after 2026-09-18 — no Saturday session data
3. No ai_outlooks_5m records — no live 5m AI generation on Saturday
4. No research_ai_call_log entries — no live AI calls
5. monitor.log = 0 bytes — monitor.py did NOT run (Saturday, cron Mon-Fri only)
6. market_snapshots_5m has 2 records from 02:22/02:26 UTC — replay-verified run, not live session
7. market_evidence_5m has 1 record from 02:24 UTC — replay-verified NIFTY evidence
8. Database integrity: OK
9. No data corruption detected
10. No fabricated data, no altered timestamps, no forced AI calls

## Monday Expected
1. monitor.py triggers at 09:15 IST on Monday via cron
2. First 5m candle completed → market snapshot created
3. Evidence inserted for NIFTY and BANKNIFTY
4. AI generation triggered if material change detected
5. First ai_outlooks_5m record created (if LLM available)
6. Paper trade created if setup qualifies (TRADE state)
7. Outcome evaluation at 5m/15m/30m/60m horizons
