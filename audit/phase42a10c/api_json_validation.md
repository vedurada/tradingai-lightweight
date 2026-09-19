# API / JSON Validation

## Required Endpoints (all must return 200 with valid data)
```text
/api/market
/api/price/NIFTY
/api/price/BANKNIFTY
/api/price/SENSEX
/api/price/FINNIFTY
/api/vix
/api/NIFTY
/api/BANKNIFTY
/api/SENSEX
/api/FINNIFTY
/api/market-outlook?symbol=NIFTY
/api/market-outlook?symbol=BANKNIFTY
/api/key-levels?symbol=NIFTY
/api/intraday-conditions?symbol=NIFTY
/api/risk/NIFTY
/api/options/state/NIFTY
/api/options/state/BANKNIFTY
/api/maxpain/NIFTY
/api/breadth
/api/pcr
/api/oi-top?symbol=NIFTY
/api/expected-move/NIFTY
/api/session-timeline
/api/market-evidence/NIFTY
/api/trade-qualification (POST)
/api/paper-trades/active
/api/trade-setup/NIFTY (GET)
/api/research
/api/summary
/api/quote/track/NIFTY
/api/quote/telemetry/NIFTY
/api/walkforward/NIFTY/2026-09-01/2026-09-21
/api/evidence/NIFTY/2026-09-18
```

## JSON → DOM Chain
```text
DATABASE → BACKEND → API → JSON → JAVASCRIPT → DOM
```

## Validation Points
- [ ] All endpoints return valid JSON
- [ ] No 500 errors during market hours
- [ ] Timestamp consistency between API and DOM
- [ ] Symbol consistency between API and DOM
- [ ] Price consistency between API and DOM
- [ ] VIX consistency between API and DOM
- [ ] AI provenance consistency
- [ ] Scenario state consistency
- [ ] Qualification state consistency

## Current Verification
