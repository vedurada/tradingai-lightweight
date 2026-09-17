# Phase 41B — API Integration Documentation
Generated: 2026-09-17

## Overview

All Phase 41 API endpoints are Flask routes in `backend/api_server.py`.
Served by gunicorn on 127.0.0.1:8000 (3 workers).
Reverse proxied through nginx to port 80.

## Phase 41 API Endpoints (10 new)

### Trade Qualification

**POST /api/trade-qualification**

```
Input:
  instrument: str (e.g., "NIFTY")
  snapshot: dict (OHLCV + indicators)
  evidence: dict (from market evidence engine)
  market_state: dict (regime, trend, volatility)
  outlook: dict (from AI outlook - bias, trade_state, confidence)
  options_data: dict (optional, from options chain)
  active_trade: dict (optional, current open trade)

Output:
  trade_status: "TRADE" | "WAIT" | "NO_TRADE"
  reason: str
  checks: dict {name: {passed: bool, detail: str}}
  rejection_reasons: list
  strategy: str | None
  direction: "BULLISH" | "BEARISH" | "NEUTRAL"
  entry_price: float | None
  stop_price: float | None
  target_price: float | None
  risk_reward: float
  confirmation: str
  invalidation: str
  engine_version: str
```

**Rate limit**: 30/minute (same as other API calls)
**Error format**: `error_response()` with code, message, timestamp

### Paper Trades (7 endpoints)

**GET /api/paper-trades**
- Returns all paper trades
- Filters: instrument, date, action (TRADED/PAPER/SKIPPED)
- Response: list of trade objects with all 22+ fields

**GET /api/paper-trades/active**
- Returns currently OPEN paper trades
- Uses DB query for OPEN + WAITING_ENTRY status
- Response: list of active trades

**GET /api/paper-trades/<trade_id>**
- Returns single trade detail
- Response: trade object with full history

**GET /api/paper-trades/<trade_id>/events**
- Returns audit trail (immutable events)
- Each event: timestamp, action, field, old_value, new_value
- Response: list of events

**GET /api/paper-trades/timeline/<instrument>**
- Returns timeline of all trades for instrument
- Groups by session
- Response: timeline with daily summaries

**POST /api/paper-trades/qualify**
- Qualifies a trade setup
- Input: qualification data, outlook, snapshot, evidence
- Output: qualification result + paper trade creation

**POST /api/paper-trades/entry**
- Triggers paper trade entry
- Input: trade_id, entry_price, timestamp
- Output: entry confirmation

**POST /api/paper-trades/exit**
- Triggers paper trade exit
- Input: trade_id, exit_reason, exit_price, timestamp
- Output: exit confirmation with PnL

### Replay

**GET /api/replay/<symbol>/<date>**
- Returns replay data for specific date
- Uses `replay_day()` from replay_engine.py
- Response: timestamp-by-timestamp replay with market state, gap, trade setup, what_ai_knew, what_ai_did_not_know
- **Phase 5 merge fix (b4c668d)**: Was broken after Phase 41 commit due to missing `replay_day` import

## API Integration in Frontend

### Current Integration

| Endpoint | Frontend Usage | Status |
|----------|---------------|--------|
| /api/trade-qualification | NOT INTEGRATED | Frontend doesn't call it |
| /api/paper-trades | NOT INTEGRATED | No page shows paper trades |
| /api/paper-trades/active | NOT INTEGRATED | No page shows active trades |
| /api/paper-trades/<id> | NOT INTEGRATED | No page shows trade detail |
| /api/paper-trades/<id>/events | NOT INTEGRATED | No audit trail shown |
| /api/paper-trades/timeline/<ins> | NOT INTEGRATED | No timeline shown |
| /api/paper-trades/qualify | NOT INTEGRATED | No qualification UI |
| /api/paper-trades/entry | NOT INTEGRATED | No entry UI |
| /api/paper-trades/exit | NOT INTEGRATED | No exit UI |
| /api/replay/<symbol>/<date> | NOT INTEGRATED | No replay UI |

### Integration Required (Step 1)

1. Today page → /api/trade-qualification + /api/paper-trades/active
2. Indices page → /api/trade-qualification + /api/paper-trades
3. Strategies page → /api/paper-trades/timeline/{symbol}
4. Backtest page → /api/replay/{symbol}/{date}
5. Tools page → /api/paper-trades (all trades)

## Rate Limits

| Endpoint | Rate Limit | Window |
|----------|-----------|--------|
| All API endpoints | 30/minute | Per API key |
| /api/walkforward/* | Rate limited | Per minute |
| /api/evidence/* | Rate limited | Per minute |
| /api/intelligence/* | Rate limited | 30/minute |

## Error Format

All errors use `error_response()`:
```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable message",
    "timestamp": "ISO timestamp"
  }
}
```

## CORS

Production origins only:
- https://tradingai.in
- https://www.tradingai.in

Debug mode: False in production.

## Authentication

API key required for all endpoints (except public price/health endpoints).
API key mapped to user ID for portfolio isolation.
One API key cannot access another user's portfolio.
