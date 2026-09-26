# Market Regime Research

## Regime Definitions

Regime classification is descriptive, not predictive. It categorizes historical
sessions based on observable price behavior.

| Regime | Definition |
|---|---|
| UPTREND | Price > MA20 AND positive momentum |
| DOWNTREND | Price < MA20 AND negative momentum |
| RANGE | Price near MA20 AND weak momentum |
| HIGH_VOLATILITY | Average daily range > 150 points |
| LOW_VOLATILITY | Average daily range < 50 points |

## Point-in-Time Methodology

Regime is classified using ONLY data available at classification time.
- Uses prior sessions only (no future data)
- MA20 is calculated from sessions available at classification time
- Momentum is based on price vs MA20 at classification time
- No session is classified using its eventual close

## Historical Period

**Period**: 2026-07-27 to 2026-09-18
**Sessions**: 39 per instrument (NIFTY, BANKNIFTY)
**Candles**: 2925 per instrument (5-minute)
**Data source**: yfinance

## Data Limitations

- yfinance 5-minute data limited to ~60 days historical depth
- Only ~39 sessions available for analysis
- Additional historical regimes could not be obtained from free source
- All sessions are within a single quarter (Q3 2026)

## NIFTY Regime Distribution

| Regime | Sessions | % of Total |
|---|---|---|
| DOWNTREND | 14 | 36% |
| HIGH_VOLATILITY | 14 | 36% |
| RANGE | 5 | 13% |
| UPTREND | 2 | 5% |
| INSUFFICIENT_DATA | 4 | 10% |

## BANKNIFTY Regime Distribution

| Regime | Sessions | % of Total |
|---|---|---|
| HIGH_VOLATILITY | 35 | 90% |
| INSUFFICIENT_DATA | 4 | 10% |

## Observations

1. The dataset contains predominantly HIGH_VOLATILITY sessions (especially BANKNIFTY)
2. NIFTY shows a mix of DOWNTREND and HIGH_VOLATILITY sessions
3. Only 5% of NIFTY sessions are UPTREND (contradicting Phase 4 assumption)
4. BANKNIFTY is almost entirely HIGH_VOLATILITY - regime-based differentiation is limited
5. The narrow window (39 sessions) limits statistical significance of regime analysis

## Scenario x Regime Research

Scenario performance should be analyzed separately by regime. However, with only
39 sessions, regime-level sample sizes are too small for meaningful conclusions.

This is a data limitation, not a methodology flaw.

## Data Quality Report

| Metric | NIFTY | BANKNIFTY |
|---|---|---|
| First candle | 2026-07-27T09:15 | 2026-07-27T09:15 |
| Last candle | 2026-09-18T15:25 | 2026-09-18T15:25 |
| Sessions | 39 | 39 |
| Candles | 2925 | 2925 |
| Expected candles/session | 76 | 76 |
| Missing candles | 0 | 0 |
| Duplicate candles | 0 | 0 |
| Quality status | PASS | PASS |
