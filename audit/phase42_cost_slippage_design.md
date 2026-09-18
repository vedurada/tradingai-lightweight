# Phase 42 — Cost and Slippage Design

**Date**: 2026-09-17
**Phase 41**: FROZEN
**Objective**: Define transaction cost and slippage assumptions for future backtests

---

## Principle

Do NOT hard-code values without verification. Current applicable costs must be sourced and documented before implementation. Test at multiple cost levels to determine whether an apparent edge survives realistic friction.

## Current Applicable Costs (TO BE SOURCED AND VERIFIED)

### Brokerage
| Category | Rate | Source | Status |
|----------|------|--------|--------|
| Equity intraday | ₹20 per executed order OR 0.03% (whichever is lower) | Broker agreement | TO BE VERIFIED |
| Options | Per-order fee from broker | Broker agreement | TO BE VERIFIED |

### Exchange Charges
| Category | Rate | Source | Status |
|----------|------|--------|--------|
| Equity intraday | 0.00325% of turnover | SEBI/Exchange | TO BE VERIFIED |
| Options | ₹20 per lot or per order | Exchange schedule | TO BE VERIFIED |

### STT (Securities Transaction Tax)
| Category | Rate | Source | Status |
|----------|------|--------|--------|
| Equity intraday | 0.025% on sale value | IT Act | TO BE VERIFIED |
| Options | 0.125% on option premium (sale) | IT Act | TO BE VERIFIED |

### GST
| Category | Rate | Source | Status |
|----------|------|--------|--------|
| On brokerage + exchange charges | 18% | GST Act | TO BE VERIFIED |

### SEBI Charges
| Category | Rate | Source | Status |
|----------|------|--------|--------|
| Transaction charges | ₹10 per crore turnover | SEBI | TO BE VERIFIED |

### Stamp Duty
| Category | Rate | Source | Status |
|----------|------|--------|--------|
| Contract note | 0.003% (₹5 per ₹10,000) | Stamp Act | TO BE VERIFIED |

### Stamp Duty (Nifty)
| Category | Rate | Source | Status |
|----------|------|--------|--------|
| Delivery | 0.003% on total trade value | Stamp Act | TO BE VERIFIED |

## Cost Scenarios for Future Testing

### Scenario 1: Zero-Cost (Theoretical)
- All costs = 0
- Purpose: Measure raw edge without friction
- Use: Upper bound on performance

### Scenario 2: Base-Cost (Realistic)
- All costs at current applicable rates (to be sourced)
- Purpose: Realistic performance estimate
- Use: Primary evaluation scenario

### Scenario 3: Stress-Cost (Pessimistic)
- All costs at upper bounds
- Slippage at 1 bps for underlying, 5 bps for options
- Purpose: Stress test
- Use: Conservative performance estimate

## Slippage Sensitivity Framework

### Underlying (NIFTY/BANKNIFTY)

| Level | Assumption | Basis |
|-------|-----------|-------|
| Zero | 0 bps | Theoretical only |
| Low | 0.25 bps | Liquid 5m candle, market order |
| Medium | 0.50 bps | Average market conditions |
| High | 1.00 bps | Thin market, urgency |

### Options

| Level | Assumption | Basis |
|-------|-----------|-------|
| Zero | 0 bps | Theoretical only |
| Low | 5 bps | ATM liquid option |
| Medium | 10 bps | Average option |
| High | 25 bps | Thin OTM option |

**Critical**: Do NOT assume LTP equals executable price. LTP is last traded, not available for market orders.

### Bid/Ask Spread (Options Only)

Where historical bid/ask data exists:
- Use mid-price for entry/exit calculation
- Apply half-spread as cost
- Document spread assumptions per option type

## Impact Analysis Design

For each cost scenario, compute:
- Net P&L after costs
- Profit factor after costs
- Win rate after costs
- Break-even point (minimum edge needed)
- Whether positive expectancy survives stress-cost scenario

## NOT IMPLEMENTED IN PHASE 42

- No cost calculations will be run on historical data
- No cost assumptions will be hard-coded
- No broker data will be fetched
- This is design documentation only
