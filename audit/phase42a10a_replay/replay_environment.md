# Phase 42A.10A Replay Environment

## Timestamp
UTC: 2026-09-19T05:00:00Z
IST: 2026-09-19 10:30 IST (Saturday, market CLOSED)

## VM Configuration
- Hostname: webserver
- RAM: 956MB (564MB available)
- CPU: 2
- Disk: 45GB
- Swap: 2GB

## Database
- Path: /opt/tradingai/database/tradingai.db
- Size: 269MB
- Integrity: ok
- Mode: WAL
- Tables: 41 (19 with data, 23 empty)

## Historical Data Available
- price_5m NIFTY: 1,588 candles, 21 trading days (Aug 20 — Sep 18, 2026)
- price_5m BANKNIFTY: 1,588 candles, 21 trading days
- price_5m SENSEX: 1,725 candles, 22 trading days
- price_5m FINNIFTY: 1,588 candles, 21 trading days
- price_1d NIFTY: 67 rows (Jun 19 — Sep 18)
- price_1d BANKNIFTY: 67 rows (Jun 19 — Sep 18)
- market_candles NIFTY 5m: 4,350 candles (Jun 24 — Sep 15, older data)
- indicators NIFTY: 39,124 rows (Sep 15 — Sep 18)
- vix_data: 2,578 rows (Sep 15 — Sep 18)

## Data Readiness Gate Assessment
- Spec requirement: 30+ trading days minimum, 60+ preferred
- price_5m has 21 trading days for NIFTY/BANKNIFTY
- BELOW 30 minimum — documented limitation
- price_1d has 67 trading days (daily only, not 5m)
- Replay will use available 21 days of price_5m data
- NO fabrication of missing data

## Production Tables Status
- market_snapshots_5m: 2 rows (minimal production snapshots)
- market_evidence_5m: 1 row (minimal production evidence)
- ai_outlooks_5m: 0 rows (AI_REPLAY=OFF)
- paper_trades: 1,188 rows (Sep 17 test data)

## Phase 42A.9 Assets Verified
All static JS/CSS assets on VM ✅
All pages HTTP 200 ✅
All APIs HTTP 200 ✅

## Replay Mode
AI_REPLAY = OFF (default)
No LLM calls during replay
Validate: snapshot → evidence → state → scenario → qualification
Verify AI input payload contains no future information