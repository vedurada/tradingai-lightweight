# Phase 14 — Real Options Data Integration & Validation

## Provider Investigation

### Sources evaluated (2026-09-20, Oracle VM)

| Provider | Status | Details |
|----------|--------|---------|
| NSE (nseindia.com) | **BLOCKED** | Returns 403/000 from VM. API returns 404. |
| Yahoo Finance | **RATE-LIMITED** | Returns 429 for chart API. No Indian options data. |
| yfinance (^NSEI/^NSEBANK) | **BROKEN** | Returns 404 for index symbols.  returns empty tuple. |
| Premium APIs | **N/A** | No API keys configured. |

### Conclusion
**No reliable free options data source is accessible from the Oracle VM.** Per Phase 14 rules, documented honestly. No options data is fabricated.

## Data Layer Design

### Option tables (SQLite)
- : Canonical contract records (instrument, expiry, strike, option_type, prices, OI, IV, Greeks, data_state)
- : Chain-level snapshots (underlying, ATM strike/premium/IV, PCR, total OI/volume)
- : Shared SQLite cache (reuses Phase 11 provider_cache pattern)

### Freshness states
- : Data age < 300s (5 min)
- : Data age >= 300s
- : No timestamp available
- : Provider unreachable
- : HTTP 429
- : Invalid timestamp or impossible values
- : Incomplete chain

### Cache architecture
- Key:  (e.g., )
- TTL: 120 seconds (2 min)
- Shared: SQLite-backed, works across Gunicorn workers
- Age recomputed at serve time: Cached data can never masquerade as fresh

### Timestamp semantics
- All timestamps in Asia/Kolkata (+05:30)
- provider_timestamp: When the provider generated the data
- source_timestamp: When the data entered our system
- served_timestamp: When the API served the response
- data_age_seconds: served_timestamp - provider_timestamp

### Contract validation
- Valid instruments: NIFTY, BANKNIFTY
- Valid option types: CE, PE
- Validates: instrument, option_type, strike (>0), expiry, timestamp
- Rejects: missing/negative prices, duplicates, malformed records
- Never silently converts missing fields to zero

### API endpoint
- GET /api/options/<instrument> — read-only
- Returns: state, timestamp, freshness, data_age, provider, underlying, expiries, contracts, validation status
- Query params: expiry, type, strike_min, strike_max
- No strategy logic. No trade decisions.

### NIFTY/BANKNIFTY isolation
- Separate cache keys per instrument
- Separate DB records per instrument
- NIFTY failure does NOT substitute BANKNIFTY

## Current State

- **Options data: NOT AVAILABLE** — no provider accessible
- option_contracts: 0 rows
- option_snapshots: 0 rows
- API returns OPTIONS_NO_DATA / OPTIONS_UNAVAILABLE
- Frontend shows Options data layer section with freshness status
- **No fabricated options data exists**

## Historical Options Data

HISTORICAL OPTIONS DATA IS NOT AVAILABLE FROM THIS SOURCE.

Current option-chain data cannot be used for historical backtests. Do not populate historical option prices by copying today chain. Do not interpolate. Do not claim historical options performance.

## Tests

- tests/test_phase14.py: 31 tests covering contract validation, freshness, API, cache, failure modes, isolation, baseline regression

## Remaining Limitations

1. No options data source available
2. Historical options data unavailable
3. Underlying consistency not yet tested
4. Partial chain detection not exercised
5. Multi-worker cache sharing not tested under concurrent load
6. Options API returns empty contracts until provider connected

## Forward Path

Phase 15 can proceed when:
1. A reliable options data provider is established
2. Underlying consistency is validated
3. Real option contracts are flowing through the data layer
