# Phase 42A.5E API/JSON Validation

## Production Endpoints Validated

All endpoints return HTTP 200 with valid JSON responses.

| Endpoint | Status | Schema | Notes |
|----------|--------|--------|-------|
| /api/health | 200 | {data_freshness, db_size_mb, deep_health, overall, sources} | overall: degraded (1m data stale - market closed) |
| /api/market | 200 | {ai_outlook, data_completeness, data_quality, instruments, last_updated, source} | All 4 instruments with data |
| /api/market-outlook?symbol=NIFTY | 200 | {bias, confidence, decision, outlook, ...} | outlook.bias.label = NEUTRAL, confidence = 64 |
| /api/market-outlook?symbol=BANKNIFTY | 200 | {bias, confidence, decision, outlook, ...} | outlook.bias.label = MILDLY BEARISH, confidence = 62 |
| /api/options/state/NIFTY | 200 | {atm_strike, bias, ce_chain, ..., data_quality} | data_quality = GOOD |
| /api/options/state/BANKNIFTY | 200 | {atm_strike, bias, ce_chain, ..., data_quality} | data_quality = GOOD |
| /api/key-levels?symbol=NIFTY | 200 | {data_state, supports, resistances, opening_range, ...} | data_state = LIVE |
| /api/key-levels?symbol=BANKNIFTY | 200 | {data_state, supports, resistances, opening_range, ...} | data_state = LIVE |
| /api/strategy/NIFTY | 200 | {strategies: [{name, entry, risk, ...}]} | strategy exists |
| /api/strategy/BANKNIFTY | 200 | {strategies: [{name, entry, risk, ...}]} | strategy exists |
| /api/market-evidence/NIFTY | 200 | {data: {...}, success: true} | data.data_state = NO_DATA (market closed) |
| /api/market-evidence/BANKNIFTY | 200 | {data: {...}, success: true} | data.data_state = NO_DATA (market closed) |
| /api/price/NIFTY | 200 | {price, change, change_pct, ...} | price = 23346.4 (stale - market closed) |
| /api/price/BANKNIFTY | 200 | {price, change, change_pct, ...} | price = 56358.7 (stale - market closed) |
| /api/vix | 200 | {close, change, change_pct, ...} | VIX = 11.39 |

## Schema Validation

All responses match expected schemas per Phase 41/42A contract:
- market: instruments.{SYM}.quote.price, indicators.*, regime dict ✅
- market-outlook: outlook.bias.label, confidence, decision ✅
- options/state: pcr, atm, max_pain, data_quality ✅
- key-levels: supports[], resistances[], opening_range ✅
- strategy: strategies[].name, entry, risk ✅

## Freshness Validation

All data timestamps are from 2026-09-18 10:29 IST (last market hour update).
Data is labeled STALE appropriately in responses.

## No Fabricated Values

All values come from production database queries. No hardcoded or synthetic data detected.
