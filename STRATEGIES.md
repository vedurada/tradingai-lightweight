# TradingAI Strategies

## Strategy Categories

### BULLISH
- **Bull Put Spread**: Lower volatility, defined risk, sell lower strike put + buy further OTM put
- **Bull Call Spread**: Higher volatility, defined risk, buy lower strike call + sell further ITM call

### BEARISH
- **Bear Call Spread**: Lower volatility, defined risk, sell lower strike call + buy further ITM call
- **Bear Put Spread**: Higher volatility, defined risk, buy lower strike put + sell further OTM put

### RANGE
- **Iron Condor**: Theta decay, sell OTM call spread + sell OTM put spread

## Selection Logic
```
BULLISH direction + HIGH volatility → Bull Call Spread
BULLISH direction + NORMAL/LOW volatility → Bull Put Spread
BEARISH direction + HIGH volatility → Bear Put Spread
BEARISH direction + NORMAL/LOW volatility → Bear Call Spread
NEUTRAL → Iron Condor
```

## Risk Parameters
- Max risk per trade: 2% of capital
- Min reward:risk: 1.5:1
- Max holding time: 4 hours
- Max qualified trades per day: 1

## Options Requirements
For a trade to qualify, options data must include:
- Strike price, option type, last price
- Bid/ask spread, volume, open interest
- Expiry date
- Implied volatility

If any critical data is unavailable: NO_TRADE.
