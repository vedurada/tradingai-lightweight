# Data Integrity Findings

## P2: 1m data stale: 498m old (last: 2026-09-18 10:29:00)

- **severity**: P2
- **affected_layer**: 1-MINUTE
- **root_cause**: Market closed or data fetcher not running during validation period
- **status**: DOCUMENTED

## P1: market_evidence_5m table has 0 rows - evidence engine not producing output

- **severity**: P1
- **affected_layer**: MARKET EVIDENCE
- **root_cause**: Evidence generation pipeline may not be configured or is broken
- **status**: DOCUMENTED

## P2: Market snapshots stale: 8.3h old

- **severity**: P2
- **affected_layer**: MARKET SNAPSHOT
- **root_cause**: No new snapshots generated since market close
- **status**: EXPECTED (market closed)

