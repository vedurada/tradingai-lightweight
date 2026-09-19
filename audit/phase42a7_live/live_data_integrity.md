# Live Data Integrity

Date: 2026-09-19 09:10 IST (Saturday, market CLOSED)

## Backup
- Path: /opt/tradingai/backups/tradingai_pre_42a7_finalfix_20260919_090520.db
- Size: 268M
- Integrity: OK

## Current Data State
| Table | Count | Latest Timestamp | State |
|-------|-------|-----------------|-------|
| price_5m | ~15960 | 2026-09-18T16:40:00 | STALE (Friday close) |
| market_regime | ~39124 | 2026-09-18T16:40:59 | STALE (Friday close) |
| ai_outlooks | 39148 | 2026-09-18T16:40:59 | STALE (Friday daily) |
| ai_outlooks_5m | 0 | N/A | NO LIVE GENERATION |
| market_snapshots_5m | 2 | 2026-09-18T04:25:00 | REPLAY-VERIFIED |
| market_evidence_5m | 1 | 2026-09-18T04:25:00 | REPLAY-VERIFIED |
| research_ai_call_log | 0 | N/A | NO LIVE CALLS |
| paper_trades | ~1188 | Friday or earlier | MARKET CLOSED |
| vix_data | 2578 | 2026-09-18T16:40:23 | STALE (Friday close) |
| trade_journal | ~1596 | N/A | POPULATED (Phase 9A) |
| price_1m | ~34370 | 2026-09-18 16:40:00 | STALE (11h old) |

## Key Findings
1. All data timestamps point to Friday 2026-09-18 — last trading day
2. No ai_outlooks_5m records exist — no live 5m AI generation on Saturday
3. No paper trades since Friday close
4. No research_ai_call_log entries — no live AI calls
5. Market snapshots and evidence from REPLAY-VERIFIED run, not live session
6. Database integrity: OK
7. No data corruption detected

## Monday Expected
1. Scheduler triggers monitor.py at 09:15 IST on Monday
2. First 5m candle completed → market snapshot created
3. Evidence inserted for NIFTY and BANKNIFTY
4. AI generation triggered if material change detected
5. First ai_outlooks_5m record created (if LLM available)
6. Paper trade created if setup qualifies (TRADE state)
7. Outcome evaluation at 5m/15m/30m/60m horizons
