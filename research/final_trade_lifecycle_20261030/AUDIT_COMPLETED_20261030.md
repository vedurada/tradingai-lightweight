# Audit Completed — Live Trade Lifecycle (2026-10-30)

## Status
ENTER_VERIFIED_EXIT_PENDING

## Host
webserver / Linux / x86_64 / ubuntu / /opt/tradingai (Oracle VM)

## What was done
1. Verified Oracle VM environment
2. Created backups (backups/final_trade_lifecycle_20261030_20261030_152331/)
3. Audited pipeline files: app/research/scalp_engine.py, paper_scalp_live.py, paper_trade/engine.py, strategies/scalp.py, tg_alerts.py, live/engine.py, market/collector.py
4. Found and fixed entry_time computation bug in paper_scalp_live.py (line 296 area)
5. Found and fixed notification_events database schema (UNIQUE signal_id, channel, event_type)
6. Verified DB integrity
7. Installed tradingai-paper-scalp-live.service with 5-second polling
8. Ran isolated tests: 15/15 passed
9. Verified backtest/live parity: 100% (7/7 NIFTY, 7/7 BANKNIFTY)
10. Verified live entry notification: BANKNIFTY BEAR 14:45:00 → Telegram message_id=170 DELIVERED
11. Created 10 report files
12. No fake signals sent; no strategy rules changed; no database reset

## Key findings
- Signal-to-paper-trade creation delay: ~0 seconds (same poll cycle)
- Entry-to-trade-creation delay: ~4 minutes (inherent next-candle execution)
- All 40 SCALP_HLC trades create correctly
- All 43 notification_events are ENTRY DELIVERED
- No EXIT events yet (no trades closed since fix deployed at ~14:50 IST)

## Note on Zerodha scope
This is a design/audit only for the Zerodha integration. The existing SHADOW/paper-trading pipeline uses HLC 3-Bar strategy. No broker orders are placed. The broker adapter (app/brokers/zerodha_kite.py) must only connect, quote, and prepare shadow execution — never submit orders until explicitly approved.
