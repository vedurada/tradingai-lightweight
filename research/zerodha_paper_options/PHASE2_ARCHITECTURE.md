# Phase 2 — Zerodha NIFTY ATM Options Paper Architecture (2026-10-30)

## Isolation guarantee
- Repo: /opt/tradingai, branch feature/zerodha-paper-trading (not production-2026-10-01)
- Unrelated working-tree modifications preserved (2306 files untouched)
- Previous audit work preserved: backups/, research/final_trade_lifecycle_20261030/
- No real broker orders; PAPER ONLY
- No Telegram / notification dependency for this engine

## Canonical HLC reuse (no changes)
- Source: /opt/tradingai/app/research/scalp_engine.py
- Strategy: 3-candle HLC (high-low-close) pattern detection
- Bullish / Bearish classification re-used unchanged
- Entry timing: completed 5-min candle evaluation only
- SL / Target evaluated on NIFTY underlying prices
- No parameter tweaks to increase frequency

## Weekly ATM option selection (design)
- Instrument master read from Zerodha master; refreshed safely
- Bullish signal → NIFTY weekly ATM CE (BUY paper)
- Bearish signal → NIFTY weekly ATM PE (BUY paper)
- Expiry: nearest upcoming weekly from master (not hardcoded weekday)
- Strike: ATM from actual interval and master instruments; deterministic tie-break when spot exactly between strikes
- Contract locked at entry; never switched
- Quote freshness validated before entry

## Database isolation
- New DB: /opt/tradingai/database/zerodha_execution.db
- Tables: zerodha_signals, zerodha_paper_trades, zerodha_trade_events, zerodha_option_contracts, zerodha_quote_snapshots, zerodha_performance
- Unique constraints: (signal_id, trade_id), (signal_id, event_type) where appropriate
- Transactions used for trade creation/exits

## Lifecycle states
SIGNAL_GENERATED → PENDING_ENTRY (if quote stale) → OPEN → CLOSED_TARGET / CLOSED_STOPLOSS / CLOSED_STRATEGY_EXIT / ENTRY_EXPIRED / CANCELLED / DATA_ERROR

## Pricing (paper only)
- Entry: ask price for simulated BUY (recorded with method)
- Exit: fresh option quote at exit trigger (no fabricated premiums)
- Underlying SL/target triggers exit process; option exit price captured separately
- Option points = Exit premium − Entry premium
- Gross P&L = Option points × lot_size × lots
- Net = Gross − charges
- All labels: SIMULATED PAPER RESULTS

## API (design — Phase 4)
Read-only endpoints from zerodha_execution.db only:
- /api/zerodha-paper/status
- /api/zerodha-paper/summary
- /api/zerodha-paper/signal/latest
- /api/zerodha-paper/trades/open
- /api/zerodha-paper/trades/closed
- /api/zerodha-paper/trades/<trade_id>
- /api/zerodha-paper/performance
- /api/zerodha-paper/latency

## Dashboard (design — Phase 4)
- /opt/tradingai/frontend/zerodha-paper.html (independent of scalp.html/backtest.html)
- Public URL: https://tradingai.in/zerodha-paper.html
- Sections: system status, summary cards, latest HLC signal, open trades, closed history, performance analytics, trade detail modal
- Refresh every 2–3s; pause when tab hidden; label stale data clearly
- Read-only: no order placement

## Engine architecture (design — Phase 3)
- Service: tradingai-zerodha-paper.service (separate from existing HLC service)
- Event-driven tick handling → build 5-min NIFTY candles in memory
- Evaluate completed candles with canonical engine
- Subscribe to selected option instrument for premium tracking
- Reconcile open trades from zerodha_execution.db on restart
- No Telegram watcher dependency

## Secret / security
- Credentials in protected .env.zerodha (already designed); never in Git
- Secret scan required before any push
- No live execution switch
- No broker order placement methods

## Testing (design — Phase 5)
23 isolated tests planned (CE/PE selection, expiry/strike, quote freshness, duplicate prevention, restart recovery, exit triggering, P&L calc, no Telegram dependency, dashboard data only, API read-only). No fake production trades.

## Deployment sequence (current)
Phase 1: Completed — audit, branch verified, existing work preserved.
Phase 2: Completed — architecture and schema designed; isolated directories created.
Phase 3+: BLOCKED — await Phase 2 sign-off; do not implement engine/dashboard until design approved and secret scan passed.

## Known limitations (design-phase)
- No kiteconnect SDK installed in environment; adapter requires SDK + protected credentials
- No actual Zerodha instrument master accessed; selection method relies on master verification
- No live WebSocket feed available in SHADOW; candle build must use existing market collector or mock
- No option premium quote source verified; design assumes fresh quote via KB/Kite
