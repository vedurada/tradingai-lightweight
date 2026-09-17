# Phase 41C — API Validation

**Date**: 2026-09-17
**Method**: HTTP requests against VM localhost:8000

---

## API Endpoint Validation

| Endpoint | Method | Status | Content-Type | Schema Check | Notes |
|----------|--------|--------|-------------|-------------|-------|
| /api/health | GET | 200 | application/json | PASS | Overall: ok |
| /api/market | GET | 200 | application/json | PASS | 42 instruments, NIFTY+SENSEX+VIX included |
| /api/price/NIFTY | GET | 200 | application/json | PASS | Live price ~23118 |
| /api/market-outlook?symbol=NIFTY | GET | 200 | application/json | PASS | Outlook data |
| /api/market-evidence/NIFTY | GET | 200 | application/json | PASS | data_state=NO_DATA (no evidence in DB) |
| /api/market-evidence/BANKNIFTY | GET | 200 | application/json | PASS | data_state=NO_DATA |
| /api/trade-qualification | POST | 200 | application/json | PASS | Returns trade_status, checks, reason |
| /api/paper-trades | GET | 200 | application/json | PASS | 100 trades (replay data) |
| /api/paper-trades/active | GET | 200 | application/json | PASS | 0 active trades, returns active_trades field |
| /api/replay/NIFTY/2026-09-15 | GET | 200 | application/json | PASS | 75 snapshots |
| /api/walkforward/NIFTY/2026-08-08/2026-09-15 | GET | 200 | application/json | PASS | INSUFFICIENT_HISTORICAL_DATA (25 days) |
| /api/evidence/NIFTY/2026-09-15 | GET | 200 | application/json | PASS | data_state=NO_DATA |

## Schema Validation Details

### /api/trade-qualification POST

| Field | Present | Value |
|-------|---------|-------|
| success | Yes | true |
| data.trade_status | Yes | NO_TRADE (with incomplete input) |
| data.checks | Yes | 22 checks with passed/bool, detail/string |
| data.reason | Yes | NO_TRADE: ai_bias_valid, ... |
| data.instrument | Yes | NIFTY |
| data.direction | Yes | NEUTRAL |
| data.strategy | Yes | null (correct for NO_TRADE) |
| data.checks.ai_outlook_present | Yes | passed: false (correct - no outlook data) |
| data.checks.risk_calculable | Yes | passed: false (correct - no entry/stop) |
| data.checks.core_data_available | Yes | passed: false (correct - missing close, vwap, rsi) |

### /api/paper-trades GET

| Field | Present | Value |
|-------|---------|-------|
| success | Yes | true |
| data.count | Yes | 100 |
| data.trades | Yes | Array of 100 trades |
| data.trades[0].trade_id | Yes | string |
| data.trades[0].entry_price | Yes | number |
| data.trades[0].pnl | Yes | number |
| data.trades[0].status | Yes | string |

### /api/paper-trades/active GET

| Field | Present | Value |
|-------|---------|-------|
| success | Yes | true |
| data.count | Yes | 0 |
| data.active_trades | Yes | [] (empty array - correct for no active trades) |

**Field mapping verified**: Frontend uses `active_trades` which matches API response. (Previously found issue: frontend used `trades` which was wrong for this endpoint.)

### /api/market-evidence/NIFTY GET

| Field | Present | Value |
|-------|---------|-------|
| success | Yes | true |
| data.data_state | Yes | NO_DATA |
| data.evidence | Yes | null (correct - no evidence data) |
| data.instrument | Yes | NIFTY |
| data.engine_version | Yes | 1.0.0-phase40 |

**Frontend field path verified**: Frontend checks `ev.data.evidence` (not `ev.data.groups`). When data is available, engine returns `evidence.groups` with 6 groups (trend, momentum, structure, volatility, options, confirmation).

## Unavailable Behavior

| Endpoint | Empty Response | Malformed Response | Error Handling |
|----------|---------------|-------------------|----------------|
| trade-qualification | Returns NO_TRADE with checks | N/A | Returns error reason |
| paper-trades | count: 0, active_trades: [] | N/A | Frontend shows "No active paper trade" |
| market-evidence | data_state=NO_DATA, evidence=null | N/A | Frontend shows "Evidence unavailable" |
| replay | N/A (valid date) | N/A | N/A |

## Field Mapping Record (Phase 41C Requirement)

### Paper Trades: active_trades vs trades

| Source | Field Name | Frontend Usage | Verified |
|--------|-----------|----------------|----------|
| /api/paper-trades/active (API) | `active_trades` | today/index.html: `pt.data.active_trades` | YES |
| /api/paper-trades/active (API) | `count` | today/index.html: `pt.data.count` | YES |
| /api/paper-trades (API) | `trades` | nifty/banknifty/index: `pt.data.trades` | YES |
| /api/paper-trades (API) | `count` | nifty/banknifty/index: `pt.data.count` | YES |

### Evidence: evidence.groups

| Source | Field Path | Frontend Usage | Verified |
|--------|-----------|----------------|----------|
| /api/market-evidence/NIFTY (API) | `data.evidence` | today/index.html: `ev.data.evidence` | YES |
| /api/market-evidence/NIFTY (API) | `data.evidence.groups` | today/index.html: `evData.groups` | YES |
| Engine evaluate() | `groups` (6 groups) | trend, momentum, structure, volatility, options, confirmation | YES |
