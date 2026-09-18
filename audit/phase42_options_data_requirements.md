# Phase 42 — Options Data Requirements

**Date**: 2026-09-17
**Phase 41**: FROZEN
**Known Limitation**: Historical option-chain data is insufficient for realistic options replay

---

## Problem

Current historical replay cannot realistically evaluate options strategy performance. The Phase 41 replay shows strategy=None for all trades, and option-chain data is unavailable historically.

## Required Option Chain Fields

For every 5-minute timestamp, the following should ideally be collected:

### Core Fields

| Field | Description | Priority |
|-------|-------------|----------|
| underlying spot | Current NIFTY/BANKNIFTY level | REQUIRED |
| expiry | Option expiry date | REQUIRED |
| strike | Strike price | REQUIRED |
| call LTP | Last traded price (call) | REQUIRED |
| put LTP | Last traded price (put) | REQUIRED |
| call bid | Best bid (call) | REQUIRED |
| call ask | Best ask (call) | REQUIRED |
| put bid | Best bid (put) | REQUIRED |
| put ask | Best ask (put) | REQUIRED |
| call volume | Volume (call) | REQUIRED |
| put volume | Volume (put) | REQUIRED |
| call OI | Open interest (call) | REQUIRED |
| put OI | Open interest (put) | REQUIRED |
| change in OI | Delta OI from previous | REQUIRED |
| IV | Implied volatility | REQUIRED |
| timestamp | Candle timestamp | REQUIRED |

### Derived Fields

| Field | Description | Priority |
|-------|-------------|----------|
| PCR (Put/Call Ratio | Put OI / Call OI | REQUIRED |
| ATM strike | At-the-money strike | REQUIRED |
| Moneyness | ITm/ATM/OTM classification | REQUIRED |
| Bid/ask spread | Ask - Bid per option | REQUIRED |
| Liquidity score | Volume + OI composite | REQUIRED |

## Expiry Requirements

### Weekly Expiry
- NIFTY weekly expiry: Every Thursday
- BANKNIFTY weekly expiry: Every Thursday
- Expiry day dynamics differ significantly from non-expiry
- Must track: T-1, T, T+1 behavior around expiry

### Monthly Expiry
- NIFTY monthly expiry: Last Thursday of month
- BANKNIFTY monthly expiry: Last Thursday of month
- Longer-term bias indicator

## Liquidity Requirements

For options strategy to be viable, the following must be verified:

### Per Strike
- Minimum daily volume: TBD (Phase 42 research)
- Minimum OI: TBD (Phase 42 research)
- Maximum bid/ask spread: TBD (Phase 42 research)

### Per Underlying
- NIFTY options: Verify sufficient liquidity for all strikes
- BANKNIFTY options: Verify sufficient liquidity for all strikes

## Slippage Considerations

Options have wider spreads than underlying:
- ATM options: Estimated 0.1-0.5% spread
- OTM options: Estimated 0.5-2.0% spread
- Deep OTM options: May be illiquid (avoid)

**Critical**: Do NOT assume LTP equals executable price for options.

## Data Source Assessment

Current data sources:
- NSE API: Real-time only, historical option chain may not be available
- yfinance: Limited Indian options historical data
- Backend options_state.py: Real-time processing only

**Research Question**: Are available historical data sources sufficient for an options backtest?

Answer: **NO**. Phase 42 options research requires either:
1. Historical NSE option chain data (need to source)
2. Synthetic option chain generation (not recommended for validation)
3. Skipping options research until data is available

## NOT IMPLEMENTED IN PHASE 42

- No option chain data will be collected
- No synthetic option data will be fabricated
- No options strategy will be tested
- No options backtest will be designed
- This is documentation only
