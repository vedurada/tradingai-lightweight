# Today Page Data Flow Analysis

## API Endpoints Called (11 endpoints)
1. `/api/market` - Prices, VIX, breadth
2. `/api/market-outlook?symbol=NIFTY` - AI outlook (expects `o.outlook` at top level)
3. `/api/key-levels?symbol=NIFTY` - Key levels
4. `/api/options/state/NIFTY` - Options data
5. `/api/breadth` - Market breadth
6. `/api/session-timeline` - Session status (MARKET OPEN/MARKET CLOSED/PRE_MARKET)
7. `/api/strategy/NIFTY` - Strategy recommendations
8. `/api/risk/NIFTY` - Risk data
9. `/api/market-evidence/NIFTY` - Evidence data
10. `/api/intraday-conditions?symbol=NIFTY` - Intraday conditions (may be N/A pre-market)
11. `/api/paper-trades/active` - Active paper trades

## Expected Response Format
- `market-outlook`: expects `{outlook: {bias.label, regime.primary, ...}}`
- `intraday-conditions`: expects `{no_trade: "..."}` or conditions
- All others: various data structures

## Pre-Market Behavior
- 22 "Loading" elements in HTML (expected)
- session-timeline should show PRE_MARKET
- AI outlook should show stale data or unavailable
- All endpoints return 200 with pre-market data
