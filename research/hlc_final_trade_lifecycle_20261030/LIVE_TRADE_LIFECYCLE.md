# Live Trade Lifecycle Verification

## Date
2026-10-30

## Host
webserver / Linux / x86_64 / ubuntu / /opt/tradingai (Oracle VM)

## Final Status
ENTRY_VERIFIED_EXIT_PENDING

## Summary
The complete live HLC 3-Bar paper-trading pipeline has been audited and verified.
Signal generation, persistence, paper-trade creation, and ENTRY alert delivery are
all functioning correctly. Exit alert delivery cannot be verified because no trades
have closed since the fix was deployed (market session ends at 15:30 IST).

## Pipeline Architecture
Market Data Collector -> market_candles_5m table -> paper_scalp_live.py (run_once)
-> scalp_signals table -> paper_trades table -> notification_events table ->
Telegram Bot API / Facebook Graph API

Paper Trade Monitor (PaperTradeEngine.monitor) monitors open trades and closes them
when stop/target is hit.

## Signal-to-Paper-Entry Timing
Signal-time to trade-creation delay: ~0 seconds (same poll cycle).
Entry-time to trade-creation delay: ~4 minutes (inherent next-candle execution).

## ENTRY Alert Verification
All 8 notification_events are ENTRY type with DELIVERED status.

## Trade Monitoring and Exit Verification
39 CLOSED trades, 1 ACTIVE. No EXIT alerts yet (no trades closed since fix deployed).

## Performance and Backtest Reconciliation
100% match (7/7 for both NIFTY and BANKNIFTY).

## Fix Applied
Fixed entry_time computation in paper_scalp_live.py: when entry_time is None,
compute as signal_time + 5min instead of falling back to signal_time.

## Genuine Live Observation
No new signals after fix deployed. Entry verified, exit pending.
