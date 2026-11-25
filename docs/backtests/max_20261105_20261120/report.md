# Historical scanner backtest (5m rule simulation)

> This report was generated before the `sma9_5min` identity was staged. Its
> `sma9` row is the rule-equivalent baseline for the new 5-minute-poll copy.

> **Not an exact 5-second paper replay for the seven 5s scanners.**
> mStock supplies 5-minute OHLCV, not historical 5-second quotes. Their
> live fills use sampled LTP; this report uses conservative proxies below.

## Assumptions

- Window: `2026-11-05` to `2026-11-20`
- Entry fill: signal candle open
- Exit fill: adverse 5m low for the ATR stop, ratcheted stop level for a trail hit
- ATM: CE/PE parity anchored by NIFTY futures, rounded to 50
- Spot OHLC for regime: reconstructed from CE/PE parity
- PnL: premium points only; no lot size, capital, target, or brokerage
- Broker: gateway identity `api` (mapped to mStock in this deployment)

## Results

| Scanner | Trades | Win % | Total pts | Avg pts | Max DD pts |
|---|---:|---:|---:|---:|---:|
| sma9 | 381 | 62.20 | 1252.08 | 3.29 | -106.73 |
| sma9_high | 32 | 62.50 | 96.50 | 3.02 | -62.09 |
| sma9_trail | 381 | 62.20 | 1252.08 | 3.29 | -106.73 |
| sma9_atr | 250 | 44.40 | -1506.57 | -6.03 | -1506.57 |
| sma9_5s_atr | 289 | 43.94 | -1817.03 | -6.29 | -1817.03 |
| sma9_1min_poll | 336 | 44.35 | -2074.78 | -6.17 | -2074.78 |

## Exit reasons

- sma9: `{"STOP_LOSS_5PCT": 144, "TRAIL_STOP_EXIT": 237}`
- sma9_high: `{"STOP_LOSS_5PCT": 12, "TRAIL_STOP_EXIT": 20}`
- sma9_trail: `{"STOP_LOSS_5PCT": 144, "TRAIL_STOP_EXIT": 237}`
- sma9_atr: `{"STOP_LOSS_ATR": 107, "TRAIL_STOP_EXIT": 143}`
- sma9_5s_atr: `{"STOP_LOSS_ATR": 123, "TRAIL_STOP_EXIT": 166}`
- sma9_1min_poll: `{"STOP_LOSS_ATR": 137, "TRAIL_STOP_EXIT": 199}`
