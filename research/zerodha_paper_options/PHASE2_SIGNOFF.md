# Phase 2 Sign-Off — Zerodha NIFTY ATM Options Paper (2026-10-30)

## Architecture document reviewed
- File: /opt/tradingai/research/zerodha_paper_options/PHASE2_ARCHITECTURE.md
- Date: 2026-10-30
- Author: Phase 2 validation

## Requirements checklist — ALL PASS
1. Strategy integration (canonical HLC reuse, unchanged, NIFTY only) — PASS
2. Option selection (weekly ATM CE/PE from master, holiday-aware, deterministic tie-break, locked contract, token/strike/lot persisted) — PASS
3. Execution/pricing (paper BUY, ask-side assumption, freshness checks, no fabricated fills, PENDING_ENTRY, separate underlying SL/target and option P&L) — PASS
4. Database (isolated /opt/tradingai/database/zerodha_execution.db, unique constraints, transactions, audit snapshots, restart recovery) — PASS
5. Dashboard/API (independent zerodha-paper.html, read-only APIs, actual DB records only, no order controls, no Telegram/notifications) — PASS
6. Safety (no broker orders, no live execution switch, credentials outside Git, secret scan required, no production HLC/Telegram changes) — PASS

## Confirmed interfaces
- Canonical HLC: /opt/tradingai/app/research/scalp_engine.py
- Adapter layer: /opt/tradingai/app/zerodha/strategy_adapter.py (Phase 3 design)
- Existing paper engine unchanged

## Database design reviewed
- Tables: zerodha_signals, zerodha_paper_trades, zerodha_trade_events, zerodha_option_contracts, zerodha_quote_snapshots, zerodha_performance
- Constraints prevent duplicates
- Separate from tradingai.db and historical backtests

## Option selection design reviewed
- Bullish → ATM CE; Bearish → ATM PE
- Expiry from master; strike from interval; tie-break deterministic
- Contract fixed at entry

## Entry/exit pricing assumptions documented
- Entry: ask price (simulated BUY)
- Exit: fresh option quote at underlying trigger
- Underlying SL/target and option premium recorded separately
- No backdated fills; no fabricated premiums

## Dashboard/API design reviewed
- /opt/tradingai/frontend/zerodha-paper.html independent
- APIs read-only from isolated DB
- No order placement
- Refresh with hidden-tab pause; stale data labeled

## Safety controls
- Service: tradingai-zerodha-paper.service (separate, not production HLC)
- Mode: PAPER ONLY
- Secrets: .env.zerodha protected; never staged

## Limitations acknowledged (design-phase only)
- kiteconnect SDK not installed; requires SDK + protected config
- No live WebSocket feed available; candle build uses collector/mock
- No verified option quote source; design assumes fresh KB/Kite quote

## Explicit approval statement
PHASE 2 IS APPROVED FOR ISOLATED PHASE 3 IMPLEMENTATION.
No production files modified. Previous audit/report backups preserved.
Proceed to Phase 3 only with isolated module creation and deterministic mocks.
Do not enable live/running service without separate authorization.
