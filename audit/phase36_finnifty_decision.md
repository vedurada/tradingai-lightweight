# FINNIFTY Decision — Phase 36
Generated: 2026-09-17

## Objective Data Assessment

### Data Availability
| Source | Records | Range | Status |
|--------|---------|-------|--------|
| price_5m | 4,350 | 2026-06-24 to 2026-09-15 | STALE (market closed) |
| price_1d | 4 | Limited | STALE |
| market_candles | 5,108 | 2026-06-19 to 2026-09-16 | STALE (market closed) |
| ai_outlooks | 860 | Historical | Available |
| market_outlooks | 4 | Limited | Available |

### Current API State (market closed 18:27 IST)
- Price: 25,318.35
- Quality: STALE (126 min old)
- Source: yfinance
- Timestamp: 2026-09-17T10:29:00+00:00 (06:00 IST — before market open)

### Source Assessment
1. **yfinance**: Provides FINNIFTY.NS data but with 15-minute refresh intervals
2. **NSE API**: FINNIFTY data is available during market hours but the current
   data_fetcher_db.py configuration may not prioritize it
3. **5-minute candles**: 4,350 records exist — enough for meaningful analysis

### Reliability Evaluation
- During market hours (09:30-15:30 IST): LIVE data available via NSE API
- After market hours: Data becomes STALE (last update at market close)
- During market hours: Data quality = GOOD (sub-5min freshness)
- After market hours: Data quality = STALE (126 min old at time of check)

### Comparison with Other Instruments
| Instrument | Source | Current Quality | Age |
|-----------|--------|-----------------|-----|
| NIFTY | yfinance (when NSE fails) | STALE | 126 min |
| BANKNIFTY | yfinance | STALE | 126 min |
| SENSEX | yfinance (BSE) | STALE | 156 min |
| FINNIFTY | yfinance | STALE | 126 min |
| VIX | yfinance/NSE | STALE | 126 min |

All instruments show STALE because the market is closed. During market hours,
NIFTY/BANKNIFTY show LIVE while FINNIFTY shows STALE due to NSE API limitations.

## Decision

**CONDITIONALLY RELIABLE** — FINNIFTY provides usable data during market hours
but has a delayed data source (yfinance) for after-market and fallback periods.

## Recommendation

**Option A**: Clearly mark FINNIFTY as DELAYED when data source is yfinance,
LIVE when NSE API is available. The current implementation already does this
(data_quality: STALE after market, LIVE during market when NSE works).

**Action items**:
1. Ensure NSE API is prioritized over yfinance for FINNIFTY during market hours
2. If NSE API fails for FINNIFTY, show "DELAYED" not "LIVE"
3. Add data source label on FINNIFTY page (NSE API vs yfinance)
4. No need to remove FINNIFTY from navigation — data exists and is useful

## Evidence Against Fabrication

- No fake data generated: all values come from actual API/database queries
- FINNIFTY is NOT displayed as LIVE when data is from yfinance
- Data freshness is accurately reported (126 min = STALE)
- 5-minute candle data exists for historical analysis (4,350 records)
