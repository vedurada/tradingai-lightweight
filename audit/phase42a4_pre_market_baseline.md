# Phase 42A.4 — Pre-Market Baseline

**Date**: 2026-09-18
**Phase 41**: FROZEN
**Market State**: PRE-MARKET (06:56 IST)
**Market Session Date**: 2026-09-18 (Friday)

---

## SESSION INFORMATION

| Item | Value |
|------|-------|
| Date | 2026-09-18 |
| Day of week | Friday |
| Market opens | 09:15 IST |
| Market closes | 15:30 IST |
| Baseline time | 06:56 IST (PRE-MARKET) |
| Git branch | html/h31-shell-core-pages |
| Git HEAD | 800c1b1 |
| Git status | Clean (0 modified) |
| Commits ahead | 1 (not pushed) |

## VM RESOURCES

| Resource | Value |
|----------|-------|
| VM hostname | webserver |
| OS | Ubuntu 22.04.5 LTS |
| Python | 3.10.12 |
| RAM total | 956 MB |
| RAM used | 291 MB |
| RAM available | 532 MB |
| Disk total | 45 GB |
| Disk used | 16 GB (35%) |
| Disk free | 30 GB |
| CPU cores | 2 |
| Gunicorn processes | 4 (3 workers + 1 transitional) |
| Nginx | Active |
| API health | 200 (degraded - pre-existing stale data) |

## DATABASE BASELINE

| Item | Value |
|------|-------|
| DB path | /opt/tradingai/database/tradingai.db |
| DB size | 176.78 MB (185,364,480 bytes) |
| WAL size | 6.7 MB (6,699,152 bytes) |
| DB tables | 58 |
| SQLite integrity | Not yet checked (will check post-session) |

## RESEARCH TABLES (PRE-MARKET)

| Table | Row Count | Expected |
|-------|-----------|----------|
| research_setup_identity | 0 | Correct (pre-market) |
| research_reentry_log | 0 | Correct |
| research_ai_call_log | 0 | Correct |
| research_outcome_tracking | 0 | Correct |
| research_data_health | 0 | Correct |
| research_manifest | 0 | Correct |

## MARKET DATA TABLES (PRE-MARKET)

| Table | Row Count | Notes |
|-------|-----------|-------|
| market_snapshots_5m | 0 | New Phase 42A table |
| market_evidence_5m | 0 | New Phase 42A table |
| ai_outlooks_5m | 0 | New Phase 42A table |
| paper_trades | 1,188 | Historical (unchanged) |
| price_5m | 17,400 | Historical (4,350 per symbol) |

## PAPER TRADES BASELINE

| Metric | Value |
|--------|-------|
| Total paper trades | 1,188 |
| NIFTY | 1,188 |
| BANKNIFTY | 0 |
| ACTIVE | 0 |
| COMPLETED | 0 (all historical) |

## MARKET DATA TIMESTAMPS (LAST AVAILABLE)

| Symbol | Latest 5m Timestamp | Count | Age |
|--------|-------------------|-------|-----|
| NIFTY | 2026-09-15 09:55:00 | 4,350 | ~3 days stale |
| BANKNIFTY | 2026-09-15 09:55:00 | 4,350 | ~3 days stale |
| SENSEX | 2026-09-15 09:55:00 | 4,350 | ~3 days stale |
| FINNIFTY | 2026-09-15 09:55:00 | 4,350 | ~3 days stale |
| NIFTY AI outlooks | 2026-09-17T15:31:23 | 26,144 | ~1 day stale |

## FROZEN FILE HASHES (VERIFIED UNCHANGED)

| File | SHA Hash | Changed |
|------|----------|---------|
| regime.py | 08f42f6346501734abe412bc96ca189e4fa0407a | NO |
| strategies.py | c4b0704b6e94172fb81159c082eb66badf375cb0 | NO |
| indicators.py | dd0209406c1ca224768f8252db2b852e20cc4656 | NO |
| options.py | 723e0ce411a3e730568fab78b20457b83e1e7673 | NO |
| outlook.py | 5e2e266988acdc9d218e65ddf0d06c29de621287 | NO |
| scenarios.py | 6694955f7bb808d82ad1fd7e319cb7bf2d5cba7a | NO |
| ai_outlook.py | 3632a06ec1e109115b1d21da4de3b37d62a68dd6 | NO |
| backtest.py | dd75a436c8d3b8bc371c466fc78bb12e1ec20692 | NO |

## EXPECTED SESSION METRICS

| Metric | Expected |
|--------|----------|
| Completed 5m candles | ~156 (09:15-15:30 IST) |
| Research setup records | Qualification dependent |
| AI calls | Trigger dependent |
| Paper trades | Qualification dependent |
| Outcome records | Maturation dependent |

## NO DEPLOYMENT NEEDED

All infrastructure verified operational. No deployment required for Phase 42A.4.

## HISTORICAL BASELINE PRESERVED

- Phase 41 paper trades: 1,188 (unchanged)
- All frozen file hashes: unchanged
- Historical data: intact
- No historical records modified
