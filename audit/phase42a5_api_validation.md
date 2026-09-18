# Phase 42A.5 API Validation

## API Endpoint Health Check

### Price Endpoints
| Endpoint | Status | Content | Latest |
|---|---|---|---|
| /api/price/NIFTY | 200 OK | STALE | 2026-09-17 15:31 (yesterday close) |
| /api/price/BANKNIFTY | 200 OK | STALE | 2026-09-17 15:31 (yesterday close) |
| /api/price/SENSEX | 200 OK | STALE | 2026-09-17 15:31 |
| /api/price/FINNIFTY | 200 OK | STALE | 2026-09-17 15:31 |
| /api/vix | 200 OK | LIVE | 2026-09-18 02:20 (fresh) |

### Market Data Endpoints
| Endpoint | Status | Content |
|---|---|---|
| /api/health | 200 OK | Degraded (outlook stale, price fresh) |
| /api/market | 200 OK | Has instruments with data |
| /api/NIFTY | 200 OK | Has ai_outlook, regime, strategies |
| /api/BANKNIFTY | 200 OK | Has ai_outlook, regime, strategies |
| /api/SENSEX | 200 OK | Data available |
| /api/FINNIFTY | 200 OK | Data available |
| /api/breadth | 200 OK | ADV=30, DEC=11, UNCH=6 |

### Evidence & Qualification
| Endpoint | Status | Content |
|---|---|---|
| /api/market-evidence/NIFTY | 200 OK | data_state: NO_DATA (pre-market) |
| /api/market-evidence/BANKNIFTY | 200 OK | data_state: NO_DATA (pre-market) |
| /api/trade-qualification | 500 | INTERNAL_ERROR (needs investigation) |

### Options
| Endpoint | Status | Content |
|---|---|---|
| /api/options/state/NIFTY | 500 | TypeError in ai_outlook.py (frozen) |
| /api/options/state/BANKNIFTY | 500 | TypeError in ai_outlook.py (frozen) |
| /api/options/state/FINNIFTY | 404 | Not available (EOD only) |

### Research
| Endpoint | Status | Content |
|---|---|---|
| /api/research/summary | 200 OK | Empty (pre-market) |
| /api/research/datasets | 200 OK | Empty (pre-market) |

### Paper Trades
| Endpoint | Status | Content |
|---|---|---|
| /api/paper-trades | 200 OK | Empty |
| /api/paper-trades/active | 200 OK | count: 0 |

### Data Files (New)
| Endpoint | Status | Size |
|---|---|---|
| /data/nifty.json | 200 OK | 7,132 bytes |
| /data/banknifty.json | 200 OK | 7,159 bytes |
| /data/sensex.json | 200 OK | 7,157 bytes |
| /data/finnifty.json | 200 OK | 4,547 bytes |
| /data/health.json | 200 OK | 268 bytes |
| /data/history.json | 200 OK | Exists |

## Schema Validation
- /api/market returns: {instruments: {NIFTY: {quote: {price, change, ...}}}} ✅ (matches frontend)
- /api/market-outlook returns: {outlook: {bias, confidence, ...}} ✅ (matches frontend)
- /api/key-levels returns: {supports: [...], resistances: [...]} ✅ (matches frontend)
- /data/*.json returns: {quote, indicators, regime, ai_outlook, ...} ✅ (matches api.js)

## Issues Found
1. /api/trade-qualification returns 500 - needs investigation (not frozen file issue)
2. /api/options/state/* returns 500 - ai_outlook.py frozen file bug (rule-based outlook TypeError)
3. /api/market-evidence returns NO_DATA - expected pre-market, will populate at market open
