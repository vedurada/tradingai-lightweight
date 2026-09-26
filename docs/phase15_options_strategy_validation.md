# Phase 15 — Options Strategy Validation & Trade Economics

## Strategy Definitions

Five approved spread strategies:

1. BULL_PUT_SPREAD: SELL higher-strike PUT + BUY lower-strike PUT (net credit)
2. BULL_CALL_SPREAD: BUY lower-strike CALL + SELL higher-strike CALL (net debit)
3. BEAR_CALL_SPREAD: SELL lower-strike CALL + BUY higher-strike CALL (net credit)
4. BEAR_PUT_SPREAD: BUY higher-strike PUT + SELL lower-strike PUT (net debit)
5. IRON_CONDOR: Four legs - buy lower put, sell higher put, sell lower call, buy higher call (net credit)

Naked short strangles/calls/puts are NOT allowed.

## Contract Model

Canonical fields per contract: instrument, underlying_price, timestamp, expiry, strike, option_type, last_price, bid, ask, volume, open_interest, change_in_open_interest, implied_volatility, source, source_timestamp, served_timestamp, data_age, freshness_state.

Required fields are strictly validated. Missing required fields = REJECT. Never silently substitute defaults.

## Expiry Selection

Deterministic: consume provider's available expiries. If required expiry unavailable -> NO_TRADE. Uses earliest available expiry as default rule. Do not hardcode expiry dates.

## Strike Selection

Deterministic: sorted by distance from underlying price. If required strikes unavailable -> NO_TRADE. Do not invent strikes absent from the chain.

## Liquidity Gates

- MIN_VOLUME = 1
- MIN_OPEN_INTEREST = 50
- MAX_SPREAD_WIDTH_PCT = 10% of strike
- If required liquidity info unavailable -> NO_TRADE

## Fill Model

- Credit strategies: prefer bid-side assumptions
- Debit strategies: prefer ask-side assumptions
- If bid/ask unavailable -> NO_TRADE
- Never silently use LTP as executable fill
- Do not claim broker-validated fills

## Risk/Reward Calculations

| Strategy | Max Risk | Max Reward | Breakeven |
|----------|----------|------------|-----------|
| Bull Put Spread | spread_width - credit | credit | sell_strike - credit |
| Bull Call Spread | debit | spread_width - debit | buy_strike + debit |
| Bear Call Spread | spread_width - credit | credit | sell_strike + credit |
| Bear Put Spread | debit | spread_width - debit | buy_strike - debit |
| Iron Condor | min(put_width, call_width) - credit | credit | lower/upper breakevens |

All calculations use round2 precision. Maximum risk/reward cannot be negative.

## Options Data Gate

Before constructing any strategy, validate:
- Chain available for correct instrument
- Correct timestamp
- Fresh data (within 300s)
- Required expiry available
- Required strikes available
- Required option types available
- Valid prices
- Liquidity requirements met
- No duplicate/malformed contracts

Failure states: OPTIONS_UNAVAILABLE, OPTIONS_NO_DATA, OPTIONS_RATE_LIMITED, OPTIONS_STALE, OPTIONS_MALFORMED, OPTIONS_PARTIAL_CHAIN, OPTIONS_MISSING_EXPIRY, OPTIONS_MISSING_STRIKE, OPTIONS_MISSING_BID_ASK, OPTIONS_INSUFFICIENT_LIQUIDITY

## Index Signal Gate

Options strategy construction must NOT independently generate an index trade. Sequence:
INDEX MARKET ENGINE -> SCENARIO -> QUALIFICATION -> OPTIONS DATA GATE -> OPTION STRATEGY

If index data is stale/unavailable -> NO_OPTIONS_TRADE.

## One-Trade/Day

MAX_QUALIFIED_TRADES_PER_DAY = 1 preserved. NIFTY and BANKNIFTY remain independent. The daily lock check occurs before the data gate.

## Current Live State

No validated live options source is accessible from the Oracle VM.
Live options qualification remains disabled by design.
API returns NO_TRADE with OPTIONS_DATA_UNAVAILABLE.

## Historical Options Data

No validated historical options dataset exists. No historical options performance claims are made. Existing index backtest results remain unchanged:
- NIFTY: 34 trades / +16.21R
- BANKNIFTY: 31 trades / +16.63R

## Tests

25 Phase 15 tests covering:
- All 5 strategies (valid/empty data)
- Contract validation (valid/invalid instrument, stale, missing fields)
- Expiry/strike selection (no data)
- Liquidity gates (insufficient volume/OI)
- Risk/reward economics for all strategies
- Iron condor 4-leg validation
- API endpoints (read-only, invalid instrument, unknown strategy)
- NIFTY/BANKNIFTY isolation
- Options data gate
- Index signal gate
- One-trade/day preservation
- Phase 13 baseline regression
- Phase 14 options API regression
- Approved strategies count

## Full Regression

Phases 10-15: 80/80 tests pass.
Baselines verified: NIFTY 34/+16.21R, BANKNIFTY 31/+16.63R.

## Remaining Limitations

1. No real options data source accessible
2. Historical options data unavailable
3. Underlying consistency not tested (requires both options and index data)
4. Partial chain detection not exercised
5. No live options trades possible
